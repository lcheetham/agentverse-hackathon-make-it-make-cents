# Old vs upgraded skill-vs-luck methods (planted traders, SYNTHETIC)

## Seed 101 (dev)

| Method | Calls | Precision | Recall (skilled) | False alarms (no-skill) | Recall @2c | @5c | @10c |
|---|---|---|---|---|---|---|---|
| v1_verdict (skilled) | 15 | 100% [80%–100%] | 47% [31%–64%] | 0% [0%–13%] | 0% [0%–32%] | 12% [2%–47%] | 88% [53%–98%] |
| v2_verdict (skilled) | 18 | 100% [82%–100%] | 56% [39%–72%] | 0% [0%–13%] | 0% [0%–32%] | 25% [7%–59%] | 100% [68%–100%] |
| v2_bottom_line (Copy or Watch) | 11 | 100% [74%–100%] | 34% [20%–52%] | 0% [0%–13%] | 0% [0%–32%] | 38% [14%–69%] | 100% [68%–100%] |
| betting evidence >= N/alpha | 18 | 100% [82%–100%] | 56% [39%–72%] | 0% [0%–13%] | 0% [0%–32%] | 25% [7%–59%] | 100% [68%–100%] |
| FDR q < 0.10 | 58 | 55% [42%–67%] | 100% [89%–100%] | 100% [87%–100%] | 100% [68%–100%] | 100% [68%–100%] | 100% [68%–100%] |
| naive: win rate > 70% | 16 | 0% [0%–19%] | 0% [0%–11%] | 62% [43%–78%] | 0% [0%–32%] | 0% [0%–32%] | 0% [0%–32%] |
| naive: top 10 by ROI | 10 | 0% [0%–28%] | 0% [0%–11%] | 38% [22%–57%] | 0% [0%–32%] | 0% [0%–32%] | 0% [0%–32%] |

- v1 left **17%** of wallets at 'Can't tell yet' with no action; v2 gives every wallet a bottom line ({"Don't copy": 47, 'Copy (paper first)': 10, 'Watch': 1}).
- Rejected diagnostic: Brier score of the shrinkage P(edge > 0) = 0.438 (0.25 = coin flip) — overconfident on selected wallets, so not used.
- Fast movers kept out of Copy/Watch by the bottom line: 100% [68%–100%].

## Seed 4242 (holdout)

| Method | Calls | Precision | Recall (skilled) | False alarms (no-skill) | Recall @2c | @5c | @10c |
|---|---|---|---|---|---|---|---|
| v1_verdict (skilled) | 15 | 93% [70%–99%] | 44% [28%–61%] | 4% [1%–19%] | 0% [0%–32%] | 12% [2%–47%] | 75% [41%–93%] |
| v2_verdict (skilled) | 17 | 94% [73%–99%] | 50% [34%–66%] | 4% [1%–19%] | 0% [0%–32%] | 25% [7%–59%] | 75% [41%–93%] |
| v2_bottom_line (Copy or Watch) | 9 | 89% [56%–98%] | 25% [13%–42%] | 4% [1%–19%] | 0% [0%–32%] | 25% [7%–59%] | 75% [41%–93%] |
| betting evidence >= N/alpha | 18 | 100% [82%–100%] | 56% [39%–72%] | 0% [0%–13%] | 0% [0%–32%] | 25% [7%–59%] | 100% [68%–100%] |
| FDR q < 0.10 | 58 | 55% [42%–67%] | 100% [89%–100%] | 100% [87%–100%] | 100% [68%–100%] | 100% [68%–100%] | 100% [68%–100%] |
| naive: win rate > 70% | 16 | 0% [0%–19%] | 0% [0%–11%] | 62% [43%–78%] | 0% [0%–32%] | 0% [0%–32%] | 0% [0%–32%] |
| naive: top 10 by ROI | 10 | 0% [0%–28%] | 0% [0%–11%] | 38% [22%–57%] | 0% [0%–32%] | 0% [0%–32%] | 0% [0%–32%] |

- v1 left **10%** of wallets at 'Can't tell yet' with no action; v2 gives every wallet a bottom line ({"Don't copy": 49, 'Copy (paper first)': 9}).
- Rejected diagnostic: Brier score of the shrinkage P(edge > 0) = 0.405 (0.25 = coin flip) — overconfident on selected wallets, so not used.
- Fast movers kept out of Copy/Watch by the bottom line: 100% [68%–100%].

## All holdout seeds

| Method | Calls | Precision | Recall (skilled) | False alarms (no-skill) | Recall @2c | @5c | @10c |
|---|---|---|---|---|---|---|---|
| v1_verdict (skilled) | 15 | 93% [70%–99%] | 44% [28%–61%] | 4% [1%–19%] | 0% [0%–32%] | 12% [2%–47%] | 75% [41%–93%] |
| v2_verdict (skilled) | 17 | 94% [73%–99%] | 50% [34%–66%] | 4% [1%–19%] | 0% [0%–32%] | 25% [7%–59%] | 75% [41%–93%] |
| v2_bottom_line (Copy or Watch) | 9 | 89% [56%–98%] | 25% [13%–42%] | 4% [1%–19%] | 0% [0%–32%] | 25% [7%–59%] | 75% [41%–93%] |
| betting evidence >= N/alpha | 18 | 100% [82%–100%] | 56% [39%–72%] | 0% [0%–13%] | 0% [0%–32%] | 25% [7%–59%] | 100% [68%–100%] |
| FDR q < 0.10 | 58 | 55% [42%–67%] | 100% [89%–100%] | 100% [87%–100%] | 100% [68%–100%] | 100% [68%–100%] | 100% [68%–100%] |
| naive: win rate > 70% | 16 | 0% [0%–19%] | 0% [0%–11%] | 62% [43%–78%] | 0% [0%–32%] | 0% [0%–32%] | 0% [0%–32%] |
| naive: top 10 by ROI | 10 | 0% [0%–28%] | 0% [0%–11%] | 38% [22%–57%] | 0% [0%–32%] | 0% [0%–32%] | 0% [0%–32%] |

- v1 left **10%** of wallets at 'Can't tell yet' with no action; v2 gives every wallet a bottom line ({"Don't copy": 49, 'Copy (paper first)': 9}).
- Rejected diagnostic: Brier score of the shrinkage P(edge > 0) = 0.405 (0.25 = coin flip) — overconfident on selected wallets, so not used.
- Fast movers kept out of Copy/Watch by the bottom line: 100% [68%–100%].

Watch = betting evidence ≥ N (the field size) and follower still profitable after the delay; chosen on the dev seed only. Priors are fitted per batch by empirical Bayes. Wilson 95% intervals in brackets.