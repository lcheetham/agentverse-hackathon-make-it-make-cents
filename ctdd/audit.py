"""Append-only, hash-chained JSONL audit log.

Every line carries the SHA-256 of the previous line, so any edit or deletion
breaks the chain and `verify()` reports where.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

from .config import LOG_DIR

_lock = threading.Lock()


def _default(o):
    try:
        import numpy as np

        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
    except ImportError:  # pragma: no cover
        pass
    return str(o)


class AuditLog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else LOG_DIR / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "genesis"
        with open(self.path, "rb") as fh:
            lines = fh.read().splitlines()
        return hashlib.sha256(lines[-1]).hexdigest() if lines else "genesis"

    def log(self, event: str, **data) -> dict:
        with _lock:
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                "event": event,
                "prev": self._last_hash(),
                **data,
            }
            line = json.dumps(entry, default=_default, ensure_ascii=False, sort_keys=False)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return entry

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        start = max(0, len(lines) - n)
        return [{"seq": start + i + 1, **json.loads(x)} for i, x in enumerate(lines[start:])]

    def verify(self) -> tuple[bool, int | None]:
        """Return (ok, first_bad_line_number)."""
        if not self.path.exists():
            return True, None
        with open(self.path, "rb") as fh:
            lines = fh.read().splitlines()
        prev = "genesis"
        for i, raw in enumerate(lines, 1):
            if json.loads(raw).get("prev") != prev:
                return False, i
            prev = hashlib.sha256(raw).hexdigest()
        return True, None
