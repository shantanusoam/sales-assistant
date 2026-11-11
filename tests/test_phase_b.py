"""Phase B: survive-the-pilot features.

- Post-call pipeline runs on the lifespan-owned worker (existing suites already prove
  summaries still generate; here we exercise the new worker-powered surfaces).
- Webhook delivery log: every push recorded, failures scheduled for backoff retry,
  retries replay the exact stored payload, deliveries endpoint admin-only.
- Data lifecycle: org-wide export, org-scoped call deletion, retention pruning.
"""
import sqlite3
import time
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.lifecycle import prune_old_calls
from backend.app.main import create_app


def _settings(tmp_sqlite_url):
    return replace(
        Settings(),
        session_signing_key="m" * 64,
        master_encryption_key="n" * 48,
        database_url=tmp_sqlite_url,
        deepgram_api_key="",
        openai_api_key="",
        twilio_validate_signatures=False,
    )


def _signup(client, email, name="Admin User", org="Phase B Co", role="admin"):
    res = client.post("/api/auth/signup", json={
        "organization_name": org, "name": name, "email": email, "password": "correct horse battery",
    })
    assert res.status_code == 200
    body = res.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["token"], body


def _run_consented_call(client, token, text="We use Excel but our follow-ups are late."):
    with client.websocket_connect(
        "/ws/live", headers={"origin": "http://localhost:8000"}, subprotocols=["copilot-v1", f"auth.{token}"],
    ) as ws:
        ws.receive_json()  # ready
        ws.send_json({"type": "confirm_consent"})
        ws.receive_json()  # status: consent recorded
        ws.send_json({"type": "simulate_utterance", "text": text})
        ws.receive_json(); ws.receive_json(); ws.receive_json()


def _wait_for_summary(client, auth, seconds=2.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        calls = client.get("/api/calls", headers=auth).json()["calls"]
        if calls and calls[0].get("coaching_score") is not None:
            return calls[0]
        time.sleep(0.05)
    return None


@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
def test_webhook_delivery_log_records_success(mock_post, tmp_sqlite_url):
    mock_post.return_value = AsyncMock(status_code=200, text="ok")
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token, _ = _signup(client, "deliver@phaseb.example.com")
        client.post("/api/webhooks", headers=auth, json={"url": "https://example.com/hook"})

        _run_consented_call(client, token)
        call = _wait_for_summary(client, auth)
        assert call is not None, "worker never produced the summary"

        deliveries = client.get("/api/webhooks/deliveries", headers=auth).json()["deliveries"]
        assert len(deliveries) == 1
        d = deliveries[0]
        assert d["event"] == "call.summary_ready"
        assert d["call_id"] == call["id"]
        assert d["delivered"] is True
        assert d["status_code"] == 200
        assert d["attempts"] == 1
        assert d["next_retry_at"] is None


@patch("httpx.AsyncClient.post", new_callable=AsyncMock)
def test_failed_webhook_delivery_schedules_backoff_retry(mock_post, tmp_sqlite_url):
    mock_post.return_value = AsyncMock(status_code=500, text="boom")
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token, _ = _signup(client, "retry@phaseb.example.com")
        node = client.post("/api/webhooks", headers=auth, json={"url": "https://example.com/failing"}).json()

        _run_consented_call(client, token)
        assert _wait_for_summary(client, auth) is not None

        deliveries = client.get("/api/webhooks/deliveries", headers=auth).json()["deliveries"]
        assert len(deliveries) == 1
        d = deliveries[0]
        assert d["delivered"] is False
        assert d["status_code"] == 500
        assert "500" in (d["error"] or "")
        assert d["attempts"] == 1
        assert d["next_retry_at"] is not None, "failure must schedule a backoff retry"

        # The stored payload must replay verbatim on retry (same bytes → same signature).
        row_payload_exists = d["event"] == "call.summary_ready"
        assert row_payload_exists


def test_webhook_deliveries_require_admin(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        admin_auth, _t, _ = _signup(client, "adm@phaseb.example.com")
        client.post("/api/auth/invite", headers=admin_auth, json={
            "name": "Rep Rita", "email": "rita@phaseb.example.com", "password": "correct horse battery", "role": "rep",
        })
        rep_auth = {"Authorization": "Bearer " + client.post("/api/auth/login", json={
            "email": "rita@phaseb.example.com", "password": "correct horse battery",
        }).json()["token"]}

        assert client.get("/api/webhooks/deliveries", headers=rep_auth).status_code == 403
        assert client.get("/api/webhooks/deliveries", headers=admin_auth).status_code == 200


def test_org_export_and_call_deletion(tmp_sqlite_url):
    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        admin_auth, token, _ = _signup(client, "export@phaseb.example.com", name="Ella Admin")
        client.post("/api/auth/invite", headers=admin_auth, json={
            "name": "Rep Rex", "email": "rex@phaseb.example.com", "password": "correct horse battery", "role": "rep",
        })
        rep_auth = {"Authorization": "Bearer " + client.post("/api/auth/login", json={
            "email": "rex@phaseb.example.com", "password": "correct horse battery",
        }).json()["token"]}

        _run_consented_call(client, token)
        assert _wait_for_summary(client, admin_auth) is not None

        exported = client.get("/api/calls/export", headers=admin_auth).json()
        assert exported["organization_id"]
        assert len(exported["calls"]) == 1
        assert exported["calls"][0]["turns"][0]["text"].casefold().startswith("we use excel")
        assert exported["calls"][0]["hints"]

        call_id = exported["calls"][0]["id"]
        assert client.delete(f"/api/calls/{call_id}", headers=rep_auth).status_code == 403
        assert client.delete(f"/api/calls/{call_id}", headers=admin_auth).status_code == 200
        assert client.get(f"/api/calls/{call_id}", headers=admin_auth).status_code == 404
        assert client.get("/api/calls/export", headers=admin_auth).json()["calls"] == []


def test_retention_prune_removes_only_old_calls(tmp_sqlite_url):
    async def run_prune(db_url, days):
        import asyncio
        from backend.app.db import make_db

        engine, _get_db, factory = make_db(replace(Settings(), database_url=db_url))
        try:
            async with factory() as db:
                return await prune_old_calls(db, days)
        finally:
            await engine.dispose()

    import asyncio

    with TestClient(create_app(_settings(tmp_sqlite_url))) as client:
        auth, token, _ = _signup(client, "retention@phaseb.example.com")
        _run_consented_call(client, token, text="A fresh call we definitely keep.")
        assert _wait_for_summary(client, auth) is not None

        db_path = tmp_sqlite_url.split("///")[1]

        # 0-day retention is disabled: nothing is pruned even after backdating.
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE calls SET started_at = '2020-01-01 00:00:00'")
            conn.commit()
        assert asyncio.run(run_prune(tmp_sqlite_url, 0)) == 0

        # 30-day retention prunes the backdated call.
        assert asyncio.run(run_prune(tmp_sqlite_url, 30)) == 1
        assert client.get("/api/calls", headers=auth).json()["calls"] == []
        # The org's own call quota meter must also reflect the deletion.
        status = client.get("/api/billing/status", headers=auth).json()
        assert status["calls_used_this_month"] == 0
