"""Auth password and session helpers."""

from job_automation.auth.passwords import hash_password, verify_password
from job_automation.auth.sessions import create_session_token, parse_session_token


def test_password_roundtrip():
    encoded = hash_password("correct-horse")
    assert verify_password("correct-horse", encoded)
    assert not verify_password("wrong-password", encoded)


def test_session_token_roundtrip():
    token = create_session_token(user_id=7, email="user@example.com")
    payload = parse_session_token(token)
    assert payload is not None
    assert payload["uid"] == 7
    assert payload["email"] == "user@example.com"
    assert parse_session_token("not-a-token") is None
    assert parse_session_token(token + "x") is None
