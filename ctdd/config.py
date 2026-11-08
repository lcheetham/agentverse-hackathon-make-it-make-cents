"""Paths, thresholds and the freeze hash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS_PATH = ROOT / "thresholds.json"
CACHE_DIR = ROOT / "data_cache"
LOG_DIR = ROOT / "logs"
EVAL_DIR = ROOT / "eval"

BANNER = "Paper trading only. Information, not financial advice."

VERDICTS = (
    "Skilled and copyable",
    "Skilled but not copyable",
    "Can't tell yet",
    "Probably luck",
)


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def freeze_hash() -> str:
    """Hash of everything that decides a verdict: thresholds, engine code, prompts.

    The planted test batch is only valid if this hash equals the one recorded at freeze time.
    """
    h = hashlib.sha256()
    files = [THRESHOLDS_PATH]
    files += sorted((ROOT / "ctdd" / "engine").glob("*.py"))
    files += [ROOT / "ctdd" / "agent" / "prompts.py", ROOT / "ctdd" / "agent" / "text_jobs.py"]
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]
