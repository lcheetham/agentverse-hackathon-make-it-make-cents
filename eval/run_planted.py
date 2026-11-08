"""Evaluation A: planted traders with known truth.

    python -m eval.run_planted --batch dev            # build/tune freely
    python -m eval.run_planted --freeze               # record the freeze hash (thresholds + engine + prompts)
    python -m eval.run_planted --batch test --seed N  # fresh seed, runs ONCE against the frozen hash

A second test run, or a test run after the hash changed, is refused unless --rerun is given,
in which case the results are stamped CONTAMINATED.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ctdd.agent.text_jobs import cluster_agreement
from ctdd.audit import AuditLog
from ctdd.config import EVAL_DIR, freeze_hash, load_thresholds
from ctdd.data.synthetic import planted_batch
from ctdd.engine.stats import wilson
from ctdd.pipeline import run_wallet

RESULTS = EVAL_DIR / "results"
FREEZE = EVAL_DIR / "freeze.json"
SKILLED = {"Skilled and copyable", "Skilled but not copyable"}
METHODS = ("verdict", "naive_top10_roi", "naive_top10", "naive_winrate70")
METHOD_NAMES = {"verdict": "Agent", "naive_top10_roi": "Naive: top 10 by ROI ('up 400%')",
                "naive_top10": "Naive: top 10 by profit", "naive_winrate70": "Naive: win rate > 70%"}


def _rate(mask_success, mask_total) -> dict:
    n = int(mask_total.sum())
    k = int((mask_success & mask_total).sum())
    p, lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": p, "lo": lo, "hi": hi}


def metrics(df: pd.DataFrame, col: str) -> dict:
    called_skilled = df[col].isin(SKILLED)
    not_skilled_truth = df["kind"].isin(["lucky", "farmer95", "clustered"])
    out = {
        "false_alarm_rate (no-skill called skilled)": _rate(called_skilled, not_skilled_truth),
        "cluster_trap_caught (not called skilled)": _rate(~called_skilled, df["kind"] == "clustered"),
        "lucky_caught (not called skilled)": _rate(~called_skilled, df["kind"] == "lucky"),
        "farmer_caught (not called skilled)": _rate(~called_skilled, df["kind"] == "farmer95"),
    }
    for e in sorted(df.loc[df["kind"] == "skilled_slow", "edge"].unique()):
        m = (df["kind"] == "skilled_slow") & (df["edge"] == e)
        out[f"detection_rate edge={e:.2f}"] = _rate(called_skilled, m)
    out["not_copyable_caught (fast -> 'Skilled but not copyable')"] = _rate(df[col] == "Skilled but not copyable", df["kind"] == "skilled_fast")
    out["copyable_correct (slow & detected -> 'copyable')"] = _rate(df[col] == "Skilled and copyable", (df["kind"] == "skilled_slow") & called_skilled)
    return out


def run(batch: str, seed: int, scale: int, rerun: bool) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    h = freeze_hash()
    contaminated = False
    if batch == "test":
        if not FREEZE.exists():
            raise SystemExit("Refusing: run --freeze after tuning on the dev batch first.")
        frozen = json.loads(FREEZE.read_text())
        out_path = RESULTS / "test.json"
        if frozen["hash"] != h or out_path.exists():
            if not rerun:
                why = "hash changed since freeze" if frozen["hash"] != h else "test batch already run once"
                raise SystemExit(f"Refusing: {why}. Use --rerun to proceed; results will be stamped CONTAMINATED.")
            contaminated = True
    audit = AuditLog(Path("logs") / f"eval_{batch}.jsonl")
    th = load_thresholds()
    t0 = time.time()
    world = planted_batch(seed=seed, scale=scale)
    F, M = world.fills_df(), world.markets_df()
    rows = []
    for i, pw in enumerate(world.planted):
        r = run_wallet(pw.wallet, F, M, world.price_at, pw.N, th=th, audit=audit, synthetic=True, seed=seed + i, write=False)
        pos = r["positions"]
        closed = pos[pos["status"] != "open"]
        row = {
            "wallet": pw.wallet, "kind": pw.kind, "edge": pw.edge, "expected": pw.expected, "N": pw.N,
            "verdict": r["verdict"], "n_positions": len(closed), "profit": float(closed["pnl"].sum()),
            "roi": float(closed["pnl"].sum() / closed["cost"].sum()) if len(closed) else float("nan"),
            "win_rate": float((closed["pnl"] > 0).mean()), "edge_hat": r["edge"]["mean"], "edge_lo": r["edge"]["lo"],
            "n_clusters": r["edge"]["n_clusters"], "luck": r["luck_n"],
            "edge_1h_lo": r["stats"].get("S.edge_delay.3600", {}).get("lo"), "cluster_method": r["cluster_method"],
        }
        if pw.kind == "clustered":
            truth = {c: s for c, s in world.story_of.items() if c in r["clusters"]}
            row["cluster_agreement"] = cluster_agreement(r["clusters"], truth)
        rows.append(row)
        print(f"[{i + 1:3d}/{len(world.planted)}] {pw.kind:13s} edge={pw.edge:.2f} -> {r['verdict']:26s} luck={r['luck_n']:.3g} ({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    # Baselines on identical wallets
    top10 = set(df.nlargest(10, "profit")["wallet"])
    df["naive_top10"] = np.where(df["wallet"].isin(top10), "Skilled and copyable", "Can't tell yet")
    top10_roi = set(df.nlargest(10, "roi")["wallet"])
    df["naive_top10_roi"] = np.where(df["wallet"].isin(top10_roi), "Skilled and copyable", "Can't tell yet")
    df["naive_winrate70"] = np.where(df["win_rate"] > 0.70, "Skilled and copyable", "Can't tell yet")
    res = {
        "batch": batch, "seed": seed, "scale": scale, "freeze_hash": h, "contaminated": contaminated,
        "synthetic": True, "n_wallets": len(df), "runtime_s": round(time.time() - t0, 1),
        "methods": {c: metrics(df, c) for c in METHODS},
        "cluster_agreement_mean": float(df["cluster_agreement"].mean()) if "cluster_agreement" in df else None,
        "confusion": pd.crosstab(df["kind"] + " " + df["edge"].map(lambda e: f"{e:.2f}" if e else ""), df["verdict"]).to_dict(),
    }
    df.to_csv(RESULTS / f"{batch}_wallets.csv", index=False)
    (RESULTS / f"{batch}.json").write_text(json.dumps(res, indent=2, default=float))
    (RESULTS / f"{batch}.md").write_text(to_markdown(res), encoding="utf-8")
    audit.log("eval_run", batch=batch, seed=seed, freeze_hash=h, contaminated=contaminated, n=len(df))
    return res


def to_markdown(res: dict) -> str:
    lines = [f"# Planted-trader evaluation — {res['batch']} batch (SYNTHETIC)", "",
             f"Seed {res['seed']} · {res['n_wallets']} wallets · freeze hash `{res['freeze_hash']}`"
             + (" · **CONTAMINATED**" if res["contaminated"] else ""), "",
             "| Metric | " + " | ".join(METHOD_NAMES[m] for m in METHODS) + " |", "|---" * (len(METHODS) + 1) + "|"]
    names = list(res["methods"]["verdict"].keys())
    for name in names:
        cells = []
        for m in METHODS:
            x = res["methods"][m][name]
            cells.append(f"{x['rate']:.0%} ({x['k']}/{x['n']}, CI {x['lo']:.0%}–{x['hi']:.0%})" if x["n"] else "—")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    if res.get("cluster_agreement_mean") is not None:
        lines += ["", f"Cluster agreement with true stories (Rand index, clustered wallets): {res['cluster_agreement_mean']:.2f}"]
    lines += ["", "Wilson 95% intervals. Synthetic traders are simpler than real ones; accuracy may not transfer exactly."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=["dev", "test"], default="dev")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--rerun", action="store_true")
    a = ap.parse_args()
    if a.freeze:
        FREEZE.write_text(json.dumps({"hash": freeze_hash(), "frozen_at": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))
        print("Frozen:", freeze_hash())
        return
    seed = a.seed if a.seed is not None else (101 if a.batch == "dev" else int(time.time()) % 1_000_000)
    res = run(a.batch, seed, a.scale, a.rerun)
    print(to_markdown(res))


if __name__ == "__main__":
    main()
