# Skill vs luck: methods, what we tested, what we kept

**Bottom line:** we keep the strict luck score (best of N no-skill twins), add **testing by betting** as a second proof of skill and as the "what would change my mind" engine, add two more no-skill nulls, and give every wallet a bottom line. Two popular upgrades — a population FDR correction and Bayesian shrinkage — were tested and **rejected** because they fail under leaderboard selection.

## What the research says (Nov 2026)

| Method | Source | Status here |
|---|---|---|
| Best-of-N correction (deflated Sharpe, haircut Sharpe) | [Bailey & López de Prado](https://papers.ssrn.com/abstract=2460551); [Harvey & Liu](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF) | **Kept** — our Luck(N) = 1 − (1 − p)^N |
| Re-run each trader's bets with the direction randomised | [Gómez-Cram, Guo, Jensen & Kung 2026](https://doi.org/10.2139/ssrn.6617059) (only 12% of top Polymarket winners beat it; ~60% of lucky winners become losers out of sample) | **Added** as the coin-flip null |
| Prices are not calibrated: <10c buys lose 19.3c/$; ≥90c earn +0.8c/$ | [Favourite-longshot bias on Polymarket](https://arxiv.org/abs/2609.12878) | **Added** as the calibrated twin (learned only from earlier positions) |
| Testing by betting / e-values, anytime-valid | [Ramdas, Grünwald, Vovk & Shafer](https://arxiv.org/html/2210.01948v2); [Arnold, Künzli & Ziegel](https://arxiv.org/pdf/2109.11761) | **Added**; best performer in our tests |
| False discovery rate across funds | [Barras, Scaillet & Wermers 2010](https://econpapers.repec.org/RePEc:bla:jfinan:v:65:y:2010:i:1:p:179-216) | **Tested, rejected** (see below) |
| Bayesian shrinkage across funds | [Jones & Shanken](https://nber.org/papers/w9392); [Baks, Metrick & Wachter](https://finance.wharton.upenn.edu/~jwachter/research/BaksMetrickWachter2001jf.pdf) | **Tested, rejected as a decision input** |
| Winners mostly provide liquidity; persistence may be selection | [Akey et al., CEPR DP21615](https://ideas.repec.org/p/cpr/ceprdp/21615.html) | Motivates the copy-delay test; maker-share flag is future work |

## The engine now

1. **Three no-skill nulls, most sceptical wins.** Fair-odds twin (independent and shared-cluster), coin-flip direction twin, and — where a population is available — a calibrated twin using Polymarket's real win rate per price band.
2. **Luck(N)** from the most sceptical null (unchanged formula).
3. **Betting evidence.** A sceptic bets, using only past clusters, that each settled event cluster's return is positive. Wealth W is a supermartingale under no skill, so P(W ever ≥ x) ≤ 1/x (Ville). Proof against a field of N: W ≥ N/5%. It also gives "≈ K more settled clusters would prove it".
4. **Verdict:** skill needs the edge CI above 0, ≥ 10 clusters, and either Luck(N) < 5% **or** W ≥ N/5%.
5. **Bottom line, for every wallet:** Copy (paper first) / Watch / Don't copy / Hold – human review. **Watch = W ≥ N and a follower still made money after the delay.** Why N: in a field of N no-skill wallets, the expected number ever reaching W ≥ N is ≤ 1, so the bar is selection-safe. (A fixed 100× bar failed: the #1 of 1,000 coin-flippers reached 196×.)
6. **What would change my mind:** clusters still needed, CI conditions, field size at which a skilled record would look lucky, and the copy-delay condition — all computed numbers.
7. **Input checks:** malformed addresses, bad fills, wash-style round trips, buying both sides, payouts, and instructions hidden in market text (withheld from the LLM). Severe failures → Hold for a human.

## Head-to-head on planted traders (fresh holdout seed 303, SYNTHETIC)

| Method | Precision | Recall (skilled) | False alarms | Recall @5c | @10c |
|---|---|---|---|---|---|
| v1 verdict (fair-odds twin only) | 100% | 47% | 0% | 12% | 75% |
| **v2 verdict** (all nulls + betting evidence) | **100%** | **50%** | **0%** | 12% | **88%** |
| v2 bottom line Copy/Watch | 100% | 28%* | 0% | 25% | 88% |
| Betting evidence alone (≥ N/α) | 100% | 53% | 0% | 12% | 100% |
| FDR q < 0.10 (rejected) | 55% | 100% | **100%** | — | — |
| Naive: win rate > 70% | 0% | 0% | 65% | 0% | 0% |
| Naive: top 10 by ROI | 0% | 0% | 38% | 0% | 0% |

*Copy/Watch deliberately excludes skilled-but-uncopyable traders (all of them kept out). Thresholds were chosen on dev seed 101 only. Full tables with Wilson 95% CIs: `eval/results/compare.md`.

**Why FDR failed:** correcting only across the wallets you are shown cannot undo the selection from the wallets you were not shown (the lucky wallets are the top 10 of 1,000). **Why shrinkage failed:** it gave lucky, 95c-farmer and cluster-trap wallets 77–100% "probability of a positive follower edge" (Brier 0.43, worse than a coin flip), because shrinking toward the selected wallets keeps their inflated mean.

## Manipulated inputs

Six attacks (wash trading, prompt injection in market text, buying both sides, three hostile/malformed addresses): **6/6 caught**, none got "Copy". See `eval/results/manipulation.md`.

## Real wallets (walk-forward)

Cut-off 24 Oct 2026, 60 leaderboard wallets, 40 with ≥ 20 settled bets before the cut-off, 1 h copy delay plus costs.

| Copies after the cut-off | Wallets | Copies | Follower return per copy | Leaders' own return, same bets | Sharpe/copy | Max drawdown on £200 |
|---|---|---|---|---|---|---|
| A. Top 10 by profit at the cut-off | 10 | 168 | **−19.1%** (CI −35.9% to −2.0%) | −9.4% | −0.20 | 100% (wiped out) |
| B / C. Agent (v1 or v2, verdict or bottom line) | 0 | 0 | holds cash | — | — | 0% |

- v1 and v2 agreed on every wallet (39 Probably luck, 1 Can't tell yet); the v2 bottom line was "Don't copy" for all 40.
- Abstaining beat copying the top 10 by **+19.1% per copy (95% CI +2.3% to +35.3%)** — evidence that the leaderboard was not worth copying, **not** evidence that the agent picks winners (it picked none).
- The calibrated twin learned Polymarket's real favourite-longshot bias from 4,509 pre-cut-off positions: 95c+ contracts won 99.0%; 5–10c contracts won 8.2%.
- An earlier run with the same cut-off measured the top 10 at −4.1% (CI −19% to +11%): the post-cut-off window runs to the time of the run, so more markets had settled. Both runs are kept (`walkforward_v1.md`, `walkforward.md`).
- Biases: today's leaderboard defines the universe; followers hold to resolution; paged history is short for very active wallets.

## Engine v2 (8 Nov 2026): grouping by match, not by name

**What changed.** Only the grouping of related bets (`ctdd/agent/text_jobs.py`); thresholds, the luck score,
the verdict rules and the prompts are untouched. Freeze hash `92465b6b62360be3` (v1) → `1e14c2d1e9f39823` (v2).

- v1 linked any two markets whose titles shared a name and that resolved within 3 days, and the links chained.
  On a real e-sports wallet, League of Legends, Dota 2 and Counter-Strike matches became one 200-market "event",
  so the no-skill twins treated 200 bets as one draw. That overstates the luck score and widens the edge interval
  (it only ever pushes towards "luck", never towards "skilled").
- v2: head-to-head markets ("A vs B", "Will A beat B?") link only to markets on the same pair of sides settling
  within a day; a rematch days later is a new event. Team names no longer link other markets to each other; a
  team's side market ("Will A win by 2+?") joins the single closest match involving that team. One event slug
  that spans several matches is split by match. Gemini can still merge groups, but code refuses any merge that
  would join two different matches.

**Why it changed after the freeze, and how it was re-tested.** The flaw was found by inspecting a real wallet
on 8 Nov, not from test scores. Re-scoring the same test data after changing the engine would contaminate it,
so v2 was frozen first and then tested on a planted seed that had never been used (4242), once, with both
engines side by side.

| Grouping accuracy (agreement with the true events, Rand index) | v1 | v2 |
|---|---|---|
| Simulated e-sports month (150 matches, shared team names; `tests/esports_world.py`) | 0.672 (3 groups) | **0.998** |
| Joyce's 1,003 wallets (true event ids) | 0.987 | 0.987 |
| Planted cluster traps, dev seed 101 | 0.913 | 0.913 |

Verdicts on dev seed 101: 0 of 58 changed. Fresh-seed and Joyce-batch verdicts: see "How we tested it" in the
app and `eval/results/v2_engine/`. Engine v1 on the fresh seed: `eval/results/v1_engine_seed4242/`. The real
walk-forward (Test 3) was run with v1; re-running it with v2 needs internet access (README).

## Limits

- Synthetic prices are fair by construction, so the coin-flip and calibrated nulls only differ from v1 on real data.
- The betting evidence's guarantee assumes outcomes are no better than the null's odds; with real longshot bias the calibrated twin is the check.
- A 5c edge still needs ~2,000+ bets to prove against a 1,000-wallet field; the "clusters still needed" number says so plainly.
