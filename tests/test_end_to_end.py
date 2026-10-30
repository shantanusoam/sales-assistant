from dataclasses import replace

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def test_end_to_end_simulated_utterance():
    settings = replace(
        Settings(),
        demo_access_code="super-secret-test-code",
        session_signing_key="a" * 64,
        deepgram_api_key="",
        openai_api_key="",
    )
    with TestClient(create_app(settings)) as client:
        wrong = client.post("/api/session", json={"access_code": "bad"})
        assert wrong.status_code == 401
        response = client.post("/api/session", json={"access_code": settings.demo_access_code})
        assert response.status_code == 200
        token = response.json()["token"]
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
