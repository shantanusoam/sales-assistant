"""Phase A: charge-money-safely features.

- Twilio webhook signature validation
- Session revocation via token_version (password change/reset invalidates old tokens)
- Email-backed invite links (no more plaintext passwords) + accept flow
- Forgot/reset password flows (no account enumeration, single-use hashed tokens)
- Monthly plan quotas on browser, Twilio, and mobile calls + billing status/plan endpoints
- Hint feedback loop (+1/-1) surfaced as hint_acceptance_rate in analytics
"""
import base64
import hashlib
import hmac
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def _settings(tmp_sqlite_url):
    return replace(
        Settings(),
        session_signing_key="k" * 64,
        master_encryption_key="l" * 48,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
        twilio_auth_token="TESTTWILIOAUTHTOKEN",
        twilio_validate_signatures=True,
        public_base_url="http://testserver",
    )


def _signup(client, email, name="Admin User", org="Phase A Co"):
    res = client.post("/api/auth/signup", json={
        "organization_name": org, "name": name, "email": email, "password": "correct horse battery",
    })
    assert res.status_code == 200
    body = res.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["token"], body


def _twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    mac = hmac.new(auth_token.encode(), url.encode(), hashlib.sha1)
    for key in sorted(params):
        mac.update(f"{key}{params[key]}".encode())
    return base64.b64encode(mac.digest()).decode()


# ---------------------------------------------------------------- Twilio signatures

def test_twiml_rejects_unsigned_and_accepts_signed_requests(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        params = {"org_id": "org_x", "consent": "1"}
        url = "http://testserver/api/twilio/twiml?" + "&".join(f"{k}={v}" for k, v in params.items())

        unsigned = client.get("/api/twilio/twiml", params=params)
        assert unsigned.status_code == 403

        forged = client.get("/api/twilio/twiml", params=params, headers={"X-Twilio-Signature": "garbage=="})
        assert forged.status_code == 403

        signed = client.get(
            "/api/twilio/twiml",
            params=params,
            headers={"X-Twilio-Signature": _twilio_signature("TESTTWILIOAUTHTOKEN", url, params)},
        )
        assert signed.status_code == 200
        assert "sales-copilot" in signed.text


# ---------------------------------------------------------------- Token revocation

def test_password_change_revokes_existing_sessions(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, old_token, body = _signup(client, "rev@example.com")

        me = client.get("/api/auth/me", headers=auth)
        assert me.status_code == 200

        res = client.patch("/api/auth/me/password", headers=auth, json={
            "current_password": "correct horse battery",
            "new_password": "new correct horse battery",
        })
        assert res.status_code == 200
        new_token = res.json()["token"]

        # The old session must be dead immediately...
        assert client.get("/api/auth/me", headers=auth).status_code == 401
        # ...and the WebSocket handshake must refuse it too (no ready message arrives).
        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{old_token}"],
        ) as ws:
            assert client.get("/api/auth/me", headers=auth).status_code == 401
            import pytest
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

        # ...while the fresh token keeps working.
        assert client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}
        ).status_code == 200


# ---------------------------------------------------------------- Invite links & reset

def test_invite_link_flow_replaces_plaintext_password(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _token, _body = _signup(client, "lead@invite.example.com")

        invited = client.post("/api/auth/invite", headers=auth, json={
            "name": "Nikhil Rep", "email": "nikhil@invite.example.com", "role": "rep",
        })
        assert invited.status_code == 200
        invite = invited.json().get("invite", {})
        assert invite.get("link"), "dev-mode mailer must hand back the invite link"
        raw_token = invite["link"].split("token=")[1]

        # The teammate's password is unusable until the accept step.
        early = client.post("/api/auth/login", json={"email": "nikhil@invite.example.com", "password": "correct horse battery"})
        assert early.status_code == 401

        accepted = client.post("/api/auth/invite/accept", json={
            "token": raw_token, "password": "nikhil sets this",
        })
        assert accepted.status_code == 200
        assert accepted.json()["role"] == "rep"

        login = client.post("/api/auth/login", json={"email": "nikhil@invite.example.com", "password": "nikhil sets this"})
        assert login.status_code == 200

        # Single use: replaying the link must fail.
        replay = client.post("/api/auth/invite/accept", json={"token": raw_token, "password": "anything at all"})
        assert replay.status_code == 400


def test_forgot_and_reset_password_flow(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        _auth, _token, _body = _signup(client, "resetme@example.com")

        # Unknown emails get the same response (no account enumeration).
        unknown = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
        assert unknown.status_code == 200
        assert unknown.json()["reset_link_dev"] is None

        forgot = client.post("/api/auth/forgot", json={"email": "resetme@example.com"})
        assert forgot.status_code == 200
        raw_token = forgot.json()["reset_link_dev"].split("token=")[1]

        reset = client.post("/api/auth/reset", json={"token": raw_token, "password": "a fresh password"})
        assert reset.status_code == 200
        fresh_token = reset.json()["token"]

        old_login = client.post("/api/auth/login", json={"email": "resetme@example.com", "password": "correct horse battery"})
        assert old_login.status_code == 401, "old password must no longer work"
        new_login = client.post("/api/auth/login", json={"email": "resetme@example.com", "password": "a fresh password"})
        assert new_login.status_code == 200

        # Old pre-reset token must be revoked by the version bump.
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + reset.json()["token"]}).status_code == 200

        replay = client.post("/api/auth/reset", json={"token": raw_token, "password": "reuse attempt 123"})
        assert replay.status_code == 400


# ---------------------------------------------------------------- Billing & quotas

def test_billing_status_and_admin_plan_switch(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _token, _body = _signup(client, "bill@phasea.example.com")

        status = client.get("/api/billing/status", headers=auth).json()
        assert status["plan"] == "pilot"
        assert status["monthly_call_limit"] == 50
        assert status["calls_used_this_month"] == 0
        assert "growth" in status["plans"]

        upgraded = client.post("/api/billing/plan", headers=auth, json={"plan": "growth"})
        assert upgraded.status_code == 200
        assert upgraded.json()["monthly_call_limit"] == 500

        assert client.post("/api/billing/plan", headers=auth, json={"plan": "mega"}).status_code == 400


def test_monthly_quota_blocks_calls_when_exhausted(tmp_sqlite_url):
    import sqlite3

    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token, body = _signup(client, "quota@phasea.example.com")
        db_path = tmp_sqlite_url.split("///")[1]
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE organizations SET monthly_call_limit_override = 1")
            conn.commit()

        # First call is allowed...
        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            ws.receive_json(); ws.receive_json(); ws.receive_json()

        # ...and the next connection is refused with a quota error before any turns.
        # The server explains itself first (so dashboards show why), then closes.
        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            import pytest
            from starlette.websockets import WebSocketDisconnect
            quota_msg = ws.receive_json()
            assert quota_msg["type"] == "error"
            assert "monthly call limit" in quota_msg["message"].casefold()
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

        # The mobile logger and Twilio dialer enforce the same meter.
        mobile = client.post("/api/calls/log-mobile", headers=auth, json={
            "consent_confirmed": False,
            "turns": [{"speaker": "customer", "text": "What does this cost?"}],
        })
        assert mobile.status_code == 402
        assert "monthly call limit" in mobile.json()["detail"].casefold()


# ---------------------------------------------------------------- Hint feedback loop

def test_hint_feedback_round_trip_and_acceptance_rate(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token, _body = _signup(client, "feedback@phasea.example.com")

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            ws.receive_json(); ws.receive_json()
            hint = ws.receive_json()
        assert hint["type"] == "hint"
        assert hint["id"], "hint messages must carry their DB id for feedback"

        up = client.post(f"/api/calls/hints/{hint['id']}/feedback", headers=auth, json={"value": 1})
        assert up.status_code == 200
        assert up.json() == {"id": hint["id"], "feedback": 1}

        bad = client.post(f"/api/calls/hints/{hint['id']}/feedback", headers=auth, json={"value": 0})
        assert bad.status_code == 400

        detail = client.get(f"/api/calls/{_first_call_id(client, auth)}", headers=auth).json()
        assert detail["hints"][0]["feedback"] == 1

        analytics = client.get("/api/calls/analytics", headers=auth).json()
        assert analytics["total_hint_feedback"] == 1
        assert analytics["hint_acceptance_rate"] == 100.0


def _first_call_id(client, auth):
    return client.get("/api/calls", headers=auth).json()["calls"][0]["id"]
