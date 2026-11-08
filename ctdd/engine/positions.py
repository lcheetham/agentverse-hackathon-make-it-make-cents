"""Fills -> positions.

Fills (one row per trade):
    wallet, condition_id, token_id, outcome_index, side ('BUY'|'SELL'), price, size, ts, title, event_slug
Markets (index = condition_id):
    title, rules, event_slug, neg_risk, resolved, resolve_ts, payouts (list[float] by outcome index or None)

One position = one (wallet, token). P&L = sell proceeds + remaining shares x payout - cost.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POSITION_COLUMNS = [
    "wallet", "condition_id", "token_id", "outcome_index", "event_slug", "title",
    "shares", "cost", "avg_entry", "shares_sold", "proceeds", "avg_exit",
    "first_ts", "last_sell_ts", "resolve_ts", "payout", "status", "pnl", "ret",
]


def build_positions(fills: pd.DataFrame, markets: pd.DataFrame, hold_sold_frac: float = 0.05) -> pd.DataFrame:
    if fills.empty:
        return pd.DataFrame(columns=POSITION_COLUMNS)
    f = fills.copy()
    f["notional"] = f["price"].astype(float) * f["size"].astype(float)
    key = ["wallet", "token_id"]

    buys = f[f["side"] == "BUY"].groupby(key).agg(
        condition_id=("condition_id", "first"),
        outcome_index=("outcome_index", "first"),
        event_slug=("event_slug", "first"),
        title=("title", "first"),
        shares=("size", "sum"),
        cost=("notional", "sum"),
        first_ts=("ts", "min"),
    )
    sells = f[f["side"] == "SELL"].groupby(key).agg(
        shares_sold=("size", "sum"),
        proceeds=("notional", "sum"),
        last_sell_ts=("ts", "max"),
    )
    p = buys.join(sells, how="left").reset_index()
    p["shares_sold"] = p["shares_sold"].fillna(0.0)
    p["proceeds"] = p["proceeds"].fillna(0.0)
    # Shares can be sold that were not bought here (splits/transfers). Scale proceeds to what we saw bought.
    over = p["shares_sold"] > p["shares"]
    p.loc[over, "proceeds"] = p.loc[over, "proceeds"] * p.loc[over, "shares"] / p.loc[over, "shares_sold"]
    p.loc[over, "shares_sold"] = p.loc[over, "shares"]

    p["avg_entry"] = p["cost"] / p["shares"]
    p["avg_exit"] = np.where(p["shares_sold"] > 0, p["proceeds"] / p["shares_sold"].where(p["shares_sold"] > 0, 1), np.nan)

    m = markets.reindex(p["condition_id"])
    resolved = m["resolved"].fillna(False).astype(bool).to_numpy()
    p["resolve_ts"] = m["resolve_ts"].to_numpy(dtype=float)

    payout = np.full(len(p), np.nan)
    for i, (pays, oi, ok) in enumerate(zip(m["payouts"].to_numpy(), p["outcome_index"].to_numpy(), resolved)):
        if ok and isinstance(pays, (list, tuple)) and 0 <= int(oi) < len(pays):
            payout[i] = float(pays[int(oi)])
    p["payout"] = payout

    remaining = p["shares"] - p["shares_sold"]
    sold_frac = p["shares_sold"] / p["shares"]
    has_payout = ~np.isnan(payout)

    status = np.where(
        has_payout & (sold_frac < hold_sold_frac), "held",
        np.where(has_payout | (remaining / p["shares"] < hold_sold_frac), "exited", "open"),
    )
    p["status"] = status
    pnl = p["proceeds"] + remaining * np.nan_to_num(payout) - p["cost"]
    # Fully exited before resolution: P&L is proceeds only.
    pnl = np.where(status == "open", np.nan, pnl)
    p["pnl"] = pnl
    p["ret"] = p["pnl"] / p["cost"]
    p = p[p["cost"] > 0]
    return p[POSITION_COLUMNS].sort_values("first_ts").reset_index(drop=True)


def closed(positions: pd.DataFrame) -> pd.DataFrame:
    """Positions with a known P&L (held to resolution or exited)."""
    return positions[positions["status"] != "open"]
