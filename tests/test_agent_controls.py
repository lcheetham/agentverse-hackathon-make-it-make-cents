import pandas as pd

from ctdd.agent.text_jobs import categorise, entities, heuristic_clusters
from ctdd.agent.writer import number_guard
from ctdd.audit import AuditLog
from ctdd.config import load_thresholds
from ctdd.controls import PaperLedger, Policy, Proposal


def _proposal(**kw):
    base = dict(trader="t", token_id="x-0", cluster="c1", title="T", leader_price=0.5, current_price=0.51,
                stake=8.0, action="copy", reasons=[], verdict="Skilled and copyable")
    base.update(kw)
    return Proposal(**base)


def test_controls_block_oversized_unclear_copy(tmp_path):
    th = load_thresholds()["controls"]
    pol, led = Policy(th, AuditLog(tmp_path / "a.jsonl")), PaperLedger()
    ok, blocks = pol.check(_proposal(stake=25.0, verdict="Can't tell yet"), led)
    assert not ok
    assert any("Per-trade cap" in b for b in blocks) and any("Verdict gate" in b for b in blocks)


def test_override_needs_reason_and_cap_still_applies(tmp_path):
    th = load_thresholds()["controls"]
    pol, led = Policy(th, AuditLog(tmp_path / "a.jsonl")), PaperLedger()
    assert pol.check(_proposal(verdict="Probably luck"), led, override_reason="I know the event")[0]
    assert not pol.check(_proposal(verdict="Probably luck", stake=50), led, override_reason="x")[0]


def test_stale_price_and_cluster_exposure(tmp_path):
    th = load_thresholds()["controls"]
    pol, led = Policy(th, AuditLog(tmp_path / "a.jsonl")), PaperLedger()
    assert not pol.check(_proposal(current_price=0.6), led)[0]
    for i in range(3):
        assert pol.execute(_proposal(token_id=f"t{i}-0"), led, approved_by="u")["executed"]
    res = pol.execute(_proposal(token_id="t9-0"), led, approved_by="u")  # 4 x 8 = 32 > 30 cap
    assert not res["executed"] and any("Event exposure" in b for b in res["blocks"])


def test_drawdown_stop_pauses_trader(tmp_path):
    th = load_thresholds()["controls"]
    pol, led = Policy(th, AuditLog(tmp_path / "a.jsonl")), PaperLedger()
    for i in range(5):
        pol.execute(_proposal(token_id=f"k{i}-0", cluster=f"c{i}", stake=10.0), led, approved_by="u")
        pol.settle(led, f"k{i}-0", 0.0)
    assert "t" in led.paused
    assert not pol.check(_proposal(cluster="new"), led)[0]


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(5):
        log.log("e", i=i)
    assert log.verify() == (True, None)
    lines = log.path.read_text().splitlines()
    lines[2] = lines[2].replace('"i": 2', '"i": 99')
    log.path.write_text("\n".join(lines) + "\n")
    assert log.verify()[0] is False


def test_number_guard():
    allowed = {12.5, 0.034, 3.4, 1000.0}
    assert number_guard("Edge was 3.4% across 1,000 traders [S.edge].", allowed) == []
    assert number_guard("Edge was 7.9% per bet.", allowed) == ["7.9%"]


def test_entities_and_heuristic_clusters():
    assert "rivera" in entities("Will Rivera win the Northfield governor race?")
    mk = pd.DataFrame({
        "title": ["Will Rivera win the Northfield governor race?", "Will Okafor concede the Northfield race by Friday?",
                  "Will Kestrel FC beat Doran United on May 05?"],
        "event_slug": ["a", "b", "c"], "resolve_ts": [1e9, 1e9 + 3600, 1e9],
    }, index=["m1", "m2", "m3"])
    cl = heuristic_clusters(mk)
    assert cl["m1"] == cl["m2"] != cl["m3"]


def test_categorise():
    assert categorise("Spread: North Texas (-16.5)") == "sports"
    assert categorise("Will Bitcoin close above $100,000 on Nov 7?") == "crypto"
    assert categorise("Will the Fed cut rates in December?") == "economics"


def test_citations_stay_with_their_sentence():
    from ctdd.agent.writer import split_cited_sentences
    t = ("Profit was $19,780.35 over 2000 positions. [S.profit, S.n_closed] They won 54.9% [S.win_rate]. "
         "Luck is 2.0%. [S.luck] Paper trading only.")
    s = split_cited_sentences(t)
    assert s == ["Profit was $19,780.35 over 2000 positions. [S.profit, S.n_closed]",
                 "They won 54.9% [S.win_rate].", "Luck is 2.0%. [S.luck]", "Paper trading only."]


def test_kill_switch_blocks_everything_and_is_logged(tmp_path):
    th = load_thresholds()["controls"]
    log = AuditLog(tmp_path / "a.jsonl")
    pol, led = Policy(th, log), PaperLedger()
    pol.kill_switch(led, True, by="judge", reason="demo")
    res = pol.execute(_proposal(), led, approved_by="u")
    assert not res["executed"] and any("Kill switch" in b for b in res["blocks"])
    pol.kill_switch(led, False, by="judge")
    assert pol.execute(_proposal(), led, approved_by="u")["executed"]
    assert [e["event"] for e in log.tail(10)].count("kill_switch") == 2


def test_hold_needs_a_human_reason(tmp_path):
    th = load_thresholds()["controls"]
    pol, led = Policy(th, AuditLog(tmp_path / "a.jsonl")), PaperLedger()
    assert not pol.check(_proposal(action="hold"), led)[0]
    assert pol.check(_proposal(action="hold"), led, override_reason="I checked the event myself")[0]
