"""Report writer with a number guard.

The template writer is always available. If an LLM is configured, its prose is accepted only if
every number in it matches a number the engine produced; otherwise the template is used and the
rejection is logged.
"""
from __future__ import annotations

import json
import math
import re

from ..audit import AuditLog
from ..config import BANNER
from .llm import LLM
from .prompts import REPORT_PROMPT

_NUM_RE = re.compile(r"(?<![\w.])[-−]?\$?£?\d[\d,]*(?:\.\d+)?%?")
_ALWAYS_OK = {95.0, 0.95, 200.0, 1.0, 0.0, 5.0, 10.0}


def _variants(v: float) -> set[float]:
    out = {round(v, 6)}
    for f in (v, v * 100):
        for d in (0, 1, 2, 3, 4):
            out.add(round(f, d))
    return out


def allowed_numbers(report: dict) -> set[float]:
    vals: set[float] = set(_ALWAYS_OK)
    for s in report["stats"].values():
        for key in ("value", "lo", "hi"):
            x = s.get(key)
            if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x)):
                vals |= _variants(float(x))
                vals |= _variants(abs(float(x)))
    for N in report["luck"].get("modes", {}).get("independent", {}).get("luck", {}):
        vals.add(float(N))
    for c in report["delay_curve"]:
        vals |= {float(c["delay_s"]), c["delay_s"] / 60, c["delay_s"] / 3600, c["delay_s"] / 86400}
    return vals


def number_guard(text: str, allowed: set[float]) -> list[str]:
    """Return the numbers in `text` that do not match any engine output (empty list = pass)."""
    bad = []
    stripped = re.sub(r"\[[^\]]*\]", "", text)  # ignore [S.ids]
    for tok in _NUM_RE.findall(stripped):
        clean = tok.replace("−", "-").replace("$", "").replace("£", "").replace(",", "").rstrip("%")
        try:
            x = float(clean)
        except ValueError:
            continue
        if not any(abs(x - a) <= max(0.0051, 0.005 * abs(a)) for a in allowed) and abs(x) not in allowed:
            bad.append(tok)
    return bad


def _pct(x: float) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.1f}%"


def template_report(report: dict) -> list[dict]:
    """Sentences, each with the stat ids it rests on."""
    s = report["stats"]
    v = report["verdict"]
    N = s["S.N_eff"]["value"]
    luck = s["S.luck"]["value"]
    edge = s["S.edge"]
    out = [
        {"text": f"Verdict: {v}.", "ids": report["deciding_stats"]},
        {"text": f"Across {s['S.n_closed']['value']} closed positions the trader made ${s['S.profit']['value']:,.2f} with a win rate of {_pct(s['S.win_rate']['value'])}.",
         "ids": ["S.n_closed", "S.profit", "S.win_rate"]},
        {"text": f"Average return per position was {_pct(edge['value'])} (95% CI {_pct(edge['lo'])} to {_pct(edge['hi'])}), based on {s['S.n_clusters']['value']} independent event clusters.",
         "ids": ["S.edge", "S.n_clusters"]},
        {"text": f"Luck score: the chance that {N:,} no-skill traders produce someone at least this good is {_pct(luck)}.",
         "ids": ["S.luck", "S.N_eff"]},
    ]
    d_id = f"S.edge_delay.{report['sim200']['delay_s']}"
    if d_id in s:
        d = s[d_id]
        out.append({"text": f"Copying {report['sim200']['delay_s'] // 3600} hour later, after spread and fees, the follower's return per position is {_pct(d['value'])} (95% CI {_pct(d['lo'])} to {_pct(d['hi'])}).",
                    "ids": [d_id]})
    out.append({"text": f"Historical simulation: £200 copying every bet at £10 a copy would have ended at £{s['S.sim200_end']['value']:,.2f}.",
                "ids": ["S.sim200_end"]})
    out.append({"text": f"Without its single biggest event cluster, profit would be ${s['S.profit_wo_top']['value']:,.2f}.", "ids": ["S.profit_wo_top"]})
    for f in report["flags"]:
        out.append({"text": f, "ids": []})
    out.append({"text": BANNER, "ids": []})
    return out


def split_cited_sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping each '[S.ids]' group with the sentence it follows.

    Handles "... positions. [S.profit]" (ids after the full stop) and "... positions [S.profit]."
    and never splits inside numbers like $19,780.35.
    """
    parts = re.split(r"(?<=[.!?])\s+(?!\[)|(?<=\])\s+(?=[^\[\s])", text.strip())
    return [p for p in (x.strip() for x in parts) if p]


def write_report(report: dict, llm: LLM | None = None, audit: AuditLog | None = None) -> dict:
    sentences = template_report(report)
    result = {"method": "template", "sentences": sentences, "rejected": None}
    if llm is None or not llm.available:
        return result
    facts = {k: {kk: vv for kk, vv in v.items() if kk in ("label", "value", "lo", "hi", "unit")} for k, v in report["stats"].items()}
    facts["verdict"] = report["verdict"]
    facts["flags"] = report["flags"]
    text = llm.complete("report", REPORT_PROMPT.replace("{facts}", json.dumps(facts, default=str)), want_json=False, timeout=45)
    if not isinstance(text, str):
        return result
    bad = number_guard(text, allowed_numbers(report))
    if bad:
        (audit or llm.audit).log("number_guard_reject", wallet=report["wallet"], offending=bad[:20])
        result["rejected"] = bad
        return result
    sents = []
    for p in split_cited_sentences(text):
        ids = re.findall(r"\[([^\]]+)\]", p)
        flat = [i.strip() for group in ids for i in group.split(",") if i.strip().startswith("S.")]
        sents.append({"text": re.sub(r"\s*\[[^\]]*\]", "", p).strip(), "ids": flat})
    return {"method": "llm", "sentences": sents, "rejected": None}
