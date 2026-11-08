"""Small statistical building blocks: cluster bootstrap and Wilson intervals."""
from __future__ import annotations

import math

import numpy as np


def cluster_bootstrap_mean(values, clusters, B: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Mean of `values` with a CI from resampling whole clusters (not individual rows).

    Ten markets on one election are one draw: the interval widens honestly when bets are correlated.
    """
    v = np.asarray(values, dtype=float)
    c = np.asarray(clusters)
    ok = ~np.isnan(v)
    v, c = v[ok], c[ok]
    n = len(v)
    if n == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0, "n_clusters": 0}
    uniq, inv = np.unique(c, return_inverse=True)
    k = len(uniq)
    sums = np.bincount(inv, weights=v, minlength=k)
    counts = np.bincount(inv, minlength=k).astype(float)
    mean = float(v.mean())
    if k < 2:
        return {"mean": mean, "lo": float("nan"), "hi": float("nan"), "n": n, "n_clusters": k}
    rng = np.random.default_rng(seed)
    out = np.empty(B)
    step = max(1, 2_000_000 // max(k, 1))
    for s in range(0, B, step):
        b = min(step, B - s)
        idx = rng.integers(0, k, size=(b, k))
        out[s:s + b] = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.quantile(out, [alpha / 2, 1 - alpha / 2])
    return {"mean": mean, "lo": float(lo), "hi": float(hi), "n": n, "n_clusters": k}


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for a proportion: (p, lo, hi)."""
    if n == 0:
        return float("nan"), 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)
