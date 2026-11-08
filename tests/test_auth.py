from dataclasses import replace

from backend.app.auth import extract_ws_token, hash_password, issue_token, verify_password, verify_token
from backend.app.config import Settings


def settings():
    return Settings(session_signing_key="S" * 48)


def test_password_hash_roundtrip():
    password_hash = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_token_carries_claims_and_is_tamper_resistant():
    s = settings()
    token = issue_token(s, {"user_id": "u1", "org_id": "o1", "role": "admin"}, ttl_seconds=60, now=1000)
    claims = verify_token(token, s, now=1001)
    assert claims is not None
    assert claims["user_id"] == "u1" and claims["org_id"] == "o1" and claims["role"] == "admin"
    assert verify_token(token, s, now=1100) is None  # expired
    assert verify_token(token + "broken", s, now=1001) is None  # tampered
    assert verify_token(token, replace(s, session_signing_key="Z" * 48), now=1001) is None  # wrong key


def test_ws_subprotocol_auth_extraction():
    assert extract_ws_token("copilot-v1, auth.abc.def") == "abc.def"
    assert not extract_ws_token("auth.abc.def")
    assert not extract_ws_token("copilot-v1, auth.a, auth.b")
