"""Tests for what the merge added: the CSV dataset adapter, split/merge conversion, the large planted batch."""
import json

import pandas as pd
import pytest

from ctdd.audit import AuditLog
from ctdd.config import EVAL_DIR, freeze_hash, load_thresholds
from ctdd.data.csvset import load_csv_dataset
from ctdd.data.polymarket import conversion_fills
from ctdd.pipeline import real_dataset, run_wallet

W = "0x" + "a" * 40


# ---------------- CSV dataset adapter ----------------
@pytest.fixture()
def csv_dir(tmp_path):
    pd.DataFrame([
        dict(market_id="M1", title="Will A win?", rules="r", open_ts=0, resolve_ts=10_000, outcome_yes=1, spread=0.01, fee_rate=0.0),
        dict(market_id="M2", title="Will B win?", rules="r", open_ts=0, resolve_ts=10_000, outcome_yes=0, spread=0.01, fee_rate=0.0),
    ]).to_csv(tmp_path / "markets.csv", index=False)
    pd.DataFrame([
        dict(tx_id="T1", wallet=W, market_id="M1", side="YES", action="BUY", price=0.40, shares=10, ts=100),
        dict(tx_id="T2", wallet=W, market_id="M2", side="NO", action="BUY", price=0.70, shares=10, ts=200),
        dict(tx_id="T3", wallet=W, market_id="M2", side="NO", action="SELL", price=0.80, shares=4, ts=5000),
    ]).to_csv(tmp_path / "trades.csv", index=False)
    pd.DataFrame([dict(market_id="M1", ts=0, price_yes=0.40), dict(market_id="M1", ts=3600, price_yes=0.55),
                  dict(market_id="M2", ts=0, price_yes=0.30)]).to_csv(tmp_path / "prices.csv", index=False)
    pd.DataFrame([dict(wallet=W, true_type="skilled", edge=0.1, demo_role="")]).to_csv(tmp_path / "wallets_truth.csv", index=False)
    return tmp_path


def test_csv_adapter_maps_schema(csv_dir):
    d = load_csv_dataset(csv_dir)
    assert set(d.fills["token_id"]) == {"M1-0", "M2-1"}
    assert list(d.fills["side"]) == ["BUY", "BUY", "SELL"]
    assert d.markets.at["M1", "payouts"] == [1.0, 0.0] and d.markets.at["M2", "payouts"] == [0.0, 1.0]
    assert (d.markets["event_slug"] == "").all()          # hidden event ids are never passed to the engine
    assert len(d.truth) == 1


def test_csv_price_at_is_a_step_function(csv_dir):
    d = load_csv_dataset(csv_dir)
    assert d.price_at("M1-0", 3599) == pytest.approx(0.40)
    assert d.price_at("M1-0", 3600) == pytest.approx(0.55)
    assert d.price_at("M1-1", 3600) == pytest.approx(0.45)    # NO = 1 - YES
    assert d.price_at("M1-0", 10_000) is None                 # resolved: no follower fill
    assert d.price_at("M9-0", 100) is None                    # unknown market


def test_engine_runs_on_csv_dataset(csv_dir):
    d = load_csv_dataset(csv_dir)
    r = run_wallet(W, d.fills, d.markets, d.price_at, 10, th=load_thresholds(), audit=AuditLog(csv_dir / "a.jsonl"),
                   synthetic=True, write=False)
    pos = r["positions"].set_index("token_id")
    assert pos.at["M1-0", "pnl"] == pytest.approx(10 * (1 - 0.40))
    assert pos.at["M2-1", "pnl"] == pytest.approx(4 * 0.80 + 6 * 1.0 - 7.0)
    assert r["verdict"] in ("Can't tell yet", "Probably luck")   # two bets prove nothing


# ---------------- split / merge conversion ----------------
def _markets(tokens=True):
    m = pd.DataFrame([dict(condition_id="C1", title="t", rules="", event_slug="ev", neg_risk=False, resolved=True,
                           resolve_ts=9e9, payouts=[1.0, 0.0], outcomes=["Yes", "No"],
                           token_ids=["T0", "T1"] if tokens else [])]).set_index("condition_id")
    return m


ACT = [dict(type="SPLIT", proxy_wallet=W.upper(), condition_id="C1", size=20, timestamp=100),
       dict(type="MERGE", proxy_wallet=W, condition_id="C1", size=5, timestamp=200)]


def test_split_and_merge_become_50c_fills_on_both_outcomes():
    f, info = conversion_fills(ACT, _markets())
    assert info == {"splits": 1, "merges": 1, "skipped": 0}
    assert len(f) == 4 and set(f["token_id"]) == {"T0", "T1"} and (f["price"] == 0.5).all()
    assert list(f["side"]) == ["BUY", "BUY", "SELL", "SELL"] and list(f["size"]) == [20, 20, 5, 5]
    assert (f["wallet"] == W).all() and set(f["conversion"]) == {"split", "merge"}
    # Cash is exact: a split costs N, a merge returns N.
    cash = (f["price"] * f["size"] * f["side"].map({"BUY": -1, "SELL": 1})).sum()
    assert cash == pytest.approx(-20 + 5)


def test_conversion_token_fallback_and_skip():
    trades = pd.DataFrame([dict(condition_id="C1", outcome_index=0, token_id="X0"), dict(condition_id="C1", outcome_index=1, token_id="X1")])
    f, _ = conversion_fills(ACT[:1], _markets(tokens=False), trades)
    assert set(f["token_id"]) == {"X0", "X1"}
    f, info = conversion_fills(ACT[:1], _markets(tokens=False))     # no token ids anywhere
    assert f.empty and info["skipped"] == 1


class FakeClient:
    """Stands in for PolymarketClient: one wallet that split, traded one side, and merged."""

    def trades(self, wallet, max_pages=4):
        return pd.DataFrame([dict(wallet=W, condition_id="C1", token_id="T0", outcome_index=0, side="SELL", price=0.9,
                                  size=10, ts=150, title="t", event_slug="ev")])

    def conversions(self, wallet, max_pages=4):
        return ACT

    def markets(self, ids):
        assert "C1" in set(ids)
        return _markets()


def test_real_dataset_includes_conversions_but_input_checks_ignore_them(tmp_path):
    fills, mk = real_dataset(FakeClient(), W)
    assert fills.attrs["conversions"]["splits"] == 1
    assert len(fills) == 5
    r = run_wallet(W, fills, mk, lambda t, ts: None, 10, th=load_thresholds(), audit=AuditLog(tmp_path / "a.jsonl"), write=False)
    checks = {c["check"]: c for c in r["integrity"]["checks"]}
    assert checks["both_sides"]["ok"]                     # a split is not "betting both sides"
    pos = r["positions"].set_index("token_id")
    # YES leg: bought 20 @ .5 (split), sold 10 @ .9, merged 5 @ .5, 5 left pay 1 -> 9 + 2.5 + 5 - 10
    assert pos.at["T0", "pnl"] == pytest.approx(6.5)


# ---------------- large planted batch ----------------
def test_large_planted_results_match_frozen_engine():
    p = EVAL_DIR / "results" / "planted_large.json"
    res = json.loads(p.read_text(encoding="utf-8"))
    assert res["freeze_hash"] == freeze_hash()
    assert res["n_wallets"] == 1003 and res["synthetic"]
    eng = res["judges"]["engine"]
    assert eng["recommends copying a no-skill wallet"]["k"] == 0
