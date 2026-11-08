"""Deterministic verdict rules. The LLM never chooses a verdict."""
from __future__ import annotations

import math


def decide(edge: dict, n_clusters: int, luck_n: float, delayed_edge: dict | None, th: dict,
           betting_proven: bool = False) -> tuple[str, list[str]]:
    """Return (verdict, reasons). Rules are applied in order; the first match wins.

    1. Luck(N_eff) >= luck_probably                                 -> Probably luck
    2. clusters < min, or edge CI touches 0, or
       (Luck >= skilled_max and betting evidence < N/alpha)          -> Can't tell yet
    3. edge at the copy delay (after costs) has CI lower bound > 0  -> Skilled and copyable
    4. otherwise                                                    -> Skilled but not copyable

    v2: betting evidence >= N/alpha (testing by betting, Ville's inequality with a Bonferroni factor N)
    is a second, independently valid proof of skill against the field. On planted traders it kept
    0 false alarms and raised recall (eval/results/compare.md).
    """
    v = th["verdict"]
    if not math.isnan(luck_n) and luck_n >= v["luck_probably"]:
        return "Probably luck", [
            f"Luck score {luck_n:.0%} >= {v['luck_probably']:.0%}: a field of no-skill traders this size produces someone this good more often than not."
        ]
    reasons = []
    if n_clusters < v["min_clusters"]:
        reasons.append(f"Only {n_clusters} independent event clusters (< {v['min_clusters']}); the record is too thin.")
    lo = edge.get("lo", float("nan"))
    if math.isnan(lo) or lo <= 0:
        reasons.append("The edge's 95% CI includes zero.")
    if (math.isnan(luck_n) or luck_n >= v["luck_skilled_max"]) and not betting_proven:
        reasons.append(f"Luck score {luck_n:.0%} is not below {v['luck_skilled_max']:.0%}, and the betting evidence has not reached N/5%.")
    if reasons:
        return "Can't tell yet", reasons
    d_lo = (delayed_edge or {}).get("lo", float("nan"))
    hours = v["copy_delay_s"] / 3600
    if not math.isnan(d_lo) and d_lo > 0:
        return "Skilled and copyable", [
            f"Edge CI excludes zero, luck score {luck_n:.1%}, and the edge survives a {hours:g} h copy delay after costs."
        ]
    return "Skilled but not copyable", [
        f"Edge CI excludes zero and luck score {luck_n:.1%}, but after a {hours:g} h delay and costs the follower's edge CI includes zero."
    ]
