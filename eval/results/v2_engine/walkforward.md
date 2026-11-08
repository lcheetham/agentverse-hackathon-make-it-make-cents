# Walk-forward on real wallets (Evaluation B)

Cut-off 2026-10-24 17:38:17 UTC · universe 60 leaderboard wallets · 39 judged with ≥ 20 resolved positions before the cut-off · copy delay 1 h, half-spread 0.5%, fee 0.00%.

Verdicts as of the cut-off — v1: {'Probably luck': 38, "Can't tell yet": 1}; v2: {'Probably luck': 38, "Can't tell yet": 1}. Bottom lines (v2): {"Don't copy": 39}. Excluded: {'< 20 resolved positions before cut-off': 17, 'no fills before cut-off': 4}.

| Portfolio (copies after the cut-off) | Wallets | Copies | Follower return per copy (after delay + costs) | Leader's own return, same bets | Sharpe per copy | Max drawdown (£200) | P&L at £10/copy |
|---|---|---|---|---|---|---|---|
| A. Top 10 by profit at the cut-off | 10 | 225 (146 clusters) | -18.7% (CI -34.1% to -2.6%) | -10.6% | -0.20 | 100% (wiped out) | £-421 |
| B1. v1 agent-approved | 0 | 0 | — (holds cash) | — | — | — | £0 |
| B. v2 agent-approved ('Skilled and copyable') | 0 | 0 | — (holds cash) | — | — | — | £0 |
| C. v2 bottom line Copy or Watch | 0 | 0 | — (holds cash) | — | — | — | £0 |

**B held cash (no wallet selected). B − A = +18.7% per copy (95% CI +2.4% to +33.8%) is the loss avoided by abstaining — not evidence of picking winners.**
**C held cash (no wallet selected). C − A = +18.7% per copy (95% CI +2.4% to +33.8%) is the loss avoided by abstaining — not evidence of picking winners.**

Calibrated no-skill twin learned from pre-cut-off positions — win rate by entry-price band: 0.00–: 0.012 (n=182), 0.05–: 0.075 (n=80), 0.10–: 0.112 (n=180), 0.20–: 0.203 (n=253), 0.30–: 0.329 (n=394), 0.40–: 0.416 (n=832), 0.50–: 0.544 (n=1096), 0.60–: 0.672 (n=383), 0.70–: 0.810 (n=263), 0.80–: 0.900 (n=226), 0.90–: 0.937 (n=117), 0.95–: 0.987 (n=387).

Empirical-Bayes prior for follower edge: mean -0.209, spread 0.274 (fitted on 38 real wallets as of 2026-10-24).

CIs resample (wallet, event) clusters. Sharpe = mean / SD of per-copy returns. Universe = today's monthly leaderboard, so membership uses information after the cut-off (affects both portfolios). Followers hold to resolution; leaders' early exits are not mirrored. Fill history is paged (most recent first); very active wallets may have few positions before the cut-off.