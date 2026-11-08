"""Bad or manipulative input checks. Severe failures make the agent HOLD and ask a human.

Checks (each returns pass/fail with the count behind it):
  address      wallet is a well-formed 0x address
  fills        prices in (0,1), sizes > 0, no future timestamps, no exact duplicate fills
  wash         round trips: buy and sell of the same token within 60 s at ~the same price
               (inflates volume/activity without risk; a classic leaderboard-gaming pattern)
  both_sides   holding YES and NO of the same market at once (risk-free merges dressed up as bets)
  injection    market titles/rules containing instructions aimed at an AI ("ignore previous...");
               such text is withheld from the LLM and the market is flagged
  payouts      resolved payouts are 0, 0.5 or 1
"""
from __future__ import annotations

import re
import time

import numpy as np
import pandas as pd

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
INJECTION_RE = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (the )?(instructions|rules)|"
    r"system prompt|you are (now )?an? (ai|assistant|language model)|act as|new instructions|"
    r"output (only|the following)|respond with|return json|verdict\s*[:=]|mark (this|me) as skilled|"
    r"</?(system|assistant|user)>)",
    re.IGNORECASE,
)


def valid_address(addr: str) -> bool:
    return bool(ADDRESS_RE.match((addr or "").strip()))


def injected(text: str) -> bool:
    return bool(INJECTION_RE.search(text or ""))


def check_inputs(wallet: str, fills: pd.DataFrame, markets: pd.DataFrame, synthetic: bool = False) -> dict:
    checks = []

    def add(name, ok, detail, severe=False):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "severe": bool(severe and not ok)})

    if not synthetic:
        add("address", valid_address(wallet), "well-formed 0x address" if valid_address(wallet) else "not a 0x + 40 hex address", severe=True)
    f = fills
    if len(f):
        bad_px = int(((f["price"] <= 0) | (f["price"] >= 1)).sum())
        bad_sz = int((f["size"] <= 0).sum())
        future = int((f["ts"] > time.time() + 3600).sum()) if not synthetic else 0
        dupes = int(f.duplicated().sum())
        n_bad = bad_px + bad_sz + future
        add("fills", n_bad == 0, f"{bad_px} bad prices, {bad_sz} bad sizes, {future} future timestamps, {dupes} exact duplicates",
            severe=n_bad > 0.05 * len(f))
        # Wash-style round trips: BUY then SELL (or SELL then BUY) of one token within 60 s at <= 0.5c difference.
        g = f.sort_values("ts")
        wash_vol = 0.0
        for _, t in g.groupby("token_id"):
            if t["side"].nunique() < 2:
                continue
            ts, px, side, sz = t["ts"].to_numpy(), t["price"].to_numpy(), t["side"].to_numpy(), t["size"].to_numpy()
            for i in range(1, len(t)):
                if side[i] != side[i - 1] and ts[i] - ts[i - 1] <= 60 and abs(px[i] - px[i - 1]) <= 0.005:
                    wash_vol += min(sz[i], sz[i - 1]) * px[i]
        total_vol = float((f["price"] * f["size"]).sum()) or 1.0
        share = wash_vol / total_vol
        add("wash", share < 0.10, f"{share:.1%} of volume is quick same-price round trips", severe=share >= 0.30)
        # Both sides of one market held at once.
        buys = f[f["side"] == "BUY"].groupby("condition_id")["outcome_index"].nunique()
        both = int((buys > 1).sum())
        n_m = int(f["condition_id"].nunique()) or 1
        add("both_sides", both / n_m < 0.20, f"{both}/{n_m} markets bought on both sides")
    else:
        add("fills", False, "no fills", severe=True)
    if len(markets):
        text = markets["title"].fillna("") + " " + markets["rules"].fillna("").astype(str)
        hits = [cid for cid, t in zip(markets.index, text) if injected(t)]
        add("injection", not hits, f"{len(hits)} market texts contain instructions aimed at an AI" + (f" (e.g. {hits[0]})" if hits else ""))
        pays = markets.loc[markets["resolved"].astype(bool), "payouts"]
        odd = sum(1 for p in pays if isinstance(p, (list, tuple)) and any(x not in (0.0, 0.5, 1.0) for x in p))
        add("payouts", odd == 0, f"{odd} resolved markets with payouts other than 0 / 0.5 / 1")
    severe = [c for c in checks if c["severe"]]
    return {"checks": checks, "ok": all(c["ok"] for c in checks), "hold": bool(severe),
            "injected_markets": [cid for cid, t in zip(markets.index, (markets["title"].fillna("") + " " + markets["rules"].fillna("").astype(str))) if injected(t)] if len(markets) else []}
