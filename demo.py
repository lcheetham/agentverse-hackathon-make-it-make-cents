"""The 4-minute demo in the terminal: a backup for when the web app or the venue Wi-Fi fails on stage.

    python demo.py           # pauses for you to press Enter between steps, and asks you to approve the live copy
    python demo.py --yes     # runs straight through (rehearsal / recording)

Runs fully offline on the synthetic demo wallets, using the same Service, engine, risk controls, kill switch
and audit log as the web app. Paper trading only. Information, not financial advice.
"""
from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("CTDD_OFFLINE", "1")          # the backup never depends on a network or an API key

from ctdd import killswitch                          # noqa: E402
from ctdd.config import BANNER                       # noqa: E402
from ctdd.evalview import evaluation                 # noqa: E402
from ctdd.service import Service                     # noqa: E402

LINE = "=" * 78


def pct(x, dp=1, signed=False):
    return "–" if x is None else f"{x * 100:+.{dp}f}%" if signed else f"{x * 100:.{dp}f}%"


class Demo:
    def __init__(self, auto: bool):
        self.auto = auto
        self.svc = Service()

    def pause(self, what: str = "next step"):
        if not self.auto:
            input(f"\n  [Enter for the {what}] ")

    def title(self, n: int, text: str):
        print(f"\n{LINE}\n {n}. {text}\n{LINE}")

    def wallet(self, w: str):
        c = self.svc.card(w)
        s, e, v = c["summary"], c["edge"], c["verdict"]
        luck = next(x for x in c["luck"]["by_n"] if x["n"] == c["params"]["leaderboard_n"])
        print(f"  {w}   ({c.get('demo_label') or ''}; SYNTHETIC)")
        print(f"  Record {s['record']} over {s['n_positions']:,} positions · win rate {pct(s['win_rate'], 0)} · "
              f"profit ${s['profit']:,.0f}")
        print(f"  Edge per position {pct(e['mean'], signed=True)} (95% CI {pct(e['ci_low'], signed=True)} to "
              f"{pct(e['ci_high'], signed=True)}, {e['n_clusters']:,} clusters)")
        print(f"  Luck score at N = {luck['n']:,}: {'≤ ' if luck.get('upper_bound') else ''}{pct(luck['score'])}"
              "  (the chance that this many no-skill traders produce someone at least this good)")
        sim = c["sim_200"]
        print(f"  £200 copying at {sim['delay_s'] // 60} min delay (historical simulation): £{sim['end']:,.2f}"
              + ("  (ran out of cash)" if sim.get("ran_out_of_cash") else ""))
        print(f"\n  VERDICT: {v['label'].upper()}")
        for d in v.get("deciding", []):
            print(f"    - {d['text']}")

    def checks(self, checks):
        for ch in checks:
            print(f"    [{'pass' if ch['passed'] else 'FAIL'}] {ch['control']}: {ch.get('reason', '')}")

    def run(self):
        print(f"{LINE}\n COPY-TRADER DUE DILIGENCE · terminal demo\n {BANNER}\n LLM: {self.svc.llm_name}\n{LINE}")
        if killswitch.status()["on"]:
            print("\n  The kill switch is ON from an earlier session. A human turns it off here:")
            self.pause("kill switch to be turned off")
            killswitch.turn_off("human (terminal demo)", self.svc.audit)

        self.title(1, "Hook: a perfect 25-0 record")
        self.wallet("0xDEMO-perfect-25-0")
        self.pause("contrast")

        self.title(2, "Contrast: a messy record, and a skilled trader you can't copy")
        self.wallet("0xDEMO-messy-skilled")
        print()
        self.wallet("0xDEMO-fast-mover")
        self.pause("live control")

        self.title(3, "Live control (labelled replay, paper only)")
        live = self.svc.ensure_live()
        live.reset()
        p = live.next_bet("0xDEMO-perfect-25-0")
        print(f"  The 25-0 trader places a new bet: {p['bet']['title']!r}")
        print("  A follower tries to copy it with £50. The code checks every control before the paper ledger:")
        r = live.decide(p["proposal_id"], "approve", 50)
        print(f"  -> {r['status'].upper()}")
        self.checks(r["checks"])
        live.decide(p["proposal_id"], "reject")
        print("\n  Now the messy-but-skilled trader bets. The agent proposes a small paper copy:")
        p = live.next_bet("0xDEMO-messy-skilled")
        print(f"  {p['bet']['title']!r}: proposed stake £{p['stake']:.2f}")
        ok = self.auto or input("  Approve this paper copy? [y/N] ").strip().lower() == "y"
        r = live.decide(p["proposal_id"], "approve" if ok else "reject", p["stake"])
        print(f"  -> {r['status'].upper()}")
        if r["status"] != "rejected":
            self.checks(r["checks"])
        self.pause("kill switch")

        self.title(4, "Kill switch: anyone can stop all copying; only a human restarts it")
        killswitch.turn_on("human (terminal demo)", "demo: stop all copying", self.svc.audit)
        p = live.next_bet("0xDEMO-messy-skilled")
        ks = next(c for c in p["precheck"] if c["control"] == "kill_switch")
        print(f"  Kill switch ON. Next proposal's kill_switch control: {'pass' if ks['passed'] else 'FAIL'}")
        live.decide(p["proposal_id"], "reject")
        try:
            killswitch.turn_off("agent", self.svc.audit)
        except PermissionError as e:
            print(f"  The agent tries to turn it off: refused ({e})")
        killswitch.turn_off("human (terminal demo)", self.svc.audit)
        print("  A human turns it off.")
        self.pause("results")

        self.title(5, "Results, stated honestly")
        ev = evaluation()
        pl, big, wf = ev.get("planted"), ev.get("planted_large"), ev.get("walkforward")
        if pl:
            m = {x["key"]: x for x in pl["metrics"]}
            fa = m["false_alarm"]
            print(f"  Planted traders, our generator (SYNTHETIC, {pl['n_wallets']} wallets): "
                  f"{fa['k']}/{fa['n']} no-skill wallets called skilled; detection {m['detection']['k']}/{m['detection']['n']}.")
        if big:
            eng = next(j for j in big["judges"] if j["key"] == "engine")
            naive = {j["key"]: j for j in big["judges"]}
            print(f"  Planted traders, independent generator (SYNTHETIC, {big['n_wallets']:,} wallets): recommended "
                  f"{eng['no_skill_copied']['k']} of {eng['no_skill_copied']['n']} no-skill wallets; "
                  f"{pct(eng['precision']['rate'], 0)} of its copy calls were truly skilled & copyable "
                  f"(top 10 by profit: {pct(naive['naive_top10']['precision']['rate'], 0)}).")
        if wf:
            print(f"  Real Polymarket wallets, walk-forward from {wf['label'].split('cut-off ')[-1]}: copying the top 10 returned "
                  f"{pct(wf['top10']['return'], signed=True)} per copy (95% CI {pct(wf['top10']['ci_low'], signed=True)} to "
                  f"{pct(wf['top10']['ci_high'], signed=True)}). The agent approved none and held cash.")
            print("  That shows the leaderboard wasn't worth copying, not that the agent picks winners.")
        ok, bad = self.svc.audit.verify()
        print(f"\n  Audit log: {'hash chain verifies' if ok else f'BROKEN at line {bad}'}.")
        print(f"\n {BANNER}\n{LINE}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="run straight through without pauses or prompts")
    a = ap.parse_args()
    try:
        Demo(a.yes).run()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
