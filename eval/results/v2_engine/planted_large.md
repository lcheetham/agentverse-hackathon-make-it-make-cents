# Planted-trader evaluation, large independent batch (SYNTHETIC)

1,003 wallets from a different generator (`data/planted_large`), never used for tuning. Engine freeze hash `1e14c2d1e9f39823` (unchanged). Types: luck 700, farmer 101, skilled 81, clustered 81, slow 40.

| Judge | Recommends copying a no-skill wallet | Of its 'copy' calls, truly skilled & copyable | 'Copy' calls |
|---|---|---|---|
| This engine (frozen) | 0.0% [0.0%, 0.4%] (0/882) | 84.6% [57.8%, 95.7%] (11/13) | 13 |
| Prototype engine (Streamlit build) | 0.0% [0.0%, 0.4%] (0/882) | 93.3% [78.7%, 98.2%] (28/30) | 30 |
| Naive: top 10 by profit | 0.0% [0.0%, 0.4%] (0/882) | 10.0% [1.8%, 40.4%] (1/10) | 10 |
| Naive: top 10 by ROI ('up 400%') | 0.2% [0.1%, 0.8%] (2/882) | 0.0% [0.0%, 27.8%] (0/10) | 10 |
| Naive: win rate > 70% | 32.5% [29.5%, 35.7%] (287/882) | 8.9% [6.4%, 12.3%] (32/359) | 359 |

## This engine (frozen)

| Metric | Result |
|---|---|
| false_alarm (no-skill called skilled) | 0.0% [0.0%, 0.4%] (0/882) |
| recommends copying a no-skill wallet | 0.0% [0.0%, 0.4%] (0/882) |
| precision (of copy calls, truly skilled & copyable) | 84.6% [57.8%, 95.7%] (11/13) |
| overall correct | 90.5% [88.6%, 92.2%] (908/1003) |
| not-copyable caught (slow -> 'Skilled but not copyable') | 37.5% [24.2%, 53.0%] (15/40) |
| 95c farmers -> 'Probably luck' | 100.0% [96.3%, 100.0%] (101/101) |
| cluster traps not called skilled | 100.0% [95.5%, 100.0%] (81/81) |

| True edge | Called 'Skilled and copyable' |
|---|---|
| 0.02-0.06 | 0.0% [0.0%, 16.8%] (0/19) |
| 0.06-0.10 | 5.9% [1.0%, 27.0%] (1/17) |
| 0.10-0.14 | 12.5% [3.5%, 36.0%] (2/16) |
| 0.14-0.20 | 27.6% [14.7%, 45.7%] (8/29) |

## Prototype engine (Streamlit build)

| Metric | Result |
|---|---|
| false_alarm (no-skill called skilled) | 0.0% [0.0%, 0.4%] (0/882) |
| recommends copying a no-skill wallet | 0.0% [0.0%, 0.4%] (0/882) |
| precision (of copy calls, truly skilled & copyable) | 93.3% [78.7%, 98.2%] (28/30) |
| overall correct | 94.2% [92.6%, 95.5%] (945/1003) |
| not-copyable caught (slow -> 'Skilled but not copyable') | 87.5% [73.9%, 94.5%] (35/40) |
| 95c farmers -> 'Probably luck' | 100.0% [96.3%, 100.0%] (101/101) |
| cluster traps not called skilled | 100.0% [95.5%, 100.0%] (81/81) |

| True edge | Called 'Skilled and copyable' |
|---|---|
| 0.02-0.06 | 0.0% [0.0%, 16.8%] (0/19) |
| 0.06-0.10 | 11.8% [3.3%, 34.3%] (2/17) |
| 0.10-0.14 | 31.2% [14.2%, 55.6%] (5/16) |
| 0.14-0.20 | 72.4% [54.3%, 85.3%] (21/29) |

Wilson 95% intervals. Costs use this engine's frozen settings (half-spread 0.5c, no fee), not the per-market costs in the CSV. Related bets are grouped by the engine's own heuristic only: the batch's event ids are hidden truth and are not shown to the engine. Synthetic traders are simpler than real ones.
