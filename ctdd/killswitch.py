"""Persistent kill switch: a file on disk, so it can be flipped from the web UI, the agent or a terminal
and it survives restarts. Anyone (including the agent) may turn it ON; only a human turns it OFF."""
from __future__ import annotations

import json
import time

from .config import LOG_DIR

PATH = LOG_DIR / "KILL_SWITCH"


def status() -> dict:
    if not PATH.exists():
        return {"on": False}
    try:
        return {"on": True, **json.loads(PATH.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, OSError):
        return {"on": True, "reason": "unknown", "by": "unknown"}


def turn_on(by: str, reason: str, audit=None) -> dict:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"by": by, "reason": reason or "stopped", "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    if audit:
        audit.log("kill_switch", on=True, by=by, reason=reason)
    return status()


def turn_off(by: str, audit=None) -> dict:
    if not by.startswith("human"):
        raise PermissionError("Only a human can turn the kill switch off.")
    if PATH.exists():
        PATH.unlink()
    if audit:
        audit.log("kill_switch", on=False, by=by)
    return status()
