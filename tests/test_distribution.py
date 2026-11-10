"""Phase 7: consent gating, call disposition, webhook nodes, and WhatsApp opt-in."""
import time
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def _settings(tmp_sqlite_url):
    return replace(
        Settings(),
        session_signing_key="e" * 64,
        master_encryption_key="f" * 48,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
    )


def _signup_and_auth(client, email="admin@distco.example.com"):
    signup = client.post("/api/auth/signup", json={
        "organization_name": "Dist Co", "name": "Dee Admin", "email": email, "password": "correct horse battery",
    })
    token = signup.json()["token"]
    return {"Authorization": f"Bearer {token}"}, token


@patch("backend.app.crm.HubSpotProvider.push_call_note", new_callable=AsyncMock)
@patch("backend.app.crm.HubSpotProvider.test_connection", new_callable=AsyncMock)
def test_crm_push_is_skipped_without_consent(mock_test, mock_push, tmp_sqlite_url):
    mock_test.return_value = None
    mock_push.return_value = None
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token = _signup_and_auth(client)
        client.post("/api/crm/connect", headers=auth, json={"provider": "hubspot", "token": "pat-na1-real"})

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()  # ready — note: no confirm_consent sent
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            ws.receive_json(); ws.receive_json(); ws.receive_json()  # transcript, signals, hint

        call_id = None
        for _ in range(40):
            calls = client.get("/api/calls", headers=auth).json()["calls"]
            if calls and calls[0].get("ended_at") is not None:
                call_id = calls[0]["id"]
                break
            time.sleep(0.05)
        assert call_id is not None

        # give the (skipped) push a moment it would have needed, then confirm it never happened
        time.sleep(0.3)
        assert not mock_push.called, "CRM push fired even though consent was never confirmed"

        detail = client.get(f"/api/calls/{call_id}", headers=auth).json()
        assert detail["consent_confirmed"] is False
        assert detail["summary"] is not None, "summary should still generate for internal history without consent"


def test_call_disposition_is_persisted_and_exposed(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token = _signup_and_auth(client, email="disp@distco.example.com")

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "simulate_utterance", "text": "This sounds good, I'm interested, let's move forward."})
            ws.receive_json(); ws.receive_json(); ws.receive_json()

        summary = None
        for _ in range(40):
            calls = client.get("/api/calls", headers=auth).json()["calls"]
            if calls and calls[0].get("disposition") is not None:
                summary = calls[0]
                break
            time.sleep(0.05)
        assert summary is not None
        assert summary["disposition"] in ("interested", "follow_up", "no_decision", "not_interested", "do_not_contact")


def test_webhook_node_crud_requires_admin(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        admin_auth, _ = _signup_and_auth(client, email="wha@distco.example.com")
        invite = client.post("/api/auth/invite", headers=admin_auth, json={
            "name": "Rep Rex", "email": "rex@distco.example.com", "password": "correct horse battery", "role": "rep",
        })
        rep_login = client.post("/api/auth/login", json={"email": "rex@distco.example.com", "password": "correct horse battery"})
        rep_auth = {"Authorization": f"Bearer {rep_login.json()['token']}"}

        denied = client.post("/api/webhooks", headers=rep_auth, json={"url": "https://example.com/hook"})
        assert denied.status_code == 403

        created = client.post("/api/webhooks", headers=admin_auth, json={"url": "https://example.com/hook"})
        assert created.status_code == 200
        body = created.json()
        assert body["url"] == "https://example.com/hook"
        assert body["enabled"] is True
        assert len(body["secret"]) >= 32

        listed = client.get("/api/webhooks", headers=admin_auth).json()["webhooks"]
        assert len(listed) == 1

        toggled = client.patch(f"/api/webhooks/{body['id']}", headers=admin_auth, json={"enabled": False})
        assert toggled.status_code == 200
        assert toggled.json()["enabled"] is False

        deleted = client.delete(f"/api/webhooks/{body['id']}", headers=admin_auth)
        assert deleted.status_code == 200
        assert client.get("/api/webhooks", headers=admin_auth).json()["webhooks"] == []


def test_webhook_rejects_non_http_url(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _ = _signup_and_auth(client, email="bad@distco.example.com")
        res = client.post("/api/webhooks", headers=auth, json={"url": "javascript:alert(1)"})
        assert res.status_code == 400


@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
def test_consented_call_delivers_signed_webhook_payload(mock_post, tmp_sqlite_url):
    import json as _json
    import hashlib
    import hmac as _hmac

    mock_post.return_value = AsyncMock(status_code=200, text="ok")
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token = _signup_and_auth(client, email="hook@distco.example.com")
        webhook = client.post("/api/webhooks", headers=auth, json={"url": "https://example.com/sales-copilot-hook"}).json()

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "confirm_consent"})
            ws.receive_json()
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            ws.receive_json(); ws.receive_json(); ws.receive_json()

        for _ in range(60):
            calls = client.get("/api/calls", headers=auth).json()["calls"]
            if calls and calls[0].get("coaching_score") is not None:
                break
            time.sleep(0.05)
        time.sleep(0.2)

        assert mock_post.called, "webhook was never delivered for a consented call"
        call_args = mock_post.call_args
        assert call_args.args[0] == "https://example.com/sales-copilot-hook"
        body = call_args.kwargs["content"]
        signature = call_args.kwargs["headers"]["X-Signature-SHA256"]
        expected = _hmac.new(webhook["secret"].encode(), body, hashlib.sha256).hexdigest()
        assert signature == expected
        payload = _json.loads(body)
        assert payload["event"] == "call.summary_ready"
        assert "disposition" in payload


def test_whatsapp_prefs_round_trip(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _ = _signup_and_auth(client, email="wa@distco.example.com")

        me = client.get("/api/auth/me", headers=auth).json()
        assert me["user"]["whatsapp_recap_enabled"] is False
        assert me["user"]["whatsapp_number"] is None

        rejected = client.patch("/api/auth/me/whatsapp", headers=auth, json={"whatsapp_recap_enabled": True})
        assert rejected.status_code == 400, "enabling recap without a number should be rejected"

        updated = client.patch("/api/auth/me/whatsapp", headers=auth, json={
            "whatsapp_number": "+919876543210", "whatsapp_recap_enabled": True,
        })
        assert updated.status_code == 200
        assert updated.json() == {"whatsapp_number": "+919876543210", "whatsapp_recap_enabled": True}

        me2 = client.get("/api/auth/me", headers=auth).json()
        assert me2["user"]["whatsapp_number"] == "+919876543210"
        assert me2["user"]["whatsapp_recap_enabled"] is True
