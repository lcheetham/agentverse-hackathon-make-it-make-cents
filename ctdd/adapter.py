"""Turns the engine's report (ctdd.engine.analyze / ctdd.pipeline) into the report-card JSON the web UI reads.

Presentation only: every number here comes from the engine. Nothing in this file changes a verdict.
What the UI deliberately does NOT show (kept in the engine for the frozen evaluation, see README "What we cut"):
the v1 verdict, the separate Copy/Watch/Don't-copy bottom line, the Bayesian posterior, and the per-null
breakdown of the luck score. One verdict is shown, plus "Hold - human review" when input checks fail.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from .config import BANNER
from .engine.copydelay import delayed_returns
from .engine.luck import conservative_luck

CODES = {
    "Skilled and copyable": "SKILLED_COPYABLE",
    "Skilled but not copyable": "SKILLED_NOT_COPYABLE",
    "Can't tell yet": "CANT_TELL",
    "Probably luck": "PROBABLY_LUCK",
}
DELAY_LABELS = {0: "0", 300: "5 min", 3600: "1 h", 86400: "1 day"}
LUCK_NS = (100, 1000, 10000)
NEAR_CERTAIN = 0.93


def _num(x):
    """JSON-safe float: NaN/inf -> None."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(x, signed=False, dp=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    s = f"{abs(x) * 100:.{dp}f}%"
    return (("+" if x >= 0 else "−") + s) if signed else (("−" if x < 0 else "") + s)


def _display(stat: dict) -> str:
    v, unit = stat.get("value"), stat.get("unit", "")
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    if unit == "$":
        out = f"{'−' if v < 0 else ''}${abs(v):,.2f}"
    elif unit == "GBP":
        out = f"£{v:,.2f}"
    elif unit in ("share", "probability"):
        signed = "edge" in stat["id"].lower()
        out = _pct(v, signed=signed, dp=2 if unit == "probability" and v < 0.01 else 1)
    elif unit == "x":
        out = f"{v:,.1f}×"
    elif unit == "$/share":
        out = f"{v * 100:.1f}c"
    else:
        out = f"{v:,}" if isinstance(v, int) else f"{v:,.4g}"
    lo, hi = stat.get("lo"), stat.get("hi")
    if lo is not None and hi is not None and unit in ("share", "probability"):
        out += f" (95% CI {_pct(lo, signed=True)} to {_pct(hi, signed=True)})"
    return out


def _cluster_label(titles: list[str]) -> str:
    t = titles[0] if titles else "?"
    t = t if len(t) <= 70 else t[:67] + "…"
    return t + (f" (+{len(titles) - 1} related)" if len(titles) > 1 else "")


def follower_sim(closed: pd.DataFrame, price_at, delay_s: int, half_spread: float, fee_rate: float) -> dict:
    """GBP 200, GBP 10 per copy at `delay_s`, in time order (same rule as the engine's sim200, any delay)."""
    order = closed.sort_values("first_ts")
    ret, _ = delayed_returns(order, price_at, delay_s, half_spread, fee_rate)
    bank, curve, copies, wiped = 200.0, [], 0, False
    ts0 = float(order["first_ts"].min()) if len(order) else 0.0
    curve.append({"ts": ts0, "value": bank})
    for r, ts in zip(ret, order["first_ts"].to_numpy(dtype=float)):
        if math.isnan(r):
            continue
        if bank < 10:
            wiped = True
            break
        bank += 10 * r
        copies += 1
        curve.append({"ts": float(ts), "value": round(bank, 2)})
    if len(curve) > 400:                                    # keep the payload small; the chart only needs the shape
        idx = np.linspace(0, len(curve) - 1, 400).astype(int)
        curve = [curve[i] for i in idx]
    return {"start": 200.0, "end": round(bank, 2), "delay_s": int(delay_s), "n_copied": copies,
            "ran_out_of_cash": wiped, "stake_per_copy": 10.0, "curve": curve}


COARSE_MIN_EVENTS = 10      # one related-bet group spanning this many separate Polymarket events gets a note


def coarse_groups(closed: pd.DataFrame, label_of: dict) -> dict | None:
    """Presentation-only check on the engine's related-bet groups (the engine itself is frozen).

    Related bets are linked when their titles share a name and they resolve close together, and those links
    chain: across a busy sports or e-sports month one group can swallow many separate matches. Treating them
    as one draw makes the luck score and the edge interval more sceptical than they should be. Real data
    only: Polymarket's event slugs are meaningful there (each match or race is its own event)."""
    if "event_slug" not in closed or closed.empty:
        return None
    slugs = closed["event_slug"].fillna("").astype(str)
    per = closed.assign(_s=slugs)[slugs != ""].groupby("cluster")["_s"].nunique()
    big = per[per >= COARSE_MIN_EVENTS]
    if big.empty:
        return None
    top = big.idxmax()
    ids = closed.loc[closed["cluster"].isin(big.index), "id"].tolist()
    n_pos = int(closed["cluster"].isin(big.index).sum())
    label = label_of.get(str(top)) or str(top)
    more = f" ({len(big)} such groups in all)" if len(big) > 1 else ""
    text = (f"Check the grouping: {n_pos} bets spanning {int(big.max())} separate Polymarket events were treated as one "
            f"related group (\u201c{label}\u201d){more}. If those events aren't really connected, the luck score and "
            f"the edge interval are more sceptical than they should be. The verdict only ever leans towards luck "
            f"because of this, never towards skill.")
    return {"text": text, "position_ids": ids, "n_positions": n_pos, "n_events": int(big.max())}


LUCK_N_MAX = 1_000_000


def luck_at(luck: dict, n: int) -> dict:
    """Luck(N) for any leaderboard size N, from the engine's stored single-twin probabilities (no re-simulation).

    Display only: the verdict keeps its frozen N. When the most sceptical mode's p is the add-one Monte Carlo
    floor (too few twins beat the trader), the true score can only be lower, so it is flagged as an upper bound.
    """
    n = int(n)
    if not 1 <= n <= LUCK_N_MAX:
        raise ValueError(f"N must be a whole number from 1 to {LUCK_N_MAX:,}")
    modes = luck.get("modes", {})
    score = conservative_luck(luck, n)
    top = max(modes.values(), key=lambda m: m["p_single"], default=None)
    return {"n": n, "score": _num(score), "upper_bound": bool(top is not None and top.get("p_method") == "mc_add_one")}


def with_delay(base: dict, delay_s: int) -> dict:
    """The cached card with the £200 simulation for one delay selected (cheap: no recomputation)."""
    c = dict(base)
    c["params"] = {**base["params"], "copy_delay_s": int(delay_s)}
    c["sim_200"] = base["sims"][str(int(delay_s))]
    return c


def wallet_row(report: dict) -> dict:
    pos = report["positions"]
    closed = pos[pos["status"] != "open"]
    wins, losses = int((closed["pnl"] > 0).sum()), int((closed["pnl"] <= 0).sum())
    return {"address": report["wallet"], "profit": _num(closed["pnl"].sum()), "n_positions": int(len(closed)),
            "win_rate": _num((closed["pnl"] > 0).mean()) if len(closed) else None, "record": f"{wins}–{losses}",
            "verdict": {"code": CODES.get(report.get("verdict"), "CANT_TELL"), "label": report.get("verdict")}}


def card(report: dict, price_at, th: dict, delay_s: int, data_mode: str, llm_name: str) -> dict:
    pos = report["positions"]
    closed = pos[pos["status"] != "open"].copy()
    closed["id"] = closed["token_id"].astype(str)
    stats = report["stats"]
    integrity = report.get("integrity") or {"checks": [], "hold": False}

    # ---- clusters ----
    cl_titles = closed.groupby("cluster")["title"].apply(lambda s: list(dict.fromkeys(s)))
    cl_profit = closed.groupby("cluster")["pnl"].sum()
    cl_ids = closed.groupby("cluster")["id"].apply(list)
    cl_markets = closed.groupby("cluster")["condition_id"].unique()      # one pass, not one scan per cluster
    clusters = [{"id": str(c), "label": _cluster_label(cl_titles[c]), "market_ids": cl_markets[c].tolist(),
                 "n_positions": int(len(cl_ids[c])), "profit": _num(cl_profit[c])} for c in cl_titles.index]
    label_of = {c["id"]: c["label"] for c in clusters}

    # ---- positions ----
    held = closed["status"] == "held"
    exit_price = np.where(held, closed["payout"], closed["avg_exit"])
    exit_ts = np.where(held, closed["resolve_ts"], closed["last_sell_ts"])
    positions = [{
        "id": r.id, "market_id": r.condition_id, "title": r.title, "category": r.category, "cluster_id": str(r.cluster),
        "token": "YES" if int(r.outcome_index) == 0 else ("NO" if int(r.outcome_index) == 1 else f"#{int(r.outcome_index)}"),
        "shares": _num(r.shares), "avg_entry": _num(r.avg_entry), "exit_price": _num(ex), "held_to_resolution": bool(h),
        "entry_ts": _num(r.first_ts), "exit_ts": _num(et), "cost": _num(r.cost), "pnl": _num(r.pnl), "ret": _num(r.ret),
        "near_certain": bool(r.avg_entry >= NEAR_CERTAIN),
    } for r, ex, et, h in zip(closed.itertuples(index=False), exit_price, exit_ts, held)]

    # ---- verdict (one label; Hold overrides when input checks fail badly) ----
    if integrity.get("hold"):
        bad = [c for c in integrity["checks"] if c.get("severe")]
        verdict = {"code": "HOLD", "label": "Hold – human review",
                   "deciding": [{"key": f"check_{c['check']}", "value": None, "text": f"Input check '{c['check']}' failed: {c['detail']}"} for c in bad]
                   + [{"key": "engine_verdict", "value": None, "text": f"The engine alone would say '{report['verdict']}', but the agent will not judge bad data on its own."}]}
    else:
        verdict = {"code": CODES[report["verdict"]], "label": report["verdict"],
                   "deciding": [{"key": f"reason_{i}", "value": None, "text": t} for i, t in enumerate(report.get("verdict_reasons") or [])]}
    verdict["thresholds"] = th["verdict"]

    # ---- luck (most sceptical of the engine's no-skill nulls) ----
    luck = report["luck"]
    modes = luck.get("modes", {})
    verdict_n = int(stats["S.N_eff"]["value"])
    by_n = [luck_at(luck, n) for n in sorted(set(LUCK_NS) | {verdict_n})]
    luck_out = {"q_single_upper": any(r.get("upper_bound") for r in by_n), "by_n": by_n, "coverage": _num(luck.get("coverage_positions")), "n_positions_used": int(luck.get("n_held", 0)),
                "twin": "most sceptical no-skill twin", "q_single": _num(max((m["p_single"] for m in modes.values()), default=None)),
                "verdict_n": verdict_n}

    # ---- copy delay ----
    curve = [{"delay_s": int(c["delay_s"]), "label": DELAY_LABELS.get(int(c["delay_s"]), f"{c['delay_s']} s"),
              "edge": _num(c["mean"]), "ci_low": _num(c["lo"]), "ci_high": _num(c["hi"]),
              "n_copyable": int(c.get("n", 0)), "n_total": int(len(closed))} for c in report["delay_curve"]]

    # ---- concentration / categories ----
    conc = report["concentration"]
    top = conc.get("top_cluster")
    concentration = {"top_cluster_id": str(top) if top is not None else None, "top_cluster_label": label_of.get(str(top)),
                     "profit_total": _num(closed["pnl"].sum()), "profit_without_top": _num(conc.get("profit_without_top")),
                     "edge_without_top": _num(conc.get("edge_without_top")), "top_share_of_profit": _num(conc.get("top_share_of_profit"))}
    categories = [{"category": c["category"], "n": c["n"], "profit": _num(c["profit"]), "edge": _num(c["edge"])} for c in report["categories"]]

    # ---- flags with the trades behind them ----
    top_ids = closed.loc[closed["cluster"] == top, "id"].tolist() if top is not None else []
    late_ids = closed.loc[held & (closed["resolve_ts"] - closed["first_ts"] < 3600) & (closed["avg_entry"] < 0.6) & (closed["payout"] > 0.5), "id"].tolist()
    farm_ids = closed.loc[closed["avg_entry"] >= 0.95, "id"].tolist()
    flags = []
    coarse = coarse_groups(closed, label_of) if data_mode == "real" else None
    for f in report["flags"]:
        if f.startswith("Needs human review"):
            flags.append({"code": "WELL_TIMED", "severity": "review", "text": f, "position_ids": late_ids})
        elif "near-certainty" in f:
            flags.append({"code": "NEAR_CERTAIN", "severity": "info", "text": f, "position_ids": farm_ids})
        elif f.startswith("Concentration"):
            flags.append({"code": "CONCENTRATION", "severity": "info", "text": f, "position_ids": top_ids})
        elif f.startswith("Input check"):
            flags.append({"code": "INPUT_CHECK", "severity": "review", "text": f, "position_ids": []})
        else:
            flags.append({"code": "NOTE", "severity": "info", "text": f, "position_ids": []})
    if coarse:
        flags.append({"code": "COARSE_GROUPING", "severity": "review", "text": coarse["text"], "position_ids": coarse["position_ids"]})
    luck_out["coarse_grouping"] = bool(coarse)

    # ---- facts + written report (sentences cite fact ids and trades) ----
    facts = {sid: {"value": _num(s["value"]) if not isinstance(s["value"], str) else s["value"], "display": _display(s),
                   "label": s["label"], "position_ids": []} for sid, s in stats.items()
             if not sid.startswith(("S.p_single.", "S.luck.coinflip", "S.luck.shared", "S.luck.independent"))}
    if "S.profit_wo_top" in facts:
        facts["S.profit_wo_top"]["position_ids"] = top_ids
    text = report.get("text") or {"method": "template", "sentences": [], "rejected": None}
    sentences = []
    for s in text["sentences"]:
        ids = [i for i in s.get("ids", []) if i in facts]
        pids = [p for i in ids for p in facts[i]["position_ids"]]
        for fl in flags:
            if fl["text"] == s["text"]:
                pids = fl["position_ids"]
        if s["text"] == BANNER:
            continue
        sentences.append({"text": s["text"], "fact_ids": ids, "position_ids": pids[:500]})
    if text["method"] == "llm":
        writer = f"Gemini ({llm_name}), number-guarded"
    elif text.get("rejected"):
        writer = f"template (Gemini's text was rejected by the number guard: {', '.join(text['rejected'][:5])})"
    else:
        writer = "template (code)"

    costs = th["costs"]
    return {
        "wallet": report["wallet"], "data_mode": data_mode, "llm_mode": llm_name,
        "params": {"copy_delay_s": int(delay_s), "verdict_delay_s": int(th["verdict"]["copy_delay_s"]), "leaderboard_n": int(stats["S.N_eff"]["value"])},
        "verdict": verdict,
        "summary": {"n_positions": int(len(closed)), "n_held": int(held.sum()), "n_sold_early": int((~held).sum()),
                    "profit": _num(closed["pnl"].sum()), "total_staked": _num(closed["cost"].sum()),
                    "win_rate": _num((closed["pnl"] > 0).mean()) if len(closed) else None,
                    "n_clusters": int(report["edge"]["n_clusters"]),
                    "record": f"{int((closed['pnl'] > 0).sum())}–{int((closed['pnl'] <= 0).sum())}"},
        "edge": {"mean": _num(report["edge"]["mean"]), "ci_low": _num(report["edge"]["lo"]), "ci_high": _num(report["edge"]["hi"]),
                 "n_positions": int(len(closed)), "n_clusters": int(report["edge"]["n_clusters"]), "method": "cluster_bootstrap"},
        "luck": luck_out,
        "delay_curve": curve,
        "concentration": concentration,
        "categories": categories,
        # One £200 simulation per delay, computed once, so the UI switches delay without another request.
        "sims": {str(d): follower_sim(closed, price_at, d, costs["half_spread"], costs["fee_rate"]) for d in DELAY_LABELS},
        "sim_200": None,                                    # filled with sims[delay] by with_delay()
        "flags": flags,
        "near_certain": {"n": int((closed["avg_entry"] >= NEAR_CERTAIN).sum()),
                         "share": _num((closed["avg_entry"] >= NEAR_CERTAIN).mean()) if len(closed) else 0.0},
        "clusters": clusters,
        "positions": positions,
        "facts": facts,
        "report": {"sentences": sentences, "writer": writer, "prompt_version": None,
                   "check": {"passed": True, "unmatched": []}},
        "what_would_change": report.get("what_would_change") or [],
        "input_checks": [{"check": c["check"], "ok": bool(c["ok"]), "detail": c["detail"], "severe": bool(c.get("severe"))}
                         for c in integrity.get("checks", [])],
        "cluster_method": report.get("cluster_method"),
        "freeze_hash": report.get("freeze_hash"),
        "data_note": report.get("data_note"),
    }


def agent_facts(c: dict) -> dict:
    """Compact, number-exact view of a card for the chat agent (no position lists)."""
    by_n = {f"N={r['n']}": _pct(r["score"]) if r["score"] is not None else "n/a" for r in c["luck"]["by_n"]}
    return {
        "wallet": c["wallet"], "data": c["data_mode"], "verdict": c["verdict"]["label"],
        "verdict_reasons": [d["text"] for d in c["verdict"]["deciding"]],
        "what_would_change_the_verdict": c["what_would_change"],
        "record": c["summary"]["record"], "positions": c["summary"]["n_positions"],
        "independent_event_clusters": c["summary"]["n_clusters"],
        "profit_usd": round(c["summary"]["profit"] or 0, 2),
        "edge_per_position": f"{_pct(c['edge']['mean'], True)} (95% CI {_pct(c['edge']['ci_low'], True)} to {_pct(c['edge']['ci_high'], True)})",
        "luck_score": by_n, "luck_score_field_size_used_for_verdict": c["luck"]["verdict_n"],
        "follower_edge_by_copy_delay": {d["label"] if d["label"] != "0" else "no delay": _pct(d["edge"], True) for d in c["delay_curve"]},
        "historical_simulation_gbp200_at_gbp10_per_copy_1h_late_NOT_A_FORECAST": c["sim_200"]["end"],
        "flags": [f["text"] for f in c["flags"]],
        "failed_input_checks": [f"{x['check']}: {x['detail']}" for x in c["input_checks"] if not x["ok"]],
    }
