"""v0.6.0: coarse-grouping note, single-copy luck, settle-next and the account history in Paper trading."""
import pandas as pd
import pytest

from ctdd import killswitch
from ctdd.adapter import coarse_groups
from ctdd.audit import AuditLog
from ctdd.service import LIVE_WALLETS, Service
from tests.test_combined import ScriptedLLM


def test_coarse_grouping_note_fires_only_for_many_separate_events():
    rows = [{"id": f"p{i}", "cluster": "big", "event_slug": f"match-{i}"} for i in range(12)]
    rows += [{"id": f"q{i}", "cluster": "election", "event_slug": "us-election"} for i in range(30)]
    out = coarse_groups(pd.DataFrame(rows), {"big": "LoL: A vs B"})
    assert out["n_events"] == 12 and out["n_positions"] == 12 and "LoL: A vs B" in out["text"]
    assert coarse_groups(pd.DataFrame(rows[12:]), {}) is None          # one real event with many markets: fine


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    d = tmp_path_factory.mktemp("logs")
    killswitch.PATH = d / "KILL_SWITCH"
    return Service(audit=AuditLog(d / "audit.jsonl"), llm=ScriptedLLM([{"final": "x"}]))


def test_synthetic_cards_never_get_the_coarse_note_and_carry_single_copy_luck(svc):
    c = svc.card("0xDEMO-one-election")
    assert not any(f["code"] == "COARSE_GROUPING" for f in c["flags"]) and c["luck"]["coarse_grouping"] is False
    assert 0 < c["luck"]["q_single"] <= 1


def test_settle_next_settles_one_copy_at_a_time_and_records_history(svc):
    killswitch.PATH.unlink(missing_ok=True)
    svc.live = None
    live = svc.ensure_live()
    assert "0xDEMO-one-election" in LIVE_WALLETS
    for _ in range(3):                                   # three copies of the skilled trader
        p = live.next_bet("0xDEMO-messy-skilled")
        r = live.decide(p["proposal_id"], "approve", 5, "test" if p["action"] != "copy" else None)
        assert r["status"] == "executed", r
    open_before = [x for x in r["state"]["ledger"] if x["status"] == "open"]
    first = min(x["resolve_ts"] for x in open_before)
    out = live.settle_next()
    assert all(x["resolve_ts"] == first for x in out["settled"]) and out["settled"]
    st = out["state"]
    assert len([x for x in st["ledger"] if x["status"] == "open"]) == len(open_before) - len(out["settled"])
    events = [h["event"] for h in st["history"]]
    assert events[0] == "start" and events.count("copied") == 3 and "settled" in events
    assert all(a["ts"] <= b["ts"] for a, b in zip(st["history"], st["history"][1:]))


def test_demo_traders_never_wait_for_gemini_grouping(tmp_path):
    """With a real Gemini key, grouping can take up to 75 s per trader; demo traders must not wait for it."""
    import time

    class SlowLLM:
        available, model = True, "slow-stub"

        def __init__(self, audit):
            self.audit, self.calls = audit, []

        def complete(self, job, prompt, want_json=True, timeout=60):
            self.calls.append(job)
            if job == "cluster":
                time.sleep(30)
            return None

    audit = AuditLog(tmp_path / "audit.jsonl")
    svc = Service(audit=audit, llm=SlowLLM(audit))
    t0 = time.time()
    rows = svc.wallets()
    assert len(rows) == 5 and time.time() - t0 < 60 and "cluster" not in svc.llm.calls
