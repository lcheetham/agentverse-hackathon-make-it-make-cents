# Planted-trader evaluation — dev batch (SYNTHETIC)

Seed 101 · 58 wallets · freeze hash `613b1528bd5d3ae5`

| Metric | Agent | Naive: top 10 by ROI ('up 400%') | Naive: top 10 by profit | Naive: win rate > 70% |
|---|---|---|---|---|
| false_alarm_rate (no-skill called skilled) | 0% (0/26, CI 0%–13%) | 38% (10/26, CI 22%–57%) | 0% (0/26, CI 0%–13%) | 62% (16/26, CI 43%–78%) |
| cluster_trap_caught (not called skilled) | 100% (8/8, CI 68%–100%) | 12% (1/8, CI 2%–47%) | 100% (8/8, CI 68%–100%) | 0% (0/8, CI 0%–32%) |
| lucky_caught (not called skilled) | 100% (10/10, CI 72%–100%) | 70% (7/10, CI 40%–89%) | 100% (10/10, CI 72%–100%) | 100% (10/10, CI 72%–100%) |
| farmer_caught (not called skilled) | 100% (8/8, CI 68%–100%) | 100% (8/8, CI 68%–100%) | 100% (8/8, CI 68%–100%) | 0% (0/8, CI 0%–32%) |
| detection_rate edge=0.02 | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) |
| detection_rate edge=0.05 | 12% (1/8, CI 2%–47%) | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) |
| detection_rate edge=0.10 | 88% (7/8, CI 53%–98%) | 0% (0/8, CI 0%–32%) | 62% (5/8, CI 31%–86%) | 0% (0/8, CI 0%–32%) |
| not_copyable_caught (fast -> 'Skilled but not copyable') | 88% (7/8, CI 53%–98%) | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) | 0% (0/8, CI 0%–32%) |
| copyable_correct (slow & detected -> 'copyable') | 100% (8/8, CI 68%–100%) | — | 100% (5/5, CI 57%–100%) | — |

Cluster agreement with true stories (Rand index, clustered wallets): 0.91

Wilson 95% intervals. Synthetic traders are simpler than real ones; accuracy may not transfer exactly.