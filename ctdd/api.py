"""Web app: Adrian's frontend served by Flask on top of Diego's engine.

    python -m ctdd.api            # http://127.0.0.1:8000   (PORT env var to change)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import killswitch
from .auditview import KINDS, LIVE_KINDS, annotate
from .config import BANNER, ROOT
from .evalview import evaluation
from .service import Service

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "dev"
DELAYS = [{"s": 0, "label": "0"}, {"s": 300, "label": "5 min"}, {"s": 3600, "label": "1 h"}, {"s": 86400, "label": "1 day"}]


def create_app(svc: Service | None = None, board=None) -> Flask:
    app = Flask(__name__, static_folder=None)
    state = {"svc": svc, "agent": None, "board": board}
    lock = threading.Lock()

    def S() -> Service:
        with lock:
            if state["svc"] is None:
                state["svc"] = Service()
            return state["svc"]

    def agent():
        from .chat import ChatAgent
        with lock:
            if state["agent"] is None:
                state["agent"] = ChatAgent(state["svc"])
            return state["agent"]

    def board():
        from .leaderboard import LiveLeaderboard
        s = S()
        with lock:
            if state["board"] is None:
                state["board"] = LiveLeaderboard(audit=s.audit)
            return state["board"]

    def body() -> dict:
        b = request.get_json(silent=True)
        if not isinstance(b, dict):
            raise ValueError("Expected a JSON object body.")
        return b

    @app.errorhandler(ValueError)
    def bad(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(PermissionError)
    def forbidden(e):
        return jsonify({"error": str(e)}), 403

    @app.after_request
    def no_stale_pages(resp):
        # The browser must re-check the page and its scripts every time, so a new version of the app shows
        # up on a normal reload instead of an old cached copy.
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # ---------------- static ----------------
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/<path:p>")
    def static_files(p):
        if p.startswith("api/"):
            return jsonify({"error": "not found"}), 404
        return send_from_directory(FRONTEND, p)

    # ---------------- read ----------------
    @app.get("/api/meta")
    def meta():
        s = S()
        c = s.th["controls"]
        return jsonify({"version": VERSION, "data_mode": "synthetic", "llm_mode": s.llm_name, "llm_available": s.llm.available, "banner": BANNER,
                        "delays": DELAYS, "verdict_delay_s": s.th["verdict"]["copy_delay_s"],
                        "limits": {"bankroll": c["bankroll"], "per_trade_cap_frac": c["per_trade_cap"], "cluster_cap_frac": c["cluster_cap"],
                                   "drawdown_stop_frac": c["drawdown_stop"], "stale_price_max_move": c["stale_price_move"]},
                        "kill_switch": killswitch.status(), "llm_status": {"mode": "gemini" if s.llm.available else "offline"}})

    @app.get("/api/wallets")
    def wallets():
        """The planted demo wallets (synthetic), used by 'Why rankings mislead'."""
        return jsonify(S().wallets())

    def board_json(extra: dict | None = None) -> dict:
        snap = board().get()
        if extra:
            snap = {**snap, **{k: v for k, v in extra.items() if v}}
        cached = S().cached_verdicts([r["address"] for r in snap.get("rows", [])])
        snap["rows"] = [{**r, "verdict": cached.get(r["address"])} for r in snap.get("rows", [])]
        return snap

    @app.get("/api/leaderboard")
    def leaderboard():
        """Real Polymarket top 10 (plain list; verdicts only for wallets someone has already opened)."""
        return jsonify(board_json())

    @app.post("/api/leaderboard/refresh")
    def leaderboard_refresh():
        r = board().refresh(force=True)
        return jsonify(board_json({"note": r["note"]}))

    @app.get("/api/wallets/<addr>/report")
    def report(addr):
        s = S()
        try:
            delay = int(request.args.get("delay", 3600))
        except ValueError:
            raise ValueError("delay must be an integer number of seconds")
        if delay not in {d["s"] for d in DELAYS}:
            raise ValueError("delay must be one of 0, 300, 3600, 86400")
        if not s.is_demo(addr):
            from .engine.integrity import valid_address
            if not valid_address(addr):
                s.audit.log("input_rejected", reason="invalid wallet address", value=addr[:80])
                raise ValueError("That is not a Polymarket wallet address (expected 0x followed by 40 hex characters).")
        try:
            return jsonify(s.card(addr if s.is_demo(addr) else addr.lower(), delay))
        except ValueError:
            raise
        except Exception as exc:                         # network etc. on real wallets
            s.audit.log("real_wallet_error", wallet=addr[:80], error=str(exc)[:300])
            return jsonify({"error": f"Could not analyse this wallet: {type(exc).__name__}: {str(exc)[:200]}"}), 502

    @app.get("/api/wallets/<addr>/luck")
    def luck(addr):
        s = S()
        try:
            n = int(request.args.get("n", ""))
        except ValueError:
            raise ValueError("n must be a whole number (the leaderboard size N)")
        if not s.is_demo(addr):
            from .engine.integrity import valid_address
            if not valid_address(addr):
                raise ValueError("That is not a Polymarket wallet address (expected 0x followed by 40 hex characters).")
            addr = addr.lower()
        return jsonify(s.luck(addr, n))

    @app.get("/api/audit")
    def audit():
        """Newest entries with a plain-English summary and a group. ?kind=live keeps only paper-trading and
        safety events (what Live mode shows); ?kind=<group> keeps one group. The file itself is untouched."""
        try:
            n = max(1, min(int(request.args.get("limit", 50)), 1000))
        except ValueError:
            raise ValueError("limit must be a whole number")
        kind = request.args.get("kind", "")
        if kind and kind != "live" and kind not in KINDS:
            raise ValueError(f"kind must be one of: live, {', '.join(KINDS)}")
        rows = [annotate(e) for e in S().audit.tail(n if not kind else 5000)]
        if kind:
            keep = LIVE_KINDS if kind == "live" else {kind}
            rows = [e for e in rows if e["kind"] in keep][-n:]
        return jsonify(rows)

    @app.get("/api/audit/kinds")
    def audit_kinds():
        return jsonify([[k, v] for k, v in KINDS.items()])        # a list keeps the display order

    @app.get("/api/audit/verify")
    def audit_verify():
        ok, bad_line = S().audit.verify()
        return jsonify({"ok": ok, "first_bad_line": bad_line})

    @app.get("/api/evaluation")
    def eval_():
        return jsonify(evaluation())

    # ---------------- live replay ----------------
    @app.get("/api/live/state")
    def live_state():
        return jsonify(S().ensure_live().state())

    @app.post("/api/live/next")
    def live_next():
        w = body().get("wallet")
        if not isinstance(w, str):
            raise ValueError("wallet must be a string")
        return jsonify(S().ensure_live().next_bet(w))

    @app.post("/api/live/decide")
    def live_decide():
        b = body()
        pid, dec = b.get("proposal_id"), b.get("decision")
        if not isinstance(pid, str) or not isinstance(dec, str):
            raise ValueError("proposal_id and decision must be strings")
        ovr = b.get("override_reason")
        if ovr is not None and not isinstance(ovr, str):
            raise ValueError("override_reason must be a string")
        r = S().ensure_live().decide(pid, dec, b.get("stake"), ovr)
        if r.get("audit_entry"):
            r["audit_entry"] = annotate(r["audit_entry"])
        return jsonify(r)

    @app.post("/api/live/settle-next")
    def live_settle_next():
        return jsonify(S().ensure_live().settle_next())

    @app.post("/api/live/advance")
    def live_advance():
        return jsonify(S().ensure_live().advance())

    @app.post("/api/live/resume")
    def live_resume():
        w = body().get("wallet")
        if not isinstance(w, str):
            raise ValueError("wallet must be a string")
        return jsonify(S().ensure_live().resume(w))

    @app.post("/api/live/reset")
    def live_reset():
        live = S().ensure_live()
        live.reset()
        return jsonify({"state": live.state()})

    # ---------------- kill switch ----------------
    @app.post("/api/killswitch")
    def kill():
        b = body()
        s = S()
        if b.get("on") is True:
            reason = b.get("reason") if isinstance(b.get("reason"), str) else "stopped from the web UI"
            ks = killswitch.turn_on("human (web UI)", reason, s.audit)
        elif b.get("on") is False:
            ks = killswitch.turn_off("human (web UI)", s.audit)
        else:
            raise ValueError("on must be true or false")
        return jsonify({"kill_switch": ks, "state": s.ensure_live().state()})

    # ---------------- agent ----------------
    @app.post("/api/agent")
    def ask():
        q = body().get("question")
        if not isinstance(q, str) or not q.strip():
            raise ValueError("question must be a non-empty string")
        if not S().llm.available:
            return jsonify({"error": "The agent needs Gemini: add GEMINI_API_KEY to .env and restart."}), 503
        return jsonify(agent().ask(q.strip()[:1000]))

    return app


def port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    port = int(os.environ.get("PORT", 8000))
    # On Windows a second server can bind the same port while the first keeps answering, so an old copy of
    # the app would silently serve the browser. Refuse to start instead.
    if port_in_use(port):
        raise SystemExit(f"Port {port} is already in use, probably by an older copy of this app in another terminal.\n"
                         f"Stop it there with Ctrl+C (or close that window), then run this again.\n"
                         f"Or use another port: PowerShell  $env:PORT=8001; python -m ctdd.api")
    print(f"{BANNER}\nCopy-Trader Due Diligence on http://127.0.0.1:{port}  (first page load runs the engine, ~10 s)")
    create_app().run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
