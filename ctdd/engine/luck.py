"""Luck score: could the best of N no-skill traders have done at least this well?

A no-skill *twin* holds the trader's exact positions (same markets, shares, cost) but each
outcome is drawn at the market's own odds. We simulate one twin M times, estimate

    p = P(twin profit >= trader profit)          (add-one estimate, never exactly 0)

and use the exact best-of-N formula for independent twins

    Luck(N) = 1 - (1 - p) ** N.

Correlation is handled with *draw groups*: each group gets one uniform draw U per simulation
and every position in the group wins or loses according to where U falls.

  independent: one group per binary market; one per negRisk event (candidates get disjoint
               intervals, so exactly one candidate wins).
  shared:      one group per cluster (maximum correlation inside a cluster).

Luck(N) is the chance that N no-skill traders produce someone at least this good.
It is NOT the probability that this trader is lucky.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TwinSpec:
    group: np.ndarray      # int, draw group per position
    lo: np.ndarray         # interval start in [0, 1)
    hi: np.ndarray         # interval end
    win_inside: np.ndarray # bool: position wins iff U in [lo, hi)
    shares: np.ndarray
    cost: np.ndarray
    n_groups: int


def _calibrate(q: np.ndarray, calibration: dict | None) -> np.ndarray:
    """Map price -> historical win rate. calibration = {'edges': [...], 'rates': [...]}."""
    if not calibration:
        return q
    edges = np.asarray(calibration["edges"], dtype=float)
    rates = np.asarray(calibration["rates"], dtype=float)
    idx = np.clip(np.searchsorted(edges, q, side="right") - 1, 0, len(rates) - 1)
    return np.clip(rates[idx], 1e-4, 1 - 1e-4)


def build_twin_spec(
    held: pd.DataFrame,
    markets: pd.DataFrame,
    mode: str = "independent",
    clusters: dict | None = None,
    directions: dict | None = None,
    calibration: dict | None = None,
) -> TwinSpec:
    """held: positions held to resolution (columns condition_id, outcome_index, avg_entry, shares, cost, event_slug)."""
    n = len(held)
    cond = held["condition_id"].to_numpy()
    oi = held["outcome_index"].to_numpy().astype(int)
    q_own = _calibrate(np.clip(held["avg_entry"].to_numpy(dtype=float), 1e-4, 1 - 1e-4), calibration)
    # Probability that outcome 0 ("YES") wins, as implied by this position's own entry price.
    q_yes = np.where(oi == 0, q_own, 1 - q_own)
    neg_risk = markets.reindex(cond)["neg_risk"].fillna(False).astype(bool).to_numpy()
    event = held["event_slug"].fillna("").to_numpy()

    # One YES-probability per market: the first position seen in that market sets it.
    market_q: dict = {}
    for c, q in zip(cond, q_yes):
        market_q.setdefault(c, q)

    # Intervals for each market's YES outcome inside its draw group.
    if mode == "shared":
        if clusters is None:
            raise ValueError("shared mode needs clusters")
        group_key = np.array([clusters.get(c, c) for c in cond], dtype=object)
    else:
        group_key = np.array([(f"ev::{e}" if (nr and e) else f"mk::{c}") for c, e, nr in zip(cond, event, neg_risk)], dtype=object)

    market_lo: dict = {}
    market_width: dict = {}
    cursor: dict = {}
    for c, gk, nr in zip(cond, group_key, neg_risk):
        if c in market_lo:
            continue
        w = market_q[c]
        if nr:
            # Mutually exclusive candidates: lay intervals end to end.
            start = cursor.get(gk, 0.0)
            cursor[gk] = start + w
        else:
            start = 0.0  # comonotone with the group's other binary markets
        market_lo[c] = start
        market_width[c] = w

    # Renormalise groups whose exclusive intervals exceed 1.
    over = {gk: tot for gk, tot in cursor.items() if tot > 1.0}
    lo = np.empty(n)
    hi = np.empty(n)
    for i, (c, gk) in enumerate(zip(cond, group_key)):
        s, w = market_lo[c], market_width[c]
        if gk in over:
            s, w = s / over[gk], w / over[gk]
        lo[i], hi[i] = s, s + w

    if mode == "shared" and directions:
        d = np.array([directions.get(c, 1) for c in cond])
        flip = (d < 0) & ~neg_risk
        lo_f, hi_f = 1 - hi[flip], 1 - lo[flip]
        lo[flip], hi[flip] = lo_f, hi_f

    win_inside = oi == 0  # YES position wins inside its market's YES interval; NO wins outside
    uniq, ginv = np.unique(group_key.astype(str), return_inverse=True)
    return TwinSpec(
        group=ginv, lo=lo, hi=hi, win_inside=win_inside,
        shares=held["shares"].to_numpy(dtype=float), cost=held["cost"].to_numpy(dtype=float),
        n_groups=len(uniq),
    )


def simulate_twin_profits(spec: TwinSpec, M: int = 50_000, seed: int = 0, chunk: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(spec.shares)
    if n == 0:
        return np.zeros(M)
    chunk = chunk or max(1000, min(50_000, 20_000_000 // max(n, 1)))
    total_cost = spec.cost.sum()
    out = np.empty(M)
    for s in range(0, M, chunk):
        m = min(chunk, M - s)
        U = rng.random((m, spec.n_groups))[:, spec.group]
        inside = (U >= spec.lo) & (U < spec.hi)
        win = inside == spec.win_inside
        out[s:s + m] = win.astype(np.float64) @ spec.shares - total_cost
    return out


MIN_HITS_FOR_MC = 20


def luck_from_profits(real_profit: float, twin_profits: np.ndarray, Ns) -> dict:
    """p from Monte Carlo when the tail is well sampled; otherwise the more sceptical of two estimates.

    With < 20 hits we take max(normal-approximation tail, add-one MC estimate). The normal tail
    alone underestimates p for right-skewed (long-shot) books — checked against a 2M-sample run —
    so it is only ever used when it is the *larger* (more luck-friendly) number.
    Callers scale M with N so the add-one floor stays below the verdict threshold.
    """
    M = len(twin_profits)
    hits = int((twin_profits >= real_profit - 1e-9).sum())
    p_mc = (1 + hits) / (M + 1)
    mu, sd = float(twin_profits.mean()), float(twin_profits.std())
    if hits >= MIN_HITS_FOR_MC or sd == 0:
        p, method = p_mc, "monte_carlo"
    else:
        from scipy.stats import norm

        p_norm = float(norm.sf((real_profit - mu) / sd))
        p, method = (p_norm, "normal_tail") if p_norm > p_mc else (p_mc, "mc_add_one")
    luck = {int(N): float(-np.expm1(N * np.log1p(-p))) for N in Ns}
    bound = {int(N): float(min(1.0, N / (M + 1))) for N in Ns}
    return {"p_single": p, "p_mc": p_mc, "p_method": method, "hits": hits, "M": M, "zero_hits": hits == 0,
            "luck": luck, "luck_upper_bound_mc_only": bound}


def luck_score(
    positions: pd.DataFrame,
    markets: pd.DataFrame,
    Ns,
    clusters: dict | None = None,
    directions: dict | None = None,
    M: int = 50_000,
    seed: int = 0,
    calibration: dict | None = None,
) -> dict:
    """Luck score in both correlation modes, on held-to-resolution positions only."""
    held = positions[positions["status"] == "held"]
    closed_ = positions[positions["status"] != "open"]
    real_profit = float(held["pnl"].sum())
    total_profit = float(closed_["pnl"].sum()) if len(closed_) else 0.0
    out = {
        "real_profit_held": real_profit,
        "coverage_positions": float(len(held) / len(closed_)) if len(closed_) else 0.0,
        "coverage_profit": float(real_profit / total_profit) if total_profit else float("nan"),
        "n_held": int(len(held)),
        "modes": {},
    }
    if len(held) == 0:
        return out
    # (mode name, correlation mode, calibration). "calibrated" uses Polymarket's empirical win rate by price band.
    modes = [("independent", "independent", None)] + ([("shared", "shared", None)] if clusters else [])
    if calibration:
        modes.append(("calibrated", "shared" if clusters else "independent", calibration))
    for mode, corr, cal in modes:
        spec = build_twin_spec(held, markets, mode=corr, clusters=clusters, directions=directions, calibration=cal)
        prof = simulate_twin_profits(spec, M=M, seed=seed)
        res = luck_from_profits(real_profit, prof, Ns)
        res["n_groups"] = spec.n_groups
        res["twin_mean"] = float(prof.mean())
        res["twin_sd"] = float(prof.std())
        out["modes"][mode] = res
    return out


def conservative_luck(luck: dict, N: int, modes=None) -> float:
    """Larger (more sceptical) luck score across the chosen null models (default: all of them)."""
    ms = [m for k, m in luck.get("modes", {}).items() if modes is None or k in modes]
    vals = [float(-np.expm1(N * np.log1p(-m["p_single"]))) for m in ms]
    return float(max(vals)) if vals else float("nan")
