"""End-to-end analysis of one wallet: fills -> positions -> clusters -> stats -> verdict -> report text."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from .agent.llm import LLM
from .agent.text_jobs import categorise, cluster_markets
from .agent.writer import write_report
from .audit import AuditLog
from .config import freeze_hash, load_thresholds
from .engine.analyze import analyze_wallet
from .engine.integrity import injected, valid_address
from .engine.positions import build_positions
from .data.polymarket import conversion_fills
from .config import EVAL_DIR

PRIOR_PATH = EVAL_DIR / "results" / "population_prior.json"


def load_population_prior() -> dict | None:
    """Empirical-Bayes prior fitted on the real walk-forward population (eval/walkforward.py writes it)."""
    import json

    if PRIOR_PATH.exists():
        return json.loads(PRIOR_PATH.read_text())
    return None


def run_wallet(
    wallet: str,
    fills: pd.DataFrame,
    markets: pd.DataFrame,
    price_at,
    N_eff: int,
    th: dict | None = None,
    llm: LLM | None = None,
    audit: AuditLog | None = None,
    synthetic: bool = False,
    luck_sims: int | None = None,
    seed: int = 0,
    write: bool = True,
    positions: pd.DataFrame | None = None,
    on_step=None,
    calibration: dict | None = None,
    prior: dict | None = None,
    cluster_with_llm: bool = True,
) -> dict:
    step = on_step or (lambda msg: None)
    th = th or load_thresholds()
    prior = prior or load_population_prior()
    audit = audit or AuditLog()
    wf = fills[fills["wallet"] == wallet]
    conds = pd.Index(wf["condition_id"].unique())
    mk = markets.loc[conds.intersection(markets.index)]
    if positions is None:
        positions = build_positions(wf, markets, th["engine"]["hold_sold_frac"])
    # Only markets behind closed positions feed any statistic, so only those are clustered.
    closed_conds = pd.Index(positions.loc[positions["status"] != "open", "condition_id"].unique())
    mk_closed = mk.loc[closed_conds.intersection(mk.index)].copy()
    # Market text is untrusted: anything that reads like instructions to an AI is withheld from the LLM.
    bad = [cid for cid, t, r in zip(mk_closed.index, mk_closed["title"].fillna(""), mk_closed["rules"].fillna("").astype(str)) if injected(t + " " + r)]
    if bad:
        mk_closed.loc[bad, "title"] = "[withheld: market text contained instructions aimed at an AI]"
        mk_closed.loc[bad, "rules"] = ""
        audit.log("injection_withheld", wallet=wallet, markets=bad)
    cl_llm = llm if cluster_with_llm else None
    step(f"Grouping {len(mk_closed)} markets into related-bet clusters"
         + (" with Gemini" if cl_llm is not None and cl_llm.available else "") + "…")
    clusters, directions, method = cluster_markets(mk_closed, cl_llm)
    categories = {cid: categorise(t) for cid, t in zip(mk.index, mk["title"])}
    step("Running the stats engine (edge, luck score, copy delay)…")
    report = analyze_wallet(wallet, positions, markets, clusters, price_at, N_eff, th, categories=categories,
                            directions=directions, synthetic=synthetic, seed=seed, luck_sims=luck_sims,
                            calibration=calibration, prior=prior,
                            # Split/merge rows are bookkeeping, not bets: keep them out of the input checks.
                            fills=wf[wf["conversion"].fillna("").eq("")] if "conversion" in wf else wf)
    report["cluster_method"] = method
    report["clusters"] = clusters
    report["freeze_hash"] = freeze_hash()
    if write:
        step("Writing the report" + (" with Gemini (number-guarded)" if llm is not None and llm.available else "") + "…")
        report["text"] = write_report(report, llm, audit)
    audit.log("verdict", wallet=wallet, synthetic=synthetic, verdict=report["verdict"], bottom_line=report["bottom_line"]["action"],
              p_follow=report["posterior_follow"]["p_pos"], e_value=report["betting"]["e_value"], luck=report["luck_n"],
              edge=report["edge"]["mean"], edge_lo=report["edge"]["lo"], n_clusters=report["edge"]["n_clusters"],
              N_eff=N_eff, cluster_method=method, freeze_hash=report["freeze_hash"])
    return report


def real_dataset(client, wallet: str, pages: int = 4):
    """Fills + market metadata for a real wallet (read-only public data)."""
    fills = client.trades(wallet, max_pages=pages)
    if fills.empty:
        return fills, pd.DataFrame()
    conv = client.conversions(wallet, max_pages=pages) if hasattr(client, "conversions") else []
    ids = pd.unique(pd.concat([fills["condition_id"], pd.Series([r.get("condition_id") for r in conv], dtype=object)]).dropna())
    mk = client.markets(ids)
    slug = fills.groupby("condition_id")["event_slug"].first()
    mk["event_slug"] = mk["event_slug"].where(mk["event_slug"].astype(bool), slug.reindex(mk.index).fillna(""))
    if conv:
        extra, info = conversion_fills(conv, mk, fills)
        fills = pd.concat([fills, extra], ignore_index=True).sort_values("ts", kind="stable").reset_index(drop=True)
        fills.attrs["conversions"] = info
    return fills, mk


def reconcile_with_polymarket(pos: pd.DataFrame, closed_pm: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Use Polymarket's own realised P&L (which includes trading fees) where a position matches.

    Our fill-level rebuild has no fee information; the gap to Polymarket's `realized_pnl` is the fee,
    which we add to cost so returns are net of fees. Returns (positions, info incl. observed fee rate).
    """
    info = {"matched": 0, "of_closed": int((pos["status"] != "open").sum()), "fee_rate": 0.0}
    if closed_pm.empty or "realized_pnl" not in closed_pm:
        return pos, info
    pm = closed_pm.assign(token_id=closed_pm["token_id"].astype(str)).drop_duplicates("token_id").set_index("token_id")
    pos = pos.copy()
    idx = pos.index[(pos["status"] != "open") & pos["token_id"].isin(pm.index)]
    if len(idx) == 0:
        return pos, info
    rows = pm.loc[pos.loc[idx, "token_id"]]
    pm_pnl = rows["realized_pnl"].astype(float).to_numpy()
    # Our fills may start mid-position (paging window). Polymarket's own size and average price are the
    # full position, so they replace ours; the fee is what remains between price x size and realised P&L.
    pm_shares = rows["total_size"].astype(float).to_numpy()
    pm_avg = rows["avg_price"].astype(float).to_numpy()
    ours_complete = np.abs(pos.loc[idx, "shares"].to_numpy() / np.where(pm_shares > 0, pm_shares, np.nan) - 1) < 0.01
    fee = np.where(ours_complete, np.clip(pos.loc[idx, "pnl"].to_numpy() - pm_pnl, 0, None),
                   rows["entry_fees_usdc"].astype(float).fillna(0).to_numpy())
    base_cost = np.where(ours_complete, pos.loc[idx, "cost"].to_numpy(), pm_shares * pm_avg)
    pos.loc[idx, "shares"] = np.where(ours_complete, pos.loc[idx, "shares"].to_numpy(), pm_shares)
    pos.loc[idx, "avg_entry"] = np.where(ours_complete, pos.loc[idx, "avg_entry"].to_numpy(), pm_avg)
    pos.loc[idx, "cost"] = base_cost + fee
    pos.loc[idx, "pnl"] = pm_pnl
    pos.loc[idx, "ret"] = pos.loc[idx, "pnl"] / pos.loc[idx, "cost"]
    notional = float(base_cost.sum())
    info.update(matched=int(len(idx)), completed_from_polymarket=int((~ours_complete).sum()),
                fee_rate=float(fee.sum() / notional) if notional > 0 else 0.0)
    return pos, info


def run_real_wallet(client, wallet: str, N_eff: int, pages: int = 4, price_positions: int = 60,
                    th: dict | None = None, llm: LLM | None = None, audit: AuditLog | None = None, on_step=None) -> dict:
    step = on_step or (lambda msg: None)
    th = copy.deepcopy(th or load_thresholds())
    wallet = wallet.strip().lower()
    if not valid_address(wallet):
        audit_ = audit or AuditLog()
        audit_.log("input_rejected", reason="invalid wallet address", value=wallet[:80])
        raise ValueError("That is not a Polymarket wallet address (expected 0x followed by 40 hex characters).")
    step("Downloading the wallet's public trades and market details from Polymarket…")
    fills, mk = real_dataset(client, wallet, pages)
    if fills.empty:
        raise ValueError("No trades found for this wallet.")
    step(f"Rebuilding positions from {len(fills)} fills and reconciling with Polymarket's own P&L…")
    pos = build_positions(fills, mk, th["engine"]["hold_sold_frac"])
    pos, rec = reconcile_with_polymarket(pos, client.closed_positions(wallet, max_pages=pages))
    # Followers pay at least the fee rate this wallet actually paid.
    th["costs"]["fee_rate"] = max(th["costs"]["fee_rate"], rec["fee_rate"])
    step(f"Fetching price history for up to {price_positions} positions (copy-delay test)…")
    price_at = client.price_at_factory(pos[pos["status"] != "open"], th["engine"]["delays_s"], max_positions=price_positions)
    report = run_wallet(wallet, fills, mk, price_at, N_eff, th=th, llm=llm, audit=audit, synthetic=False, positions=pos,
                        on_step=step)
    report["reconciliation"] = rec
    report["_price_at"] = price_at          # for the UI's copy-delay simulation at other delays
    report["_th"] = th                      # thresholds with this wallet's observed fee rate
    span = (fills["ts"].max() - fills["ts"].min()) / 86400
    conv = fills.attrs.get("conversions") or {}
    conv_note = ""
    if conv:
        conv_note = (f" Includes {conv['splits']} splits and {conv['merges']} merges, recorded as 50c fills on both outcomes"
                     + (f" ({conv['skipped']} skipped)." if conv.get("skipped") else "."))
    report["conversions"] = conv
    report["data_note"] = (f"{len(fills)} most recent fills ({pages} pages, {span:.1f} days). P&L reconciled to Polymarket's own "
                           f"realised P&L on {rec['matched']}/{rec['of_closed']} closed positions; observed fees ≈ {rec['fee_rate']:.2%} of notional, "
                           f"charged to the follower too. Copy-delay prices fetched for the {price_positions} most recent closed positions; "
                           f"others count as missed copies." + conv_note)
    return report
