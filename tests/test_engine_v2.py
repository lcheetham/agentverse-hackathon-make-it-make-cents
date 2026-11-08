"""Engine v2 grouping: a team is not an event, a match is."""


import pandas as pd

from ctdd.agent.text_jobs import cluster_agreement, heuristic_clusters, matchup




def test_matchup_parser():
    assert matchup("LoL: Anyone's Legend vs Karmine Corp (BO1) - Worlds Group Stage") == frozenset({"anyone's legend", "karmine corp"})
    assert matchup("Dota 2: 1win vs GamerLegion - Game 2 Winner") == matchup("Dota 2: 1win vs GamerLegion - Game 1 Winner")
    assert matchup("Will Orkalenkasel FC beat Zencyanrosel United on Jul 20?") == frozenset({"orkalenkasel", "zencyanrosel"})
    assert matchup("Lakers vs. Celtics: O/U 220.5") == frozenset({"lakers", "celtics"})
    for t in ["Will Sorensen win the Westwick mayoral election?", "Will Southmere Albion avoid defeat against Kingsford United?",
              "Pabelanlunsel governor: will Vikrenorfarsel carry the capital district?", "Will BTC be above $92,700 on 2 Sep?"]:
        assert matchup(t) is None


def _m(rows):
    return pd.DataFrame(rows, columns=["cid", "title", "event_slug", "resolve_ts"]).set_index("cid")


def test_shared_team_names_no_longer_chain_matches():
    day = 86_400
    M = _m([("a1", "LoL: T1 vs Gen.G - Game 1 Winner", "", 0), ("a2", "LoL: T1 vs Gen.G - Game 2 Winner", "", 3600),
            ("b1", "LoL: Gen.G vs DRX (BO3) - Worlds", "", day), ("c1", "LoL: DRX vs Fnatic (BO3) - Worlds", "", 2 * day),
            ("d1", "LoL: T1 vs Gen.G (BO3) - Worlds", "", 6 * day)])            # a rematch days later is a new event
    cl = heuristic_clusters(M)
    assert cl["a1"] == cl["a2"] and len({cl["a1"], cl["b1"], cl["c1"], cl["d1"]}) == 4


def test_side_markets_join_one_match_and_elections_still_group():
    M = _m([("m", "Will Kingsford United beat Southmere Albion?", "", 100), ("s1", "Will Kingsford United win by 2+ goals?", "", 100),
            ("s2", "Will Southmere Albion keep a clean sheet?", "", 100), ("x", "Will Kingsford United beat Eastgate Rovers?", "", 100 + 9 * 86_400),
            ("e1", "Will Sorensen win the Westwick mayoral election?", "", 500), ("e2", "Will Sorensen concede the Westwick race by Friday?", "", 600)])
    cl = heuristic_clusters(M)
    assert cl["m"] == cl["s1"] == cl["s2"] != cl["x"] and cl["e1"] == cl["e2"]


def test_one_slug_spanning_several_matches_is_split_by_match():
    M = _m([("a", "MOUZ vs Liquid - Map 1", "pgl-bucharest", 0), ("b", "MOUZ vs Liquid - Map 2", "pgl-bucharest", 3600),
            ("c", "FaZe vs Vitality - Map 1", "pgl-bucharest", 7200)])
    cl = heuristic_clusters(M)
    assert cl["a"] == cl["b"] != cl["c"]


def test_esports_month_regression():
    from tests.esports_world import world
    M, truth = world()
    cl = heuristic_clusters(M)
    assert cluster_agreement(cl, truth) > 0.99 and pd.Series(cl).value_counts().iloc[0] <= 10
