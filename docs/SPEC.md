# Copy-Trader Due Diligence — Build Spec v2

Agentverse 2026 · Finance track · revised 7 Nov 2026 (v1 by @Lawrence)

> **One-liner for judges:** "A backtest tells you what a trader made. We tell you whether it was skill, and whether *you* can still get it."

User: someone with about £200 who saw a "copy this wallet, up 400%" post on TikTok or X. They copy whoever tops the leaderboard by profit. Some of those traders are lucky survivors of a large search; others earn in ways a follower can't replicate. Polymarket is the demonstration venue because its trades are public; the question — *should you believe this track record?* — applies to any copy-trading platform. Paper trading only. Information, not financial advice.

---

## 0. What changed from v1 and why

| # | v1 | v2 | Why |
|---|---|---|---|
| 1 | Data API endpoints unspecified | **Pinned to Data API v2** (endpoints below, all checked live on 7 Nov) | The v1 Data API and `lb-api` now return HTTP 410. Any copied tutorial code fails. |
| 2 | Twin positions win independently | **Twins are simulated per draw group**: one random draw per market, per mutually-exclusive event (negRisk), or per LLM cluster. Report the *independent* and *shared-cluster* cases; the verdict uses the conservative one. | Ten bets on one election rise and fall together. Independent twins are too steady, so the best twin looks weaker and a lucky trader looks skilled — the exact error we exist to catch. |
| 3 | "Simulate N twins, take the best, repeat a few thousand times" | **Simulate one twin M times, estimate p = P(twin ≥ trader), then Luck(N) = 1 − (1 − p)^N** | Exact for independent twins, one simulation serves every N, and it runs in seconds instead of ~10¹⁰ draws. |
| 4 | Luck = share of runs | **p = (1 + hits)/(M + 1)**; zero hits → report the bound Luck ≤ N/(M+1) | Never claims a fake 0%. |
| 5 | Wording unspecified | **Fixed wording:** "the chance that N no-skill traders produce someone at least this good" — never "the probability this trader is lucky" | That is what the number means. The other phrasing is a stats error judges will catch. |
| 6 | "Too few clusters" undefined | **< 10 independent clusters → CI flagged unreliable, verdict capped at "Can't tell yet"** | A bootstrap over 4 clusters just reshuffles 4 events. |
| 7 | Verdict thresholds "tuned on the dev set" | **Thresholds live in `thresholds.json`, hashed and frozen before the test batch; the test run refuses to execute against a different hash and stamps any rerun "contaminated"** | Makes "frozen" verifiable rather than a promise. |
| 8 | Planted "pure luck" = win prob = price | **Pure luck = the top 10 of a simulated no-skill population of known size N** | A random no-skill wallet is trivially not skilled. The trap the TikTok user falls into is *selection*, so we plant selection. |
| 9 | Skilled planted traders, size unspecified | **Planted skilled traders hold 150–600 positions** | Best-of-1,000 coin-flippers sits ≈3.2σ out. A +10c edge over 80 bets is only ≈1.8σ, so short records are genuinely undetectable — that is a finding, not a bug, and the power curve shows it. |
| 10 | Copy-delay fill price | **Follower fill = market price at entry + delay, plus half-spread, plus the market's fee** | Matches what a real follower pays. |
| 11 | Only naive baselines | **Adds a third baseline: "LLM with no tools"** (optional, if an API key is available) | Shows the tools — not the LLM — carry the accuracy. |
| 12 | 3 roles | **5 roles with fixed hand-off times** (section 9) | Team of 4–5 with a 10-hour clock. |
| 13 | LLM required | **Every LLM job has a deterministic fallback**; the prototype runs fully offline | The demo can't depend on an API key or rate limit. The LLM upgrades clustering and prose; it never gates a number. |

**Learned while building the prototype (7 Nov):**

| # | Finding | Change |
|---|---|---|
| 14 | `/v2/trades?user=` is **incomplete**: one wallet returned 591 fills where `/v2/activity` listed 1,932 trades; rebuilt share counts were ~50% of Polymarket's | Fills come from **`/v2/activity` (type TRADE)**. Share counts now match (median ratio 1.00). |
| 15 | Gamma **silently omits resolved markets** unless `closed=true` | Query closed first, then open; batch 50 ids per call (feasibility run: >10 min → 23 s). |
| 16 | Our P&L differs from Polymarket's by the **trading fee** (exactly `entry_fees_usdc` on held positions; ~1–2.5% of notional baked into exits for some wallets) | Matched positions use Polymarket's `realized_pnl`, fee added to cost; the wallet's observed fee rate is charged to the follower. |
| 17 | Paged fills cover only days for active wallets, so early positions have **truncated cost** (one wallet showed +436% mean return; true −28.7%) | Where Polymarket has the closed position, its size and average price replace ours. The card states coverage. |
| 18 | With profit ranking and varied stake sizes, **a 10c edge needs ~1,000–2,000 bets (5c: ~2,000–3,000) to beat a 1,000-wallet field** | Planted skilled traders hold 800–2,500 positions. "How long a record do you need?" is a deck slide. |
| 19 | The normal tail alone **underestimates** p for long-shot books (0.087 vs 0.126 from a 2M-sample run) | Below 20 MC hits use max(normal tail, add-one MC); M scales as 40 × N. |
| 20 | "Top 10 by profit" looks fine on planted data because long skilled records dominate absolute profit | Added **"top 10 by ROI"** — what an "up 400%" post shows. It is fooled 38% of the time (7/8 cluster traps). |

---

## 1. Scope

**In:** report card for any wallet; live mode as a labelled replay with human approve/reject; code-enforced risk controls; append-only audit log; two-part evaluation (planted traders + real-wallet walk-forward).

**Out:** real money, wallet keys, order placement; linking wallets to people; insider-trading claims (unusual timing is flagged "needs human review", nothing more).

## 2. Data (critical path)

| Source | Endpoint (verified 7 Nov 2026) | Use |
|---|---|---|
| Leaderboard | `GET data-api.polymarket.com/v2/leaderboard?time_period=month&limit=…` (cursor paging) | Wallet universe, **N** for the luck score |
| Fills | `GET /v2/activity?user=<wallet>&limit=500` + `next_cursor`, keep `type == TRADE` (**not** `/v2/trades`, which is incomplete) | Position rebuild |
| Positions | `GET /v2/positions?user=<wallet>&status=CLOSED` (has `realized_pnl`, `total_size`, `avg_price`, `entry_fees_usdc`) | Reconcile P&L incl. fees; complete truncated positions |
| Markets | `GET gamma-api.polymarket.com/markets?condition_ids=a&condition_ids=b…&closed=true`, then again without `closed` | Title, rules text, outcomes, resolution, `negRisk` |
| Prices | `GET clob.polymarket.com/prices-history?market=<token>&startTs&endTs&fidelity=1` | Copy-delay re-pricing |
| Synthetic | `ctdd/data/synthetic.py` | Planted traders with known truth |

**First-hour check** — run on 7 Nov (`python -m eval.feasibility`): step 1 **pass** (fills incl. SELLs via `/v2/activity`); step 2 **pass after fixes 14–17** (share counts match; P&L correlation 0.996–1.000, residual = fees, now reconciled); step 3 **pass** (CLOB price history at arbitrary timestamps); step 4 **partial** — 1 of 3 top wallets had ≥ 20 resolved positions either side of a 14-day cut-off with 2 pages of fills. Pull more pages or pick an earlier cut-off for the walk-forward.

Rules: synthetic data labelled on every chart; wallets by address only; prefer fast-resolving markets for the walk-forward; licences cited in the README before the deck is written.

## 3. Stats engine (plain, unit-tested Python — the LLM computes nothing)

1. **Positions, not fills.** One position per (wallet, outcome token). P&L = sell proceeds + remaining shares × payout − cost. A position is *held to resolution* if < 5% of shares were sold before resolution.
2. **Edge.** Return per position = P&L / cost. Mean with 95% CI.
3. **Cluster bootstrap.** Resample whole clusters (LLM grouping; `event_slug` fallback). Report the cluster count. < 10 clusters → unreliable.
4. **Luck score.**
   1. Inputs: held-to-resolution positions **inside the selection window only** (later positions are the out-of-sample test).
   2. No-skill twin: same markets, costs and shares; win probability = entry price (or the calibrated win rate at that price, estimated only from markets resolved *before* the window, extreme buckets pooled).
   3. Draw groups: one uniform draw per binary market; per negRisk event, candidates get disjoint probability intervals (exactly one wins); in *shared* mode, one draw per LLM cluster (maximum correlation). Report both modes; the verdict uses the larger luck score.
   4. Simulate the twin M times (default 200,000), ranking metric = profit. p = (1 + hits)/(M + 1). Luck(N) = 1 − (1 − p)^N.
   5. N: 100, 1,000, 10,000 and **N_eff** = wallets with ≥ 20 positions in the window, **including abandoned and blown-up wallets** (survivorship sets N — dead wallets still searched for an edge, and they stay on-chain).
   6. Coverage: the report states what share of positions and of profit the score covers (early exits excluded; stretch: random-timing twin for exits).
5. **Concentration.** Profit and edge with the biggest cluster removed.
6. **Copy-delay decay.** Re-price each entry at +5 min, +1 h, +1 day; follower pays price + half-spread + fee. Edge vs delay with CIs.

**Sanity numbers (unit-tested):** one coin-flipper hits 38/50 ≈ 1 in 6,500; the best of 10,000 does so ≈ 78–80% of the time; a no-skill buyer at 95c goes 25–0 ≈ 28% of the time.

## 4. Verdicts (deterministic, thresholds frozen in `thresholds.json`)

| Order | Condition | Verdict |
|---|---|---|
| 1 | Luck(N_eff) ≥ 0.50 | **Probably luck** |
| 2 | < 10 clusters, or edge CI includes 0, or Luck(N_eff) ≥ 0.05 | **Can't tell yet** |
| 3 | Edge at the copy delay (default 1 h, after costs) has CI lower bound > 0 | **Skilled and copyable** |
| 4 | Otherwise | **Skilled but not copyable** |

The card shows the verdict with the one or two numbers that decided it, edge ± CI with cluster count, Luck(N) table in both correlation modes, the delay curve, concentration, category breakdown, "what £200 would have become" (labelled *historical simulation*), human-review flags, input checks, and the banner **"Paper trading only. Information, not financial advice."**

## 5. LLM layer (reads and judges text; never a number)

| Job | Fallback without an API key |
|---|---|
| Correlated-bet clustering (lead feature) | `event_slug` + shared named entities within a 3-day window (union-find) |
| Near-certainty detection | price ≥ 0.95 + rules-text keywords |
| Categorisation | keyword rules |
| Report writing | template; LLM prose must pass the **number guard** (every number in the text must match an engine output, else the template is used and the rejection is logged) |
| Live copy decision | deterministic scoring and reasons text; no LLM (the LLM summary was removed as low-value) |

Market titles and rules are untrusted text: LLM output is JSON, schema-validated, and logged with the prompt version. Prompts are frozen with the thresholds.

## 6. Risk controls (code between agent and ledger)

Paper only by construction · human approval for every copy · per-trade cap 5% of bankroll · verdict gate (no copying "Can't tell yet"/"Probably luck" without a logged override reason) · one-cluster exposure cap 15% · drawdown stop 20% (auto-pause, human re-enables) · stale price (skip if price moved > 3c since the leader's entry). Audit log: append-only JSONL with timestamps for every data pull, LLM call, verdict, proposal, approval, block and override.

## 7. Evaluation

**A. Planted traders (main slide).** Types: skilled (edge 2c / 5c / 10c, slow price drift → copyable), skilled-but-fast (price reaches fair value within minutes), pure luck (top 10 of a no-skill population of size N), 95c farmer, clustered bettor (many markets on 1–3 stories, one lucky outcome). Dev batch → freeze (`eval/freeze.json` hash) → fresh-seed test batch, run once. Metrics with Wilson 95% CIs: false-alarm rate, detection by edge size, not-copyable catch rate, cluster-trap catch rate. Baselines: top-10-by-profit, win rate > 70%, (optional) LLM with no tools.

**B. Real-wallet walk-forward.** Cut-off date; verdicts from data before it; after it, paper-copy "top 10" vs "agent-approved" with delay and costs; report the return difference with a CI and the sample size. Small sample → say so.

## 8. Demo (4 min)

Hook: a 25–0 wallet → reveal: all at 95c, no skill does that 28% of the time → **Probably luck**. Contrast: a messy trader whose edge survives delay → **Skilled and copyable**. Labelled replay: agent proposes a paper copy, human approves. Live control: an oversized copy of an unclear trader is blocked and the log line appears. Results: planted table + walk-forward, CIs stated honestly.

## 9. Team of 5, 10 hours

| Person | Owns | Hand-off |
|---|---|---|
| P1 Data | `ctdd/data/polymarket.py`, `eval/feasibility.py`, `eval/walkforward.py` | Real positions for 3–5 wallets by **3:00** |
| P2 Stats | `ctdd/engine/*` | `analyze_wallet()` stable by **3:00** |
| P3 Eval | `ctdd/data/synthetic.py`, `eval/run_planted.py` | Frozen test results by **5:30** |
| P4 Agent | `ctdd/agent/*`, `ctdd/controls.py`, `ctdd/audit.py` | Live replay + controls by **6:30** |
| P5 Story | `app/`, deck, README, demo script, Q&A | Final deck by **9:00** |

Checkpoints: 3:00 merge (pipeline runs on one wallet) · 5:30 cut point (never cut evaluation) · 9:00 rehearsal. Cut order: live mode → calibrated twin → whole-field luck simulation.

## 10. Open questions

Does the Agentverse kit's hidden test mode apply to market agents? · Cut-off date with enough resolved positions after it · Current fee schedule per market type · Polymarket's UK geoblocking status (one-line answer for judges) · Gemini vs Claude for the LLM layer.
