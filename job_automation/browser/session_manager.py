"""Portal login session persistence."""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Page

from job_automation.browser.browser_manager import BrowserManager
from job_automation.browser.credentials import CredentialStore
from job_automation.browser.portal_login import get_credential, login_with_credentials
from job_automation.logging_config import get_logger, log_event
from job_automation.paths import SESSIONS_DIR, ensure_dirs

logger = get_logger(__name__)

PORTAL_URLS = {
    "hiringcafe": "https://hiring.cafe/",
    "builtin": "https://builtin.com/jobs",
    "jobright": "https://jobright.ai/",
    "glassdoor": "https://www.glassdoor.com/Job/index.htm",
}

LOGIN_INDICATORS = {
    "hiringcafe": ["sign in", "log in", "login"],
    "builtin": ["sign in", "log in"],
    "jobright": ["sign in", "log in"],
    "glassdoor": ["sign in", "create account"],
}


class SessionManager:
    def __init__(self, browser_manager: BrowserManager, credential_store: CredentialStore | None = None):
        self.browser_manager = browser_manager
        self.credential_store = credential_store or CredentialStore()
        ensure_dirs()

    def session_path(self, portal: str) -> Path:
        return SESSIONS_DIR / f"{portal}.json"

    def has_session(self, portal: str) -> bool:
        return self.session_path(portal).exists()

    async def ensure_logged_in(self, portal: str, *, allow_headful_recovery: bool = True) -> tuple[Page, bool]:
        storage = str(self.session_path(portal)) if self.has_session(portal) else None
        page = await self.browser_manager.new_page(portal, storage)
        url = PORTAL_URLS.get(portal, "about:blank")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        logged_in = await self._check_login(page, portal)
        if logged_in:
            log_event(logger, "Session valid", portal=portal, action="session_check")
            return page, True

        log_event(logger, "Session expired or missing", portal=portal, action="session_check", level=30)

        credential = self.credential_store.get(portal)
        if credential:
            logged_in = await login_with_credentials(
                page,
                portal,
                credential,
                check_logged_in=self._check_login,
            )
            if logged_in:
                await self.save_session(portal)
                return page, True

        if allow_headful_recovery and (self.browser_manager.headful or self.browser_manager.uses_kasm):
            if self.browser_manager.uses_kasm:
                log_event(
                    logger,
                    "Waiting for manual login in Kasm (open Watch link in dashboard)",
                    portal=portal,
                    action="manual_login",
                )
            else:
                log_event(logger, "Waiting for manual login", portal=portal, action="manual_login")
            await page.wait_for_timeout(120000)
            logged_in = await self._check_login(page, portal)
            if logged_in:
                await self.save_session(portal)
                return page, True
        await page.close()
        return page, False

    async def save_session(self, portal: str) -> None:
        path = str(self.session_path(portal))
        await self.browser_manager.save_context_state(portal, path)
        log_event(logger, f"Saved session to {path}", portal=portal, action="save_session")

    async def interactive_login(self, portal: str) -> None:
        original_headful = self.browser_manager.headful
        self.browser_manager.headful = True
        page = await self.browser_manager.new_page(portal)
        url = PORTAL_URLS.get(portal, "about:blank")
        await page.goto(url, wait_until="domcontentloaded")
        log_event(logger, "Complete login in browser window (120s)", portal=portal, action="interactive_login")
        await page.wait_for_timeout(120000)
        await self.save_session(portal)
        await page.close()
        self.browser_manager.headful = original_headful

    async def _check_login(self, page: Page, portal: str) -> bool:
        try:
            content = (await page.content()).lower()
        except Exception:
            return False
        indicators = LOGIN_INDICATORS.get(portal, [])
        if not indicators:
            return True
        hits = sum(1 for token in indicators if token in content)
        return hits == 0
