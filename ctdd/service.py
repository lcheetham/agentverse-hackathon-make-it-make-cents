"""One object that holds the app's state: demo world, cached reports, LLM, audit log, live replay, agent."""
from __future__ import annotations

import threading
import time

import numpy as np

from .adapter import card, luck_at, wallet_row, with_delay
from .agent.llm import LLM
from .audit import AuditLog
from .config import load_thresholds
from .data.synthetic import demo_world
from .pipeline import run_real_wallet, run_wallet

DEMO_LABELS = {
    "0xDEMO-perfect-25-0": "Hook: a perfect 25–0 record",
    "0xDEMO-messy-skilled": "Messy record, real edge",
    "0xDEMO-fast-mover": "Real edge, but the price moves in minutes",
    "0xDEMO-one-election": "Cluster trap: one election, many bets",
    "0xDEMO-leaderboard-00": "#1 of 1,000 coin-flippers",
}
# Ground truth for the planted demo wallets (we built them), shown only after the reveal on
# "Why rankings mislead". `ok` = the verdicts that count as right for that kind of trader.
DEMO_TRUTH = {
    "0xDEMO-perfect-25-0": {"truth": "No skill: 25 bets at 95c, which win almost every time anyway", "ok": ["PROBABLY_LUCK", "CANT_TELL"]},
    "0xDEMO-messy-skilled": {"truth": "Real skill (8c edge) that a follower could still capture", "ok": ["SKILLED_COPYABLE"]},
    "0xDEMO-fast-mover": {"truth": "Real skill (10c edge), but the price catches up within minutes", "ok": ["SKILLED_NOT_COPYABLE"]},
    "0xDEMO-one-election": {"truth": "No proven skill: many bets on just three stories, so really three draws", "ok": ["CANT_TELL", "PROBABLY_LUCK"]},
    "0xDEMO-leaderboard-00": {"truth": "No skill: the luckiest of 1,000 coin-flippers", "ok": ["PROBABLY_LUCK", "CANT_TELL"]},
}
LIVE_WALLETS = ["0xDEMO-messy-skilled", "0xDEMO-fast-mover", "0xDEMO-perfect-25-0", "0xDEMO-one-election"]
REPLAY_CUT = 0.85            # live mode: the report uses the first 85% of the history, the rest is replayed
REAL_TTL_S = 30 * 60         # a real wallet's analysis is reused for 30 min, then redone on the next request


class Service:
    def __init__(self, audit: AuditLog | None = None, llm: LLM | None = None):
        self.th = load_thresholds()
        self.audit = audit or AuditLog()
        self.llm = llm or LLM(self.audit)
        self.world = demo_world()
        self.F, self.M = self.world.fills_df(), self.world.markets_df()
        self._reports: dict = {}
        self._cards: dict = {}
        self._lock = threading.Lock()
        self._real_client = None
        self.live = None

    # ---------------- names ----------------
    @property
    def llm_name(self) -> str:
        return self.llm.model if self.llm.available else "offline (no Gemini key: template text, heuristic clusters)"

    def is_demo(self, wallet: str) -> bool:
        return wallet in DEMO_LABELS

    def demo_N(self, wallet: str) -> int:
        return next(p.N for p in self.world.planted if p.wallet == wallet)

    # ---------------- engine reports (cached; deterministic) ----------------
    def report(self, wallet: str, history_frac: float | None = None) -> dict:
        key = (wallet, history_frac)
        with self._lock:
            if key in self._reports:
                return self._reports[key]
        if self.is_demo(wallet):
            F = self.F[self.F["wallet"] == wallet]
            if history_frac is not None:
                F = F[F["ts"] < F["ts"].quantile(history_frac)]
            # Planted demo traders are grouped by the engine's rules, as in the evaluation: deterministic, and
            # seconds instead of minutes (Gemini grouping can take up to 75 s per trader). Gemini still writes
            # the report text.
            rep = run_wallet(wallet, F, self.M, self.world.price_at, self.demo_N(wallet), th=self.th, llm=self.llm,
                             audit=self.audit, synthetic=True, cluster_with_llm=False)
            rep["_price_at"] = self.world.price_at
        else:
            rep = self.real_report(wallet)
        with self._lock:
            self._reports[key] = rep
        return rep

    def real_report(self, wallet: str, N_eff: int = 1000, pages: int = 4, price_positions: int = 60) -> dict:
        from .data.polymarket import PolymarketClient

        if self._real_client is None:
            self._real_client = PolymarketClient(audit=self.audit)
        return run_real_wallet(self._real_client, wallet, N_eff, pages, price_positions, th=self.th, llm=self.llm,
                               audit=self.audit)

    def card(self, wallet: str, delay_s: int = 3600) -> dict:
        """Report card JSON. Built once per wallet (it holds the £200 simulation for every delay); a delay
        change only selects a different simulation."""
        with self._lock:
            base = self._cards.get(wallet)
            if base is not None and not self.is_demo(wallet) and time.time() - base.get("analysed_at", 0) > REAL_TTL_S:
                base = None
                self._cards.pop(wallet, None)
                self._reports.pop((wallet, None), None)
        if base is None:
            rep = self.report(wallet)
            th = rep.get("_th") or self.th
            base = card(rep, rep["_price_at"], th, delay_s, "synthetic" if rep.get("synthetic") else "real", self.llm_name)
            base["demo_label"] = DEMO_LABELS.get(wallet)
            base["analysed_at"] = time.time()
            with self._lock:
                self._cards[wallet] = base
        return with_delay(base, delay_s)

    def cached_verdicts(self, wallets: list[str]) -> dict:
        """Verdicts already worked out (someone opened the wallet), for the Home leaderboard. Never triggers
        an analysis: that would cost hundreds of API requests per row."""
        out = {}
        with self._lock:
            for w in wallets:
                c = self._cards.get(w)
                if c is not None and time.time() - c.get("analysed_at", 0) <= REAL_TTL_S:
                    out[w] = {"code": c["verdict"]["code"], "label": c["verdict"]["label"], "analysed_at": c["analysed_at"]}
        return out

    def luck(self, wallet: str, n: int) -> dict:
        """Luck score at any leaderboard size N (display only; the verdict keeps its frozen N)."""
        rep = self.report(wallet)
        out = luck_at(rep["luck"], n)
        out["verdict_n"] = int(rep["stats"]["S.N_eff"]["value"])
        return out

    def wallets(self) -> list[dict]:
        rows = []
        for w in DEMO_LABELS:
            r = wallet_row(self.report(w))
            r["demo_role"] = DEMO_LABELS[w]
            r["truth"] = DEMO_TRUTH[w]["truth"]
            r["verdict_ok"] = r["verdict"]["code"] in DEMO_TRUTH[w]["ok"]
            rows.append(r)
        rows.sort(key=lambda r: -(r["profit"] or 0))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        return rows

    def ensure_live(self):
        if self.live is None:
            from .replay import LiveSession
            self.live = LiveSession(self)
        return self.live
