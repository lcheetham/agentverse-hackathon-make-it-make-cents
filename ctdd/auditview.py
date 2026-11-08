"""Plain-English view of the audit log, for the screen.

The log file itself is untouched and complete (every field, every hash). This module only adds two
display fields to each entry it returns: `kind` (which group the event belongs to, for filtering) and
`summary` (one sentence a non-specialist can read). Raw fields stay in the entry for the
"show technical details" view.
"""
from __future__ import annotations

KINDS = {
    "trading": "Paper trading",
    "safety": "Safety controls",
    "agent": "Agent",
    "analysis": "Analysis",
    "data": "Data pulls",
    "model": "Model calls",
    "other": "Other",
}

EVENT_KIND = {
    "copy_proposed": "trading", "copy_rejected_by_human": "trading", "paper_copy_executed": "trading",
    "paper_settled": "trading", "live_reset": "trading",
    "control_check": "safety", "copy_blocked": "safety", "kill_switch": "safety", "drawdown_stop": "safety",
    "drawdown_resumed": "safety", "input_rejected": "safety", "injection_withheld": "safety",
    "agent_question": "agent", "agent_tool_call": "agent", "agent_final": "agent", "agent_fallback": "agent",
    "verdict": "analysis", "real_wallet_error": "analysis", "eval_run": "analysis", "walkforward_run": "analysis",
    "data_pull": "data", "leaderboard_refresh": "data",
    "llm_call": "model", "llm_error": "model", "llm_bad_json": "model", "llm_cluster_batches": "model",
    "llm_cluster_budget_hit": "model", "llm_cluster_capped": "model",
}

# What Live mode shows next to the action: the trading and safety story, nothing else.
LIVE_KINDS = {"trading", "safety"}

TOOL_WORDS = {
    "list_demo_wallets": "listed the demo wallets",
    "analyse_wallet": "analysed {wallet}",
    "compare_wallets": "compared {wallet_a} and {wallet_b}",
    "preview_copy": "checked a £{stake_gbp} copy of {wallet} against the risk controls (nothing booked)",
    "kill_switch_status": "checked the kill switch",
    "stop_all_copying": "turned the kill switch on",
}


def short(addr) -> str:
    a = str(addr or "?")
    return a if a.startswith("0xDEMO") or len(a) <= 14 else f"{a[:6]}…{a[-4:]}"


def _money(x) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "£?"
    return f"{'−' if x < 0 else ''}£{abs(x):,.2f}"


def _cents(x) -> str:
    try:
        return f"{round(float(x) * 100)}c"
    except (TypeError, ValueError):
        return "?"


def summarise(e: dict) -> str:
    ev, g = e.get("event", ""), e.get
    t = short(g("trader") or g("wallet"))
    if ev == "copy_proposed":
        act = str(g("action") or "").lower()
        if act == "copy":
            return f"Rule-based proposer suggested copying {t}'s bet with {_money(g('stake'))}. Waiting for a human decision."
        if act == "hold":
            return f"Rule-based proposer was unsure about {t}'s bet and asked a human."
        return f"Rule-based proposer suggested skipping {t}'s bet ({act or 'no action'})."
    if ev == "control_check":
        if g("allowed"):
            return f"All risk controls passed for a {_money(g('stake'))} copy of {t}."
        blocks = g("blocks") or []
        first = str(blocks[0]).split(":")[0] if blocks else "a control"
        more = f" and {len(blocks) - 1} more" if len(blocks) > 1 else ""
        return f"Risk controls refused a {_money(g('stake'))} copy of {t}: {first}{more}."
    if ev == "copy_blocked":
        return f"Copy of {t} blocked. Nothing was placed."
    if ev == "paper_copy_executed":
        who = g("approved_by") or "a human"
        ovr = f" Override reason given: “{str(g('override_reason'))[:80]}”." if g("override_reason") else ""
        return f"Paper copy placed: {_money(g('stake'))} on “{str(g('title') or '?')[:70]}” at {_cents(g('price'))}, approved by {who}.{ovr}"
    if ev == "copy_rejected_by_human":
        return f"A human rejected the proposed copy of {t}. No trade."
    if ev == "paper_settled":
        pnl = g("pnl")
        res = "won" if (pnl or 0) > 0 else "lost"
        return f"Paper copy settled: “{str(g('title') or '?')[:70]}” {res}, {('+' if (pnl or 0) >= 0 else '')}{_money(pnl)}."
    if ev == "live_reset":
        return "Paper trading session reset by a human."
    if ev == "kill_switch":
        if g("on"):
            why = f" ({g('reason')})" if g("reason") else ""
            return f"Kill switch turned ON by {g('by') or '?'}{why}. All copying stopped."
        return f"Kill switch turned off by {g('by') or '?'}. Copying allowed again."
    if ev == "drawdown_stop":
        n = len(g("paused") or [])
        return f"Drawdown stop: the paper account fell past the drawdown limit from its high, so copying of {n} trader{'s' if n != 1 else ''} was paused."
    if ev == "drawdown_resumed":
        return f"A human re-enabled copying of {t} after a drawdown stop."
    if ev == "input_rejected":
        return f"Rejected bad input: {g('reason') or 'invalid value'}."
    if ev == "injection_withheld":
        n = len(g("markets") or [])
        return f"{n} market title{'s' if n != 1 else ''} looked like instructions to the AI, so the model never saw {'them' if n != 1 else 'it'}."
    if ev == "agent_question":
        return f"Someone asked the agent: “{str(g('question') or '')[:100]}”"
    if ev == "agent_tool_call":
        args = {k: (short(v) if "wallet" in k else v) for k, v in (g("args") or {}).items()}
        try:
            words = TOOL_WORDS.get(g("tool"), "ran {tool}").format(tool=g("tool"), **args)
        except (KeyError, IndexError, ValueError):
            words = f"ran {g('tool')}"
        return f"Agent {words}."
    if ev == "agent_final":
        if g("accepted"):
            return "Agent's answer passed the checks and was shown."
        why = []
        if g("unknown_numbers"):
            why.append("it quoted numbers no tool returned")
        if g("banned_phrases"):
            why.append("it used forecasting or advice wording")
        if g("reason"):
            why.append(str(g("reason")))
        return f"Agent's answer was rejected because {' and '.join(why) or 'it failed a check'}; it was asked to rewrite."
    if ev == "agent_fallback":
        return "Agent's answers kept failing the checks, so a template answer built from the tool results was shown."
    if ev == "verdict":
        kind = "demo" if g("synthetic") else "real"
        return f"Verdict for {kind} wallet {t}: {g('verdict')}."
    if ev == "real_wallet_error":
        return f"Could not analyse {t}: {str(g('error') or '')[:100]}"
    if ev == "data_pull":
        url = str(g("url") or "")
        what = ("leaderboard" if "leaderboard" in url else "trade history" if "activity" in url or "trades" in url
                else "positions" if "positions" in url else "market details" if "gamma" in url
                else "price history" if "prices-history" in url else "data")
        return f"Downloaded {what} from Polymarket's public API."
    if ev == "leaderboard_refresh":
        return (f"Leaderboard refreshed from Polymarket ({g('n')} traders)." if g("ok")
                else f"Leaderboard refresh failed ({str(g('error') or '?')[:80]}); kept the last saved copy.")
    if ev == "llm_call":
        return f"Gemini was asked to do one job: {g('job')}."
    if ev in ("llm_error", "llm_bad_json"):
        return f"Gemini call for '{g('job')}' failed; the app fell back to rules."
    if ev == "llm_cluster_batches":
        ok, total = g("ok") or 0, g("total") or 0
        if not ok:
            return "Gemini didn't group the related bets this time, so the rule-based grouping was used."
        return f"Gemini grouped related bets in {ok} of {total} batches (checked by code; any rejected batch used rules)."
    if ev.startswith("llm_cluster"):
        return "Gemini's bet-grouping hit its size limit; the remaining bets were grouped by rules."
    if ev in ("eval_run", "walkforward_run"):
        return "Evaluation run recorded."
    return ev.replace("_", " ").capitalize() + "."


def annotate(e: dict) -> dict:
    kind = EVENT_KIND.get(e.get("event", ""), "other")
    try:
        text = summarise(e)
    except Exception:                       # never let a display helper hide a log line
        text = str(e.get("event", "event")).replace("_", " ")
    return {**e, "kind": kind, "kind_label": KINDS[kind], "summary": text}
