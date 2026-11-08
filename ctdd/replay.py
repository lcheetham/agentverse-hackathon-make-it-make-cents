"""Live mode, run as a labelled REPLAY of recorded synthetic trades.

For each live trader, the report card is built from the first 85% of their history; the remaining
bets are replayed one at a time. The agent proposes (ctdd.agent.live.propose), the code controls
check (ctdd.controls.Policy), a human approves or rejects. The paper ledger lives in memory; every
step goes to the audit log.
"""
from __future__ import annotations

import uuid

from .adapter import CODES
from .agent.live import propose
from .agent.text_jobs import categorise, heuristic_clusters
from .controls import PaperLedger, Policy
from .service import DEMO_LABELS, LIVE_WALLETS, REPLAY_CUT

MAX_BETS = 12        # per trader; enough for a demo


def _verdict(label: str) -> dict:
    return {"code": CODES.get(label, "CANT_TELL"), "label": label}


class LiveSession:
    def __init__(self, svc):
        self.svc = svc
        self.policy = Policy(svc.th["controls"], svc.audit)
        self.reset(log=False)

    # ---------------- setup ----------------
    def reset(self, log: bool = True):
        c = self.svc.th["controls"]
        self.ledger = PaperLedger(bankroll=c["bankroll"], cash=c["bankroll"])
        self.bets, self.idx, self.pending, self.rows = {}, {}, {}, []
        F, M, hs = self.svc.F, self.svc.M, self.svc.th["costs"]["half_spread"]
        for w in LIVE_WALLETS:
            tf = F[F["wallet"] == w]
            cut = tf["ts"].quantile(REPLAY_CUT)
            later = tf[tf["ts"] >= cut].sort_values("ts").drop_duplicates("token_id").head(MAX_BETS)
            hist = self.svc.report(w, REPLAY_CUT)
            # Event groups for the exposure control: the engine's own heuristic over ALL this trader's markets, so
            # replayed bets on the same event share a group even though the history report never saw them.
            groups = heuristic_clusters(M.loc[tf["condition_id"].unique()])
            bets = []
            for b in later.itertuples(index=False):
                m = M.loc[b.condition_id]
                now = float(b.ts) + 300                      # the follower sees the trade 5 minutes later
                bets.append({
                    "bet_id": f"{b.token_id}", "wallet": w, "market_id": b.condition_id, "token_id": b.token_id,
                    "title": b.title, "category": categorise(b.title),
                    "cluster_id": str(groups.get(b.condition_id, b.event_slug)),
                    "token": "YES" if int(b.outcome_index) == 0 else "NO",
                    "leader_price": float(b.price), "leader_ts": float(b.ts),
                    "current_price": self.svc.world.price_at(b.token_id, now), "current_ts": now,
                    "spread": 2 * hs, "fee_rate": self.svc.th["costs"]["fee_rate"],
                    "resolve_ts": float(m["resolve_ts"]), "payout": float(m["payouts"][int(b.outcome_index)]),
                })
            self.bets[w], self.idx[w] = bets, 0
        all_ts = [b["leader_ts"] for bs in self.bets.values() for b in bs]
        self.clock = min(all_ts) if all_ts else 0.0
        # Account value over replay time, for the chart: one point at the start, after each copy, after each settlement.
        self.history = [{"ts": self.clock, "value": round(self.ledger.equity(), 2), "event": "start"}]
        if log:
            self.svc.audit.log("live_reset", by="human (web UI)")

    # ---------------- helpers ----------------
    @staticmethod
    def _public(bet: dict) -> dict:
        return {k: v for k, v in bet.items() if k != "payout"}        # outcome hidden until settlement

    def _settle_until(self, ts: float) -> list:
        settled = []
        for row in sorted(self.rows, key=lambda r: r["resolve_ts"]):
            if row["status"] == "open" and row["resolve_ts"] <= ts:
                before = {id(p) for p in self.ledger.closed}
                self.policy.settle(self.ledger, row["token_id"], row["_payout"])
                new = [p for p in self.ledger.closed if id(p) not in before]
                row["status"], row["pnl"] = "settled", sum(p["pnl"] for p in new)
                settled.append({k: v for k, v in row.items() if not k.startswith("_")})
                self._mark(row["resolve_ts"], "settled")
        return settled

    def _mark(self, ts: float, event: str) -> None:
        ts, value, last = float(max(ts, self.history[-1]["ts"])), round(self.ledger.equity(), 2), self.history[-1]
        if value != last["value"]:                       # a step, not a slope: the value changes at this moment
            self.history.append({"ts": ts, "value": last["value"], "event": "step"})
        self.history.append({"ts": ts, "value": value, "event": event})

    def _proposal_json(self, pid: str) -> dict:
        p = self.pending[pid]
        return {"proposal_id": pid, "bet": self._public(p["bet"]), "action": p["prop"].action, "stake": p["prop"].stake,
                "reasons": p["prop"].reasons, "precheck": p["precheck"], "verdict": _verdict(p["prop"].verdict)}

    # ---------------- API ----------------
    def state(self) -> dict:
        from . import killswitch

        c = self.svc.th["controls"]
        return {
            "bankroll": self.ledger.bankroll, "cash": round(self.ledger.cash, 2), "equity": round(self.ledger.equity(), 2),
            "ledger": [{k: v for k, v in r.items() if not k.startswith("_")} for r in self.rows],
            "paused": sorted(self.ledger.paused), "clock_ts": self.clock,
            "pending": [self._proposal_json(pid) for pid in self.pending],
            "limits": {"bankroll": c["bankroll"], "per_trade_cap_frac": c["per_trade_cap"], "cluster_cap_frac": c["cluster_cap"],
                       "drawdown_stop_frac": c["drawdown_stop"], "stale_price_max_move": c["stale_price_move"]},
            "wallets_with_bets": [{"address": w, "label": DEMO_LABELS.get(w, "Trader"), "remaining": len(self.bets[w]) - self.idx[w]}
                                  for w in LIVE_WALLETS],
            "kill_switch": killswitch.status(),
            "history": self.history,
            "next_resolution_ts": min((r["resolve_ts"] for r in self.rows if r["status"] == "open"), default=None),
        }

    def next_bet(self, wallet: str) -> dict:
        if wallet not in self.bets:
            raise ValueError("No replay bets for that trader.")
        if self.pending:
            raise ValueError("Decide the pending proposal first.")
        if self.idx[wallet] >= len(self.bets[wallet]):
            raise ValueError("No bets left for this trader. Reset the session to replay again.")
        bet = self.bets[wallet][self.idx[wallet]]
        self.idx[wallet] += 1
        self.clock = max(self.clock, bet["current_ts"])
        self._settle_until(self.clock)
        hist = self.svc.report(wallet, REPLAY_CUT)
        prop = propose(wallet, {"token_id": bet["token_id"], "title": bet["title"], "leader_price": bet["leader_price"]},
                       hist, self.ledger, self.svc.th["controls"], bet["current_price"], bet["category"], bet["cluster_id"])
        pid = uuid.uuid4().hex[:12]
        self.pending[pid] = {"bet": bet, "prop": prop, "precheck": self.policy.checks(prop, self.ledger)}
        self.svc.audit.log("copy_proposed", trader=wallet, token=prop.token_id, action=prop.action, stake=prop.stake,
                           reasons=prop.reasons, replay=True)
        return self._proposal_json(pid)

    def decide(self, pid: str, decision: str, stake=None, override_reason: str | None = None) -> dict:
        if pid not in self.pending:
            raise ValueError("Unknown or already decided proposal.")
        p = self.pending[pid]
        prop, bet = p["prop"], p["bet"]
        if decision == "reject":
            entry = self.svc.audit.log("copy_rejected_by_human", trader=prop.trader, token=prop.token_id)
            del self.pending[pid]
            return {"status": "rejected", "checks": p["precheck"], "audit_entry": entry, "state": self.state()}
        if decision != "approve":
            raise ValueError("decision must be 'approve' or 'reject'")
        if stake is not None:
            if isinstance(stake, bool) or not isinstance(stake, (int, float)) or stake < 0:
                raise ValueError("Stake must be a non-negative number of pounds.")
            prop.stake = round(float(stake), 2)
        checks = self.policy.checks(prop, self.ledger, override_reason)
        res = self.policy.execute(prop, self.ledger, approved_by="human (web UI)", override_reason=override_reason)
        entry = self.svc.audit.tail(1)[-1]
        if not res["executed"]:
            p["precheck"] = checks
            return {"status": "blocked", "checks": checks, "audit_entry": entry, "state": self.state()}
        self.rows.append({"id": pid, "wallet": prop.trader, "title": bet["title"], "token": bet["token"], "token_id": bet["token_id"],
                          "stake": prop.stake, "entry_price": prop.current_price, "status": "open", "pnl": None,
                          "resolve_ts": bet["resolve_ts"], "_payout": bet["payout"]})
        del self.pending[pid]
        self._mark(self.clock, "copied")
        return {"status": "executed", "checks": checks, "audit_entry": entry, "state": self.state()}

    def settle_next(self) -> dict:
        """Move the replay clock to the earliest open copy's resolution and settle only what has resolved by then."""
        open_rows = [r for r in self.rows if r["status"] == "open"]
        if not open_rows:
            return {"settled": [], "state": self.state()}
        self.clock = max(self.clock, min(r["resolve_ts"] for r in open_rows))
        return {"settled": self._settle_until(self.clock), "state": self.state()}

    def advance(self) -> dict:
        open_rows = [r for r in self.rows if r["status"] == "open"]
        if open_rows:
            self.clock = max(self.clock, max(r["resolve_ts"] for r in open_rows))
        settled = self._settle_until(self.clock)
        return {"settled": settled, "state": self.state()}

    def resume(self, wallet: str) -> dict:
        self.ledger.paused.discard(wallet)
        self.svc.audit.log("drawdown_resumed", trader=wallet, by="human (web UI)")
        return {"state": self.state()}
