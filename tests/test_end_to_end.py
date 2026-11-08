from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def test_end_to_end_simulated_utterance(tmp_sqlite_url):
    settings = replace(
        Settings(),
        session_signing_key="a" * 64,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
    )
    with TestClient(create_app(settings)) as client:
        bad_login = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
        assert bad_login.status_code == 401

        signup = client.post("/api/auth/signup", json={
            "organization_name": "Acme Sales",
            "name": "Ava Admin",
            "email": "ava@acme.example",
            "password": "correct horse battery",
        })
        assert signup.status_code == 200
        token = signup.json()["token"]
        assert signup.json()["role"] == "admin"

        login = client.post("/api/auth/login", json={"email": "ava@acme.example", "password": "correct horse battery"})
        assert login.status_code == 200
        token = login.json()["token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["organization"]["name"] == "Acme Sales"

        with client.websocket_connect(
            "/ws/live",
            headers={"origin": "http://localhost:8000"},
            subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["microphone_enabled"] is False
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            transcript = ws.receive_json()
            hint = ws.receive_json()
            assert transcript["type"] == "transcript_final"
            assert transcript["source"] == "manual-test"
            assert hint["type"] == "hint"
            assert hint["method"] == "rules-demo"
            assert "follow" in hint["text"].casefold() or "inquiry" in hint["text"].casefold()
            assert hint["sources"]
            assert hint["processing_ms"] >= 0
