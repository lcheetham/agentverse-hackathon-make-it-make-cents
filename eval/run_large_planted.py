"""Evaluation A2: the frozen engine on a large, independently generated planted batch.

    python -m eval.run_large_planted                      # data/planted_large -> eval/results/planted_large.*

Why this exists: eval/run_planted.py tests the engine on 58 wallets from our own generator
(ctdd/data/synthetic.py). This run uses 1,003 wallets made by a *different* generator (the
Streamlit prototype's copytrader/data/generate.py, seed 2), which the engine was never tuned on.
The engine, prompts and thresholds are not touched, so the freeze hash is unchanged; the hash is
recorded in the results so anyone can check.

The batch also carries the prototype engine's own verdicts on the same wallets
(data/planted_large/prototype_verdicts.csv), so the two engines can be compared like for like.

Truth types: skilled (win prob = price + edge, slow prices -> copyable), slow (skilled, but buys just
before news so a follower is too late -> not copyable), luck (a 700-wallet no-skill field), farmer
(buys at >= 95c), clustered (many bets on a few related stories). SYNTHETIC DATA.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from ctdd.audit import AuditLog
from ctdd.config import EVAL_DIR, ROOT, freeze_hash, load_thresholds
from ctdd.data.csvset import load_csv_dataset
from ctdd.engine.stats import wilson
from ctdd.pipeline import run_wallet

RESULTS = EVAL_DIR / "results"
SKILLED = {"Skilled and copyable", "Skilled but not copyable"}
NO_SKILL = ("luck", "farmer", "clustered")
# What counts as a correct verdict for each planted type (same definition the prototype used).
CORRECT = {
    "skilled": {"Skilled and copyable"},
    "slow": {"Skilled but not copyable"},
    "luck": {"Probably luck", "Can't tell yet"},
    "farmer": {"Probably luck"},
    "clustered": {"Can't tell yet", "Probably luck"},
}
NO_SKILL_COPY = "recommends copying a no-skill wallet"
PRECISION = "precision (of copy calls, truly skilled & copyable)"
EDGE_BINS = [0.02, 0.06, 0.10, 0.14, 0.20001]
JUDGES = {
    "engine": "This engine (frozen)",
    "prototype": "Prototype engine (Streamlit build)",
    "naive_top10": "Naive: top 10 by profit",
    "naive_top10_roi": "Naive: top 10 by ROI ('up 400%')",
    "naive_winrate70": "Naive: win rate > 70%",
}


def _rate(success, total) -> dict:
    n, k = int(total.sum()), int((success & total).sum())
    p, lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": p, "lo": lo, "hi": hi}


def score(data_dir: Path, limit: int | None = None) -> pd.DataFrame:
    d = load_csv_dataset(data_dir)
    th = load_thresholds()
    audit = AuditLog(ROOT / "logs" / "eval_planted_large.jsonl")
    truth = d.truth if limit is None else d.truth.head(limit)
    N = len(d.truth)                     # the whole planted field is the population a leader is picked from
    rows, t0 = [], time.time()
    for i, w in enumerate(truth.itertuples(index=False)):
        r = run_wallet(w.wallet, d.fills, d.markets, d.price_at, N, th=th, audit=audit,
                       synthetic=True, seed=i, write=False)
        closed = r["positions"][r["positions"]["status"] != "open"]
        cost = float(closed["cost"].sum())
        rows.append({
            "wallet": w.wallet, "true_type": w.true_type, "true_edge": float(w.edge),
            "engine": r["verdict"], "n_positions": len(closed), "profit": float(closed["pnl"].sum()),
            "roi": float(closed["pnl"].sum()) / cost if cost else float("nan"),
            "win_rate": float((closed["pnl"] > 0).mean()) if len(closed) else float("nan"),
            "edge_hat": r["edge"]["mean"], "luck": r["luck_n"], "n_clusters": r["edge"]["n_clusters"],
        })
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(truth)} wallets ({time.time() - t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    proto = data_dir / "prototype_verdicts.csv"
    if proto.exists():
        df = df.merge(pd.read_csv(proto)[["wallet", "verdict"]].rename(columns={"verdict": "prototype"}),
                      on="wallet", how="left")
    top10 = set(df.nlargest(10, "profit")["wallet"])
    top10_roi = set(df.nlargest(10, "roi")["wallet"])
    df["naive_top10"] = df["wallet"].isin(top10).map({True: "Skilled and copyable", False: "Can't tell yet"})
    df["naive_top10_roi"] = df["wallet"].isin(top10_roi).map({True: "Skilled and copyable", False: "Can't tell yet"})
    df["naive_winrate70"] = (df["win_rate"] > 0.70).map({True: "Skilled and copyable", False: "Can't tell yet"})
    return df


def summarise(df: pd.DataFrame, data_dir: Path) -> dict:
    no_skill = df["true_type"].isin(NO_SKILL)
    judges = [j for j in JUDGES if j in df]
    res = {"synthetic": True, "data": str(data_dir.relative_to(ROOT) if data_dir.is_relative_to(ROOT) else data_dir),
           "n_wallets": len(df), "freeze_hash": freeze_hash(),
           "types": df["true_type"].value_counts().to_dict(), "judges": {}, "power_curve": {}}
    for j in judges:
        v = df[j]
        copy = v == "Skilled and copyable"
        res["judges"][j] = {
            "name": JUDGES[j],
            "false_alarm (no-skill called skilled)": _rate(v.isin(SKILLED), no_skill),
            NO_SKILL_COPY: _rate(copy, no_skill),
            PRECISION: _rate(df["true_type"] == "skilled", copy),
            "copy_calls": int(copy.sum()),
        }
        if j in ("engine", "prototype"):
            ok = pd.Series([x in CORRECT[t] for x, t in zip(v, df["true_type"])], index=df.index)
            res["judges"][j].update({
                "overall correct": _rate(ok, pd.Series(True, index=df.index)),
                "not-copyable caught (slow -> 'Skilled but not copyable')": _rate(v == "Skilled but not copyable", df["true_type"] == "slow"),
                "95c farmers -> 'Probably luck'": _rate(v == "Probably luck", df["true_type"] == "farmer"),
                "cluster traps not called skilled": _rate(~v.isin(SKILLED), df["true_type"] == "clustered"),
            })
            curve = []
            sk = df["true_type"] == "skilled"
            for lo, hi in zip(EDGE_BINS[:-1], EDGE_BINS[1:]):
                m = sk & (df["true_edge"] >= lo) & (df["true_edge"] < hi)
                curve.append({"edge_bin": f"{lo:.2f}-{min(hi, 0.20):.2f}", **_rate(v == "Skilled and copyable", m)})
            res["power_curve"][j] = curve
    res["confusion_engine"] = pd.crosstab(df["true_type"], df["engine"]).to_dict()
    return res


def _fmt(x: dict) -> str:
    return f"{x['rate']:.1%} [{x['lo']:.1%}, {x['hi']:.1%}] ({x['k']}/{x['n']})" if x["n"] else "—"


def to_markdown(res: dict) -> str:
    L = ["# Planted-trader evaluation, large independent batch (SYNTHETIC)", "",
         f"{res['n_wallets']:,} wallets from a different generator (`{res['data']}`), never used for tuning. "
         f"Engine freeze hash `{res['freeze_hash']}` (unchanged). Types: "
         + ", ".join(f"{k} {v}" for k, v in res["types"].items()) + ".", "",
         "| Judge | Recommends copying a no-skill wallet | Of its 'copy' calls, truly skilled & copyable | 'Copy' calls |",
         "|---|---|---|---|"]
    for j, r in res["judges"].items():
        L.append(f"| {r['name']} | {_fmt(r[NO_SKILL_COPY])} | {_fmt(r[PRECISION])} | {r['copy_calls']} |")
    for j in ("engine", "prototype"):
        if j not in res["judges"]:
            continue
        r = res["judges"][j]
        L += ["", f"## {r['name']}", "", "| Metric | Result |", "|---|---|"]
        for k, x in r.items():
            if isinstance(x, dict) and "k" in x:
                L.append(f"| {k} | {_fmt(x)} |")
        L += ["", "| True edge | Called 'Skilled and copyable' |", "|---|---|"]
        L += [f"| {p['edge_bin']} | {_fmt(p)} |" for p in res["power_curve"][j]]
    L += ["", "Wilson 95% intervals. Costs use this engine's frozen settings (half-spread 0.5c, no fee), not the "
          "per-market costs in the CSV. Related bets are grouped by the engine's own heuristic only: the batch's "
          "event ids are hidden truth and are not shown to the engine. Synthetic traders are simpler than real ones."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "planted_large"))
    ap.add_argument("--limit", type=int, default=None, help="score only the first N wallets (quick check)")
    a = ap.parse_args()
    data_dir = Path(a.data).resolve()
    print(f"Scoring {data_dir} with the frozen engine (hash {freeze_hash()}) ...", flush=True)
    df = score(data_dir, a.limit)
    res = summarise(df, data_dir)
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / "planted_large_wallets.csv", index=False)
    (RESULTS / "planted_large.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    md = to_markdown(res)
    (RESULTS / "planted_large.md").write_text(md, encoding="utf-8")
    print(md)
    print(pd.crosstab(df["true_type"], df["engine"]))


if __name__ == "__main__":
    main()
