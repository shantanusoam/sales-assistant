from dataclasses import replace

from backend.app.auth import issue_token, verify_token, extract_ws_token
from backend.app.config import Settings


def settings():
    return Settings(demo_access_code="long-demo-access-code", session_signing_key="S" * 48)


def test_token_is_short_lived_and_tamper_resistant():
    s = settings()
    token = issue_token(s, now=1000)
    assert verify_token(token, s, now=1001)
    assert not verify_token(token, s, now=2000)
    assert not verify_token(token + "broken", s, now=1001)
    assert not verify_token(token, replace(s, session_signing_key="Z" * 48), now=1001)


def test_ws_subprotocol_auth_extraction():
    assert extract_ws_token("copilot-v1, auth.abc.def") == "abc.def"
    assert not extract_ws_token("auth.abc.def")
    assert not extract_ws_token("copilot-v1, auth.a, auth.b")
