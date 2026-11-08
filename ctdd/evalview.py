"""Evaluation results for the web UI, read from Diego's saved runs (eval/results/). Nothing is re-run here.

planted     : holdout seed 303 from eval/compare_methods.py (thresholds chosen on dev seed 101 only), SYNTHETIC
planted_large: 1,003 wallets from the Streamlit prototype's generator, scored by the same frozen engine
              (eval/run_large_planted.py), with the prototype engine's verdicts alongside, SYNTHETIC
walkforward : real Polymarket wallets, cut-off 24 Oct 2026, from eval/walkforward.py, REAL DATA
"""
from __future__ import annotations

import json
import math
import time

import pandas as pd

from .adapter import CODES
from .config import EVAL_DIR
from .engine.stats import wilson

RES = EVAL_DIR / "results"
# Engine v2 (v0.7.0): grouping fix. Its results live in their own folder; engine v1's original runs stay in RES.
ENGINE_RES = RES / "v2_engine"
V1_FRESH = RES / "v1_engine_seed4242"       # engine v1 on the same fresh batch, for the side-by-side
FRESH_SEED = 4242
ENGINE_HASHES = {"v1": "92465b6b62360be3", "v2": "1e14c2d1e9f39823"}
SKILLED = ("Skilled and copyable", "Skilled but not copyable")
OK = {  # verdicts that count as correct for each planted type
    "skilled_slow": {"Skilled and copyable"},
    "skilled_fast": {"Skilled but not copyable"},
    "lucky": {"Probably luck", "Can't tell yet"},
    "farmer95": {"Probably luck", "Can't tell yet"},
    "clustered": {"Can't tell yet", "Probably luck"},
}
NO_SKILL = ("lucky", "farmer95", "clustered")


def _rate(k: int, n: int) -> dict:
    lo, hi = (wilson(k, n)[1:] if n else (None, None))
    return {"k": int(k), "n": int(n), "rate": (k / n) if n else None, "ci_low": lo, "ci_high": hi}


def _clean(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def _engine_metrics(w: pd.DataFrame) -> dict:
    v = w["v2_verdict"]
    skilled_call, no_skill = v.isin(SKILLED), w["kind"].isin(NO_SKILL)
    skilled_true, approved = w["kind"].isin(("skilled_slow", "skilled_fast")), v == "Skilled and copyable"
    ok = sum(r.v2_verdict in OK[r.kind] for r in w.itertuples(index=False))
    return {"false_alarm": _rate(int((skilled_call & no_skill).sum()), int(no_skill.sum())),
            "precision": _rate(int((approved & (w["kind"] == "skilled_slow")).sum()), int(approved.sum())),
            "detection": _rate(int((skilled_call & skilled_true).sum()), int(skilled_true.sum())),
            "correct": _rate(int(ok), int(len(w)))}


def planted(seed: int = FRESH_SEED, folder=ENGINE_RES) -> dict | None:
    path = folder / "compare_wallets.csv"
    if not path.exists():
        return None
    w = pd.read_csv(path)
    w = w[w["seed"] == seed]
    v = w["v2_verdict"]
    skilled_call = v.isin(SKILLED)
    no_skill = w["kind"].isin(NO_SKILL)
    skilled_true = w["kind"].isin(("skilled_slow", "skilled_fast"))
    approved = v == "Skilled and copyable"
    metrics = [
        {"name": "False alarms: no-skill wallet (lucky, 95c farmer, cluster trap) called skilled", "key": "false_alarm",
         **_rate(int((skilled_call & no_skill).sum()), int(no_skill.sum()))},
        {"name": "Precision: wallets rated 'Skilled and copyable' that truly were", "key": "precision",
         **_rate(int((approved & (w["kind"] == "skilled_slow")).sum()), int(approved.sum()))},
        {"name": "Detection: truly skilled wallets found (either skilled verdict)", "key": "detection",
         **_rate(int((skilled_call & skilled_true).sum()), int(skilled_true.sum()))},
        {"name": "Uncopyable skill caught as 'Skilled but not copyable'", "key": "not_copyable_catch",
         **_rate(int(((w["kind"] == "skilled_fast") & (v == "Skilled but not copyable")).sum()), int((w["kind"] == "skilled_fast").sum()))},
        {"name": "Cluster traps not called skilled", "key": "cluster_trap_catch",
         **_rate(int(((w["kind"] == "clustered") & ~skilled_call).sum()), int((w["kind"] == "clustered").sum()))},
        {"name": "95c farmers not called skilled", "key": "farmer_catch",
         **_rate(int(((w["kind"] == "farmer95") & ~skilled_call).sum()), int((w["kind"] == "farmer95").sum()))},
        {"name": "Leaderboard winners of 1,000 coin-flippers not called skilled", "key": "lucky_catch",
         **_rate(int(((w["kind"] == "lucky") & ~skilled_call).sum()), int((w["kind"] == "lucky").sum()))},
    ]
    power = []
    for e, g in w[w["kind"] == "skilled_slow"].groupby("edge_true"):
        power.append({"edge": float(e), **_rate(int((g["v2_verdict"] == "Skilled and copyable").sum()), len(g))})
    confusion = {k: {CODES[c]: int(n) for c, n in g["v2_verdict"].value_counts().items()} for k, g in w.groupby("kind")}

    baselines = []
    comp = json.loads((folder / "compare.json").read_text())["scores"].get(f"Seed {seed} (holdout)", {}).get("methods", {})
    n_ns, n_sk = int(no_skill.sum()), int(skilled_true.sum())
    for name, key in (("Copy the top 10 by ROI ('up 400%')", "naive: top 10 by ROI"), ("Win rate > 70% = skilled", "naive: win rate > 70%")):
        m = comp.get(key)
        if m:
            fa, rc = m["false_alarm"], m["recall"]
            baselines.append({"name": name, "key": key,
                              "false_alarm": {"k": round(fa[0] * n_ns), "n": n_ns, "rate": fa[0], "ci_low": fa[1], "ci_high": fa[2]},
                              "detection": {"k": round(rc[0] * n_sk), "n": n_sk, "rate": rc[0], "ci_low": rc[1], "ci_high": rc[2]}})

    errors = []
    for r in w.itertuples(index=False):
        if r.v2_verdict not in OK[r.kind]:
            errors.append({"wallet": r.wallet, "planted": r.kind, "true_edge": r.edge_true, "verdict": r.v2_verdict,
                           "profit": r.profit, "win_rate": r.win_rate})
    engines = [{"name": "Engine v2 (this build)", "hash": ENGINE_HASHES["v2"], **_engine_metrics(w)}]
    v1p = V1_FRESH / "compare_wallets.csv"
    if v1p.exists():
        w1 = pd.read_csv(v1p)
        w1 = w1[w1["seed"] == seed]
        if len(w1):
            engines.append({"name": "Engine v1 (v0.6.0)", "hash": ENGINE_HASHES["v1"], **_engine_metrics(w1),
                            "changed": int((w.set_index("wallet")["v2_verdict"] != w1.set_index("wallet")["v2_verdict"]).sum())})
    return _clean({
        "engines": engines,
        "label": f"SYNTHETIC planted traders (fresh seed {seed})", "batch": "holdout", "dev_seeds": [101], "test_seeds": [seed],
        "n_wallets": int(len(w)), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
        "metrics": metrics, "power_curve": power, "confusion": confusion, "baselines": baselines, "errors": errors,
        "notes": [
            f"Seed {seed} had never been used. It was run once, after engine v2 was frozen (hash {ENGINE_HASHES['v2']}), "
            f"with both engines. Thresholds are unchanged since they were set on dev seed 101.",
            "Engine v1's original holdout (seed 303) is kept in the repo (eval/results/compare.md).",
            "The one false alarm is a cluster trap: three election stories, every bet won. The grouping split each "
            "story in two, because the place name appeared in so many of this trader's markets that an existing rule "
            "treats it as a common word. Engines v1 and v2 share that rule and both made this error. It was found on "
            "test data, so it is reported here, not fixed: a fix needs another fresh batch to be tested on.",
            "Planted traders are simpler than real ones; accuracy may not transfer exactly.",
            "Every miss is listed above. All errors are skilled traders the agent did not clear: it leans cautious by design.",
            "A small edge needs a very long record: a 5c edge needs roughly 2,000+ bets to stand out from a 1,000-wallet field.",
        ],
    })


def walkforward() -> dict | None:
    v2 = ENGINE_RES / "walkforward.json"
    path = v2 if v2.exists() else RES / "walkforward.json"
    if not path.exists():
        return None
    engine_note = (f"Run with engine v2 (hash {ENGINE_HASHES['v2']})." if path == v2 else
                   f"Run with engine v1 (hash {ENGINE_HASHES['v1']}). Re-running it with engine v2 needs internet access "
                   f"(README: 'Re-running the real-data test').")
    d = json.loads(path.read_text())
    t, a, diff = d["top10"], d["agent_approved"], d["approved_minus_top10"]
    cutoff = pd.Timestamp(d["cutoff_utc"], tz="UTC").timestamp()
    return _clean({
        "label": f"REAL Polymarket wallets (live public data), cut-off {d['cutoff_utc'][:10]}",
        "real": True, "cutoff_ts": cutoff, "copy_delay_s": d["delay_s"], "n_wallets": d["judged"], "universe": d["universe"],
        "n_positions_after": t["copies"], "n_agent_approved": a["n_wallets"],
        "top10": {"return": t["mean_ret"], "ci_low": t["lo"], "ci_high": t["hi"], "n_positions": t["copies"],
                  "max_drawdown": t["max_drawdown_on_200"], "leader_return": t["leader_mean_ret_same_positions"]},
        "agent": {"return": None if a["n_wallets"] == 0 else a["mean_ret"], "n_positions": a["copies"],
                  "holds_cash": a["n_wallets"] == 0},
        # Point estimate = agent return minus top-10 return (so the three numbers on screen add up). The
        # interval is the paired cluster bootstrap from eval/walkforward.py; older result files stored the
        # bootstrap's average as "mean", which differs slightly from the point estimate.
        "diff": {"mean": (a["mean_ret"] if a["n_wallets"] else 0.0) - t["mean_ret"], "ci_low": diff["lo"], "ci_high": diff["hi"]},
        "verdict_counts": d["verdict_counts"],
        "notes": [
            f"The agent judged {d['judged']} leaderboard wallets as of the cut-off: "
            f"{', '.join(f'{n} {v}' for v, n in sorted(d['verdict_counts'].items(), key=lambda kv: -kv[1]))}. "
            f"It approved none, so it held cash.",
            "Abstaining beat copying the top 10 by the difference shown: evidence the leaderboard was not worth copying, "
            "not evidence that the agent picks winners (it picked none).",
            *d.get("bias_notes", []),
            engine_note,
        ],
    })


def planted_large() -> dict | None:
    path = ENGINE_RES / "planted_large.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    r = lambda x: {"rate": x["rate"], "ci_low": x["lo"], "ci_high": x["hi"], "k": x["k"], "n": x["n"]}  # noqa: E731
    judges = [{"key": k, "name": ("Engine v2 (this build)" if k == "engine" else j["name"]), "copy_calls": j["copy_calls"],
               "no_skill_copied": r(j["recommends copying a no-skill wallet"]),
               "precision": r(j["precision (of copy calls, truly skilled & copyable)"])}
              for k, j in d["judges"].items()]
    old = RES / "planted_large.json"                       # engine v1's run on the same wallets
    if old.exists():
        j = json.loads(old.read_text(encoding="utf-8"))["judges"]["engine"]
        judges.insert(1, {"key": "engine_v1", "name": "Engine v1 (v0.6.0)", "copy_calls": j["copy_calls"],
                          "no_skill_copied": r(j["recommends copying a no-skill wallet"]),
                          "precision": r(j["precision (of copy calls, truly skilled & copyable)"])})
    pretty = {"false_alarm (no-skill called skilled)": "False alarms: no-skill wallet called skilled",
              "overall correct": "Overall: verdict acceptable for the planted type"}
    detail = {k: [{"name": pretty.get(m, m[0].upper() + m[1:]), **r(x)} for m, x in j.items() if isinstance(x, dict) and "k" in x
                  and m not in ("recommends copying a no-skill wallet", "precision (of copy calls, truly skilled & copyable)")]
              for k, j in d["judges"].items() if k in ("engine", "prototype")}
    return _clean({
        "label": "Synthetic, independent generator", "n_wallets": d["n_wallets"], "types": d["types"],
        "freeze_hash": d["freeze_hash"], "judges": judges, "detail": detail, "power_curve": d["power_curve"],
        "notes": [
            "This batch was already used to test engine v1, so for engine v2 it is a second look, not a fresh test. "
            "The fresh test of v2 is Test 1's new seed.",
            "Made by a different generator (the Streamlit prototype's) that this engine was never tuned on. "
            "The prototype engine was tuned on this generator's dev batch, so it has home advantage here.",
            "Both engines recommended 0 of 882 no-skill wallets. This engine is more cautious: it clears fewer "
            "skilled traders and catches fewer 'buys just before news' traders as not copyable.",
            "Costs use this engine's frozen settings, not the batch's per-market fees. Related bets are grouped by "
            "the engine's own heuristic; the batch's true event ids are never shown to it.",
        ],
    })


def evaluation() -> dict:
    return {"planted": planted(), "planted_large": planted_large(), "walkforward": walkforward()}
