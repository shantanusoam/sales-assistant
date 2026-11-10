"""Tests for platform extensions: tenant broadcast isolation, Twilio phone persistence,
customer/rep simulator speaker attribution, team listing, call analytics/filtering/regeneration,
webhook test delivery, playbook CRUD + live reload, and favicon."""
import time
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def _settings(tmp_sqlite_url, tmp_path=None):
    playbook_dir = (tmp_path / "playbooks") if tmp_path else Settings().playbook_dir
    if tmp_path:
        playbook_dir.mkdir(parents=True, exist_ok=True)
        (playbook_dir / "01_core_playbook.md").write_text(
            "# Core Playbook\nWhen a prospect mentions Excel or manual spreadsheets, ask how many leads slip per week.\n",
            encoding="utf-8",
        )
    return replace(
        Settings(),
        session_signing_key="g" * 64,
        master_encryption_key="h" * 48,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
        playbook_dir=playbook_dir,
    )


def _signup(client, org_name, email, name="Admin User"):
    res = client.post("/api/auth/signup", json={
        "organization_name": org_name,
        "name": name,
        "email": email,
        "password": "correct horse battery",
    })
    assert res.status_code == 200
    body = res.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["token"], body["organization"]["id"]


def test_favicon_and_pwa_routes_return_valid_assets(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        for path in ("/favicon.ico", "/favicon.svg"):
            res = client.get(path)
            assert res.status_code == 200
            assert "image/svg+xml" in res.headers["content-type"]
            assert "<svg" in res.text

        manifest = client.get("/manifest.webmanifest")
        assert manifest.status_code == 200
        assert "application/manifest+json" in manifest.headers["content-type"]
        assert manifest.json()["display"] == "standalone"

        sw = client.get("/sw.js")
        assert sw.status_code == 200
        assert "javascript" in sw.headers["content-type"]
        assert "sales-copilot-shell-v1" in sw.text


def test_twilio_broadcast_is_isolated_to_owning_org_and_persists_phone_numbers(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth_a, token_a, org_a = _signup(client, "Org Alpha", "alpha@example.com")
        auth_b, token_b, org_b = _signup(client, "Org Beta", "beta@example.com")

        # Verify TwiML includes to_number and from_number parameters
        twiml = client.get(
            "/api/twilio/twiml",
            params={
                "org_id": org_a,
                "rep_user_id": "u1",
                "consent": "1",
                "to_number": "+919876543210",
                "from_number": "+15551234567",
            },
        )
        assert twiml.status_code == 200
        assert 'name="to_number" value="+919876543210"' in twiml.text
        assert 'name="from_number" value="+15551234567"' in twiml.text

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token_a}"]
        ) as ws_a, client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token_b}"]
        ) as ws_b:
            ws_a.receive_json()  # ready
            ws_b.receive_json()  # ready

            with client.websocket_connect("/ws/twilio-media") as twilio_ws:
                twilio_ws.send_json({
                    "event": "start",
                    "start": {
                        "callSid": "CA_TEST_ISOLATION",
                        "streamSid": "MZ_TEST_1",
                        "customParameters": {
                            "org_id": org_a,
                            "consent": "1",
                            "to_number": "+919876543210",
                            "from_number": "+15551234567",
                        },
                    },
                })
                msg_a = ws_a.receive_json()
                assert msg_a["type"] == "status"
                assert "CA_TEST_ISOLATION" in msg_a["message"]

                # Org B must NOT receive Org A's Twilio status broadcast; verify by sending a ping-like control to ws_b
                ws_b.send_json({"type": "confirm_consent"})
                msg_b = ws_b.receive_json()
                assert msg_b == {"type": "status", "message": "Consent recorded for this call."}

                twilio_ws.send_json({"event": "stop"})
                end_a = ws_a.receive_json()
                assert end_a["type"] == "status"
                assert "ended" in end_a["message"]

        # Verify phone numbers were persisted on Org A's Twilio call
        twilio_call = None
        for _ in range(30):
            calls = client.get("/api/calls?channel=twilio", headers=auth_a).json()["calls"]
            if calls and calls[0]["ended_at"] is not None:
                twilio_call = calls[0]
                break
            time.sleep(0.05)
        assert twilio_call is not None
        assert twilio_call["to_number"] == "+919876543210"
        assert twilio_call["from_number"] == "+15551234567"
        assert twilio_call["consent_confirmed"] is True


def test_simulate_utterance_customer_speaker_updates_customer_talk_time(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        _auth, token, _org = _signup(client, "Sim Co", "sim@example.com")
        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"]
        ) as ws:
            ws.receive_json()  # ready
            ws.send_json({
                "type": "simulate_utterance",
                "speaker": "customer",
                "text": "आपका solution थोड़ा expensive लग रहा है, हम अभी Excel use करते हैं।",
            })
            transcript = ws.receive_json()
            signals = ws.receive_json()
            hint = ws.receive_json()
            assert transcript["source"] == "customer-test"
            assert transcript["sentiment"] == "negative"
            assert "objection" in transcript["intents"]
            assert signals["talk_time"]["customer_words"] > 0
            assert signals["talk_time"]["customer_pct"] == 100
            assert hint["type"] == "hint"


def test_team_list_and_login_session_includes_whatsapp_prefs(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _token, _org = _signup(client, "Team Co", "lead@teamco.example.com", name="Lead Admin")
        client.patch("/api/auth/me/whatsapp", headers=auth, json={
            "whatsapp_number": "+919999888877",
            "whatsapp_recap_enabled": True,
        })
        relogin = client.post("/api/auth/login", json={
            "email": "lead@teamco.example.com",
            "password": "correct horse battery",
        }).json()
        assert relogin["user"]["whatsapp_number"] == "+919999888877"
        assert relogin["user"]["whatsapp_recap_enabled"] is True

        client.post("/api/auth/invite", headers=auth, json={
            "name": "Priya Rep",
            "email": "priya@teamco.example.com",
            "password": "correct horse battery",
            "role": "rep",
        })
        team = client.get("/api/auth/team", headers=auth)
        assert team.status_code == 200
        members = team.json()["members"]
        assert len(members) == 2
        assert [m["role"] for m in members] == ["admin", "rep"]


def test_call_analytics_filtering_and_regenerate_summary(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token, _org = _signup(client, "Analytics Co", "mgr@analytics.example.com", name="Maya Manager")
        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"]
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "confirm_consent"})
            ws.receive_json()
            ws.send_json({
                "type": "simulate_utterance",
                "speaker": "customer",
                "text": "This sounds good, I'm interested in moving forward next week.",
            })
            ws.receive_json(); ws.receive_json(); ws.receive_json()

        call_id = None
        for _ in range(40):
            calls = client.get("/api/calls", headers=auth).json()["calls"]
            if calls and calls[0]["coaching_score"] is not None:
                call_id = calls[0]["id"]
                break
            time.sleep(0.05)
        assert call_id is not None

        analytics = client.get("/api/calls/analytics", headers=auth).json()
        assert analytics["total_calls"] == 1
        assert analytics["completed_calls"] == 1
        assert analytics["consented_calls"] == 1
        assert analytics["avg_coaching_score"] is not None
        assert analytics["reps"][0]["name"] == "Maya Manager"

        # Filter by disposition and search query
        matched = client.get("/api/calls?disposition=interested&q=moving+forward", headers=auth).json()["calls"]
        assert len(matched) == 1
        assert matched[0]["rep_name"] == "Maya Manager"
        assert matched[0]["summary_preview"]

        unmatched = client.get("/api/calls?disposition=not_interested", headers=auth).json()["calls"]
        assert unmatched == []

        # On-demand summary regeneration
        regen = client.post(f"/api/calls/{call_id}/summarize", headers=auth)
        assert regen.status_code == 200
        assert regen.json()["disposition"] == "interested"


@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
def test_webhook_test_delivery_endpoint(mock_post, tmp_sqlite_url):
    mock_post.return_value = AsyncMock(status_code=202, text="accepted")
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _token, _org = _signup(client, "HookTest Co", "admin@hooktest.example.com")
        node = client.post("/api/webhooks", headers=auth, json={"url": "https://example.com/hook"}).json()
        res = client.post(f"/api/webhooks/{node['id']}/test", headers=auth)
        assert res.status_code == 200
        assert res.json() == {"ok": True, "status_code": 202}
        assert mock_post.called


def test_playbook_crud_and_live_reload(tmp_sqlite_url, tmp_path):
    with TestClient(create_app(_settings(tmp_sqlite_url, tmp_path))) as client:
        auth, token, _org = _signup(client, "Playbook Co", "admin@pb.example.com")

        initial = client.get("/api/playbooks", headers=auth).json()
        assert len(initial["playbooks"]) == 1

        # Cannot delete the last remaining playbook
        blocked = client.delete(f"/api/playbooks/{initial['playbooks'][0]['slug']}", headers=auth)
        assert blocked.status_code == 400

        # Add a new custom playbook and verify it immediately grounds live hints
        created = client.post("/api/playbooks", headers=auth, json={
            "title": "02 Enterprise Security Compliance",
            "content": "SOC2 Type II and DPDP Act 2023 compliance are included on all enterprise plans with zero audio retention.",
        })
        assert created.status_code == 200
        slug = created.json()["playbook"]["slug"]
        assert created.json()["total_chunks"] >= 2

        with client.websocket_connect(
            "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"]
        ) as ws:
            ws.receive_json()
            ws.send_json({"type": "simulate_utterance", "text": "Do you have SOC2 Type II security compliance?"})
            ws.receive_json(); ws.receive_json()
            hint = ws.receive_json()
            assert any("Security" in s["title"] for s in hint["sources"])

        # Delete the second playbook
        deleted = client.delete(f"/api/playbooks/{slug}", headers=auth)
        assert deleted.status_code == 200
        assert len(client.get("/api/playbooks", headers=auth).json()["playbooks"]) == 1


@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
def test_mobile_call_logger_generates_summary_hint_and_respects_consent(mock_post, tmp_sqlite_url):
    mock_post.return_value = AsyncMock(status_code=200, text="ok")
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, _token, _org = _signup(client, "Mobile Field Co", "rep@mobilefield.example.com", name="Arjun Field")
        client.post("/api/webhooks", headers=auth, json={"url": "https://example.com/mobile-hook"})

        # 1. Without consent: summary & hint generated, but webhook NOT called
        unconsented = client.post("/api/calls/log-mobile", headers=auth, json={
            "to_number": "+919811122233",
            "consent_confirmed": False,
            "turns": [
                {"speaker": "customer", "text": "आपका solution थोड़ा expensive लग रहा है, अभी बजट नहीं है।"},
                {"speaker": "rep", "text": "How does your team currently track missed follow-ups in Excel?"},
            ],
        })
        assert unconsented.status_code == 200
        body_no_consent = unconsented.json()
        assert body_no_consent["channel"] == "mobile"
        assert body_no_consent["consent_confirmed"] is False
        assert body_no_consent["hint"]["text"]
        assert body_no_consent["summary"]["coaching_score"] is not None
        assert not mock_post.called

        # 2. With consent: summary & hint generated AND signed webhook delivered
        consented = client.post("/api/calls/log-mobile", headers=auth, json={
            "to_number": "+919876543210",
            "consent_confirmed": True,
            "turns": [
                {"speaker": "customer", "text": "This sounds good, I'm interested — when can we start onboarding?"},
                {"speaker": "rep", "text": "Which team will use the system first on day one?"},
            ],
        })
        assert consented.status_code == 200
        body_consent = consented.json()
        assert body_consent["consent_confirmed"] is True
        assert body_consent["summary"]["disposition"] == "interested"
        assert mock_post.called

        # Verify mobile calls are filterable in Call History
        mobile_calls = client.get("/api/calls?channel=mobile", headers=auth).json()["calls"]
        assert len(mobile_calls) == 2
        assert mobile_calls[0]["to_number"] in ("+919876543210", "+919811122233")
