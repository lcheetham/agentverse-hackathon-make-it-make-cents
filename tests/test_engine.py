import numpy as np
import pandas as pd
import pytest
from scipy.stats import binom

from ctdd.engine.luck import build_twin_spec, luck_score, simulate_twin_profits
from ctdd.engine.positions import build_positions
from ctdd.engine.stats import cluster_bootstrap_mean, wilson
from ctdd.engine.verdict import decide
from ctdd.config import load_thresholds


def make_held(prices, wins, outcome_index=0, events=None, neg_risk=False, shares=1.0):
    n = len(prices)
    cond = [f"c{i}" for i in range(n)]
    pos = pd.DataFrame({
        "condition_id": cond,
        "outcome_index": [outcome_index] * n,
        "avg_entry": prices,
        "shares": [shares] * n,
        "cost": np.asarray(prices) * shares,
        "event_slug": events or cond,
        "status": "held",
        "pnl": (np.asarray(wins, float) - np.asarray(prices)) * shares,
    })
    markets = pd.DataFrame({"neg_risk": [neg_risk] * n}, index=cond)
    return pos, markets


def test_38_of_50_coin_flips_matches_spec_sanity_numbers():
    pos, mk = make_held([0.5] * 50, [1] * 38 + [0] * 12)
    res = luck_score(pos, mk, [1, 10_000], M=2_000_000, seed=1)["modes"]["independent"]
    exact = binom.sf(37, 50, 0.5)  # ~1 in 6,500
    assert 1 / 8000 < exact < 1 / 5500
    assert res["p_single"] == pytest.approx(exact, rel=0.25)
    assert res["luck"][10_000] == pytest.approx(1 - (1 - exact) ** 10_000, abs=0.05)
    assert 0.70 < res["luck"][10_000] < 0.86


def test_25_0_at_95c_happens_28_percent_of_the_time():
    pos, mk = make_held([0.95] * 25, [1] * 25)
    res = luck_score(pos, mk, [1], M=400_000, seed=2)["modes"]["independent"]
    assert res["p_single"] == pytest.approx(0.95 ** 25, abs=0.01)


def test_no_position_wins_with_its_own_price():
    pos, mk = make_held([0.3, 0.7], [1, 0], outcome_index=1)  # NO tokens
    spec = build_twin_spec(pos, mk)
    U = np.random.default_rng(0).random((200_000, spec.n_groups))[:, spec.group]
    win = ((U >= spec.lo) & (U < spec.hi)) == spec.win_inside
    assert win.mean(axis=0) == pytest.approx([0.3, 0.7], abs=0.01)


def test_neg_risk_event_has_exactly_one_winner():
    pos, mk = make_held([0.5, 0.3, 0.2], [1, 0, 0], events=["elec"] * 3, neg_risk=True)
    prof = simulate_twin_profits(build_twin_spec(pos, mk), M=20_000)
    assert np.allclose(prof, 0.0)  # bought every candidate for $1 total, exactly one pays $1


def test_shared_mode_is_more_sceptical_for_correlated_bets():
    # 12 markets on one story, all won: independent twins say "impossible", shared twins say "one coin flip".
    pos, mk = make_held([0.5] * 12, [1] * 12)
    clusters = {c: "story" for c in pos["condition_id"]}
    res = luck_score(pos, mk, [1000], clusters=clusters, M=100_000)
    assert res["modes"]["shared"]["luck"][1000] > 0.99
    assert res["modes"]["independent"]["p_single"] < 0.001
    assert res["modes"]["shared"]["p_single"] == pytest.approx(0.5, abs=0.01)


def test_luck_never_reports_zero():
    pos, mk = make_held([0.2] * 40, [1] * 40)
    res = luck_score(pos, mk, [100], M=10_000)["modes"]["independent"]
    assert res["zero_hits"] and res["p_single"] >= 1 / 10_001


def test_sparse_tail_estimate_is_never_less_sceptical_than_mc_floor():
    # 400 coin flips at 50c with 232 wins (z = 3.2): exact p ~ 8e-4; with 20k sims hits are few.
    pos, mk = make_held([0.5] * 400, [1] * 232 + [0] * 168)
    res = luck_score(pos, mk, [1000], M=20_000, seed=3)["modes"]["independent"]
    exact = binom.sf(231, 400, 0.5)
    assert res["p_single"] >= res["p_mc"] - 1e-12 or res["p_method"] == "monte_carlo"
    assert res["p_single"] == pytest.approx(exact, rel=0.6)


def test_cluster_bootstrap_widens_with_correlation():
    rng = np.random.default_rng(0)
    v = rng.normal(0.05, 0.5, 400)
    narrow = cluster_bootstrap_mean(v, np.arange(400))
    wide = cluster_bootstrap_mean(np.repeat(v[:40], 10), np.repeat(np.arange(40), 10))
    assert (wide["hi"] - wide["lo"]) > 2 * (narrow["hi"] - narrow["lo"])
    assert wide["n_clusters"] == 40


def test_wilson():
    p, lo, hi = wilson(8, 10)
    assert p == 0.8 and 0.49 < lo < 0.45 + 0.1 and 0.94 < hi < 0.97


def test_positions_rebuild_held_and_exited():
    fills = pd.DataFrame([
        # held: buy 10 @ .40 + 10 @ .60 -> avg .50, resolves YES
        dict(wallet="w", condition_id="a", token_id="ta", outcome_index=0, side="BUY", price=0.4, size=10, ts=1, title="A", event_slug="ea"),
        dict(wallet="w", condition_id="a", token_id="ta", outcome_index=0, side="BUY", price=0.6, size=10, ts=2, title="A", event_slug="ea"),
        # exited: buy 10 @ .30, sell 10 @ .50 before resolution
        dict(wallet="w", condition_id="b", token_id="tb", outcome_index=1, side="BUY", price=0.3, size=10, ts=3, title="B", event_slug="eb"),
        dict(wallet="w", condition_id="b", token_id="tb", outcome_index=1, side="SELL", price=0.5, size=10, ts=4, title="B", event_slug="eb"),
    ])
    markets = pd.DataFrame({
        "title": ["A", "B"], "rules": ["", ""], "event_slug": ["ea", "eb"], "neg_risk": [False, False],
        "resolved": [True, False], "resolve_ts": [100.0, np.nan], "payouts": [[1.0, 0.0], None],
    }, index=["a", "b"])
    p = build_positions(fills, markets).set_index("token_id")
    assert p.loc["ta", "status"] == "held" and p.loc["ta", "avg_entry"] == pytest.approx(0.5)
    assert p.loc["ta", "pnl"] == pytest.approx(10.0)
    assert p.loc["tb", "status"] == "exited" and p.loc["tb", "pnl"] == pytest.approx(2.0)


def test_verdict_order():
    th = load_thresholds()
    good_edge = {"mean": 0.1, "lo": 0.05, "hi": 0.15}
    assert decide(good_edge, 50, 0.9, None, th)[0] == "Probably luck"
    assert decide(good_edge, 5, 0.01, None, th)[0] == "Can't tell yet"
    assert decide({"lo": -0.01}, 50, 0.01, None, th)[0] == "Can't tell yet"
    assert decide(good_edge, 50, 0.01, {"lo": 0.02}, th)[0] == "Skilled and copyable"
    assert decide(good_edge, 50, 0.01, {"lo": -0.02}, th)[0] == "Skilled but not copyable"
