"""Evaluation B: real-wallet walk-forward (spec section 7B).

    python -m eval.walkforward --universe 60 --cutoff-days 14

1. Universe: wallets from the Polymarket monthly leaderboard (stated bias: membership uses today's ranking).
2. As of the cut-off: pull each wallet's fills with `end=cutoff` and treat only markets resolved before the
   cut-off as resolved. Run the full engine -> verdict. Nothing after the cut-off is visible.
3. After the cut-off, paper-copy every new position (GBP 10 each) at the price `delay` later plus half the
   spread and fees, held to resolution, for two portfolios:
     A. "Top 10"          - the 10 wallets with the highest profit as of the cut-off (what a follower would see)
     B. "Agent-approved"  - wallets with verdict "Skilled and copyable" as of the cut-off
4. Report mean return per copy for each, and B - A, with 95% CIs from resampling (wallet, event) clusters.
   If the agent approves nobody, portfolio B holds cash (0%); that abstention is reported as a result.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import time

import numpy as np
import pandas as pd

from ctdd.audit import AuditLog
from ctdd.config import EVAL_DIR, load_thresholds
from ctdd.data.polymarket import PolymarketClient
from ctdd.engine.positions import build_positions
from ctdd.engine.decision import bottom_line
from ctdd.engine.skill import calibration_table, fit_prior, se_from_ci, shrink
from ctdd.engine.stats import cluster_bootstrap_mean
from ctdd.pipeline import run_wallet

RESULTS = EVAL_DIR / "results"


def markets_as_of(mk: pd.DataFrame, cutoff: float) -> pd.DataFrame:
    """Hide resolutions that happened after the cut-off."""
    m = mk.copy()
    later = ~(m["resolved"].astype(bool) & (m["resolve_ts"].astype(float) < cutoff))
    m.loc[later, "resolved"] = False
    m.loc[later, "payouts"] = None
    m.loc[later, "resolve_ts"] = np.nan
    return m


def copy_returns(client, positions: pd.DataFrame, delay: int, half_spread: float, fee: float, max_copies: int):
    """Follower return per post-cut-off position: enter `delay` after the leader, hold to resolution."""
    out = []
    pos = positions.sort_values("first_ts").head(max_copies)
    for r in pos.itertuples(index=False):
        rec = {"token_id": r.token_id, "event": r.event_slug or r.condition_id, "title": r.title, "status": "ok", "ret": np.nan, "t": int(r.first_ts),
               "leader_ret": float(r.ret) if r.ret == r.ret else np.nan, "leader_price": float(r.avg_entry)}
        if not (r.payout == r.payout):
            rec["status"] = "unresolved"
        else:
            t_in = int(r.first_ts) + delay
            if r.resolve_ts == r.resolve_ts and t_in >= r.resolve_ts:
                rec["status"] = "missed (resolved before copy)"
            else:
                hist = client.price_history(r.token_id, t_in - 300, t_in + 1800, fidelity=1)
                px = next((p for t, p in hist if t >= t_in), None)
                if px is None or not (0 < px < 1):
                    rec["status"] = "missed (no price)"
                else:
                    entry = min(px + half_spread, 0.999) * (1 + fee)
                    rec["ret"] = float(r.payout) / entry - 1
        out.append(rec)
    return out


def bootstrap_diff(a_ret, a_cl, b_ret, b_cl, B=4000, seed=0):
    rng = np.random.default_rng(seed)

    def draws(ret, cl):
        ret, cl = np.asarray(ret, float), np.asarray(cl)
        if len(ret) == 0:
            return np.zeros(B)
        u, inv = np.unique(cl, return_inverse=True)
        s, c = np.bincount(inv, weights=ret), np.bincount(inv).astype(float)
        idx = rng.integers(0, len(u), size=(B, len(u)))
        return s[idx].sum(1) / c[idx].sum(1)

    d = draws(b_ret, b_cl) - draws(a_ret, a_cl)
    lo, hi = np.quantile(d, [0.025, 0.975])
    # Point estimate is the plain difference of the two means (so it matches the per-portfolio numbers);
    # the bootstrap only supplies the interval.
    point = (float(np.mean(b_ret)) if len(b_ret) else 0.0) - (float(np.mean(a_ret)) if len(a_ret) else 0.0)
    return point, float(lo), float(hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=int, default=60, help="leaderboard wallets to consider")
    ap.add_argument("--period", default="month")
    ap.add_argument("--cutoff-days", type=float, default=14)
    ap.add_argument("--pre-pages", type=int, default=4, help="500 fills per page, before the cut-off")
    ap.add_argument("--post-pages", type=int, default=6)
    ap.add_argument("--N", type=int, default=1000, help="field size for the luck score")
    ap.add_argument("--max-copies", type=int, default=40, help="post-cut-off copies per wallet (price calls)")
    ap.add_argument("--min-pre", type=int, default=20, help="min resolved positions before the cut-off")
    ap.add_argument("--cutoff-ts", type=int, default=None, help="fixed cut-off (unix seconds) to reuse cached pulls")
    ap.add_argument("--price-positions", type=int, default=25, help="pre-cut-off positions priced for the copy-delay test")
    ap.add_argument("--out", default=None, help="folder for the results (default eval/results); keeps runs of different engines apart")
    a = ap.parse_args()
    global RESULTS
    if a.out:
        RESULTS = Path(a.out).resolve()

    th = load_thresholds()
    delay, hs, fee = th["verdict"]["copy_delay_s"], th["costs"]["half_spread"], th["costs"]["fee_rate"]
    audit = AuditLog("logs/walkforward.jsonl")
    client = PolymarketClient(audit=audit)
    cutoff = int(a.cutoff_ts) if a.cutoff_ts else int(time.time() - a.cutoff_days * 86400)
    t0 = time.time()
    lb = client.leaderboard(a.period, n=a.universe)
    wallets = lb["user_id"].str.lower().tolist()
    print(f"Universe: {len(wallets)} wallets · cut-off {pd.Timestamp(cutoff, unit='s')} UTC", flush=True)

    # Pass 1: everyone's history as of the cut-off (no look-ahead).
    rows, data, post_positions = [], {}, {}
    for w in wallets:
        pre = client.trades_window(w, end_ts=cutoff, max_pages=a.pre_pages)
        post = client.trades_window(w, stop_before_ts=cutoff, max_pages=a.post_pages)
        post = post[post["ts"] >= cutoff] if not post.empty else post
        if pre.empty:
            rows.append({"wallet": w, "status": "no fills before cut-off"})
            continue
        mk_all = client.markets(pd.concat([pre, post])["condition_id"].unique())
        slug = pd.concat([pre, post]).groupby("condition_id")["event_slug"].first()
        mk_all["event_slug"] = mk_all["event_slug"].where(mk_all["event_slug"].astype(bool), slug.reindex(mk_all.index).fillna(""))
        mk_pre = markets_as_of(mk_all, cutoff)
        pos_pre = build_positions(pre, mk_pre, th["engine"]["hold_sold_frac"])
        data[w] = (pre, post, mk_all, mk_pre, pos_pre)

    # Calibrated no-skill twin: Polymarket's empirical win rate by price band, learned only from
    # positions resolved before the cut-off across the whole universe.
    cal = calibration_table(pd.concat([d[4] for d in data.values()])) if data else None
    if cal:
        print(f"Calibration from {cal['n']} pre-cut-off held positions: "
              + ", ".join(f"{e:.2f}+:{r:.3f}" for e, r in zip(cal["edges"], cal["rates"])), flush=True)

    # Pass 2: judge every wallet with enough history (fair-odds, shared, coin-flip and calibrated nulls).
    reports = {}
    for i, (w, (pre, post, mk_all, mk_pre, pos_pre)) in enumerate(data.items()):
        n_res = int((pos_pre["status"] != "open").sum())
        row = {"wallet": w, "pre_fills": len(pre), "pre_span_days": round((pre["ts"].max() - pre["ts"].min()) / 86400, 1),
               "pre_resolved": n_res, "pre_profit": float(pos_pre.loc[pos_pre["status"] != "open", "pnl"].sum()),
               "post_fills": len(post)}
        if n_res < a.min_pre:
            row.update(status=f"< {a.min_pre} resolved positions before cut-off", verdict=None)
            rows.append(row)
            continue
        closed = pos_pre[pos_pre["status"] != "open"]
        price_at = client.price_at_factory(closed, th["engine"]["delays_s"], max_positions=a.price_positions)
        rep = run_wallet(w, pre, mk_pre, price_at, a.N, th=th, audit=audit, write=False, positions=pos_pre, calibration=cal)
        reports[w] = rep
        d = next((c for c in rep["delay_curve"] if c["delay_s"] == delay), {})
        row.update(status="judged", verdict=rep["verdict"], verdict_v1=rep["verdict_v1"], luck=rep["luck_n"], luck_v1=rep["luck_n_v1"],
                   edge=rep["edge"]["mean"], edge_lo=rep["edge"]["lo"], edge_se=se_from_ci(rep["edge"]["lo"], rep["edge"]["hi"]),
                   follow=d.get("mean", np.nan), follow_se=se_from_ci(d.get("lo"), d.get("hi")),
                   e_value=rep["betting"]["e_value"], clusters_needed=rep["betting"]["clusters_needed"],
                   n_clusters=rep["edge"]["n_clusters"], integrity_hold=rep["integrity"]["hold"])
        rows.append(row)
        if not post.empty:
            pp = build_positions(post, mk_all, th["engine"]["hold_sold_frac"])
            post_positions[w] = pp[pp["first_ts"] >= cutoff]
        print(f"[{i + 1:3d}/{len(data)}] {w[:10]} pre={n_res:4d} · v1 {row['verdict_v1']:24s} v2 {row['verdict']:24s} ({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    judged = df[df.get("status") == "judged"].copy() if "status" in df else df.iloc[:0]

    # Empirical-Bayes prior learned across these real wallets (saved for the app), then the bottom line.
    RESULTS.mkdir(parents=True, exist_ok=True)
    prior_follow = fit_prior(judged["follow"], judged["follow_se"]) if len(judged) else None
    prior_edge = fit_prior(judged["edge"], judged["edge_se"]) if len(judged) else None
    if prior_follow:
        prior_follow.update(source=f"fitted on {prior_follow['n']} real wallets as of {pd.Timestamp(cutoff, unit='s'):%Y-%m-%d}")
        (RESULTS / "population_prior.json").write_text(json.dumps(prior_follow, indent=2))
    acts = []
    for w, dm, dse in zip(judged["wallet"], judged["follow"], judged["follow_se"]):
        rep = reports[w]
        acts.append(bottom_line(rep["verdict"], rep["betting"], dm, rep["integrity"])["action"])
    judged["bottom_line"] = acts
    df = df.merge(judged[["wallet", "bottom_line"]], on="wallet", how="left")

    top10 = judged.nlargest(10, "pre_profit")["wallet"].tolist()
    approved = judged.loc[judged["verdict"] == "Skilled and copyable", "wallet"].tolist()
    any_skilled = judged.loc[judged["verdict"].astype(str).str.startswith("Skilled"), "wallet"].tolist()
    approved_v1 = judged.loc[judged["verdict_v1"] == "Skilled and copyable", "wallet"].tolist()
    copy_watch = judged.loc[judged["bottom_line"].isin(["Copy (paper first)", "Watch"]), "wallet"].tolist()

    copies: dict = {}
    for w in sorted(set(top10) | set(approved) | set(any_skilled) | set(approved_v1) | set(copy_watch)):
        if w in post_positions:
            copies[w] = copy_returns(client, post_positions[w], delay, hs, fee, a.max_copies)

    def portfolio(ws):
        recs = [dict(r, wallet=w) for w in ws for r in copies.get(w, [])]
        ok = sorted([r for r in recs if r["status"] == "ok"], key=lambda r: r["t"])
        ret = [r["ret"] for r in ok]
        leader = [r["leader_ret"] for r in ok if r["leader_ret"] == r["leader_ret"]]
        cl = [f"{r['wallet']}|{r['event']}" for r in ok]
        ci = cluster_bootstrap_mean(ret, cl, B=2000) if ok else {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0, "n_clusters": 0}
        status = pd.Series([r["status"] for r in recs]).value_counts().to_dict() if recs else {}
        pnl = 10 * np.asarray(ret, float)
        equity = 200 + np.cumsum(pnl) if len(pnl) else np.array([200.0])
        peak = np.maximum.accumulate(np.r_[200.0, equity])
        mdd = float(np.max((peak[1:] - equity) / peak[1:])) if len(pnl) else 0.0
        sharpe = float(np.mean(ret) / np.std(ret, ddof=1)) if len(ret) > 2 and np.std(ret) > 0 else float("nan")
        return {"wallets": ws, "n_wallets": len(ws), "copies": len(ok), "status_counts": status,
                "mean_ret": ci["mean"], "lo": ci["lo"], "hi": ci["hi"], "n_clusters": ci["n_clusters"],
                "gbp10_pnl": float(pnl.sum()), "sharpe_per_copy": sharpe, "max_drawdown_on_200": mdd,
                "win_rate": float(np.mean(np.asarray(ret) > 0)) if ret else float("nan"),
                "leader_mean_ret_same_positions": float(np.mean(leader)) if leader else None,
                "_ret": ret, "_cl": cl}

    A, B_, S = portfolio(top10), portfolio(approved), portfolio(any_skilled)
    B1, C = portfolio(approved_v1), portfolio(copy_watch)
    diff = bootstrap_diff(A["_ret"], A["_cl"], B_["_ret"], B_["_cl"])
    diff_c = bootstrap_diff(A["_ret"], A["_cl"], C["_ret"], C["_cl"])
    res = {
        "cutoff_utc": str(pd.Timestamp(cutoff, unit="s")), "cutoff_days_ago": a.cutoff_days, "universe": len(wallets),
        "judged": int(len(judged)), "verdict_counts": judged["verdict"].value_counts().to_dict() if len(judged) else {},
        "excluded": df[df.get("status") != "judged"]["status"].value_counts().to_dict() if "status" in df else {},
        "delay_s": delay, "half_spread": hs, "fee_rate": fee, "N": a.N,
        "top10": {k: v for k, v in A.items() if not k.startswith("_")},
        "agent_approved": {k: v for k, v in B_.items() if not k.startswith("_")},
        "any_skilled": {k: v for k, v in S.items() if not k.startswith("_")},
        "agent_approved_v1": {k: v for k, v in B1.items() if not k.startswith("_")},
        "bottom_line_copy_or_watch": {k: v for k, v in C.items() if not k.startswith("_")},
        "approved_minus_top10": {"mean": diff[0], "lo": diff[1], "hi": diff[2]},
        "copywatch_minus_top10": {"mean": diff_c[0], "lo": diff_c[1], "hi": diff_c[2]},
        "verdict_counts_v1": judged["verdict_v1"].value_counts().to_dict() if len(judged) else {},
        "bottom_line_counts": judged["bottom_line"].value_counts().to_dict() if len(judged) else {},
        "calibration": cal, "prior_follow": prior_follow, "prior_edge": prior_edge,
        "runtime_s": round(time.time() - t0, 1),
        "bias_notes": [
            "Universe = today's monthly leaderboard, so membership uses information after the cut-off (affects both portfolios).",
            "Followers hold to resolution; leaders' early exits are not mirrored.",
            "Fill history is paged (most recent first); very active wallets may have few positions before the cut-off.",
        ],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "walkforward.json").write_text(json.dumps(res, indent=2, default=float))
    df.to_csv(RESULTS / "walkforward_wallets.csv", index=False)
    (RESULTS / "walkforward.md").write_text(to_markdown(res), encoding="utf-8")
    audit.log("walkforward_run", cutoff=cutoff, judged=res["judged"], approved=len(approved), diff=res["approved_minus_top10"])
    print(to_markdown(res))


def to_markdown(r: dict) -> str:
    def row(name, p):
        if p["copies"] == 0:
            return f"| {name} | {p['n_wallets']} | 0 | — (holds cash) | — | — | — | £0 |"
        lead = p.get("leader_mean_ret_same_positions")
        sh = p.get("sharpe_per_copy")
        return (f"| {name} | {p['n_wallets']} | {p['copies']} ({p['n_clusters']} clusters) | "
                f"{p['mean_ret']:+.1%} (CI {p['lo']:+.1%} to {p['hi']:+.1%}) | "
                f"{'—' if lead is None else f'{lead:+.1%}'} | "
                f"{'—' if sh is None or sh != sh else f'{sh:+.2f}'} | {('100% (wiped out)' if p.get('max_drawdown_on_200', 0) >= 1 else format(p.get('max_drawdown_on_200', 0), '.0%'))} | £{p['gbp10_pnl']:+,.0f} |")

    def verdict_line(d, port, name):
        if port["copies"]:
            return f"**{name} − A: {d['mean']:+.1%} per copy (95% CI {d['lo']:+.1%} to {d['hi']:+.1%}).**"
        return (f"**{name} held cash (no wallet selected). {name} − A = {d['mean']:+.1%} per copy (95% CI {d['lo']:+.1%} to {d['hi']:+.1%}) "
                f"is the loss avoided by abstaining — not evidence of picking winners.**")

    cal = r.get("calibration") or {}
    cal_txt = ", ".join(f"{e:.2f}–: {rate:.3f} (n={n})" for e, rate, n in zip(cal.get("edges", []), cal.get("rates", []), cal.get("counts", [])) if n)
    pf = r.get("prior_follow") or {}
    lines = [
        "# Walk-forward on real wallets (Evaluation B)", "",
        f"Cut-off {r['cutoff_utc']} UTC · universe {r['universe']} leaderboard wallets · {r['judged']} judged with ≥ 20 resolved positions "
        f"before the cut-off · copy delay {r['delay_s'] // 3600} h, half-spread {r['half_spread']:.1%}, fee {r['fee_rate']:.2%}.", "",
        f"Verdicts as of the cut-off — v1: {r.get('verdict_counts_v1', {})}; v2: {r['verdict_counts']}. "
        f"Bottom lines (v2): {r.get('bottom_line_counts', {})}. Excluded: {r['excluded']}.", "",
        "| Portfolio (copies after the cut-off) | Wallets | Copies | Follower return per copy (after delay + costs) | Leader's own return, same bets | Sharpe per copy | Max drawdown (£200) | P&L at £10/copy |",
        "|---|---|---|---|---|---|---|---|",
        row("A. Top 10 by profit at the cut-off", r["top10"]),
        row("B1. v1 agent-approved", r.get("agent_approved_v1", r["agent_approved"])),
        row("B. v2 agent-approved ('Skilled and copyable')", r["agent_approved"]),
        row("C. v2 bottom line Copy or Watch", r.get("bottom_line_copy_or_watch", r["agent_approved"])), "",
        verdict_line(r["approved_minus_top10"], r["agent_approved"], "B"),
        verdict_line(r.get("copywatch_minus_top10", r["approved_minus_top10"]), r.get("bottom_line_copy_or_watch", r["agent_approved"]), "C"), "",
        f"Calibrated no-skill twin learned from pre-cut-off positions — win rate by entry-price band: {cal_txt or 'n/a'}.", "",
        f"Empirical-Bayes prior for follower edge: mean {pf.get('m', float('nan')):+.3f}, spread {pf.get('tau', float('nan')):.3f} ({pf.get('source', 'n/a')}).", "",
        "CIs resample (wallet, event) clusters. Sharpe = mean / SD of per-copy returns. " + " ".join(r["bias_notes"]),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
