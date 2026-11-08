# Walk-forward on real wallets (Evaluation B)

Cut-off 2026-10-24 17:38:17 UTC · universe 60 leaderboard wallets · 40 judged with ≥ 20 resolved positions before the cut-off · copy delay 1 h, half-spread 0.5%, fee 0.00%.

Verdicts as of the cut-off — v1: {'Probably luck': 39, "Can't tell yet": 1}; v2: {'Probably luck': 39, "Can't tell yet": 1}. Bottom lines (v2): {"Don't copy": 40}. Excluded: {'< 20 resolved positions before cut-off': 17, 'no fills before cut-off': 3}.

| Portfolio (copies after the cut-off) | Wallets | Copies | Follower return per copy (after delay + costs) | Leader's own return, same bets | Sharpe per copy | Max drawdown (£200) | P&L at £10/copy |
|---|---|---|---|---|---|---|---|
| A. Top 10 by profit at the cut-off | 10 | 168 (112 clusters) | -19.1% (CI -35.9% to -2.0%) | -9.4% | -0.20 | 100% (wiped out) | £-322 |
| B1. v1 agent-approved | 0 | 0 | — (holds cash) | — | — | — | £0 |
| B. v2 agent-approved ('Skilled and copyable') | 0 | 0 | — (holds cash) | — | — | — | £0 |
| C. v2 bottom line Copy or Watch | 0 | 0 | — (holds cash) | — | — | — | £0 |

**B held cash (no wallet selected). B − A = +19.1% per copy (95% CI +2.3% to +35.3%) is the loss avoided by abstaining — not evidence of picking winners.**
**C held cash (no wallet selected). C − A = +19.1% per copy (95% CI +2.3% to +35.3%) is the loss avoided by abstaining — not evidence of picking winners.**

Calibrated no-skill twin learned from pre-cut-off positions — win rate by entry-price band: 0.00–: 0.012 (n=184), 0.05–: 0.082 (n=82), 0.10–: 0.120 (n=182), 0.20–: 0.215 (n=247), 0.30–: 0.328 (n=396), 0.40–: 0.417 (n=825), 0.50–: 0.544 (n=1096), 0.60–: 0.669 (n=389), 0.70–: 0.796 (n=263), 0.80–: 0.899 (n=233), 0.90–: 0.935 (n=128), 0.95–: 0.990 (n=484).

Empirical-Bayes prior for follower edge: mean -0.200, spread 0.266 (fitted on 39 real wallets as of 2026-10-24).

CIs resample (wallet, event) clusters. Sharpe = mean / SD of per-copy returns. Universe = today's monthly leaderboard, so membership uses information after the cut-off (affects both portfolios). Followers hold to resolution; leaders' early exits are not mirrored. Fill history is paged (most recent first); very active wallets may have few positions before the cut-off.