"""Tests for the combined app: API shapes, live replay + controls, kill switch, chat agent guards."""
import json

import pytest

from ctdd import killswitch
from ctdd.api import create_app
from ctdd.audit import AuditLog
from ctdd.service import Service


class ScriptedLLM:
    """Stands in for Gemini: plays back fixed agent replies; returns nothing for other jobs (template fallbacks)."""
    available, model = True, "scripted-test"

    def __init__(self, replies, audit=None):
        self.replies, self.i, self.audit = replies, 0, audit or AuditLog("/tmp/scripted_llm_audit.jsonl")

    def complete(self, job, prompt, want_json=True, timeout=60):
        if job != "agent":
            return None
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    d = tmp_path_factory.mktemp("logs")
    killswitch.PATH = d / "KILL_SWITCH"
    return Service(audit=AuditLog(d / "audit.jsonl"), llm=ScriptedLLM([{"final": "x"}]))


@pytest.fixture()
def client(svc):
    killswitch.PATH.unlink(missing_ok=True)
    svc.live = None
    return create_app(svc).test_client()


def test_report_card_shape_and_hook_verdict(client):
    j = client.get("/api/wallets/0xDEMO-perfect-25-0/report?delay=3600").get_json()
    assert j["verdict"]["label"] == "Probably luck" and j["summary"]["record"] == "25–0"
    for k in ("edge", "luck", "delay_curve", "facts", "report", "positions", "what_would_change", "input_checks", "sim_200"):
        assert k in j
    assert [r["n"] for r in j["luck"]["by_n"]] == [100, 1000, 10000]
    ids = {p["id"] for p in j["positions"]}
    for s in j["report"]["sentences"]:                     # every citation points at something real
        assert set(s["fact_ids"]) <= set(j["facts"]) and set(s["position_ids"]) <= ids
    assert "bottom_line" not in j and "posterior" not in json.dumps(j)


def test_bad_inputs_rejected(client):
    assert client.get("/api/wallets/0x123/report").status_code == 400
    assert client.get("/api/wallets/0xDEMO-perfect-25-0/report?delay=7").status_code == 400
    assert client.post("/api/live/decide", json={"proposal_id": ["x"], "decision": "approve"}).status_code == 400


def test_live_block_then_execute(client):
    p = client.post("/api/live/next", json={"wallet": "0xDEMO-perfect-25-0"}).get_json()
    r = client.post("/api/live/decide", json={"proposal_id": p["proposal_id"], "decision": "approve", "stake": 50}).get_json()
    failed = {c["control"] for c in r["checks"] if not c["passed"]}
    assert r["status"] == "blocked" and {"per_trade_cap", "verdict_gate"} <= failed
    client.post("/api/live/decide", json={"proposal_id": p["proposal_id"], "decision": "reject"})
    p = client.post("/api/live/next", json={"wallet": "0xDEMO-messy-skilled"}).get_json()
    r = client.post("/api/live/decide", json={"proposal_id": p["proposal_id"], "decision": "approve", "stake": p["stake"]}).get_json()
    assert r["status"] == "executed"


def test_kill_switch_blocks_and_only_human_turns_it_off(client):
    assert client.post("/api/killswitch", json={"on": True}).get_json()["kill_switch"]["on"]
    p = client.post("/api/live/next", json={"wallet": "0xDEMO-messy-skilled"}).get_json()
    assert not next(c for c in p["precheck"] if c["control"] == "kill_switch")["passed"]
    with pytest.raises(PermissionError):
        killswitch.turn_off("agent")
    assert not client.post("/api/killswitch", json={"on": False}).get_json()["kill_switch"]["on"]


def test_audit_chain_verifies(client):
    client.get("/api/wallets")
    assert client.get("/api/audit/verify").get_json()["ok"]
    assert all("seq" in e for e in client.get("/api/audit?limit=5").get_json())


def test_evaluation_has_errors_and_real_walkforward(client):
    e = client.get("/api/evaluation").get_json()
    assert e["planted"]["errors"] and e["walkforward"]["real"]


def _ask(svc, replies, q):
    from ctdd.chat import ChatAgent
    svc.llm = ScriptedLLM(replies)
    return ChatAgent(svc).ask(q)


def test_agent_grounded_answer(svc):
    r = _ask(svc, [{"tool": "analyse_wallet", "args": {"wallet": "0xDEMO-perfect-25-0"}},
                   {"final": "The verdict was Probably luck: a 25–0 record at near-certain prices is common among no-skill traders."}],
             "Is 0xDEMO-perfect-25-0 skilled?")
    assert not r["fallback"] and r["tool_calls"][0]["tool"] == "analyse_wallet"


def test_agent_stake_question_forces_risk_check(svc):
    r = _ask(svc, [{"tool": "analyse_wallet", "args": {"wallet": "0xDEMO-perfect-25-0"}},
                   {"final": "It was Probably luck."},
                   {"tool": "preview_copy", "args": {"wallet": "0xDEMO-perfect-25-0", "stake_gbp": 30}},
                   {"final": "No: the per-trade cap and the verdict gate both block it."}],
             "Can I put £30 on 0xDEMO-perfect-25-0?")
    assert [c["tool"] for c in r["tool_calls"]] == ["analyse_wallet", "preview_copy"] and "cap" in r["answer"]


def test_agent_invented_numbers_fall_back_to_template(svc):
    r = _ask(svc, [{"tool": "analyse_wallet", "args": {"wallet": "0xDEMO-perfect-25-0"}},
                   {"final": "They will make 37% next month, you should copy them."}], "Worth copying?")
    assert r["fallback"] and "Probably luck" in r["answer"]


def test_agent_can_stop_but_has_no_resume_tool(svc):
    from ctdd.chat import ChatAgent
    killswitch.PATH.unlink(missing_ok=True)
    _ask(svc, [{"tool": "stop_all_copying", "args": {"reason": "data looks off"}}, {"final": "I turned the kill switch on."}], "stop everything")
    assert killswitch.status()["on"] and not any("resume" in t or "off" in t for t in ChatAgent.TOOLS)
    killswitch.PATH.unlink(missing_ok=True)
