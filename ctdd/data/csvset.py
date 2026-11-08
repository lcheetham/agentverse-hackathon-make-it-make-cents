"""Load a dataset in the CSV schema used by the Streamlit prototype (`copytrader/`) into the shapes
the engine expects, so the frozen engine can be run on it unchanged.

Input directory (one row per ...):
    markets.csv        market_id, title, rules, open_ts, resolve_ts, outcome_yes, spread, fee_rate
    trades.csv         tx_id, wallet, market_id, side (YES|NO), action (BUY|SELL), price, shares, ts
    prices.csv         market_id, ts, price_yes   (a step function: each price holds until the next row)
    wallets_truth.csv  wallet, true_type, edge, demo_role   (planted answers; evaluation only)

Mapping to the engine (see ctdd/engine/positions.py):
    condition_id = market_id;  outcome_index = 0 for YES, 1 for NO;  token_id = "<market_id>-<index>"
    side = action;  size = shares;  payouts = [1, 0] if outcome_yes == 1 else [0, 1]
    event_slug = "" (the CSV has no event grouping; markets_truth.csv does, but that is hidden truth
    and the engine never reads it), so related bets are grouped only by the engine's own heuristic.

price_at(token_id, ts) follows the prototype's PriceBook: the latest price row at or before ts,
and None once the market has resolved (the engine treats that as "no follower fill").
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class CsvDataset:
    path: Path
    fills: pd.DataFrame
    markets: pd.DataFrame
    truth: pd.DataFrame | None
    _ts: dict
    _px: dict

    def price_at(self, token_id: str, ts: float):
        mid, _, idx = str(token_id).rpartition("-")
        if mid not in self._ts:
            return None
        if ts >= self.markets.at[mid, "resolve_ts"]:
            return None
        arr = self._ts[mid]
        i = int(np.searchsorted(arr, ts, side="right")) - 1
        p = float(self._px[mid][max(i, 0)])
        return p if idx == "0" else 1.0 - p


def load_csv_dataset(path: str | Path) -> CsvDataset:
    path = Path(path)
    mk = pd.read_csv(path / "markets.csv")
    tr = pd.read_csv(path / "trades.csv")
    pr = pd.read_csv(path / "prices.csv").sort_values(["market_id", "ts"])

    resolved = mk["outcome_yes"].notna()
    markets = pd.DataFrame({
        "title": mk["title"].fillna(""),
        "rules": mk["rules"].fillna(""),
        "event_slug": "",
        "neg_risk": False,
        "resolved": resolved,
        "resolve_ts": mk["resolve_ts"].astype(float),
        "payouts": [([1.0, 0.0] if y == 1 else [0.0, 1.0]) if ok else None
                    for y, ok in zip(mk["outcome_yes"], resolved)],
    })
    markets.index = mk["market_id"].astype(str)

    idx = np.where(tr["side"].str.upper() == "YES", 0, 1)
    mid = tr["market_id"].astype(str)
    fills = pd.DataFrame({
        "wallet": tr["wallet"].astype(str),
        "condition_id": mid,
        "token_id": mid + "-" + idx.astype(str),
        "outcome_index": idx,
        "side": tr["action"].str.upper(),
        "price": tr["price"].astype(float),
        "size": tr["shares"].astype(float),
        "ts": tr["ts"].astype(int),
        "title": mid.map(markets["title"]).fillna(""),
        "event_slug": "",
    })

    ts, px = {}, {}
    for m, g in pr.groupby("market_id", sort=False):
        ts[str(m)] = g["ts"].to_numpy()
        px[str(m)] = g["price_yes"].to_numpy(dtype=float)

    tf = path / "wallets_truth.csv"
    truth = pd.read_csv(tf, dtype={"demo_role": "string"}).fillna({"demo_role": ""}) if tf.exists() else None
    return CsvDataset(path, fills, markets, truth, ts, px)
