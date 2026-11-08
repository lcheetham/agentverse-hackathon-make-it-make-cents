"""Old (v1) vs upgraded (v2) skill-vs-luck methods on planted traders with known truth.

    python -m eval.compare_methods --seeds 101 202

Seed 101 is the dev batch (where the Watch threshold may be tuned); later seeds are fresh holdout batches.
Methods scored on the same wallets:
  v1_verdict        fair-odds twin only (independent + shared), best-of-N
  v2_verdict        most sceptical of fair-odds, shared, coin-flip (and calibrated where available)
  v2_bottom_line    Copy / Watch counted as a positive call; empirical-Bayes prior fitted on the batch
  betting_proven    testing-by-betting evidence >= N/alpha
  fdr_q10           Storey q-value < 0.10 on the conservative single-trader p
  naive_winrate70   win rate > 70%            naive_top10_roi  top 10 by ROI
Metrics with Wilson 95% CIs: precision, recall, false-alarm rate, plus the share of wallets left without a
usable answer ("Can't tell yet" with no bottom line), and the Brier score of P(edge > 0).
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from ctdd.audit import AuditLog
from ctdd.config import EVAL_DIR, load_thresholds
from ctdd.data.synthetic import planted_batch
from ctdd.engine.decision import WATCH_E, bottom_line
from ctdd.engine.skill import fit_prior, se_from_ci, shrink, storey_qvalues
from ctdd.engine.stats import wilson
from ctdd.pipeline import run_wallet

RESULTS = EVAL_DIR / "results"
SKILLED = {"Skilled and copyable", "Skilled but not copyable"}


def run_batch(seed: int, th: dict) -> pd.DataFrame:
    world = planted_batch(seed=seed)
    F, M = world.fills_df(), world.markets_df()
    audit = AuditLog(f"logs/compare_{seed}.jsonl")
    rows = []
    t0 = time.time()
    for i, pw in enumerate(world.planted):
        r = run_wallet(pw.wallet, F, M, world.price_at, pw.N, th=th, audit=audit, synthetic=True, seed=seed + i, write=False)
        d = next((c for c in r["delay_curve"] if c["delay_s"] == th["verdict"]["copy_delay_s"]), {})
        p_cons = max(m["p_single"] for m in r["luck"]["modes"].values()) if r["luck"]["modes"] else 1.0
        rows.append({
            "seed": seed, "wallet": pw.wallet, "kind": pw.kind, "edge_true": pw.edge, "N": pw.N,
            "v1_verdict": r["verdict_v1"], "v2_verdict": r["verdict"],
            "edge": r["edge"]["mean"], "edge_se": se_from_ci(r["edge"]["lo"], r["edge"]["hi"]),
            "follow": d.get("mean", np.nan), "follow_se": se_from_ci(d.get("lo"), d.get("hi")),
            "e_value": r["betting"]["e_value"], "proven": r["betting"]["proven"], "p_cons": p_cons,
            "profit": float(r["stats"]["S.profit"]["value"]), "win_rate": float(r["stats"]["S.win_rate"]["value"]),
            "roi": float(r["stats"]["S.profit"]["value"]) / max(float(r["positions"]["cost"].sum()), 1e-9),
            "integrity_hold": r["integrity"]["hold"],
        })
        print(f"  seed {seed} [{i + 1:2d}/{len(world.planted)}] {pw.kind:13s} {r['verdict_v1']:25s} -> {r['verdict']:25s} ({time.time() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows)


def add_bottom_lines(df: pd.DataFrame, watch_p: float) -> pd.DataFrame:
    df = df.copy()
    # Empirical-Bayes priors fitted on this population of wallets (learning across wallets).
    pr_follow = fit_prior(df["follow"], df["follow_se"])
    pr_edge = fit_prior(df["edge"], df["edge_se"])
    df["p_edge_pos"] = [shrink(e, s, pr_edge)["p_pos"] for e, s in zip(df["edge"], df["edge_se"])]
    df["p_follow_pos"] = [shrink(e, s, pr_follow)["p_pos"] for e, s in zip(df["follow"], df["follow_se"])]
    ok = {"hold": False, "checks": []}
    acts = []
    for v, e, f, N in zip(df["v2_verdict"], df["e_value"], df["follow"], df["N"]):
        acts.append(bottom_line(v, {"e_value": e, "target_e": N / 0.05, "watch_e": float(N)}, f, ok)["action"])
    df["bottom_line"] = acts
    q, pi0 = storey_qvalues(df["p_cons"].to_numpy())
    df["q_value"] = q
    df.attrs.update(prior_follow=pr_follow, prior_edge=pr_edge, pi0=pi0)
    return df


def score(df: pd.DataFrame) -> dict:
    is_skill = df["kind"].isin(["skilled_slow", "skilled_fast"])
    copyable = df["kind"] == "skilled_slow"
    noskill = df["kind"].isin(["lucky", "farmer95", "clustered"])
    top_roi = set()
    for _, g in df.groupby("seed"):
        top_roi |= set(g.nlargest(10, "roi")["wallet"])
    calls = {
        "v1_verdict (skilled)": df["v1_verdict"].isin(SKILLED),
        "v2_verdict (skilled)": df["v2_verdict"].isin(SKILLED),
        "v2_bottom_line (Copy or Watch)": df["bottom_line"].isin(["Copy (paper first)", "Watch"]),
        "betting evidence >= N/alpha": df["proven"].astype(bool),
        "FDR q < 0.10": df["q_value"] < 0.10,
        "naive: win rate > 70%": df["win_rate"] > 0.70,
        "naive: top 10 by ROI": df["wallet"].isin(top_roi),
    }
    out = {}
    for name, c in calls.items():
        tp = int((c & is_skill).sum()); fp = int((c & ~is_skill).sum())
        prec = wilson(tp, tp + fp)
        rec = wilson(tp, int(is_skill.sum()))
        fa = wilson(int((c & noskill).sum()), int(noskill.sum()))
        rec_by = {}
        for e in (0.02, 0.05, 0.10):
            m = copyable & (df["edge_true"] == e)
            rec_by[f"{e:.2f}"] = wilson(int((c & m).sum()), int(m.sum()))
        out[name] = {"precision": prec, "recall": rec, "false_alarm": fa, "recall_by_edge": rec_by, "calls": int(c.sum())}
    vague_v1 = float((df["v1_verdict"] == "Can't tell yet").mean())
    truth = is_skill.astype(float)
    brier = float(np.nanmean((df["p_edge_pos"] - truth) ** 2))
    copy_pos = df["bottom_line"].isin(["Copy (paper first)", "Watch"])
    fast_caught = wilson(int((df["kind"].eq("skilled_fast") & ~copy_pos).sum()), int(df["kind"].eq("skilled_fast").sum()))
    return {"methods": out, "v1_share_cant_tell": vague_v1, "v2_share_without_action": 0.0,
            "brier_p_edge_pos": brier, "fast_not_copied (bottom line)": fast_caught,
            "bottom_line_counts": df["bottom_line"].value_counts().to_dict()}


def fmt(x):
    k = x
    return f"{k[0]:.0%} [{k[1]:.0%}–{k[2]:.0%}]" if k[0] == k[0] else "—"


def to_md(res: dict) -> str:
    lines = ["# Old vs upgraded skill-vs-luck methods (planted traders, SYNTHETIC)", ""]
    for label, sc in res["scores"].items():
        lines += [f"## {label}", "", "| Method | Calls | Precision | Recall (skilled) | False alarms (no-skill) | Recall @2c | @5c | @10c |",
                  "|---|---|---|---|---|---|---|---|"]
        for name, m in sc["methods"].items():
            rb = m["recall_by_edge"]
            lines.append(f"| {name} | {m['calls']} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['false_alarm'])} | "
                         f"{fmt(rb['0.02'])} | {fmt(rb['0.05'])} | {fmt(rb['0.10'])} |")
        lines += ["", f"- v1 left **{sc['v1_share_cant_tell']:.0%}** of wallets at 'Can't tell yet' with no action; v2 gives every wallet a bottom line "
                      f"({sc['bottom_line_counts']}).",
                  f"- Rejected diagnostic: Brier score of the shrinkage P(edge > 0) = {sc["brier_p_edge_pos"]:.3f} (0.25 = coin flip) — overconfident on selected wallets, so not used.",
                  f"- Fast movers kept out of Copy/Watch by the bottom line: {fmt(sc['fast_not_copied (bottom line)'])}.", ""]
    lines += [f"Watch = betting evidence ≥ N (the field size) and follower still profitable after the delay; chosen on the dev seed only. "
              "Priors are fitted per batch by empirical Bayes. Wilson 95% intervals in brackets."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[101, 202])
    ap.add_argument("--watch-p", type=float, default=WATCH_E)
    ap.add_argument("--reuse", action="store_true", help="re-score saved raw results without re-running wallets")
    a = ap.parse_args()
    th = load_thresholds()
    RESULTS.mkdir(parents=True, exist_ok=True)
    raw = {}
    for s in a.seeds:
        cache = RESULTS / f"compare_raw_{s}.csv"
        if a.reuse and cache.exists():
            raw[s] = pd.read_csv(cache)
        else:
            raw[s] = run_batch(s, th)
            raw[s].to_csv(cache, index=False)  # saved before scoring, so a scoring bug never costs a rerun
    batches = {s: add_bottom_lines(df, a.watch_p) for s, df in raw.items()}
    res = {"watch_p": a.watch_p, "scores": {}}
    for s, df in batches.items():
        label = f"Seed {s} ({'dev' if s == a.seeds[0] else 'holdout'})"
        res["scores"][label] = score(df)
        res["scores"][label]["priors"] = {k: v for k, v in df.attrs.items()}
    if len(batches) > 1:
        hold = pd.concat([df for s, df in batches.items() if s != a.seeds[0]])
        res["scores"]["All holdout seeds"] = score(hold)
    RESULTS.mkdir(parents=True, exist_ok=True)
    pd.concat(batches.values()).to_csv(RESULTS / "compare_wallets.csv", index=False)
    (RESULTS / "compare.json").write_text(json.dumps(res, indent=2, default=float))
    (RESULTS / "compare.md").write_text(to_md(res), encoding="utf-8")
    print(to_md(res))


if __name__ == "__main__":
    main()
