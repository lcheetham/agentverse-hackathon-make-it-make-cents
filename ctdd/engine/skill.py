"""Upgraded skill-vs-luck methods (see docs/SPEC.md §3b and the research notes in docs/METHODS.md).

1. coin_flip_luck      Direction-randomised null (Gomez-Cram, Guo, Jensen & Kung 2026): keep each bet's
                       market, timing and stake, flip buy-this-side vs buy-the-other-side at random.
                       Needs no assumption that prices are calibrated.
2. calibration_table   Polymarket's empirical win rate by price band, learned from *earlier* resolved
                       positions (favourite-longshot bias), for a calibrated no-skill twin.
3. betting_evidence    Testing by betting (Shafer/Vovk; Ramdas et al.): a sceptic's wealth from betting that
                       the trader has an edge, on event-cluster returns. Anytime-valid by Ville's inequality,
                       and it gives "how many more settled clusters would prove it".
4. fit_prior / shrink  Empirical-Bayes normal-normal shrinkage across a population (Jones & Shanken 2005;
                       Baks, Metrick & Wachter 2001): every wallet gets a posterior edge and P(edge > 0).
5. storey_qvalues      False-discovery-rate view across a population (Barras, Scaillet & Wermers 2010).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from .luck import luck_from_profits


# ---------------------------------------------------------------- 1. coin-flip null
def coin_flip_profits(held: pd.DataFrame, M: int = 50_000, seed: int = 0) -> np.ndarray:
    """Profit distribution when each bet's direction is a fair coin flip.

    Original bet: stake c at price p on side S -> profit a = c/p * 1[S wins] - c.
    Flipped bet:  same stake on the other side at 1-p -> profit b = c/(1-p) * 1[S loses] - c.
    Outcomes are the real ones; only the direction is randomised.
    """
    if len(held) == 0:
        return np.zeros(M)
    p = np.clip(held["avg_entry"].to_numpy(dtype=float), 0.01, 0.99)
    c = held["cost"].to_numpy(dtype=float)
    won = (held["payout"].to_numpy(dtype=float) > 0.5).astype(float)
    a = c / p * won - c
    b = c / (1 - p) * (1 - won) - c
    rng = np.random.default_rng(seed)
    out = np.empty(M)
    chunk = max(1000, min(50_000, 20_000_000 // len(p)))
    base, diff = b.sum(), a - b
    for s in range(0, M, chunk):
        m = min(chunk, M - s)
        keep = rng.random((m, len(p))) < 0.5
        out[s:s + m] = base + keep.astype(np.float64) @ diff
    return out


def coin_flip_luck(positions: pd.DataFrame, Ns, M: int = 50_000, seed: int = 0) -> dict | None:
    held = positions[positions["status"] == "held"]
    if len(held) == 0:
        return None
    real = float(held["pnl"].sum())
    res = luck_from_profits(real, coin_flip_profits(held, M, seed), Ns)
    res["null"] = "coin-flip direction (Gomez-Cram et al. 2026)"
    return res


# ---------------------------------------------------------------- 2. calibrated twin
CAL_EDGES = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.0]


def calibration_table(history: pd.DataFrame, pseudo: float = 30.0) -> dict:
    """Empirical win rate per price band from earlier held-to-resolution positions.

    Each band is shrunk toward its own mid-price with `pseudo` pseudo-observations, so thin bands stay
    close to "prices are fair" instead of swinging on a handful of results.
    """
    h = history[history["status"] == "held"]
    edges = np.asarray(CAL_EDGES)
    mids = (edges[:-1] + edges[1:]) / 2
    p = np.clip(h["avg_entry"].to_numpy(dtype=float), 1e-4, 1 - 1e-4)
    won = (h["payout"].to_numpy(dtype=float) > 0.5).astype(float)
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(mids) - 1)
    rates, counts = [], []
    for k in range(len(mids)):
        m = idx == k
        n = int(m.sum())
        avg_p = float(p[m].mean()) if n else mids[k]
        rates.append(float((won[m].sum() + pseudo * avg_p) / (n + pseudo)))
        counts.append(n)
    return {"edges": edges.tolist(), "rates": rates, "counts": counts, "n": int(len(h))}


# ---------------------------------------------------------------- 3. testing by betting
def cluster_returns(closed: pd.DataFrame, cluster_col: str = "cluster") -> pd.DataFrame:
    """One return per event cluster (dollar-weighted), in time order. Under a fair-odds null each has mean 0."""
    g = closed.groupby(cluster_col).agg(pnl=("pnl", "sum"), cost=("cost", "sum"), t=("first_ts", "min"))
    g = g[g["cost"] > 0]
    g["r"] = g["pnl"] / g["cost"]
    return g.sort_values("t")


def _lam(r: np.ndarray, lam_max: float) -> float:
    if len(r) < 3:
        return 0.0
    m, v = float(r.mean()), float(r.var())
    return float(np.clip(m / (v + m * m), 0.0, lam_max)) if m > 0 else 0.0


def betting_evidence(R: np.ndarray, N: int, alpha: float = 0.05, lam_max: float = 0.5) -> dict:
    """A sceptic bets fraction lambda_t (chosen only from past clusters) that each cluster return is positive.

    Wealth W_t = prod(1 + lambda_t r_t). Under the null E[r] <= 0, W is a nonnegative supermartingale, so
    P(sup W >= x) <= 1/x (Ville). Proof of skill against a field of N: W >= N/alpha.
    Bets-needed extrapolates the full-sample log-growth per cluster.
    """
    R = np.asarray(R, dtype=float)
    W, logW, maxW = 1.0, 0.0, 1.0
    for t in range(len(R)):
        lam = _lam(R[:t], lam_max)
        logW += math.log1p(lam * R[t])
        maxW = max(maxW, math.exp(logW))
    target = math.log(N / alpha)
    lam_star = _lam(R, lam_max)
    g = float(np.mean(np.log1p(lam_star * R))) if len(R) else 0.0
    need = None
    if logW >= target:
        need = 0
    elif g > 1e-9:
        need = int(math.ceil((target - logW) / g))
    return {"e_value": math.exp(min(logW, 700)), "log_e": logW, "max_e": maxW, "target_e": N / alpha, "watch_e": float(N),
            "proven": logW >= target, "growth_per_cluster": g, "clusters_needed": need, "n_clusters": int(len(R))}


# ---------------------------------------------------------------- 4. empirical-Bayes shrinkage
def se_from_ci(lo: float, hi: float) -> float:
    if lo is None or hi is None or any(isinstance(x, float) and math.isnan(x) for x in (lo, hi)):
        return float("nan")
    return max((hi - lo) / (2 * 1.96), 1e-6)


def fit_prior(est, se, center_zero: bool = False) -> dict:
    """Normal-normal prior N(m, tau^2) by method of moments (Jones & Shanken style learning across wallets)."""
    est, se = np.asarray(est, float), np.asarray(se, float)
    ok = ~(np.isnan(est) | np.isnan(se))
    est, se = est[ok], se[ok]
    if len(est) < 5:
        return {"m": 0.0, "tau": 0.03, "n": int(len(est)), "source": "default (too few wallets to fit)"}
    w = 1 / se ** 2
    m = 0.0 if center_zero else float(np.sum(w * est) / np.sum(w))
    tau2 = max(float(np.mean((est - m) ** 2 - se ** 2)), 1e-6)
    return {"m": m, "tau": math.sqrt(tau2), "n": int(len(est)), "source": "fitted"}


def shrink(est: float, se: float, prior: dict) -> dict:
    """Posterior of the true edge given an estimate and its standard error."""
    if est is None or math.isnan(est) or math.isnan(se):
        return {"mean": float("nan"), "sd": float("nan"), "p_pos": float("nan"), "B": float("nan")}
    tau2, s2 = prior["tau"] ** 2, se ** 2
    B = tau2 / (tau2 + s2)
    mean = prior["m"] + B * (est - prior["m"])
    sd = math.sqrt(B * s2)
    return {"mean": mean, "sd": sd, "p_pos": float(norm.sf(-mean / sd)) if sd > 0 else float(mean > 0), "B": B}


# ---------------------------------------------------------------- 5. false-discovery view
def storey_qvalues(pvals, lam: float = 0.5) -> tuple[np.ndarray, float]:
    """Storey (2002) pi0 estimate and q-values: q = expected share of false discoveries if you call this one skilled."""
    p = np.asarray(pvals, float)
    n = len(p)
    if n == 0:
        return p, float("nan")
    pi0 = float(min(1.0, np.mean(p > lam) / (1 - lam)))
    order = np.argsort(p)
    q = np.empty(n)
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, pi0 * p[i] * n / rank)
        q[i] = prev
    return q, pi0
