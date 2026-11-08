"""Copy-delay decay: what a follower actually gets after delay, spread and fees."""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from .stats import cluster_bootstrap_mean

PriceFn = Callable[[str, float], Optional[float]]


def delayed_returns(
    positions: pd.DataFrame,
    price_at: PriceFn,
    delay_s: float,
    half_spread: float = 0.005,
    fee_rate: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Follower return per closed position. Returns (ret, missed); ret is NaN where the copy was impossible.

    Follower enters at the market price `delay_s` after the leader's first entry, paying
    half the spread and the fee. Held positions settle at the payout; early exits are copied
    `delay_s` after the leader's last sell at the then-price minus half the spread.
    """
    n = len(positions)
    ret = np.full(n, np.nan)
    missed = np.zeros(n, dtype=bool)
    for i, r in enumerate(positions.itertuples(index=False)):
        if r.status == "open":
            missed[i] = True
            continue
        t_in = float(r.first_ts) + delay_s
        res_ts = float(r.resolve_ts) if r.resolve_ts == r.resolve_ts else np.inf
        if t_in >= res_ts:
            missed[i] = True
            continue
        px = price_at(r.token_id, t_in)
        if px is None or not (0 < px < 1):
            missed[i] = True
            continue
        entry = min(px + half_spread, 0.999) * (1 + fee_rate)
        if r.status == "held":
            exit_ = float(r.payout)
        else:
            t_out = float(r.last_sell_ts) + delay_s if r.last_sell_ts == r.last_sell_ts else t_in
            if t_out >= res_ts and r.payout == r.payout:
                exit_ = float(r.payout)
            else:
                px2 = price_at(r.token_id, t_out)
                exit_ = max(px2 - half_spread, 0.0) if px2 is not None else float(r.avg_exit)
        ret[i] = exit_ / entry - 1
    return ret, missed


def delay_curve(
    positions: pd.DataFrame,
    cluster_col: str,
    price_at: PriceFn,
    delays,
    half_spread: float,
    fee_rate: float,
    B: int = 1000,
    seed: int = 0,
) -> list[dict]:
    closed = positions[positions["status"] != "open"].reset_index(drop=True)
    out = []
    for d in delays:
        ret, missed = delayed_returns(closed, price_at, d, half_spread, fee_rate)
        ci = cluster_bootstrap_mean(ret, closed[cluster_col].to_numpy(), B=B, seed=seed)
        ci.update({"delay_s": int(d), "miss_rate": float(missed.mean()) if len(missed) else float("nan")})
        out.append(ci)
    return out
