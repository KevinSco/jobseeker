"""Signed session cookies for JobSeek dashboard auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from job_automation.paths import DATA_DIR, ensure_dirs

COOKIE_NAME = "jobseek_session"
SESSION_TTL_SEC = 60 * 60 * 24 * 30  # 30 days
SECRET_KEY_PATH = DATA_DIR / ".auth_secret"


def _session_secret() -> bytes:
    ensure_dirs()
    env_key = (os.environ.get("JOB_AUTOMATION_SECRET") or "").strip()
    if env_key:
        return hashlib.sha256(env_key.encode("utf-8")).digest()
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_bytes()
    key = os.urandom(32)
    SECRET_KEY_PATH.write_bytes(key)
    try:
        os.chmod(SECRET_KEY_PATH, 0o600)
    except OSError:
        pass
    return key


def create_session_token(*, user_id: int, email: str) -> str:
    payload = {
        "uid": user_id,
        "email": email,
        "exp": int(time.time()) + SESSION_TTL_SEC,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except (json.JSONDecodeError, ValueError):
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    if not payload.get("uid") or not payload.get("email"):
        return None
    return payload
