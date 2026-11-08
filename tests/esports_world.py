"""A realistic e-sports month: 3 games, 16 teams, matches every day, team names repeat across matches."""
import sys, itertools, random
import pandas as pd
def world():
    rnd = random.Random(5)
    games = {"LoL": ["T1", "Gen.G", "Anyone's Legend", "Karmine Corp", "G2 Esports", "Fnatic"],
             "Dota 2": ["1win", "GamerLegion", "Team Spirit", "Tundra Esports", "BetBoom Team"],
             "Counter-Strike": ["MOUZ", "Liquid", "Vitality", "FaZe", "Natus Vincere"]}
    rows, truth, t0, k = [], {}, 1_790_000_000, 0
    for day in range(25):
        for game, teams in games.items():
            for a, b in rnd.sample(list(itertools.combinations(teams, 2)), 2):
                k += 1; ev = f"{game}-{a}-{b}-{day}"; ts = t0 + day * 86400 + rnd.randint(0, 40000)
                tour = {"LoL": "Worlds Group Stage", "Dota 2": "The International", "Counter-Strike": "PGL Masters Bucharest Group Stage"}[game]
                titles = [f"{game}: {a} vs {b} (BO3) - {tour}", f"{game}: {a} vs {b} - Game 1 Winner", f"{game}: {a} vs {b} - Game 2 Winner"]
                for j, title in enumerate(titles[: rnd.randint(1, 3)]):
                    cid = f"m{k}-{j}"; rows.append({"cid": cid, "title": title, "event_slug": "", "resolve_ts": ts + 3600 * j}); truth[cid] = ev
    return pd.DataFrame(rows).set_index("cid"), truth
if __name__ == "__main__":
    sys.path.insert(0, sys.argv[1])
    from ctdd.agent.text_jobs import heuristic_clusters, cluster_agreement
    M, truth = world(); cl = heuristic_clusters(M)
    sizes = pd.Series(cl).value_counts()
    print(f"{sys.argv[1]}: {len(M)} markets, {M.index.map(truth.get).nunique()} true matches -> {sizes.size} groups; biggest {sizes.iloc[0]}; agreement {cluster_agreement(cl, truth):.3f}")
