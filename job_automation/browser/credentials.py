"""Encrypted local storage for portal login credentials."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from job_automation.paths import DATA_DIR, ensure_dirs

CREDENTIALS_PATH = DATA_DIR / "credentials.enc"
SECRET_KEY_PATH = DATA_DIR / ".credential_key"

SUPPORTED_PORTALS = ("hiringcafe", "builtin", "jobright", "glassdoor")


class PortalCredential(BaseModel):
    username: str
    password: str = Field(repr=False)
    login_url: str | None = None
    email_app_password: str | None = Field(default=None, repr=False)


class PortalCredentialStatus(BaseModel):
    portal: str
    configured: bool
    username: str | None = None
    has_session: bool = False


def _get_fernet():
    import hashlib

    from cryptography.fernet import Fernet

    ensure_dirs()
    env_key = os.environ.get("JOB_AUTOMATION_SECRET")
    if env_key:
        key = base64.urlsafe_b64encode(hashlib.sha256(env_key.encode("utf-8")).digest())
    elif SECRET_KEY_PATH.exists():
        key = SECRET_KEY_PATH.read_bytes()
    else:
        key = Fernet.generate_key()
        SECRET_KEY_PATH.write_bytes(key)
        try:
            os.chmod(SECRET_KEY_PATH, 0o600)
        except OSError:
            pass
    return Fernet(key)


class CredentialStore:
    def __init__(self, path: Path | None = None):
        self.path = path or CREDENTIALS_PATH
        ensure_dirs()

    def _load_all(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        fernet = _get_fernet()
        raw = fernet.decrypt(self.path.read_bytes())
        return json.loads(raw.decode("utf-8"))

    def _save_all(self, data: dict[str, dict]) -> None:
        fernet = _get_fernet()
        payload = fernet.encrypt(json.dumps(data).encode("utf-8"))
        self.path.write_bytes(payload)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def save(self, portal: str, credential: PortalCredential) -> None:
        if portal not in SUPPORTED_PORTALS:
            raise ValueError(f"Unsupported portal: {portal}")
        data = self._load_all()
        data[portal] = credential.model_dump()
        self._save_all(data)

    def get(self, portal: str) -> PortalCredential | None:
        data = self._load_all()
        item = data.get(portal)
        if not item:
            return None
        return PortalCredential.model_validate(item)

    def delete(self, portal: str) -> None:
        data = self._load_all()
        if portal in data:
            del data[portal]
            self._save_all(data)

    def list_status(self) -> list[PortalCredentialStatus]:
        from job_automation.paths import SESSIONS_DIR

        data = self._load_all()
        statuses: list[PortalCredentialStatus] = []
        for portal in SUPPORTED_PORTALS:
            item = data.get(portal)
            session_file = SESSIONS_DIR / f"{portal}.json"
            statuses.append(
                PortalCredentialStatus(
                    portal=portal,
                    configured=bool(item),
                    username=item.get("username") if item else None,
                    has_session=session_file.exists(),
                )
            )
        return statuses
