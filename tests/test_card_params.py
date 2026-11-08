"""Report-card parameters: delay switching from one cached card, and Luck(N) at any leaderboard size."""
import numpy as np
import pytest

from ctdd import killswitch
from ctdd.adapter import luck_at
from ctdd.api import create_app
from ctdd.audit import AuditLog
from ctdd.engine.luck import conservative_luck
from ctdd.service import Service

W = "0xDEMO-perfect-25-0"


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    d = tmp_path_factory.mktemp("logs")
    killswitch.PATH = d / "KILL_SWITCH"
    return Service(audit=AuditLog(d / "audit.jsonl"))


@pytest.fixture()
def client(svc):
    return create_app(svc).test_client()


def test_one_card_holds_every_delay(client):
    j = client.get(f"/api/wallets/{W}/report?delay=3600").get_json()
    assert set(j["sims"]) == {"0", "300", "3600", "86400"}
    assert j["sim_200"] == j["sims"]["3600"] and j["params"]["copy_delay_s"] == 3600
    for d in (0, 300, 86400):                               # same card, different simulation selected
        k = client.get(f"/api/wallets/{W}/report?delay={d}").get_json()
        assert k["sim_200"] == j["sims"][str(d)] and k["verdict"] == j["verdict"]


def test_card_is_cached_not_rebuilt(svc):
    a, b = svc.card(W, 0), svc.card(W, 86400)
    assert a["positions"] is b["positions"]                 # shared base, only the selected sim differs
    assert a["sim_200"]["delay_s"] == 0 and b["sim_200"]["delay_s"] == 86400


def test_luck_at_any_n_matches_engine(svc):
    luck = svc.report(W)["luck"]
    for n in (1, 37, 1000, 250_000):
        assert luck_at(luck, n)["score"] == pytest.approx(conservative_luck(luck, n))
    s = [luck_at(luck, n)["score"] for n in (10, 100, 1000, 10_000)]
    assert all(np.diff(s) >= 0)                             # bigger field, more luck


def test_verdict_n_row_always_present(client):
    j = client.get(f"/api/wallets/{W}/report?delay=3600").get_json()
    assert j["luck"]["verdict_n"] in [r["n"] for r in j["luck"]["by_n"]]


def test_luck_endpoint_and_validation(client, svc):
    j = client.get(f"/api/wallets/{W}/luck?n=5000").get_json()
    assert j["n"] == 5000 and 0 <= j["score"] <= 1 and j["verdict_n"] == svc.demo_N(W)
    before = client.get(f"/api/wallets/{W}/report?delay=3600").get_json()["verdict"]
    client.get(f"/api/wallets/{W}/luck?n=7")
    assert client.get(f"/api/wallets/{W}/report?delay=3600").get_json()["verdict"] == before   # display only
    for bad in ("0", "-3", "abc", "2.5", "2000000"):
        assert client.get(f"/api/wallets/{W}/luck?n={bad}").status_code == 400
