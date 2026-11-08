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


_VS_RE = re.compile(r"^(?P<a>.+?)\s+(?:vs\.?|v\.?|versus|beat)\s+(?P<b>.+?)"
                    r"(?:\s*[\(\[\-\u2013\u2014\?:,]|\s+on\s|\s+by\s|\s+in\s|$)", re.I)


def _side(text: str) -> str:
    words = re.sub(r"[^\w\s'\u2019]", " ", text.lower()).split()
    words = [w.strip("'\u2019") for w in words if w.strip("'\u2019") and w not in _STOP and w != "the"]
    return " ".join(words)


def matchup(title: str) -> frozenset | None:
    """The two sides of a head-to-head market ("A vs B", "Will A beat B?"), or None.

    Engine v2: a team is not an event, a match is. "LoL: T1 vs Gen.G (BO3) - Game 2 Winner" and
    "T1 vs Gen.G: total maps O/U 2.5" are the same match; "T1 vs DRX" the next day is a different one."""
    t = (title or "").strip()
    t = re.sub(r"^\s*will\s+", "", t, flags=re.I)
    head, sep, rest = t.partition(":")
    if sep and len(head) <= 25 and re.search(r"\s(?:vs\.?|v\.?|versus|beat)\s", rest, re.I):
        t = rest                                          # drop a short "LoL:" / "Dota 2:" style prefix
    m = _VS_RE.match(t.strip())
    if not m:
        return None
    a, b = _side(m.group("a")), _side(m.group("b"))
    if not a or not b or a == b or len(a.split()) > 6 or len(b.split()) > 6:
        return None
    return frozenset((a, b))


def heuristic_clusters(markets: pd.DataFrame, window_s: float = 3 * 86_400, bridge_s: float = 86_400) -> dict:
    """Group markets that hinge on the same outcome.

    v2 (engine 2026-11-08): links can no longer chain different matches together.
      * Same event slug -> linked, except that two different head-to-head matches are never joined this way.
      * Head-to-head markets link only to markets on the SAME pair of sides resolving within `bridge_s` (a
        rematch days later is a different event).
      * Other markets link by a shared named entity within `window_s`, as in v1, except that team names
        (the sides of any head-to-head market) no longer link them to each other.
      * A non-head-to-head market about a team ("Will A win by 2+ goals?") joins at most ONE match: the
        closest in time involving that team, within `bridge_s`.
    v1 linked any two markets sharing a name within 3 days, and the links chained: across a month of
    e-sports one team or game title could pull dozens of separate matches into one "event"."""
    ids = list(markets.index)
    uf = _UF(ids)
    titles = dict(zip(ids, markets["title"].fillna("")))
    pair = {cid: matchup(t) for cid, t in titles.items()}
    rts = markets["resolve_ts"].astype(float).fillna(0.0).to_dict()

    by_slug: dict = {}
    for cid, slug in zip(ids, markets["event_slug"].fillna("")):
        if slug:
            by_slug.setdefault(slug, []).append(cid)
    for group in by_slug.values():
        pairs = {pair[c] for c in group if pair[c] is not None}
        if len(pairs) <= 1:
            for other in group[1:]:
                uf.union(group[0], other)
        else:                                             # a slug spanning several matches: one group per match
            for pr in pairs:
                members = [c for c in group if pair[c] == pr]
                for other in members[1:]:
                    uf.union(members[0], other)

    by_pair: dict = {}
    for cid in ids:
        if pair[cid] is not None:
            by_pair.setdefault(pair[cid], []).append(cid)
    for group in by_pair.values():
        group = sorted(group, key=lambda c: rts[c])
        for a, b in zip(group, group[1:]):
            if abs(rts[a] - rts[b]) <= bridge_s:          # one match's markets settle within hours; a rematch is a new event
                uf.union(a, b)

    team_ents = set().union(*(entities(" ".join(pr).title()) | {*pr} for pr in by_pair)) if by_pair else set()
    plain = [cid for cid in ids if pair[cid] is None]
    ents = {cid: entities(titles[cid]) for cid in plain}
    count: dict = {}
    for es in ents.values():
        for e in es:
            count[e] = count.get(e, 0) + 1
    generic = {e for e, c in count.items() if c > 8 and c > 0.25 * len(ids)}
    by_ent: dict = {}
    for cid, es in ents.items():
        for e in es - generic - team_ents:
            by_ent.setdefault(e, []).append(cid)
    for group in by_ent.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda c: rts[c])
        for a, b in zip(group, group[1:]):
            if abs(rts[a] - rts[b]) <= window_s:
                uf.union(a, b)

    # Team-specific side markets join the single closest match involving that team.
    side_of = {}
    for pr, group in by_pair.items():
        for side in pr:
            for e in entities(side.title()) | {side}:
                side_of.setdefault(e, []).extend(group)
    for cid in plain:
        cands = {m for e in ents[cid] & team_ents for m in side_of.get(e, [])}
        cands = [m for m in cands if abs(rts[m] - rts[cid]) <= bridge_s]
        if cands:
            uf.union(cid, min(cands, key=lambda m: (abs(rts[m] - rts[cid]), str(m))))
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
    pair = {cid: matchup(t) for cid, t in zip(ids, markets["title"].fillna(""))}
    rejected = 0
    for chunk, out in zip(chunks, outs):
        if not _ok(out):
            continue
        valid = set(chunk.index)
        for cl in out["clusters"]:
            members = [i for i in cl.get("ids", []) if i in valid]
            # Engine v2: the model may group, but code refuses any merge that would put two different
            # head-to-head matches into one group (the model never splits; this stops it over-merging).
            roots = {uf.find(i) for i in members}
            pairs = {pr for c in ids if uf.find(c) in roots for pr in [pair.get(c)] if pr is not None}
            if len(pairs) > 1:
                rejected += 1
                continue
            for a in members[1:]:
                uf.union(members[0], a)
            for k, v in (cl.get("direction") or {}).items():
                if k in valid and v in (1, -1):
                    directions[k] = int(v)
    if rejected:
        llm.audit.log("llm_cluster_merges_refused", refused=rejected, reason="would join different matches")
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
