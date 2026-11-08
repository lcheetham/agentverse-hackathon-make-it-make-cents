"""Polymarket public data client (read-only). Data API v2 + Gamma + CLOB price history, with a disk cache.

Endpoints verified live on 7 Nov 2026 (the v1 Data API and lb-api return HTTP 410):
  data-api.polymarket.com/v2/leaderboard?time_period=month|week|day|all
  data-api.polymarket.com/v2/activity?user=<wallet>&limit=500 (+ cursor): TRADE, SPLIT and MERGE rows
  data-api.polymarket.com/v2/positions?user=<wallet>&status=CLOSED
  gamma-api.polymarket.com/markets?condition_ids=<id>
  clob.polymarket.com/prices-history?market=<token>&startTs=&endTs=&fidelity=<minutes>
No keys, no order endpoints: this module cannot trade.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import requests

from ..audit import AuditLog
from ..config import CACHE_DIR

DATA = "https://data-api.polymarket.com/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "copy-trader-due-diligence/0.1 (hackathon research, read-only)"}


class PolymarketClient:
    def __init__(self, cache_dir: Path = CACHE_DIR, audit: AuditLog | None = None, min_interval: float = 0.15):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.audit = audit or AuditLog()
        self.min_interval = min_interval
        self._last = 0.0
        self._price_cache: dict = {}

    # ---------- HTTP ----------
    def _get(self, url: str, params=None, ttl: float | None = None):
        key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True, default=str)).encode()).hexdigest()[:32]
        path = self.cache / f"{key}.json"
        if path.exists() and (ttl is None or time.time() - path.stat().st_mtime < ttl):
            return json.loads(path.read_text(encoding="utf-8"))
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            r = requests.get(url, params=params, headers=UA, timeout=30)
            self._last = time.time()
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            path.write_text(json.dumps(data), encoding="utf-8")
            self.audit.log("data_pull", url=url, params=params, status=r.status_code)
            return data
        r.raise_for_status()

    def _paged(self, url: str, params: dict, max_pages: int, ttl: float | None) -> list:
        out, cursor = [], None
        for _ in range(max_pages):
            p = dict(params, **({"cursor": cursor} if cursor else {}))
            page = self._get(url, p, ttl=ttl)
            out += page.get("data", [])
            pag = page.get("pagination") or {}
            if not pag.get("has_more") or not pag.get("next_cursor"):
                break
            cursor = pag["next_cursor"]
        return out

    # ---------- endpoints ----------
    def leaderboard(self, time_period: str = "month", n: int = 500, ttl: float = 3600) -> pd.DataFrame:
        rows = self._paged(f"{DATA}/leaderboard", {"time_period": time_period, "limit": min(n, 500)}, max(1, n // 500 + 1), ttl)
        return pd.DataFrame(rows[:n])

    def trades(self, wallet: str, max_pages: int = 20, ttl: float = 6 * 3600) -> pd.DataFrame:
        """All fills for a wallet, from /v2/activity (type TRADE).

        /v2/trades?user= is incomplete: for one leaderboard wallet it returned 591 fills where
        /v2/activity listed 1,932 trades, and rebuilt share counts were ~half of Polymarket's.
        """
        rows = self._paged(f"{DATA}/activity", {"user": wallet, "limit": 500}, max_pages, ttl)
        rows = [r for r in rows if r.get("type") == "TRADE" and r.get("side") in ("BUY", "SELL")]
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return pd.DataFrame({
            "wallet": df["proxy_wallet"].str.lower(),
            "condition_id": df["condition_id"],
            "token_id": df["token_id"].astype(str),
            "outcome_index": pd.to_numeric(df["outcome_index"], errors="coerce").fillna(-1).astype(int),
            "side": df["side"].str.upper(),
            "price": df["price"].astype(float),
            "size": df["size"].astype(float),
            "ts": df["timestamp"].astype(int),
            "title": df.get("title", ""),
            "event_slug": df.get("event_slug", "").fillna("") if "event_slug" in df else "",
        })

    def conversions(self, wallet: str, max_pages: int = 20, ttl: float = 6 * 3600) -> list[dict]:
        """The wallet's SPLIT and MERGE rows from the same /v2/activity pages as `trades()`.

        Same URL and params as `trades()`, so the pages come from the disk cache: no extra requests.
        """
        rows = self._paged(f"{DATA}/activity", {"user": wallet, "limit": 500}, max_pages, ttl)
        return [r for r in rows if str(r.get("type", "")).upper() in ("SPLIT", "MERGE")]

    def trades_window(self, wallet: str, end_ts: int | None = None, stop_before_ts: int | None = None,
                      max_pages: int = 6, ttl: float = 6 * 3600) -> pd.DataFrame:
        """Fills newest-first, from `end_ts` (or now) back to `stop_before_ts` or the page cap.

        `/v2/activity` honours `end=`, so the history *as it stood at a cut-off* can be pulled without look-ahead.
        """
        rows, cursor = [], None
        for _ in range(max_pages):
            params = {"user": wallet, "limit": 500, **({"end": int(end_ts)} if end_ts else {}), **({"cursor": cursor} if cursor else {})}
            page = self._get(f"{DATA}/activity", params, ttl=ttl)
            data = page.get("data", [])
            rows += data
            pag = page.get("pagination") or {}
            if not data or not pag.get("has_more") or not pag.get("next_cursor"):
                break
            if stop_before_ts and min(r["timestamp"] for r in data) < stop_before_ts:
                break
            cursor = pag["next_cursor"]
        return self._fills_frame(rows)

    def _fills_frame(self, rows: list) -> pd.DataFrame:
        rows = [r for r in rows if r.get("type") == "TRADE" and r.get("side") in ("BUY", "SELL")]
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return pd.DataFrame({
            "wallet": df["proxy_wallet"].str.lower(),
            "condition_id": df["condition_id"],
            "token_id": df["token_id"].astype(str),
            "outcome_index": pd.to_numeric(df["outcome_index"], errors="coerce").fillna(-1).astype(int),
            "side": df["side"].str.upper(),
            "price": df["price"].astype(float),
            "size": df["size"].astype(float),
            "ts": df["timestamp"].astype(int),
            "title": df["title"] if "title" in df else "",
            "event_slug": df["event_slug"].fillna("") if "event_slug" in df else "",
        })

    def closed_positions(self, wallet: str, max_pages: int = 10, ttl: float = 6 * 3600) -> pd.DataFrame:
        return pd.DataFrame(self._paged(f"{DATA}/positions", {"user": wallet, "status": "CLOSED", "limit": 500}, max_pages, ttl))

    def markets(self, condition_ids, ttl: float = 24 * 3600, batch: int = 50) -> pd.DataFrame:
        """Gamma omits resolved markets unless closed=true, so query closed first, then the rest."""
        ids = list(pd.unique(pd.Series(list(condition_ids))))
        rows, found = [], set()
        for closed in (True, False):
            todo = [c for c in ids if c not in found]
            for s in range(0, len(todo), batch):
                chunk = todo[s:s + batch]
                params = [("condition_ids", c) for c in chunk] + [("limit", str(len(chunk)))]
                if closed:
                    params.append(("closed", "true"))
                data = self._get(f"{GAMMA}/markets", params, ttl=ttl)
                for m in data if isinstance(data, list) else []:
                    if m.get("conditionId") in chunk and m["conditionId"] not in found:
                        rows.append(_parse_market(m))
                        found.add(m["conditionId"])
        return pd.DataFrame(rows).set_index("condition_id") if rows else pd.DataFrame(
            columns=["title", "rules", "event_slug", "neg_risk", "resolved", "resolve_ts", "payouts"])

    def price_history(self, token_id: str, start_ts: int, end_ts: int, fidelity: int = 5) -> list[tuple[int, float]]:
        data = self._get(f"{CLOB}/prices-history", {"market": token_id, "startTs": int(start_ts), "endTs": int(end_ts), "fidelity": fidelity}, ttl=None)
        return [(int(h["t"]), float(h["p"])) for h in (data or {}).get("history", [])]

    def price_at_factory(self, positions: pd.DataFrame, delays=(0, 300, 3600, 86400), max_positions: int = 150):
        """Pre-fetch histories around each position's entry and return price_at(token, ts).

        Only the most recent `max_positions` positions get histories (rate limits); others return None
        and count as 'missed' copies in the delay curve.
        """
        sample = positions.sort_values("first_ts").tail(max_positions)
        span = max(delays) + 3600
        for r in sample.itertuples(index=False):
            hist = self.price_history(r.token_id, int(r.first_ts) - 600, int(r.first_ts) + span)
            if r.last_sell_ts == r.last_sell_ts:
                hist += self.price_history(r.token_id, int(r.last_sell_ts) - 600, int(r.last_sell_ts) + span)
            pts = sorted(set(self._price_cache.get(r.token_id, []) + hist))
            self._price_cache[r.token_id] = pts

        def price_at(token_id: str, ts: float):
            pts = self._price_cache.get(token_id)
            if not pts:
                return None
            i = bisect.bisect_left(pts, (int(ts), -1.0))
            if i >= len(pts) or pts[i][0] - ts > 1800:  # first observation at/after ts, within 30 min
                return None
            return pts[i][1]

        return price_at


def _parse_market(m: dict) -> dict:
    def _list(x):
        if isinstance(x, str):
            try:
                return json.loads(x)
            except json.JSONDecodeError:
                return []
        return x or []

    prices = [float(p) for p in _list(m.get("outcomePrices"))]
    closed = bool(m.get("closed"))
    resolved = closed and len(prices) > 0 and all(p in (0.0, 0.5, 1.0) for p in prices) and abs(sum(prices) - 1) < 1e-6
    end = m.get("closedTime") or m.get("endDate")
    try:
        resolve_ts = pd.Timestamp(str(end).replace("+00", "+00:00") if str(end).endswith("+00") else end).timestamp() if end else float("nan")
    except (ValueError, TypeError):
        resolve_ts = float("nan")
    events = m.get("events") or []
    return {
        "condition_id": m.get("conditionId"),
        "title": m.get("question", ""),
        "rules": m.get("description", ""),
        "event_slug": (events[0].get("slug") if events else None) or m.get("slug", ""),
        "neg_risk": bool(m.get("negRisk", False)),
        "resolved": resolved,
        "resolve_ts": resolve_ts if resolved else float("nan"),
        "payouts": prices if resolved else None,
        "outcomes": _list(m.get("outcomes")),
        "token_ids": [str(t) for t in _list(m.get("clobTokenIds"))],
        "fee_rate": 0.0,
        "synthetic": False,
    }


def conversion_fills(rows: list[dict], markets: pd.DataFrame, fills: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Turn SPLIT / MERGE activity into equivalent fills (ported from the Streamlit prototype).

    Splits and merges aren't trades, but market makers use them constantly: a SPLIT turns $N into
    N shares of each outcome, and a MERGE turns N of each back into $N. We record a split as buying N of
    each outcome at 50c and a merge as selling N of each at 50c. The cash is exact, so each market's total
    P&L is right; how it divides between the two outcomes is approximate.

    Token ids come from Gamma (`clobTokenIds`), else from the wallet's own trades in that market.
    Only binary markets are converted. Returns (fills, info) with counts of what was skipped.
    """
    cols = ["wallet", "condition_id", "token_id", "outcome_index", "side", "price", "size", "ts", "title", "event_slug",
            "conversion"]
    seen: dict = {}
    if fills is not None and len(fills):
        for c, oi, t in zip(fills["condition_id"], fills["outcome_index"], fills["token_id"]):
            seen.setdefault((c, int(oi)), str(t))
    out, skipped = [], 0
    for r in rows:
        kind, cid = str(r.get("type", "")).upper(), r.get("condition_id")
        size = float(r.get("size") or 0)
        if kind not in ("SPLIT", "MERGE") or size <= 0 or not cid:
            skipped += 1
            continue
        toks = []
        if cid in markets.index and "token_ids" in markets:
            t = markets.at[cid, "token_ids"]
            toks = list(t) if isinstance(t, (list, tuple)) else []
        toks = [toks[i] if i < len(toks) else seen.get((cid, i)) for i in (0, 1)]
        outcomes = markets.at[cid, "outcomes"] if (cid in markets.index and "outcomes" in markets) else None
        binary = not isinstance(outcomes, (list, tuple)) or len(outcomes) == 2
        if not binary or not all(toks):
            skipped += 1
            continue
        slug = markets.at[cid, "event_slug"] if cid in markets.index else ""
        for i, tok in enumerate(toks):
            out.append(dict(wallet=str(r.get("proxy_wallet", "")).lower(), condition_id=cid, token_id=str(tok),
                            outcome_index=i, side="BUY" if kind == "SPLIT" else "SELL", price=0.5, size=size,
                            ts=int(r.get("timestamp")), title=r.get("title", ""), event_slug=slug or "",
                            conversion=kind.lower()))
    info = {"splits": sum(str(r.get("type", "")).upper() == "SPLIT" for r in rows),
            "merges": sum(str(r.get("type", "")).upper() == "MERGE" for r in rows), "skipped": skipped}
    return pd.DataFrame(out, columns=cols), info
