"""Optional LLM provider (Gemini REST). Without GEMINI_API_KEY every job falls back to deterministic code.

The LLM reads and writes text only. Its output is parsed as JSON, validated by the caller,
and every call is written to the audit log with the prompt version.
"""
from __future__ import annotations

import json
import os
import re

import requests

from ..audit import AuditLog
from .prompts import PROMPT_VERSION

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _load_dotenv() -> None:
    """Read KEY=VALUE lines from the project's git-ignored .env (real environment variables win)."""
    from ..config import ROOT

    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class LLM:
    def __init__(self, audit: AuditLog | None = None, model: str | None = None):
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = model or os.environ.get("CTDD_GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.audit = audit or AuditLog()

    @property
    def available(self) -> bool:
        return bool(self.key) and os.environ.get("CTDD_OFFLINE") != "1"

    def complete(self, job: str, prompt: str, want_json: bool = True, timeout: int = 60) -> str | dict | None:
        if not self.available:
            return None
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.0}}
        if want_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        try:
            # Key goes in a header, never the URL, so it can't leak into error messages or logs.
            r = requests.post(GEMINI_URL.format(model=self.model), headers={"x-goog-api-key": self.key}, json=body, timeout=timeout)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:  # network, quota, schema
            self.audit.log("llm_error", job=job, model=self.model, prompt_version=PROMPT_VERSION,
                           error=str(exc).replace(self.key, "<redacted>")[:400])
            return None
        out = text
        if want_json:
            try:
                out = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())
            except json.JSONDecodeError:
                self.audit.log("llm_bad_json", job=job, model=self.model, prompt_version=PROMPT_VERSION, raw=text[:500])
                return None
        self.audit.log("llm_call", job=job, model=self.model, prompt_version=PROMPT_VERSION,
                       prompt_chars=len(prompt), output=out if want_json else text[:2000])
        return out
