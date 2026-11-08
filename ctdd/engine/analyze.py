"""analyze_wallet(): every number on the report card, each with a stable id."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .copydelay import delay_curve, delayed_returns
from .decision import bottom_line, what_would_change
from .integrity import check_inputs
from .luck import conservative_luck, luck_score
from .skill import betting_evidence, cluster_returns, coin_flip_luck, se_from_ci, shrink
from .stats import cluster_bootstrap_mean
from .verdict import decide

DEFAULT_PRIOR = {"m": 0.0, "tau": 0.03, "n": 0, "source": "default (no population fitted yet)"}


def _stat(stats: dict, sid: str, label: str, value, unit: str = "", lo=None, hi=None, source: str = ""):
    stats[sid] = {"id": sid, "label": label, "value": value, "unit": unit, "lo": lo, "hi": hi, "source": source}


def analyze_wallet(
    wallet: str,
    positions: pd.DataFrame,
    markets: pd.DataFrame,
    clusters: dict,
    price_at,
    N_eff: int,
    th: dict,
    categories: dict | None = None,
    directions: dict | None = None,
    synthetic: bool = False,
    seed: int = 0,
    luck_sims: int | None = None,
    calibration: dict | None = None,
    prior: dict | None = None,
    fills: pd.DataFrame | None = None,
) -> dict:
    eng, costs, vth = th["engine"], th["costs"], th["verdict"]
    pos = positions.copy()
    pos["cluster"] = [clusters.get(c) or (e or c) for c, e in zip(pos["condition_id"], pos["event_slug"])]
    pos["category"] = [(categories or {}).get(c, "other") for c in pos["condition_id"]]
    closed = pos[pos["status"] != "open"].reset_index(drop=True)
    stats: dict = {}

    profit = float(closed["pnl"].sum())
    _stat(stats, "S.profit", "Realised profit", round(profit, 2), "$", source="sum of position P&L")
    _stat(stats, "S.n_closed", "Closed positions", int(len(closed)), source="positions with known P&L")
    _stat(stats, "S.n_open", "Open positions (excluded)", int((pos["status"] == "open").sum()))
    win_rate = float((closed["pnl"] > 0).mean()) if len(closed) else float("nan")
    _stat(stats, "S.win_rate", "Win rate", round(win_rate, 4), "share")
    _stat(stats, "S.avg_price", "Average entry price", round(float(closed["avg_entry"].mean()), 4) if len(closed) else float("nan"), "$/share")

    # Edge with cluster bootstrap
    edge = cluster_bootstrap_mean(closed["ret"], closed["cluster"], B=eng["bootstrap_B"], seed=seed)
    _stat(stats, "S.edge", "Edge per position (return on cost)", round(edge["mean"], 4), "share", round(edge["lo"], 4), round(edge["hi"], 4),
          "mean of P&L/cost, CI by resampling event clusters")
    _stat(stats, "S.n_clusters", "Independent event clusters", int(edge["n_clusters"]))

    # Luck score
    Ns = sorted(set(list(eng["luck_N"]) + [int(N_eff)]))
    # Scale M with N so the add-one floor, 1-(1-1/M)^N ~ N/M, stays at ~0.025 (below the 0.05 threshold).
    M = luck_sims or int(min(400_000, max(eng["luck_sims"], 40 * int(N_eff))))
    luck = luck_score(pos, markets, Ns, clusters=dict(zip(pos["condition_id"], pos["cluster"])),
                      directions=directions, M=M, seed=seed, calibration=calibration)
    flip = coin_flip_luck(pos, Ns, M=M, seed=seed)
    if flip is not None:
        luck["modes"]["coinflip"] = flip
    # v1 used only the fair-odds twin (independent + shared); v2 takes the most sceptical of every null.
    luck_n_v1 = conservative_luck(luck, int(N_eff), modes=("independent", "shared"))
    luck_n = conservative_luck(luck, int(N_eff))
    _stat(stats, "S.N_eff", "Field size N (wallets the trader was picked from)", int(N_eff))
    _stat(stats, "S.luck", f"Luck score at N={int(N_eff)} (conservative mode)", round(luck_n, 4), "probability",
          source="1-(1-p)^N, p from M simulated no-skill twins")
    for mode, res in luck.get("modes", {}).items():
        _stat(stats, f"S.p_single.{mode}", f"Chance one no-skill twin does this well ({mode})", res["p_single"], "probability")
        for N, val in res["luck"].items():
            _stat(stats, f"S.luck.{mode}.{N}", f"Luck score N={N} ({mode})", round(val, 4), "probability")
    _stat(stats, "S.luck_coverage", "Share of closed positions covered by the luck score", round(luck["coverage_positions"], 4), "share")

    # Copy-delay decay
    curve = delay_curve(pos, "cluster", price_at, eng["delays_s"], costs["half_spread"], costs["fee_rate"], B=1000, seed=seed)
    delayed = next((c for c in curve if c["delay_s"] == vth["copy_delay_s"]), None)
    for c in curve:
        _stat(stats, f"S.edge_delay.{c['delay_s']}", f"Follower edge at {c['delay_s']}s delay after costs",
              round(c["mean"], 4) if not math.isnan(c["mean"]) else float("nan"), "share",
              round(c["lo"], 4) if not math.isnan(c["lo"]) else None, round(c["hi"], 4) if not math.isnan(c["hi"]) else None)

    # Concentration: drop the single biggest-profit cluster
    if len(closed):
        by_cluster = closed.groupby("cluster")["pnl"].sum().sort_values(ascending=False)
        top = by_cluster.index[0]
        rest = closed[closed["cluster"] != top]
        conc = {
            "top_cluster": str(top),
            "top_cluster_profit": float(by_cluster.iloc[0]),
            "profit_without_top": float(rest["pnl"].sum()),
            "edge_without_top": float(rest["ret"].mean()) if len(rest) else float("nan"),
            "top_share_of_profit": float(by_cluster.iloc[0] / profit) if profit > 0 else float("nan"),
        }
    else:
        conc = {"top_cluster": None, "top_cluster_profit": 0.0, "profit_without_top": 0.0, "edge_without_top": float("nan"), "top_share_of_profit": float("nan")}
    _stat(stats, "S.profit_wo_top", "Profit without the biggest cluster", round(conc["profit_without_top"], 2), "$")

    # Category breakdown
    cats = []
    for cat, g in closed.groupby("category"):
        ci = cluster_bootstrap_mean(g["ret"], g["cluster"], B=500, seed=seed)
        cats.append({"category": cat, "n": int(len(g)), "profit": float(g["pnl"].sum()), "edge": ci["mean"], "lo": ci["lo"], "hi": ci["hi"]})
    cats.sort(key=lambda x: -x["profit"])

    # What GBP 200 would have become: GBP 10 per copy at the verdict's copy delay, after costs (historical simulation)
    ret_d, _ = delayed_returns(closed, price_at, vth["copy_delay_s"], costs["half_spread"], costs["fee_rate"])
    bank, peak, mdd, wiped = 200.0, 200.0, 0.0, False
    for r in ret_d:
        if math.isnan(r):
            continue
        if bank < 10:
            wiped = True
            break
        bank += 10 * r
        peak = max(peak, bank)
        mdd = max(mdd, (peak - bank) / peak)
    sim = {"start": 200.0, "end": round(bank, 2), "max_drawdown": round(mdd, 4), "stake_per_copy": 10.0,
           "delay_s": vth["copy_delay_s"], "copies": int(np.sum(~np.isnan(ret_d))), "ran_out_of_cash": wiped}
    _stat(stats, "S.sim200_end", "GBP 200 copying at the verdict delay became (historical simulation)", sim["end"], "GBP")

    # Flags for human review (never accusations)
    flags = []
    held = closed[closed["status"] == "held"]
    if len(held):
        late = held[(held["resolve_ts"] - held["first_ts"] < 3600) & (held["avg_entry"] < 0.6) & (held["payout"] > 0.5)]
        if len(late) >= 3 and len(late) / len(held) >= 0.1:
            flags.append(f"Needs human review: {len(late)} winning entries below 60c placed within an hour of resolution.")
    if len(closed) and (closed["avg_entry"] >= 0.95).mean() > 0.5:
        flags.append("Pattern: most entries are at 95c or above (near-certainty farming). One upset can erase many small wins.")
    if not math.isnan(conc["top_share_of_profit"]) and conc["top_share_of_profit"] > 0.5:
        flags.append("Concentration: over half of the profit comes from one event cluster.")
    if luck["coverage_positions"] < 0.6 and len(closed):
        flags.append(f"Luck score covers only {luck['coverage_positions']:.0%} of positions (early exits are excluded).")
    if edge["n_clusters"] < vth["min_clusters"]:
        flags.append(f"Only {edge['n_clusters']} independent clusters: confidence intervals are unreliable.")

    # --- v2: evidence that grows with every settled cluster (testing by betting) ---
    R = cluster_returns(closed)["r"].to_numpy() if len(closed) else np.array([])
    betting = betting_evidence(R, int(N_eff))
    _stat(stats, "S.e_value", "Betting evidence (wealth multiple of a sceptic betting on skill)", round(betting["e_value"], 3), "x",
          source=f"testing by betting on {betting['n_clusters']} cluster returns; skill proven at >= N/5% = {betting['target_e']:,.0f}")
    if betting["clusters_needed"] is not None:
        _stat(stats, "S.clusters_needed", "More settled event clusters needed to prove skill at the current edge", int(betting["clusters_needed"]))
    verdict, reasons = decide(edge, edge["n_clusters"], luck_n, delayed, th, betting_proven=betting["proven"])
    verdict_v1, _ = decide(edge, edge["n_clusters"], luck_n_v1, delayed, th)
    d_mean = (delayed or {}).get("mean", float("nan"))
    # Diagnostic only (tested and rejected as a decision input: overconfident on selected wallets).
    prior = prior or DEFAULT_PRIOR
    post_edge = shrink(edge["mean"], se_from_ci(edge["lo"], edge["hi"]), prior)
    post_follow = shrink(d_mean, se_from_ci((delayed or {}).get("lo"), (delayed or {}).get("hi")), prior)
    integrity = check_inputs(wallet, fills if fills is not None else pd.DataFrame(), markets.loc[markets.index.intersection(pos["condition_id"].unique())], synthetic)
    for c in integrity["checks"]:
        if not c["ok"]:
            flags.append(f"Input check '{c['check']}' failed: {c['detail']}." + (" Agent holds for human review." if c["severe"] else ""))
    action = bottom_line(verdict, betting, d_mean, integrity)
    changes = what_would_change(verdict, luck_n, int(N_eff), th, betting, delayed, edge["n_clusters"], edge)
    return {
        "wallet": wallet,
        "synthetic": synthetic,
        "verdict": verdict,
        "verdict_v1": verdict_v1,
        "luck_n_v1": luck_n_v1,
        "bottom_line": action,
        "what_would_change": changes,
        "betting": betting,
        "posterior_edge": post_edge,
        "posterior_follow": post_follow,
        "prior": prior,
        "integrity": integrity,
        "verdict_reasons": reasons,
        "deciding_stats": ["S.luck", "S.edge", "S.n_clusters", f"S.edge_delay.{vth['copy_delay_s']}"],
        "stats": stats,
        "edge": edge,
        "luck": luck,
        "luck_n": luck_n,
        "delay_curve": curve,
        "concentration": conc,
        "categories": cats,
        "sim200": sim,
        "flags": flags,
        "positions": pos,
    }
