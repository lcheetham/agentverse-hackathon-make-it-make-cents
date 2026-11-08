"""Text jobs: correlated-bet clustering, categorisation, near-certainty flags.

Each job has a deterministic fallback; the LLM (if configured) only refines clustering.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait

import pandas as pd

from .llm import LLM
from .prompts import CLUSTER_PROMPT

_STOP = {
    "will", "the", "a", "an", "of", "on", "in", "by", "to", "be", "vs", "vs.", "and", "or", "for", "at", "is", "any",
    "yes", "no", "over", "under", "o/u", "spread", "total", "moneyline", "who", "what", "which", "when", "how",
    "fc", "united", "city", "awards", "council", "governor", "race", "seat", "party", "district", "county",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "et", "pm", "am", "up", "down",
    "round", "next", "first", "time", "winner", "points", "close", "above", "below", "price", "daily", "game", "match",
}

_ENTITY_RE = re.compile(r"(?:[A-Z][\w'’\.]*)(?:\s+[A-Z][\w'’\.]*)*")


def entities(title: str) -> set[str]:
    out = set()
    for m in _ENTITY_RE.findall(title or ""):
        words = [w.strip(".'’").removesuffix("'s").removesuffix("’s") for w in m.split()]
        words = [w for w in words if w and w.lower() not in _STOP and not w.isdigit()]
        if words:
            ent = " ".join(words)
            if len(ent) >= 3:
                out.add(ent.lower())
    return out


class _UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def heuristic_clusters(markets: pd.DataFrame, window_s: float = 3 * 86_400) -> dict:
    """Union markets that share an event slug, or share a named entity and resolve within `window_s`."""
    ids = list(markets.index)
    uf = _UF(ids)
    by_slug: dict = {}
    for cid, slug in zip(ids, markets["event_slug"].fillna("")):
        if slug:
            by_slug.setdefault(slug, []).append(cid)
    for group in by_slug.values():
        for other in group[1:]:
            uf.union(group[0], other)

    ents = {cid: entities(t) for cid, t in zip(ids, markets["title"].fillna(""))}
    count: dict = {}
    for es in ents.values():
        for e in es:
            count[e] = count.get(e, 0) + 1
    generic = {e for e, c in count.items() if c > 8 and c > 0.25 * len(ids)}
    rts = markets["resolve_ts"].astype(float).fillna(0.0).to_dict()
    by_ent: dict = {}
    for cid, es in ents.items():
        for e in es - generic:
            by_ent.setdefault(e, []).append(cid)
    for group in by_ent.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda c: rts[c])
        for a, b in zip(group, group[1:]):
            if abs(rts[a] - rts[b]) <= window_s:
                uf.union(a, b)
    return {cid: f"cl::{uf.find(cid)}" for cid in ids}


def llm_clusters(markets: pd.DataFrame, llm: LLM, batch: int = 60, max_markets: int = 600,
                 workers: int = 6, budget_s: float = 75.0) -> tuple[dict, dict] | None:
    """Ask the LLM to merge markets that hinge on the same outcome. Returns (clusters, directions) or None."""
    if not llm.available:
        return None
    ids = list(markets.index)
    uf = _UF(ids)
    directions: dict = {}
    base = heuristic_clusters(markets)  # the LLM refines on top of slug/entity links; it never splits an event slug
    for root_ids in _group_by(base).values():
        for a in root_ids[1:]:
            uf.union(root_ids[0], a)
    # Large wallets: only the most recent `max_markets` go to the LLM (others keep heuristic links);
    # batches run in parallel so a 600-market wallet takes about one batch's latency.
    ordered = markets.assign(_r=markets["resolve_ts"].astype(float).fillna(0)).sort_values("_r")
    if len(ordered) > max_markets:
        llm.audit.log("llm_cluster_capped", markets=len(ordered), sent=max_markets)
        ordered = ordered.tail(max_markets)
    chunks = [ordered.iloc[s:s + batch] for s in range(0, len(ordered), batch)]

    def ask(chunk):
        listing = "\n".join(json.dumps({"id": cid, "title": r.title, "rules": str(r.rules)[:300],
                                        "resolves": pd.Timestamp(float(r._r), unit="s").strftime("%Y-%m-%d")})
                            for cid, r in chunk.iterrows())
        prompt = CLUSTER_PROMPT.replace("{markets}", listing)
        out = llm.complete("cluster", prompt, timeout=45)
        if not _ok(out) and time.time() < deadline - 30:  # one retry if time allows
            out = llm.complete("cluster", prompt, timeout=30)
        return out

    # Hard time budget: batches not answered by the deadline keep their heuristic links.
    deadline = time.time() + budget_s
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(ask, ch) for ch in chunks]
    done, _ = wait(futures, timeout=budget_s)
    pool.shutdown(wait=False, cancel_futures=True)
    outs = [f.result() if f in done else None for f in futures]
    if len(done) < len(futures):
        llm.audit.log("llm_cluster_budget_hit", budget_s=budget_s, answered=len(done), total=len(futures))
    good = sum(_ok(o) for o in outs)
    if good == 0:
        return None
    llm.audit.log("llm_cluster_batches", ok=good, total=len(chunks))
    for chunk, out in zip(chunks, outs):
        if not _ok(out):
            continue
        valid = set(chunk.index)
        for cl in out["clusters"]:
            members = [i for i in cl.get("ids", []) if i in valid]
            for a in members[1:]:
                uf.union(members[0], a)
            for k, v in (cl.get("direction") or {}).items():
                if k in valid and v in (1, -1):
                    directions[k] = int(v)
    return {cid: f"cl::{uf.find(cid)}" for cid in ids}, directions


def _ok(out) -> bool:
    return isinstance(out, dict) and isinstance(out.get("clusters"), list)


def _group_by(mapping: dict) -> dict:
    g: dict = {}
    for k, v in mapping.items():
        g.setdefault(v, []).append(k)
    return g


def cluster_markets(markets: pd.DataFrame, llm: LLM | None = None) -> tuple[dict, dict, str]:
    """(clusters, directions, method)."""
    if llm is not None:
        res = llm_clusters(markets, llm)
        if res is not None:
            return res[0], res[1], "llm"
    return heuristic_clusters(markets), {}, "heuristic"


_CATS = {
    "sports": r"\b(fc|united|nba|nfl|nhl|mlb|ufc|epl|vs\.?|spread|o/u|match|game|cup|league|open|grand prix|beat|win the series)\b",
    "crypto": r"\b(bitcoin|btc|eth|ethereum|solana|sol|xrp|doge|crypto|coin|token|close above|close below)\b|kestrium|zolcoin|vantra|orbix|pellet|quorra|lumex|tavik",
    "politics": r"\b(election|elected|president|governor|senate|house|mayor|council|parliament|prime minister|vote|poll|concede|party|primary|nominee)\b",
    "economics": r"\b(fed|rates?|inflation|cpi|gdp|unemployment|jobs report|recession|tariff)\b",
    "weather": r"\b(temperature|rain|snow|hurricane|weather|°c|°f)\b",
}


def categorise(title: str) -> str:
    t = (title or "").lower()
    for cat, pat in _CATS.items():
        if re.search(pat, t):
            return cat
    return "other"


def cluster_agreement(pred: dict, truth: dict) -> float:
    """Pairwise agreement (Rand index) between predicted clusters and true stories, over ids in `truth`."""
    ids = [i for i in truth if i in pred]
    agree = total = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            agree += (pred[a] == pred[b]) == (truth[a] == truth[b])
            total += 1
    return agree / total if total else float("nan")
