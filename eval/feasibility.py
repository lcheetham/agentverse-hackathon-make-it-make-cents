"""First-hour feasibility check (spec section 2), against live Polymarket data.

    python -m eval.feasibility --wallets 3 --pages 4

1. Pull fills (incl. SELLs) for leaderboard wallets.
2. Rebuild positions and compare realised P&L with Polymarket's own CLOSED positions.
3. Confirm price history at arbitrary timestamps.
4. Count wallets with >= 20 resolved positions either side of a candidate cut-off.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from ctdd.config import EVAL_DIR, load_thresholds
from ctdd.data.polymarket import PolymarketClient
from ctdd.engine.positions import build_positions
from ctdd.pipeline import real_dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallets", type=int, default=3)
    ap.add_argument("--pages", type=int, default=4, help="500 fills per page")
    ap.add_argument("--period", default="month")
    ap.add_argument("--cutoff-days", type=float, default=14, help="candidate cut-off = now - this many days")
    a = ap.parse_args()
    th = load_thresholds()
    c = PolymarketClient()
    report = {"steps": {}}

    lb = c.leaderboard(a.period, n=max(50, a.wallets))
    print(f"Leaderboard ({a.period}): {len(lb)} wallets pulled")
    wallets = lb["user_id"].str.lower().head(a.wallets).tolist()
    cutoff = pd.Timestamp.now(tz="UTC").timestamp() - a.cutoff_days * 86400
    rows = []
    for w in wallets:
        fills, mk = real_dataset(c, w, a.pages)
        if fills.empty:
            rows.append({"wallet": w, "fills": 0})
            continue
        pos = build_positions(fills, mk, th["engine"]["hold_sold_frac"])
        closed_pm = c.closed_positions(w, max_pages=4)
        match = {}
        if not closed_pm.empty:
            pm = closed_pm.assign(token_id=closed_pm["token_id"].astype(str)).set_index("token_id")["realized_pnl"].astype(float)
            ours = pos[pos["status"] != "open"].set_index("token_id")["pnl"]
            both = ours.to_frame("ours").join(pm.rename("polymarket"), how="inner")
            if len(both) >= 3:
                match = {"n_matched": int(len(both)), "corr": float(np.corrcoef(both["ours"], both["polymarket"])[0, 1]),
                         "median_abs_diff": float((both["ours"] - both["polymarket"]).abs().median()),
                         "within_1usd_or_2pct": float((((both["ours"] - both["polymarket"]).abs() <= np.maximum(1, 0.02 * both["polymarket"].abs()))).mean())}
        resolved = pos[pos["status"] != "open"]
        rows.append({
            "wallet": w, "fills": len(fills), "sells": int((fills["side"] == "SELL").sum()),
            "fills_span_days": round((fills["ts"].max() - fills["ts"].min()) / 86400, 1),
            "positions": len(pos), "held": int((pos["status"] == "held").sum()), "exited": int((pos["status"] == "exited").sum()),
            "open": int((pos["status"] == "open").sum()),
            "resolved_before_cutoff": int((resolved["first_ts"] < cutoff).sum()),
            "resolved_after_cutoff": int((resolved["first_ts"] >= cutoff).sum()),
            **{f"pnl_check_{k}": v for k, v in match.items()},
        })
        print(json.dumps(rows[-1]))
    df = pd.DataFrame(rows)
    report["steps"]["1_fills_incl_sells"] = bool((df.get("sells", pd.Series([0])) > 0).any())
    report["steps"]["2_pnl_rebuild_corr"] = float(df["pnl_check_corr"].mean()) if "pnl_check_corr" in df else None

    # Step 3: price at an arbitrary timestamp for one token
    any_fills = c.trades(wallets[0], max_pages=1)
    tok, ts = any_fills.iloc[-1]["token_id"], int(any_fills.iloc[-1]["ts"])
    hist = c.price_history(tok, ts - 600, ts + 3 * 3600)
    report["steps"]["3_price_history_points"] = len(hist)

    ok4 = df[(df.get("resolved_before_cutoff", 0) >= 20) & (df.get("resolved_after_cutoff", 0) >= 20)] if "resolved_before_cutoff" in df else df.iloc[:0]
    report["steps"]["4_wallets_with_20_each_side"] = f"{len(ok4)}/{len(df)}"
    report["wallets"] = rows
    out = EVAL_DIR / "results" / "feasibility.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["steps"], indent=2))


if __name__ == "__main__":
    main()
