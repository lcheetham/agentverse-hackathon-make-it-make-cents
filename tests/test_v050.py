"""v0.5.0: live leaderboard snapshots, plain-English activity record, agent wallet comparison, eval point estimate."""
import json

import pytest

from ctdd import killswitch
from ctdd.api import create_app
from ctdd.audit import AuditLog
from ctdd.auditview import annotate, summarise
from ctdd.leaderboard import LiveLeaderboard, parse
from ctdd.service import Service
from tests.test_combined import ScriptedLLM

A = "0x" + "a" * 40
B = "0x" + "b" * 40


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def board(tmp_path, results):
    """A leaderboard whose fetch plays back `results` (a list of rows, or an exception to raise)."""
    it = iter(results)

    def fetch():
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    clock = Clock()
    return LiveLeaderboard(store=tmp_path / "lb", fetch=fetch, clock=clock), clock


def test_parse_reads_v2_rows_and_keeps_top_10():
    rows = parse({"data": [{"user_id": A.upper().replace("0X", "0x"), "user_name": "alice", "pnl": "1234.5", "vol": 9}]
                  + [{"user_id": "not-an-address"}] + [{"proxyWallet": "0x" + f"{i:040x}", "pnl": i} for i in range(20)]})
    assert len(rows) == 10 and rows[0] == {"address": A, "name": "alice", "profit": 1234.5, "volume": 9.0, "rank": 1}


def test_failed_refresh_never_overwrites_a_good_list(tmp_path):
    lb, clock = board(tmp_path, [[{"address": A, "rank": 1}], ConnectionError("wifi down"), []])
    assert lb.get()["rows"][0]["address"] == A and lb.get()["source"] == "live"
    clock.t += 31 * 60                                   # stale: next get() tries again, and fails
    snap = lb.get()
    assert snap["rows"][0]["address"] == A and snap["stale"] and "Could not reach" in snap["note"]
    clock.t += 60
    assert lb.refresh(force=True)["ok"] is False         # empty answer counts as a failure too
    assert lb.get()["rows"][0]["address"] == A


def test_refresh_keeps_previous_copy_and_limits_button_spam(tmp_path):
    lb, clock = board(tmp_path, [[{"address": A, "rank": 1}], [{"address": B, "rank": 1}]])
    lb.refresh()
    clock.t += 5
    assert "Try again" in lb.refresh(force=True)["note"]  # within 30 s of the last attempt
    clock.t += 60
    assert lb.refresh(force=True)["ok"]
    prev = json.loads((tmp_path / "lb" / "previous.json").read_text())
    assert lb.get()["rows"][0]["address"] == B and prev["rows"][0]["address"] == A


def test_bundled_snapshot_when_nothing_was_ever_fetched(tmp_path):
    lb, _ = board(tmp_path, [ConnectionError("offline")])
    snap = lb.get()
    assert snap["source"] == "bundled" and len(snap["rows"]) == 10 and snap["stale"]


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    d = tmp_path_factory.mktemp("logs")
    killswitch.PATH = d / "KILL_SWITCH"
    return Service(audit=AuditLog(d / "audit.jsonl"), llm=ScriptedLLM([{"final": "x"}]))


def test_leaderboard_endpoint_marks_only_already_analysed_wallets(svc, tmp_path):
    lb, _ = board(tmp_path, [[{"address": A, "rank": 1}, {"address": "0xDEMO-perfect-25-0", "rank": 2}]])
    c = create_app(svc, board=lb).test_client()
    svc.card("0xDEMO-perfect-25-0")
    rows = c.get("/api/leaderboard").get_json()["rows"]
    assert rows[0]["verdict"] is None and rows[1]["verdict"]["label"] == "Probably luck"


def test_activity_record_is_plain_english_and_filterable(svc, tmp_path):
    lb, _ = board(tmp_path, [[]])
    c = create_app(svc, board=lb).test_client()
    killswitch.PATH.unlink(missing_ok=True)
    c.post("/api/killswitch", json={"on": True, "reason": "test"})
    c.post("/api/killswitch", json={"on": False})
    live = c.get("/api/audit?kind=live&limit=50").get_json()
    assert live and all(e["kind"] in ("trading", "safety") for e in live)
    assert any(e["summary"].startswith("Kill switch turned ON by human") for e in live)
    assert c.get("/api/audit?kind=nonsense").status_code == 400
    raw = svc.audit.tail(1)[0]
    assert "prev" in raw and "summary" not in raw           # the file itself is untouched


def test_summaries_never_crash_on_odd_entries():
    for e in [{}, {"event": "control_check", "allowed": False, "blocks": ["Per-trade cap: too big"], "stake": 30, "trader": A},
              {"event": "agent_tool_call", "tool": "preview_copy", "args": {"wallet": A}}, {"event": "brand_new_event"}]:
        assert isinstance(annotate(e)["summary"], str)
    assert "Per-trade cap" in summarise({"event": "control_check", "allowed": False, "blocks": ["Per-trade cap: too big"], "stake": 30})


def test_agent_compares_two_wallets_with_overlap(svc):
    from ctdd.chat import ChatAgent
    svc.llm = ScriptedLLM([{"tool": "compare_wallets", "args": {"wallet_a": "0xDEMO-messy-skilled", "wallet_b": "0xDEMO-fast-mover"}},
                           {"final": "Skilled and copyable for one, Skilled but not copyable for the other; they shared 0 markets."}])
    r = ChatAgent(svc).ask("Compare 0xDEMO-messy-skilled and 0xDEMO-fast-mover")
    assert not r["fallback"] and r["tool_calls"][0]["tool"] == "compare_wallets"
    from ctdd.chat import market_overlap
    a = {"positions": [{"market_id": "m1", "token": "YES"}, {"market_id": "m2", "token": "NO"}]}
    b = {"positions": [{"market_id": "m1", "token": "NO"}, {"market_id": "m3", "token": "YES"}]}
    assert market_overlap(a, b)["shared_markets"] == 1 and market_overlap(a, b)["shared_opposite_side"] == 1


def test_walkforward_difference_adds_up():
    from ctdd.evalview import walkforward
    wf = walkforward()
    agent = wf["agent"]["return"] or 0.0
    assert abs(wf["diff"]["mean"] - (agent - wf["top10"]["return"])) < 1e-12


def test_preview_copy_analyses_the_wallet_itself(svc):
    from ctdd.chat import ChatAgent
    svc.llm = ScriptedLLM([{"tool": "preview_copy", "args": {"wallet": "0xDEMO-perfect-25-0", "stake_gbp": 30}},
                           {"final": "No: the per-trade cap and the verdict gate block it. The verdict was Probably luck."}])
    r = ChatAgent(svc).ask("I want to put £30 on 0xDEMO-perfect-25-0. Can I?")
    assert r["tool_calls"] == [{"tool": "preview_copy", "args": {"wallet": "0xDEMO-perfect-25-0", "stake_gbp": 30}, "ok": True}]
    assert not r["fallback"]


def test_default_polymarket_names_count_as_no_name():
    rows = parse([{"user_id": A, "user_name": A + "-1789545517033"}, {"user_id": B, "user_name": "alice"}])
    assert rows[0]["name"] is None and rows[1]["name"] == "alice"
