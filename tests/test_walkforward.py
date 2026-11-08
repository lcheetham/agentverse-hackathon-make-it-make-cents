import numpy as np
import pandas as pd

from eval.walkforward import bootstrap_diff, markets_as_of


def test_markets_as_of_hides_later_resolutions():
    mk = pd.DataFrame({
        "resolved": [True, True, False],
        "resolve_ts": [100.0, 300.0, np.nan],
        "payouts": [[1.0, 0.0], [0.0, 1.0], None],
    }, index=["early", "late", "open"])
    m = markets_as_of(mk, cutoff=200)
    assert bool(m.loc["early", "resolved"]) and m.loc["early", "payouts"] == [1.0, 0.0]
    assert not bool(m.loc["late", "resolved"]) and m.loc["late", "payouts"] is None
    assert not bool(m.loc["open", "resolved"])
    assert bool(mk.loc["late", "resolved"])  # original untouched


def test_bootstrap_diff_with_empty_portfolio_is_minus_a():
    a = [-1.0, 0.5, -1.0, 0.2]
    mean, lo, hi = bootstrap_diff(a, ["x", "y", "z", "w"], [], [])
    assert abs(mean - (-np.mean(a))) < 0.1 and lo <= mean <= hi
