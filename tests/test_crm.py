import time
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.crypto import decrypt_secret, encrypt_secret
from backend.app.main import create_app


def _settings(tmp_sqlite_url):
    return replace(
        Settings(),
        session_signing_key="c" * 64,
        master_encryption_key="d" * 48,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
    )


def test_encrypt_decrypt_roundtrip():
    settings = Settings(master_encryption_key="super-secret-master-key")
    ciphertext = encrypt_secret("pat-na1-abc123", settings)
    assert ciphertext != "pat-na1-abc123"
    assert decrypt_secret(ciphertext, settings) == "pat-na1-abc123"


def _signup_and_auth(client, email="admin@crmco.example.com"):
    signup = client.post("/api/auth/signup", json={
        "organization_name": "CRM Co", "name": "Carl Admin", "email": email, "password": "correct horse battery",
    })
    token = signup.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_crm_status_disconnected_by_default(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth = _signup_and_auth(client)
        status = client.get("/api/crm/status", headers=auth)
        assert status.status_code == 200
        assert status.json()["connected"] is False
        assert "hubspot" in status.json()["providers"]


@patch("backend.app.crm.HubSpotProvider.test_connection", new_callable=AsyncMock)
def test_crm_connect_rejects_invalid_token(mock_test, tmp_sqlite_url):
    from backend.app.crm import CRMError
    mock_test.side_effect = CRMError("HubSpot rejected the token.")
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth = _signup_and_auth(client)
        res = client.post("/api/crm/connect", headers=auth, json={"provider": "hubspot", "token": "bad-token"})
        assert res.status_code == 400
        assert client.get("/api/crm/status", headers=auth).json()["connected"] is False


@patch("backend.app.crm.HubSpotProvider.test_connection", new_callable=AsyncMock)
def test_crm_connect_disconnect_and_settings(mock_test, tmp_sqlite_url):
    mock_test.return_value = None
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth = _signup_and_auth(client)

        connect = client.post("/api/crm/connect", headers=auth, json={"provider": "hubspot", "token": "pat-na1-real"})
        assert connect.status_code == 200
        assert connect.json() == {"connected": True, "provider": "hubspot"}

        status = client.get("/api/crm/status", headers=auth).json()
        assert status["connected"] is True
        assert status["provider"] == "hubspot"
        assert status["auto_push"] is True

        toggled = client.patch("/api/crm/settings", headers=auth, json={"auto_push": False})
        assert toggled.status_code == 200
        assert client.get("/api/crm/status", headers=auth).json()["auto_push"] is False

        disconnect = client.post("/api/crm/disconnect", headers=auth)
        assert disconnect.status_code == 200
        assert client.get("/api/crm/status", headers=auth).json()["connected"] is False


def test_crm_connect_requires_admin_role(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        admin_auth = _signup_and_auth(client)
        invite = client.post("/api/auth/invite", headers=admin_auth, json={
            "name": "Rep Rita", "email": "rita@crmco.example.com", "password": "correct horse battery", "role": "rep",
        })
        assert invite.status_code == 200
        rep_login = client.post("/api/auth/login", json={"email": "rita@crmco.example.com", "password": "correct horse battery"})
        rep_auth = {"Authorization": f"Bearer {rep_login.json()['token']}"}

        res = client.post("/api/crm/connect", headers=rep_auth, json={"provider": "hubspot", "token": "x"})
        assert res.status_code == 403


@patch("backend.app.crm.HubSpotProvider.push_call_note", new_callable=AsyncMock)
@patch("backend.app.crm.HubSpotProvider.test_connection", new_callable=AsyncMock)
def test_post_call_summary_pushes_to_connected_crm(mock_test, mock_push, tmp_sqlite_url):
    mock_test.return_value = None
    mock_push.return_value = None
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth = _signup_and_auth(client)
        token = auth["Authorization"].removeprefix("Bearer ")
        connect = client.post("/api/crm/connect", headers=auth, json={"provider": "hubspot", "token": "pat-na1-real"})
        assert connect.status_code == 200

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": "confirm_consent"})
            ws.receive_json()  # status: consent recorded
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            ws.receive_json(); ws.receive_json(); ws.receive_json()  # transcript, signals, hint

        for _ in range(40):
            calls = client.get("/api/calls", headers=auth).json()["calls"]
            if calls and calls[0].get("coaching_score") is not None:
                break
            time.sleep(0.05)

        assert mock_push.called, "post-call summary was not pushed to the connected CRM"
        pushed_body = mock_push.call_args.args[0]
        assert "coaching score" in pushed_body.casefold()
