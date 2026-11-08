"""The bottom line for the GBP 200 user, and what would change the agent's mind. Deterministic, from engine numbers.

The four strict verdicts (verdict.py) stay. Every report also gets one action:
  Copy (paper first)  strict verdict "Skilled and copyable"
  Watch               not proven, but betting evidence >= N (field size) and a follower still made money after the delay
  Don't copy          luck, uncopyable, copying lost money, or no real evidence
  Hold - human review severe data-integrity problem; the agent will not judge

Why the Watch bar is N: by Ville's inequality each no-skill wallet reaches e >= x with probability <= 1/x, so in a
field of N no-skill wallets the expected number reaching e >= N is <= 1 (a fixed bar like 100x is not selection-safe:
the #1 of 1,000 coin-flippers in the demo reached 196x). Chosen on the dev seed only (eval/compare_methods.py).
A shrinkage-based probability was tested and rejected: it gave lucky and 95c-farmer wallets 77-100% because
shrinking toward the wallets you see cannot undo selection.
"""
from __future__ import annotations

import math

WATCH_E = 100.0


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def bottom_line(verdict: str, betting: dict, delayed_mean: float, integrity: dict) -> dict:
    if integrity.get("hold"):
        bad = "; ".join(c["detail"] for c in integrity["checks"] if c["severe"])
        return {"action": "Hold – human review", "why": f"Input problem the agent won't judge on its own: {bad}."}
    if verdict == "Skilled and copyable":
        return {"action": "Copy (paper first)", "why": "Skill is proven against the field and survives the copy delay after costs."}
    if verdict == "Skilled but not copyable":
        return {"action": "Don't copy", "why": "The skill is real but the price moves before a follower can get in."}
    if verdict == "Probably luck":
        return {"action": "Don't copy", "why": "A field of no-skill traders this size produces a record this good more often than not."}
    e = betting.get("e_value", float("nan"))
    if not _nan(delayed_mean) and delayed_mean < 0:
        return {"action": "Don't copy", "why": "Not proven either way, and copying it after the delay lost money anyway."}
    watch_e = betting.get("watch_e", WATCH_E)
    if not _nan(e) and e >= watch_e and not _nan(delayed_mean) and delayed_mean > 0:
        return {"action": "Watch", "why": f"Not proven yet, but leaning skill: the betting evidence is {e:,.0f}× (proof needs "
                                          f"{betting.get('target_e', float('nan')):,.0f}×) and a follower still made money after the delay."}
    return {"action": "Don't copy", "why": f"Not proven, and the evidence is weak (betting evidence {e:,.1f}×; 'Watch' needs {watch_e:,.0f}×, the field size)."}


def what_would_change(verdict: str, luck_n: float, N: int, th: dict, betting: dict, delayed: dict | None,
                      n_clusters: int, edge: dict) -> list[str]:
    """Concrete, numeric conditions under which the verdict would flip."""
    v = th["verdict"]
    out = []
    need = betting.get("clusters_needed")
    if verdict in ("Can't tell yet", "Probably luck"):
        if need is None:
            out.append("At its current results the evidence is not growing (edge ≤ 0 per event cluster), so more bets of the same kind would not prove skill.")
        elif need > 0:
            out.append(f"About {need} more settled event clusters at its current edge would push the betting evidence past {betting['target_e']:,.0f}× "
                       f"(= N/5% with N = {N:,}), enough to call it skill against this field.")
        if n_clusters < v["min_clusters"]:
            out.append(f"At least {v['min_clusters'] - n_clusters} more independent event clusters are needed before any verdict.")
        if not _nan(edge.get("lo")) and edge["lo"] <= 0:
            out.append(f"The edge's 95% CI ({edge['lo']:.1%} to {edge['hi']:.1%}) would have to move fully above zero.")
    if verdict == "Probably luck" and not _nan(luck_n):
        out.append(f"The luck score ({luck_n:.0%}) would have to fall below {v['luck_probably']:.0%} to leave 'Probably luck', "
                   f"and below {v['luck_skilled_max']:.0%} (or the betting evidence reach N/5%) to count as skill.")
    if verdict.startswith("Skilled"):
        out.append(f"A bigger field (N above ~{_n_flip(luck_n, N, v['luck_skilled_max']):,}) would make this record look like luck "
                   "unless the betting evidence also clears N/5% for that N.")
    d_lo = (delayed or {}).get("lo")
    hours = v["copy_delay_s"] / 3600
    if verdict == "Skilled and copyable" and not _nan(d_lo):
        out.append(f"If the follower's edge after a {hours:g} h delay fell below zero (its CI lower bound is now {d_lo:.1%}), it would become 'not copyable'.")
    if verdict == "Skilled but not copyable":
        out.append(f"Copying faster than {hours:g} h, or a slower-moving market, would be needed for a follower to keep the edge.")
    return out


def _n_flip(luck_n: float, N: int, threshold: float) -> int:
    """Field size at which Luck(N) would reach `threshold`, given Luck at N."""
    if _nan(luck_n) or luck_n <= 0:
        return 10 ** 9
    p = -math.expm1(math.log1p(-min(luck_n, 1 - 1e-12)) / N)
    return int(math.log1p(-threshold) / math.log1p(-p)) if p > 0 else 10 ** 9
