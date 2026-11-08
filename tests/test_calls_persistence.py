import time
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def test_live_session_is_persisted_and_visible_in_call_history(tmp_sqlite_url):
    settings = replace(
        Settings(),
        session_signing_key="b" * 64,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
    )
    with TestClient(create_app(settings)) as client:
        signup = client.post("/api/auth/signup", json={
            "organization_name": "Persist Co",
            "name": "Pat Admin",
            "email": "pat@persist.example.com",
            "password": "correct horse battery",
        })
        token = signup.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        with client.websocket_connect(
            "/ws/live",
            headers={"origin": "http://localhost:8000"},
            subprotocols=["copilot-v1", f"auth.{token}"],
        ) as ws:
            ws.receive_json()  # ready
            ws.send_json({"type": "simulate_utterance", "text": "We use Excel but our follow-ups are late."})
            ws.receive_json()  # transcript_final
            ws.receive_json()  # hint

        # The websocket's cleanup (closing the Call row) runs after the test client's
        # `with ws:` block returns, so briefly poll rather than asserting immediately.
        call = None
        for _ in range(20):
            call_list = client.get("/api/calls", headers=auth).json()["calls"]
            if call_list and call_list[0]["ended_at"] is not None:
                call = call_list[0]
                break
            time.sleep(0.05)
        assert call is not None, "call row was never closed"
        assert call["channel"] == "browser"
        assert call["turn_count"] == 1
        assert call["hint_count"] == 1

        detail = client.get(f"/api/calls/{call['id']}", headers=auth)
        assert detail.status_code == 200
        body = detail.json()
        assert body["turns"][0]["source"] == "manual-test"
        assert "follow" in body["turns"][0]["text"].casefold()
        assert body["hints"][0]["method"] == "rules-demo"
        assert body["hints"][0]["sources"]

        # another organization cannot see this call
        other_signup = client.post("/api/auth/signup", json={
            "organization_name": "Other Co",
            "name": "Ollie Admin",
            "email": "ollie@other.example.com",
            "password": "correct horse battery",
        })
        other_auth = {"Authorization": f"Bearer {other_signup.json()['token']}"}
        assert client.get("/api/calls", headers=other_auth).json()["calls"] == []
        assert client.get(f"/api/calls/{call['id']}", headers=other_auth).status_code == 404
