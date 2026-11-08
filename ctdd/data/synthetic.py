"""Synthetic markets and planted traders with known truth. Everything here is labelled SYNTHETIC.

Planted types (spec v2, section 7):
  skilled_slow   true win prob = price + edge; price drifts to fair value over ~2 days -> Skilled and copyable
                 (800-2,500 positions: shorter records cannot beat a 1,000-wallet field; see eval/record_length.py)
  skilled_fast   same edge, but price reaches fair value within ~2 minutes           -> Skilled but not copyable
  lucky          top 10 by profit of a no-skill population of size N                 -> not skilled
  farmer95       buys only 93-98c favourites, no skill, selected for a clean record  -> not skilled
  clustered      many markets on 2-3 stories (different event slugs), one lucky draw -> not skilled
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DAY = 86_400
T0 = 1_780_000_000  # May 2026

_SYL = ["ka", "ro", "vel", "an", "tor", "mi", "sel", "dra", "qu", "nor", "bel", "ix", "far", "lun", "zen", "or",
        "pa", "ste", "vik", "mar", "os", "tal", "ren", "dor", "cy", "len", "ha", "gro", "wy", "ul"]
_COINS = ["Kestrium", "Zolcoin", "Vantra", "Orbix", "Pellet", "Quorra", "Lumex", "Tavik"]


@dataclass
class PlantedWallet:
    wallet: str
    kind: str
    edge: float
    expected: str
    N: int
    note: str = ""


@dataclass
class _Path:
    t_entry: float
    p_entry: float
    fair: float
    tau: float
    resolve_ts: float


@dataclass
class SyntheticWorld:
    seed: int = 0
    fills: list = field(default_factory=list)
    markets: dict = field(default_factory=dict)
    paths: dict = field(default_factory=dict)
    planted: list = field(default_factory=list)
    story_of: dict = field(default_factory=dict)   # condition_id -> true correlation story (for clustering accuracy)
    _names: set = field(default_factory=set)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self._mid = 0

    # ---------- names ----------
    def _name(self) -> str:
        """Unique pronounceable name: a counter written in base-30 syllables, scrambled by a coprime stride."""
        if not hasattr(self, "_name_ctr"):
            self._name_ctr = int(self.rng.integers(0, 10_000))
        self._name_ctr += 1
        x = (self._name_ctr * 7919 + 1_000) % 24_300_000  # 30^5, 7919 is coprime to 30
        sylls = []
        while x or len(sylls) < 3:
            x, r = divmod(x, 30)
            sylls.append(_SYL[r])
        n = "".join(sylls).capitalize()
        self._names.add(n)
        return n

    def _title(self, category: str, ts: float) -> tuple[str, str]:
        date = pd.Timestamp(ts, unit="s").strftime("%b %d")
        if category == "sports":
            a, b = self._name(), self._name()
            return f"Will {a} FC beat {b} United on {date}?", f"Resolves YES if {a} FC wins the match scheduled for {date}."
        if category == "politics":
            a, place = self._name(), self._name()
            return f"Will {a} win the {place} council seat?", f"Resolves YES if {a} is certified winner of the {place} council seat."
        if category == "crypto":
            coin = f"{self._name()} {self.rng.choice(_COINS)}"
            lvl = int(self.rng.integers(2, 90)) * 1000
            return f"Will {coin} close above ${lvl:,} on {date}?", f"Resolves YES if the {date} daily close of {coin} is above ${lvl:,}."
        a = self._name()
        return f"Will the {a} Awards name a first-time winner?", f"Resolves YES if the {a} Awards top prize goes to a first-time winner."

    # ---------- markets ----------
    def _new_market(self, title, rules, event_slug, category, resolve_ts, yes_wins: bool, neg_risk=False) -> str:
        self._mid += 1
        cond = f"syn-{self.seed}-{self._mid:06d}"
        self.markets[cond] = {
            "title": title, "rules": rules, "event_slug": event_slug, "neg_risk": neg_risk,
            "resolved": True, "resolve_ts": float(resolve_ts),
            "payouts": [1.0, 0.0] if yes_wins else [0.0, 1.0], "category": category, "synthetic": True,
        }
        return cond

    def _add_position(self, wallet, category, p, true_p, win, tau, t_entry, horizon, event_slug=None,
                      title=None, rules=None, stake=None) -> str:
        """Leader buys one outcome token at price p; it wins with prob true_p (outcome already drawn = win)."""
        side_idx = int(self.rng.integers(0, 2))           # which outcome token the leader holds
        yes_wins = win if side_idx == 0 else not win
        resolve_ts = t_entry + horizon
        if title is None:
            title, rules = self._title(category, resolve_ts)
        slug = event_slug or f"ev-{self.seed}-{self._mid + 1}"
        cond = self._new_market(title, rules, slug, category, resolve_ts, yes_wins)
        token = f"{cond}-{side_idx}"
        stake = stake if stake is not None else float(np.clip(self.rng.lognormal(math.log(40), 0.8), 2, 2000))
        shares = stake / p
        n_fills = int(self.rng.integers(1, 4))
        for k in range(n_fills):
            self.fills.append(dict(wallet=wallet, condition_id=cond, token_id=token, outcome_index=side_idx, side="BUY",
                                   price=p, size=shares / n_fills, ts=int(t_entry + 7 * k), title=title, event_slug=slug))
        self.paths[token] = _Path(t_entry, p, true_p, tau, resolve_ts)
        return cond

    def price_at(self, token_id: str, ts: float):
        path = self.paths.get(token_id)
        if path is None or ts >= path.resolve_ts:
            return None
        if ts <= path.t_entry:
            return path.p_entry
        return path.p_entry + (path.fair - path.p_entry) * (1 - math.exp(-(ts - path.t_entry) / path.tau))

    def _t(self):
        return T0 + float(self.rng.uniform(0, 60 * DAY))

    def _horizon(self):
        return float(self.rng.uniform(1.5, 10) * DAY)

    def _cat(self):
        return str(self.rng.choice(["sports", "politics", "crypto", "culture"], p=[0.45, 0.2, 0.25, 0.1]))

    # ---------- planted types ----------
    def skilled(self, wallet: str, n: int, edge: float, fast: bool, N: int = 1000):
        tau = 120.0 if fast else 2 * DAY
        for _ in range(n):
            p = float(self.rng.uniform(0.15, 0.85))
            true_p = min(p + edge, 0.97)
            win = bool(self.rng.random() < true_p)
            self._add_position(wallet, self._cat(), p, true_p, win, tau, self._t(), self._horizon())
        kind = "skilled_fast" if fast else "skilled_slow"
        self.planted.append(PlantedWallet(wallet, kind, edge, "Skilled but not copyable" if fast else "Skilled and copyable", N))

    def lucky_population(self, prefix: str, N: int = 1000, top_k: int = 10, n_range=(30, 90)):
        """Simulate N no-skill wallets, keep the top_k by profit (the leaderboard the TikTok user sees)."""
        sizes = self.rng.integers(n_range[0], n_range[1], size=N)
        profits, books = np.empty(N), []
        for i, n in enumerate(sizes):
            p = self.rng.uniform(0.2, 0.8, size=n)
            stake = np.clip(self.rng.lognormal(math.log(40), 0.8, size=n), 2, 2000)
            win = self.rng.random(n) < p
            profits[i] = float((stake * (win / p - 1)).sum())
            books.append((p, stake, win))
        for rank, i in enumerate(np.argsort(-profits)[:top_k]):
            wallet = f"{prefix}-{rank:02d}"
            p, stake, win = books[i]
            for pj, sj, wj in zip(p, stake, win):
                self._add_position(wallet, self._cat(), float(pj), float(pj), bool(wj), 2 * DAY, self._t(), self._horizon(), stake=float(sj))
            self.planted.append(PlantedWallet(wallet, "lucky", 0.0, "Probably luck", N, f"rank {rank + 1} of {N} no-skill wallets"))

    def farmer95(self, wallet: str, n: int, N: int = 1000, clean_record: bool = True):
        for _ in range(1000):
            p = self.rng.uniform(0.93, 0.98, size=n)
            win = self.rng.random(n) < p
            if win.all() or not clean_record:
                break
        for pj, wj in zip(p, win):
            self._add_position(wallet, self._cat(), float(pj), float(pj), bool(wj), 2 * DAY, self._t(), self._horizon(),
                               stake=float(self.rng.uniform(100, 600)))
        self.planted.append(PlantedWallet(wallet, "farmer95", 0.0, "Probably luck", N, f"{int(win.sum())}-{int((~win).sum())} record at 93-98c"))

    def clustered(self, wallet: str, n_stories: int = 3, per_story=(6, 12), n_noise: int = 4, N: int = 1000):
        """Many markets hinging on the same outcome, different event slugs, one lucky draw per story (all won)."""
        for s in range(n_stories):
            cand, rival, place = self._name(), self._name(), self._name()
            p_story = float(self.rng.uniform(0.35, 0.65))
            t = self._t()
            horizon = self._horizon()
            templates = [
                (f"Will {cand} win the {place} governor race?", f"Resolves YES if {cand} is declared winner of the {place} governor race."),
                (f"Will {cand} win {place} by 5+ points?", f"Resolves YES if {cand}'s margin in {place} is at least 5 points."),
                (f"Will {rival} concede the {place} race by Friday?", f"Resolves YES if {rival} publicly concedes the {place} race by Friday."),
                (f"{place} governor: will {cand} carry the capital district?", f"Resolves YES if {cand} wins the {place} capital district."),
                (f"Will {place}'s next governor be from {cand}'s party?", f"Resolves YES if the {place} governor-elect belongs to {cand}'s party."),
                (f"Will {rival} win any {place} county?", f"Resolves NO-side for this trader if {rival} wins no county in {place}."),
            ]
            k = int(self.rng.integers(per_story[0], per_story[1] + 1))
            for j in range(k):
                title, rules = templates[j % len(templates)]
                if j >= len(templates):
                    title = f"{title} (round {j // len(templates) + 1})"
                p = float(np.clip(p_story + self.rng.normal(0, 0.05), 0.1, 0.9))
                cond = self._add_position(wallet, "politics", p, p, True, 2 * DAY, t + 600 * j, horizon,
                                          event_slug=f"ev-{self.seed}-story{s}-{j}", title=title, rules=rules)
                self.story_of[cond] = f"{wallet}-story{s}"
        for _ in range(n_noise):
            p = float(self.rng.uniform(0.3, 0.7))
            cond = self._add_position(wallet, self._cat(), p, p, bool(self.rng.random() < p), 2 * DAY, self._t(), self._horizon())
            self.story_of[cond] = cond
        self.planted.append(PlantedWallet(wallet, "clustered", 0.0, "Can't tell yet", N, f"{n_stories} stories, all won"))

    # ---------- outputs ----------
    def fills_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.fills)

    def markets_df(self) -> pd.DataFrame:
        return pd.DataFrame.from_dict(self.markets, orient="index")

    def truth_df(self) -> pd.DataFrame:
        return pd.DataFrame([p.__dict__ for p in self.planted])


def planted_batch(seed: int, scale: int = 1) -> SyntheticWorld:
    """A standard batch: 8 x scale of each type, plus the top 10 of a 1,000-wallet no-skill population."""
    w = SyntheticWorld(seed=seed)
    rng = np.random.default_rng(seed + 991)
    k = 8 * scale
    for e in (0.02, 0.05, 0.10):
        for i in range(k):
            w.skilled(f"0xSYN-skilled{int(e * 100):02d}-{seed}-{i:02d}", int(rng.integers(800, 2500)), e, fast=False)
    for i in range(k):
        w.skilled(f"0xSYN-fast-{seed}-{i:02d}", int(rng.integers(1500, 2500)), 0.10, fast=True)
    w.lucky_population(f"0xSYN-lucky-{seed}", N=1000, top_k=10)
    for i in range(k):
        w.farmer95(f"0xSYN-farmer-{seed}-{i:02d}", int(rng.integers(20, 40)))
    for i in range(k):
        w.clustered(f"0xSYN-cluster-{seed}-{i:02d}", n_stories=int(rng.integers(2, 4)))
    return w


def demo_world(seed: int = 7) -> SyntheticWorld:
    """Fixed wallets for the 4-minute demo."""
    w = SyntheticWorld(seed=seed)
    # Hook: a perfect 25-0 record, every trade at 95c.
    w.farmer95("0xDEMO-perfect-25-0", 25)
    # Contrast: a messy trader (wins ~55%) with a real, slow-to-price edge.
    w.skilled("0xDEMO-messy-skilled", 2000, 0.08, fast=False)
    # Skilled but uncopyable: the price snaps to fair value within minutes.
    w.skilled("0xDEMO-fast-mover", 2000, 0.10, fast=True)
    # Cluster trap: 3 election stories, every related bet won once.
    w.clustered("0xDEMO-one-election", n_stories=3)
    # The leaderboard winner: best of 1,000 coin-flippers.
    w.lucky_population("0xDEMO-leaderboard", N=1000, top_k=1)
    return w
