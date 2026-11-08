# Copy-Trader Due Diligence

**A backtest tells you what a trader made. We tell you whether it was skill, and whether *you* can still get it.**

Agentverse 2026 · Finance track · **Version 0.7.2** (see `VERSION`; the team keeps a separate changelog). Someone with £200 sees a "copy this wallet, up 400%" post. The app reads a Polymarket wallet's public history and gives one verdict: **Skilled and copyable · Skilled but not copyable · Can't tell yet · Probably luck**, or **Hold – human review** if the input data looks manipulated. Every number traces back to the trades behind it.

> **Paper trading only. Information, not financial advice.** There are no wallet keys or order endpoints in this codebase.

Built with help from Claude (Anthropic) as a coding assistant; the app's own language model is Gemini. This is the team's combined build. **Diego** wrote the engine, real-data loader and evaluation. **Adrian** wrote the web frontend. **Lawrence** wrote the chat agent and persistent kill switch. **Joyce**'s Streamlit prototype (a separate build of the same spec) contributed the 1,003-wallet planted batch and its verdicts, split/merge handling for the Polymarket pull, and the terminal demo.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                    # 75 tests
python -m ctdd.api                     # http://127.0.0.1:8000  (PORT=... to change)
python demo.py                         # backup: the 4-minute demo in the terminal, offline (--yes runs straight through)
python -m eval.run_large_planted --out eval/results/v2_engine   # ~3 min: re-scores the 1,003-wallet batch with the frozen engine
```

**Gemini (optional, needed for the chat agent):**
1. Copy `.env.example` to `.env`. It's git-ignored, so the key never gets committed.
2. Paste your key after `GEMINI_API_KEY=`.
3. The default model is `gemini-3.5-flash-lite`. Set `CTDD_GEMINI_MODEL=gemini-3.8-flash` if your key only has that one.

Without a key, everything except the agent works: report text comes from a template and related bets are grouped by a heuristic. Set `CTDD_OFFLINE=1` to force offline mode.

## The app (3 tabs)

| Tab | What it shows |
|---|---|
| **Home** | One box: paste a wallet address to open its report card, or type a question for the agent (`#/?ask=...` runs a question for demos). Below it, the **live Polymarket top 10 by profit**, refreshed every 30 minutes and on demand, with the time it was last updated. The **?** next to the heading explains why a profit ranking isn't enough and links to "Why rankings mislead". A wallet's verdict appears in the table once someone has opened it (worked-out verdicts are reused for 30 minutes) |
| **Report card** (opened from Home) | The verdict and its reasons, **what would change the verdict**, a written report where each sentence links to its numbers and trades, **flags needing human review**, edge with a cluster-bootstrap CI, luck score, copy-delay decay, concentration, categories, a £200 historical simulation, **input checks**, and the trades table |
| **Paper trading** | Practice data, clearly labelled. Four planted traders (copyable skill, uncopyable skill, a 25–0 luck record, a cluster trap). Fixed rules in code (not the language model) propose a paper copy of each trader's next bet, eight code-enforced controls check it, and a human approves or rejects. The stake box shows the £10 cap and warns while you type. **Settle next** resolves one copy at a time and an **account value** chart steps with each result. The **kill switch** is here; a "What just happened" feed shows the paper-trading and safety events in plain English |
| **Under the hood** | Three sub-tabs. **Why rankings mislead**: five planted traders shown the way a leaderboard shows them, then revealed. **How we tested it**: Tests 1–3 (below). **Activity record**: the append-only, hash-chained log in plain English, filterable by kind, with a check that no line was edited |

**Always visible:** the "Paper trading only" banner, a **Copying: allowed / stopped** indicator in the top bar (the kill switch state, on every page), and a **Technical details** switch that shows raw log fields, hashes, the engine's diagnostics and the leaderboard-size N control. It's off by default.

**Offline behaviour of the leaderboard.** One request per refresh, at most one forced refresh every 30 s. The last two good lists are kept in `data_cache/leaderboard/`, and a failed or empty fetch never overwrites them. On a fresh install with no internet it shows `data/leaderboard_snapshot.json` (the ten wallets from the real-data test, labelled as a saved copy).

## Where to find each judging criterion

| Criterion | Where to look |
|---|---|
| **Traceable reasoning** | Report card: click any sentence of the written report to see its numbers and trades; "What would change this verdict"; flags with "Highlight trades". Verdict rules are in `thresholds.json` and `ctdd/engine/verdict.py`, never in the model |
| **Testing on unseen data** | Under the hood → How we tested it: Test 1 (planted, holdout seed), Test 2 (1,003 wallets from an independent generator), Test 3 (real Polymarket walk-forward), naive baselines, every error listed, 95% intervals |
| **Risk controls** | Paper trading: the eight controls on every proposal, the kill switch (the agent can turn it on, never off), the drawdown stop; the top-bar indicator; Activity record → Safety controls |
| **Relevance** | Home: the live leaderboard and a pasted real wallet |
| **Ambition** | The agent on Home: Gemini picks tools (analyse, compare two wallets with their market overlap, preview a stake against the controls, stop all copying); code rejects any answer that quotes a number no tool returned or gives advice |

## Demo script (≈4 min)

1. **Hook.** On Home, point at the live leaderboard and its **?**, then paste `0xDEMO-perfect-25-0`: a 25–0 record. The verdict is *Probably luck*. Every bet was at 95c or above, and the bootstrap CI looks great (+4.1% to +5.3%), but the luck score is >99.9%.
2. **Contrast.** Open `0xDEMO-messy-skilled`: only 55% wins, but *Skilled and copyable*. Then `0xDEMO-fast-mover`: real edge, but 5 minutes late the follower's edge is gone, so *Skilled but not copyable*.
3. **Agent.** Ask "I want to put £30 on 0xDEMO-perfect-25-0. Can I?". It analyses the wallet, runs the risk checks, and explains both blocks. If it tries to answer without the risk check, code rejects the answer.
4. **Live control.** In Paper trading, pick the 25–0 trader, click **Next bet**, set the stake to £50 and approve. It's blocked by the per-trade cap, the verdict gate and the event-exposure cap. Then click **Stop all copying** and watch every proposal fail.
5. **Results.** Under the hood → Why rankings mislead (reveal), then How we tested it: on a fresh batch never used before, 1/26 false alarms against 10/26 and 16/26 for the naive judges (the one miss is shown and explained on the page). On 1,003 wallets from a different generator, it recommended **0 of 882 no-skill wallets**, and 11 of its 13 copy calls (85%) were truly skilled and copyable, against 1 in 10 for "top 10 by profit". On real wallets, copying the top 10 an hour late lost 18.7% per copy (the leaders themselves lost 10.6% on the same bets), while the agent approved none and held cash.

**If the web app or Wi-Fi fails:** `python demo.py` runs the same five steps in the terminal, offline, through the same engine, controls, kill switch and audit log.

## How it works

```
public fills -> positions (reconciled to Polymarket's P&L incl. fees) -> input checks (wash, both-sides, injection...)
   -> related-bet clusters (Gemini or heuristic; injected market text withheld from the LLM)
   -> stats engine: edge + cluster bootstrap | luck score | copy-delay decay | concentration | betting evidence
   -> frozen verdict rules (thresholds.json) -> report card (number-guarded text) -> web UI / chat agent
live: agent proposes -> code controls (kill switch, hold, cap, verdict gate, exposure, drawdown, stale price, cash)
      -> human approves -> paper ledger -> hash-chained audit log
```

**Luck score.** A no-skill *twin* holds the trader's exact positions, but each outcome is drawn at the market's own odds. Related bets share one draw. In multi-candidate markets exactly one candidate wins. The score is Luck(N) = 1 − (1 − p)^N: the chance that N no-skill traders produce someone at least this good. The app shows the most sceptical of the engine's no-skill nulls. See `docs/METHODS.md`.

## What we cut, and why

| Cut | Why |
|---|---|
| The separate Copy / Watch / Don't-copy "bottom line" | Two labels per wallet confused the story. There's now one verdict, plus *Hold – human review* when input checks fail |
| v1 verdict, Bayesian posterior and per-null breakdown in the UI | These are diagnostics. They stay in the engine and the evaluation (`docs/METHODS.md`), not on screen |
| The Leaderboard-size N toggle on the main view | It made the verdict look arbitrary. The verdict uses the frozen N = 1,000; the card shows the luck score for 100, 1,000 and 10,000. A custom N is still available with **Technical details** on |
| Five top-level tabs | Now three. The synthetic leaderboard moved to Under the hood as a demonstration; Ask the agent merged into Home; Evaluation and Audit log became sub-tabs. Old links (`#/agent`, `#/live`, `#/evaluation`, `#/audit`) still work |
| Adrian's startup LLM pass, key pooling, mock clusterer and near-certainty LLM job | They were only needed to read thousands of synthetic markets at startup. Now the LLM reads only the markets of the wallet being viewed, and "bought at ≥93c" is a rule in code |
| Lawrence's separate LLM summary and copy note | The chat agent covers them |
| Diego's Streamlit app | Replaced by Adrian's frontend |
| Joyce's Streamlit prototype (app, engine, Gemini client) | One engine is easier to defend than two. Its planted batch, its verdicts on that batch, its split/merge handling and its demo script were kept; see below |
| Fixture/mock mode in the frontend | The sample data was out of date |

**The engine was edited once, openly, in v0.7.0.** `ctdd/engine/*`, the prompts, `text_jobs.py` and `thresholds.json` are covered by the freeze hash: `92465b6b62360be3` for engine v1 (Diego's frozen results), `1e14c2d1e9f39823` for engine v2 (the grouping fix only). Everything else above is in the presentation layer (`ctdd/adapter.py`).

## Second planted test: 1,003 wallets from an independent generator

`data/planted_large/` is the test batch from Joyce's prototype (seed 2, made by a different generator: hidden random walks per event, prices as exact probabilities, wallets planted as skilled, slow-to-copy, luck, 95c farmer or clustered). `ctdd/data/csvset.py` loads it into the engine's shapes without touching the engine, and `eval/run_large_planted.py` scores every wallet. Results: `eval/results/planted_large.md`.

| Judge (same 1,003 wallets) | Recommends copying a no-skill wallet | Of its "copy" calls, truly skilled & copyable |
|---|---|---|
| **Engine v2 (this build)** | **0 / 882** (CI 0–0.4%) | **11 / 13 = 85%** |
| Engine v1 (v0.6.0) | 0 / 882 (CI 0–0.4%) | 12 / 14 = 86% (CI 60–96%) |
| Prototype engine | 0 / 882 | 28 / 30 = 93% |
| Naive: top 10 by profit | 0 / 882 | 1 / 10 = 10% |
| Naive: top 10 by ROI | 2 / 882 | 0 / 10 |
| Naive: win rate > 70% | 287 / 882 = 33% | 32 / 359 = 9% |

What to say about it:
- The engine was **never tuned on this generator**, and the freeze hash (`92465b6b62360be3`) is unchanged, so this is a genuine out-of-sample test. The prototype engine *was* tuned on this generator's dev batch, so it has home advantage.
- This engine is **more cautious**. It catches 16/40 slow-to-copy traders as *Skilled but not copyable* (prototype: 35/40) and clears fewer skilled traders (31% at 14–20c edge; prototype 72%). It never mistakes a no-skill wallet for a skilled one.
- Costs use the frozen settings (0.5c half-spread, no fee), not the batch's per-market fees. Related bets are grouped only by the engine's own heuristic; the batch's true event ids (`markets_truth.csv`) are never shown to it.

## Layout

| Path | What |
|---|---|
| `ctdd/engine/`, `ctdd/data/`, `ctdd/pipeline.py`, `eval/` | Diego: engine, Polymarket client, synthetic world, evaluation runs |
| `ctdd/controls.py` | Risk controls, now with a per-control pass/fail list and the persistent kill switch |
| `ctdd/killswitch.py` | A file on disk. Anyone can turn it on; only a human can turn it off |
| `ctdd/adapter.py` | Engine report → report-card JSON. Presentation only |
| `ctdd/replay.py`, `ctdd/service.py`, `ctdd/evalview.py`, `ctdd/api.py` | Live replay, app state, evaluation view, Flask API |
| `ctdd/chat.py` | The chat agent and its code-level guards; `compare_wallets` reports both verdicts and the market overlap |
| `ctdd/leaderboard.py` | Live top 10 with two saved snapshots and a bundled fallback |
| `ctdd/auditview.py` | Plain-English one-line summaries and groups for the activity record (display only; the log file is untouched) |
| `ctdd/data/csvset.py`, `eval/run_large_planted.py`, `data/planted_large/` | The second planted test (merge) |
| `ctdd/data/polymarket.py::conversion_fills` | Splits and merges turned into 50c fills on both outcomes (merge, from Joyce's prototype) |
| `demo.py` | Terminal backup demo (merge) |
| `frontend/` | Adrian's UI, restructured in v0.5.0 into Home / Paper trading / Under the hood |

## Known limits (say these in the deck)

- **Planted traders are simpler than real ones.** All 16 evaluation errors are skilled traders the agent didn't clear, so it leans cautious. A 5c edge needs about 2,000+ bets to stand out against 1,000 wallets.
- **The real walk-forward approved no wallets.** It shows that the leaderboard wasn't worth copying, not that the agent picks winners. Its universe is today's leaderboard, followers hold to resolution, and history is paged.
- **Engine v2 changed the grouping after the original freeze.** v1 linked markets that shared any name, and the links chained (a month of e-sports matches became one "event"). v2 groups by match. It was frozen before testing and tested once on a never-used planted seed, with v1 alongside; see `docs/METHODS.md`. The real-data walk-forward was run with v1 and still needs a v2 re-run (below). The "Check the grouping" note on report cards stays as a safety net.
- **The luck twin is a clone of the trader.** Positions sold early are excluded from the luck score; coverage is shown on the card.
- **Splits and merges are approximate.** A split is recorded as buying both outcomes at 50c and a merge as selling both at 50c, so each market's total P&L is exact but the split between outcomes is approximate. Where Polymarket's own closed position matches, its P&L is used anyway. Converted rows are kept out of the input checks (a split is not "betting both sides"). The published real walk-forward was run before this change and uses trades only.
- **Not yet tested in this combined build:**
  - the chat agent against live Gemini (its guards are tested with a scripted model);
  - real-wallet analysis through the new web UI;
  - the live leaderboard fetch against Polymarket (tested with recorded-shape responses; field names are read defensively);
  - split/merge conversion against the live API (tested against recorded-shape fake responses only). Diego's real-data pipeline itself was run end to end on real wallets.

**Keep the `--out` folders.** Engine v1's original results stay in `eval/results/` and are shown as the comparison rows; running an evaluation script without `--out eval/results/v2_engine` would overwrite them with engine v2's numbers.

## Re-running the real-data test (Test 3) with engine v2

Needs internet (Polymarket's public API), about 5 minutes. Use the same cut-off as the original run so the two engines see identical data:

```
python -m eval.walkforward --cutoff-ts 1792863497 --out eval/results/v2_engine
```

The app then shows the v2 result under Test 3 automatically (restart it). Note that today's leaderboard differs from 7 Nov's, so the wallet universe may differ slightly; the output says which wallets were judged.

## Data and licences

Polymarket's public APIs (Data API v2, Gamma, CLOB) are read-only. Check Polymarket's terms before publishing data extracts. Wallets are shown by address only and never linked to people. Unusual timing is flagged only as "needs human review". Synthetic data is labelled wherever it appears.
