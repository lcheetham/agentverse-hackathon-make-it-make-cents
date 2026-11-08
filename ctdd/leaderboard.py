"""Live Polymarket leaderboard for the Home page: a plain top-10 list, no verdicts computed in advance.

* One request per refresh (Polymarket Data API v2 /leaderboard), so refreshing is cheap. Analysing a
  wallet is the expensive part, and that only happens when someone opens it.
* Refreshes automatically when the saved list is older than REFRESH_S, and on demand from the refresh
  button (at most once every MIN_GAP_S, to stay well inside Polymarket's rate limits).
* Two saved copies, `latest` and `previous`. A refresh only overwrites them when it actually returned
  traders, so a failed or empty fetch can never replace a good list.
* If nothing has ever been fetched (fresh install, no internet), a snapshot bundled in the repo is shown,
  clearly labelled with its date.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import requests

from .config import CACHE_DIR, ROOT

URL = "https://data-api.polymarket.com/v2/leaderboard"
UA = {"User-Agent": "copy-trader-due-diligence/0.5 (hackathon research, read-only)"}
REFRESH_S = 30 * 60
MIN_GAP_S = 30
TOP_N = 10
TIMEOUT_S = 8
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
BUNDLED = ROOT / "data" / "leaderboard_snapshot.json"


def _first(row: dict, *keys):
    for k in keys:
        if row.get(k) not in (None, ""):
            return row[k]
    return None


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def parse(payload) -> list[dict]:
    """Polymarket's leaderboard rows -> [{rank, address, name, profit, volume}]. Field names are read
    defensively because the v2 API has renamed them before."""
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        addr = str(_first(r, "user_id", "proxyWallet", "proxy_wallet", "address", "wallet") or "").lower()
        if not ADDR.match(addr):
            continue
        name = _first(r, "user_name", "userName", "name", "pseudonym")
        if name is not None and str(name).lower().startswith("0x"):
            name = None                                       # Polymarket's default "0x<address>-<timestamp>"
        out.append({
            "address": addr,
            "name": name,
            "profit": _num(_first(r, "pnl", "profit", "amount")),
            "volume": _num(_first(r, "vol", "volume")),
        })
    for i, r in enumerate(out[:TOP_N], 1):
        r["rank"] = i
    return out[:TOP_N]


def _fetch() -> list[dict]:
    r = requests.get(URL, params={"time_period": "month", "limit": TOP_N}, headers=UA, timeout=TIMEOUT_S)
    r.raise_for_status()
    return parse(r.json())


class LiveLeaderboard:
    def __init__(self, audit=None, store: Path | None = None, fetch=_fetch, clock=time.time):
        self.audit, self.fetch, self.clock = audit, fetch, clock
        self.store = Path(store) if store else CACHE_DIR / "leaderboard"
        self._lock = threading.Lock()
        self._last_attempt = 0.0
        self._last_error: str | None = None

    # ---------------- snapshots ----------------
    def _path(self, name: str) -> Path:
        return self.store / f"{name}.json"

    def _load(self, name: str) -> dict | None:
        p = self._path(name)
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def _save(self, rows: list[dict]) -> dict:
        self.store.mkdir(parents=True, exist_ok=True)
        latest = self._path("latest")
        if latest.exists():                                   # latest -> previous, then write the new latest
            latest.replace(self._path("previous"))
        snap = {"fetched_at": self.clock(), "source": "live", "rows": rows}
        tmp = self.store / "latest.tmp"
        tmp.write_text(json.dumps(snap), encoding="utf-8")
        tmp.replace(latest)
        return snap

    def _bundled(self) -> dict | None:
        try:
            snap = json.loads(BUNDLED.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return {**snap, "source": "bundled"}

    # ---------------- refresh ----------------
    def refresh(self, force: bool = False) -> dict:
        """Try one fetch. Returns {ok, note}. Never raises; never overwrites a good list with a bad one."""
        with self._lock:
            now = self.clock()
            gap = now - self._last_attempt
            if force and gap < MIN_GAP_S:
                return {"ok": False, "note": f"Refreshed {int(gap)} s ago. Try again in {int(MIN_GAP_S - gap)} s."}
            self._last_attempt = now
            try:
                rows = self.fetch()
                if not rows:
                    raise ValueError("Polymarket returned no traders")
            except Exception as exc:                          # network down, API change, rate limit...
                self._last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                if self.audit:
                    self.audit.log("leaderboard_refresh", ok=False, error=self._last_error)
                return {"ok": False, "note": "Could not reach Polymarket; showing the last saved list."}
            self._save(rows)
            self._last_error = None
            if self.audit:
                self.audit.log("leaderboard_refresh", ok=True, n=len(rows))
            return {"ok": True, "note": "Updated from Polymarket."}

    def get(self) -> dict:
        """The list to show, refreshing first if the saved one is stale (and we haven't just tried)."""
        latest = self._load("latest")
        stale = latest is None or self.clock() - latest.get("fetched_at", 0) > REFRESH_S
        note = None
        if stale and self.clock() - self._last_attempt > MIN_GAP_S:
            note = self.refresh()["note"]
            latest = self._load("latest")
        snap = latest or self._load("previous") or self._bundled() or {"fetched_at": None, "source": "none", "rows": []}
        return {**snap, "refresh_every_s": REFRESH_S, "stale": snap.get("source") != "live"
                or self.clock() - (snap.get("fetched_at") or 0) > REFRESH_S,
                "last_error": self._last_error, "note": note}
