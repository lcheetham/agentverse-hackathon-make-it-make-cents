"""Code-enforced risk controls between the agent and the paper ledger.

The agent may *propose*; only `Policy.check` + a human approval can put a trade on the ledger.
There are no wallet keys or order endpoints anywhere in this codebase (paper only by construction).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .audit import AuditLog

SKILLED = ("Skilled and copyable", "Skilled but not copyable")


@dataclass
class PaperLedger:
    bankroll: float = 200.0
    cash: float = 200.0
    open: list = field(default_factory=list)
    closed: list = field(default_factory=list)
    peak: float = 200.0
    paused: set = field(default_factory=set)
    halted: bool = False  # kill switch: nothing executes until a human re-arms it

    def equity(self) -> float:
        return self.cash + sum(p["stake"] for p in self.open)

    def cluster_exposure(self, cluster: str) -> float:
        return sum(p["stake"] for p in self.open if p["cluster"] == cluster)


@dataclass
class Proposal:
    trader: str
    token_id: str
    cluster: str
    title: str
    leader_price: float
    current_price: float | None
    stake: float
    action: str            # "copy" | "skip"
    reasons: list
    verdict: str


class Policy:
    def __init__(self, controls: dict, audit: AuditLog | None = None):
        self.c = controls
        self.audit = audit or AuditLog()

    def kill_switch(self, ledger: PaperLedger, on: bool, by: str, reason: str = "") -> None:
        ledger.halted = on
        self.audit.log("kill_switch", on=on, by=by, reason=reason)

    def checks(self, p: Proposal, ledger: PaperLedger, override_reason: str | None = None) -> list[dict]:
        """Every control as {control, passed, reason}. Nothing here can be skipped by the agent."""
        from . import killswitch

        c, out = self.c, []
        has_reason = bool(override_reason and override_reason.strip())

        def add(control, passed, ok_text, fail_text):
            out.append({"control": control, "passed": bool(passed), "reason": ok_text if passed else fail_text})

        ks = killswitch.status()
        halted = ks["on"] or getattr(ledger, "halted", False)
        add("kill_switch", not halted, "Kill switch is off.",
            f"Kill switch is ON ({ks.get('reason', 'stopped')}): all copying is stopped until a human turns it off.")
        if p.action == "hold":
            add("agent_hold", has_reason, "Agent was unsure; a human gave a reason to copy anyway.",
                "Agent is unsure (it proposed HOLD): a human must give a reason to copy anyway.")
        cap = c["per_trade_cap"] * ledger.bankroll
        add("per_trade_cap", p.stake <= cap + 1e-9, f"Stake £{p.stake:.2f} is within the £{cap:.2f} cap.",
            f"Per-trade cap: stake £{p.stake:.2f} exceeds £{cap:.2f} ({c['per_trade_cap']:.0%} of bankroll).")
        gate_ok = p.verdict in SKILLED or has_reason
        add("verdict_gate", gate_ok,
            "Trader is rated skilled." if p.verdict in SKILLED else "Overridden with a stated reason (logged).",
            f"Verdict gate: trader is '{p.verdict}'. Copying needs an explicit override with a reason.")
        exposure = ledger.cluster_exposure(p.cluster) + p.stake
        ccap = c["cluster_cap"] * ledger.bankroll
        add("cluster_exposure", exposure <= ccap + 1e-9, f"£{exposure:.2f} in this event cluster, within £{ccap:.2f}.",
            f"Event exposure: £{exposure:.2f} in one event cluster exceeds £{ccap:.2f}.")
        add("drawdown_stop", p.trader not in ledger.paused, "Trader is not paused.",
            "Drawdown stop: copying this trader is paused until a human re-enables it.")
        if p.current_price is None:
            add("stale_price", False, "", "No current price: market closed or unavailable.")
        else:
            move = abs(p.current_price - p.leader_price)
            add("stale_price", move <= c["stale_price_move"], f"Price moved {move * 100:.1f}c since the leader (limit {c['stale_price_move'] * 100:.0f}c).",
                f"Stale price: moved {move * 100:.1f}c since the leader's entry (limit {c['stale_price_move'] * 100:.0f}c).")
        add("cash", p.stake <= ledger.cash + 1e-9, "Enough paper cash.", "Insufficient paper cash.")
        return out

    def check(self, p: Proposal, ledger: PaperLedger, override_reason: str | None = None) -> tuple[bool, list[str]]:
        results = self.checks(p, ledger, override_reason)
        blocks = [r["reason"] for r in results if not r["passed"]]
        ok = not blocks
        self.audit.log("control_check", trader=p.trader, token=p.token_id, stake=p.stake, verdict=p.verdict,
                       override_reason=override_reason, allowed=ok, blocks=blocks)
        return ok, blocks

    def execute(self, p: Proposal, ledger: PaperLedger, approved_by: str, override_reason: str | None = None) -> dict:
        """Human-approved execution. Re-runs every control; nothing bypasses them."""
        ok, blocks = self.check(p, ledger, override_reason)
        if not ok:
            self.audit.log("copy_blocked", trader=p.trader, token=p.token_id, blocks=blocks, approved_by=approved_by)
            return {"executed": False, "blocks": blocks}
        price = p.current_price
        pos = {"trader": p.trader, "token_id": p.token_id, "cluster": p.cluster, "title": p.title,
               "stake": p.stake, "price": price, "shares": p.stake / price}
        ledger.cash -= p.stake
        ledger.open.append(pos)
        self.audit.log("paper_copy_executed", approved_by=approved_by, override_reason=override_reason, **pos)
        return {"executed": True, "position": pos}

    def settle(self, ledger: PaperLedger, token_id: str, payout: float) -> None:
        for pos in [p for p in ledger.open if p["token_id"] == token_id]:
            value = pos["shares"] * payout
            ledger.cash += value
            ledger.open.remove(pos)
            pos = {**pos, "payout": payout, "pnl": value - pos["stake"]}
            ledger.closed.append(pos)
            self.audit.log("paper_settled", **pos)
        eq = ledger.equity()
        ledger.peak = max(ledger.peak, eq)
        if (ledger.peak - eq) / ledger.peak >= self.c["drawdown_stop"]:
            traders = {p["trader"] for p in ledger.closed}
            ledger.paused |= traders
            self.audit.log("drawdown_stop", equity=eq, peak=ledger.peak, paused=sorted(traders))
