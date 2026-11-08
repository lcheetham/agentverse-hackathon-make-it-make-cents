# Team contract (every Claude session reads this first)

Project: Copy-Trader Due Diligence (Agentverse 2026, finance). Spec: `docs/SPEC.md`. Python backend (Flask, `ctdd/api.py`) + vanilla JS frontend (`frontend/`, no build step).

## Hard rules
- The LLM never computes a number. All numbers come from `ctdd/engine/` (plain, unit-tested Python).
- Paper trading only. Never add wallet keys, signing, or order endpoints.
- Every action that matters goes through `AuditLog.log(...)` (append-only, hash-chained). Never edit `logs/*.jsonl`.
- Verdicts come only from `ctdd/engine/verdict.py` + `thresholds.json`. Do not change either after `eval/freeze.json` exists unless the team agrees (it contaminates the test batch).
- Synthetic data must be labelled SYNTHETIC wherever shown.
- Polymarket fills come from `/v2/activity` (not `/v2/trades`, which is incomplete); Gamma needs `closed=true` for resolved markets.

## Shared shapes
- fills: wallet, condition_id, token_id, outcome_index, side, price, size, ts, title, event_slug
- markets (index condition_id): title, rules, event_slug, neg_risk, resolved, resolve_ts, payouts
- positions: see `ctdd/engine/positions.py::POSITION_COLUMNS` (status in held | exited | open)
- report: `ctdd/engine/analyze.py::analyze_wallet` return dict; every stat has an id like `S.edge`

## Ownership (touch only your folder unless agreed)
P1 `ctdd/data/polymarket.py`, `eval/feasibility.py`, `eval/walkforward.py` · P2 `ctdd/engine/` · P3 `ctdd/data/synthetic.py`, `eval/run_planted.py` · P4 `ctdd/agent/`, `ctdd/controls.py`, `ctdd/audit.py` · P5 `frontend/`, `ctdd/api.py`, `ctdd/adapter.py`, `ctdd/leaderboard.py`, `ctdd/auditview.py`, `docs/`, README · Merge (Joyce) `ctdd/data/csvset.py`, `eval/run_large_planted.py`, `data/planted_large/`, `demo.py`, `conversion_fills` in `ctdd/data/polymarket.py`

## Commands
- tests: `.venv/Scripts/python -m pytest tests -q`
- app: `.venv/Scripts/python -m ctdd.api` (http://127.0.0.1:8000)
- eval: `python -m eval.run_planted --batch dev` → `--freeze` → `--batch test --seed N` (once)
- large planted batch (independent generator): `python -m eval.run_large_planted` (~3 min; never retune on it)
- terminal backup demo: `python demo.py` (`--yes` to run straight through)
- fills may carry a `conversion` column (`split`/`merge`); `run_wallet` keeps those rows out of the input checks

## Versions
- `VERSION` holds the current version; zips are named `copytrader-dd-v<version>.zip`. Bump it with every shared build and add an entry to the team changelog.
