"""Tests for portal session persistence."""

from pathlib import Path

import pytest

from job_automation.browser.browser_manager import BrowserManager
from job_automation.browser.session_manager import SessionManager
from job_automation.config.loader import load_rules


@pytest.mark.asyncio
async def test_saved_session_loaded_even_in_guest_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("job_automation.browser.session_manager.SESSIONS_DIR", tmp_path)
    session_file = tmp_path / "builtin.json"
    session_file.write_text('{"cookies": []}', encoding="utf-8")

    config = load_rules()
    browser = BrowserManager(config, headful=False, guest=True)
    session_manager = SessionManager(browser)
    storage_used = None

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def close(self):
            return None

    async def fake_new_page(portal: str, storage_state: str | None = None):
        nonlocal storage_used
        storage_used = storage_state
        return FakePage()

    async def fake_check_login(page, portal: str) -> bool:
        return True

    browser.new_page = fake_new_page  # type: ignore[method-assign]
    session_manager._check_login = fake_check_login  # type: ignore[method-assign]

    page, logged_in = await session_manager.ensure_logged_in("builtin", allow_headful_recovery=False)

    assert logged_in is True
    assert storage_used == str(session_file)


@pytest.mark.asyncio
async def test_session_saved_after_credential_login(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("job_automation.browser.session_manager.SESSIONS_DIR", tmp_path)

    config = load_rules()
    browser = BrowserManager(config, headful=False, guest=True)
    session_manager = SessionManager(browser)
    saved = False

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def close(self):
            return None

    async def fake_new_page(portal: str, storage_state: str | None = None):
        return FakePage()

    async def fake_save_context_state(portal: str, path: str):
        nonlocal saved
        Path(path).write_text('{"cookies": [{"name": "sid", "value": "abc"}]}', encoding="utf-8")
        saved = True

    check_calls = 0

    async def fake_check_login(page, portal: str) -> bool:
        nonlocal check_calls
        check_calls += 1
        return check_calls > 1

    async def fake_login_with_credentials(page, portal, credential, *, check_logged_in):
        return True

    browser.new_page = fake_new_page  # type: ignore[method-assign]
    browser.save_context_state = fake_save_context_state  # type: ignore[method-assign]
    session_manager._check_login = fake_check_login  # type: ignore[method-assign]
    monkeypatch.setattr(
        "job_automation.browser.session_manager.login_with_credentials",
        fake_login_with_credentials,
    )
    monkeypatch.setattr(
        session_manager.credential_store,
        "get",
        lambda portal: object(),
    )

    page, logged_in = await session_manager.ensure_logged_in("builtin", allow_headful_recovery=False)

    assert logged_in is True
    assert saved is True
    assert session_manager.has_session("builtin")
