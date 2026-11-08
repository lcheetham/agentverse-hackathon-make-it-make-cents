"""Live mode (run as a labelled replay): the agent proposes a paper copy, a human approves or rejects.

The proposal is scored and explained by code only; no LLM is involved.
"""
from __future__ import annotations

from ..controls import PaperLedger, Proposal, SKILLED


def propose(trader: str, bet: dict, report: dict, ledger: PaperLedger, controls: dict, price_now: float | None,
            category: str, cluster: str, stake_frac: float = 0.04) -> Proposal:
    """bet: {token_id, title, leader_price}. Returns a Proposal the human then approves or rejects."""
    reasons, action = [], "copy"
    verdict = report["verdict"]
    bl = (report.get("bottom_line") or {}).get("action", "")
    if bl.startswith("Hold") or bl == "Watch":
        # Unsure: the agent does not decide; it holds and asks the human (who must give a reason to copy).
        action = "hold"
        reasons.append(f"Agent is unsure ({bl}): {report['bottom_line']['why']} Asking a human.")
    elif verdict not in SKILLED:
        action = "skip"
        reasons.append(f"Trader verdict is '{verdict}'.")
    elif verdict == "Skilled but not copyable":
        action = "skip"
        reasons.append("The trader's edge does not survive copy delay; copying is unlikely to capture it.")
    cat_row = next((c for c in report["categories"] if c["category"] == category), None)
    if cat_row is None or cat_row["n"] < 10:
        reasons.append(f"Little history in '{category}' ({0 if cat_row is None else cat_row['n']} positions).")
    elif verdict not in SKILLED:
        reasons.append(f"{cat_row['n']} past positions in '{category}', but the overall record is not established, so category results are not evidence of skill.")
    elif cat_row["lo"] == cat_row["lo"] and cat_row["lo"] > 0:
        reasons.append(f"'{category}' is where the edge is: {cat_row['edge']:.1%} per position (CI lower bound {cat_row['lo']:.1%}).")
    else:
        reasons.append(f"Edge in '{category}' is not established (CI includes zero).")
    if price_now is None:
        action = "skip"
        reasons.append("Market is closed or has no current price.")
    else:
        move = price_now - bet["leader_price"]
        reasons.append(f"Price has moved {move * 100:+.1f}c since the leader entered.")
        if abs(move) > controls["stale_price_move"]:
            action = "skip"
    overlap = ledger.cluster_exposure(cluster)
    if overlap > 0:
        reasons.append(f"You already hold £{overlap:.2f} in this event cluster.")
    stake = round(stake_frac * ledger.bankroll, 2)
    p = Proposal(trader=trader, token_id=bet["token_id"], cluster=cluster, title=bet["title"],
                 leader_price=bet["leader_price"], current_price=price_now, stake=stake, action=action,
                 reasons=reasons, verdict=verdict)
    return p
