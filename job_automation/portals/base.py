"""Base portal worker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from playwright.async_api import Page

from job_automation.browser.browser_manager import BrowserManager
from job_automation.browser.session_manager import SessionManager
from job_automation.config.loader import SearchConfig
from job_automation.logging_config import get_logger, log_event
from job_automation.models.domain import JobDetail, RawJob

logger = get_logger(__name__)


class BasePortalWorker(ABC):
    portal_name: str = "base"
    base_url: str = ""

    def __init__(
        self,
        config: SearchConfig,
        browser_manager: BrowserManager,
        session_manager: SessionManager,
        *,
        early_duplicate_check: Callable[[str | None, str | None], bool] | None = None,
        on_job_collected: Callable[[RawJob], Any] | None = None,
    ):
        self.config = config
        self.browser_manager = browser_manager
        self.session_manager = session_manager
        self.early_duplicate_check = early_duplicate_check
        self.on_job_collected = on_job_collected

    async def _emit_job(self, raw: RawJob) -> None:
        if not self.on_job_collected:
            return
        result = self.on_job_collected(raw)
        if hasattr(result, "__await__"):
            await result

    @abstractmethod
    async def is_logged_in(self, page: Page) -> bool:
        ...

    @abstractmethod
    async def search_jobs(self, page: Page) -> list[RawJob]:
        ...

    @abstractmethod
    async def open_job(self, page: Page, raw_job: RawJob) -> JobDetail:
        ...

    @abstractmethod
    async def extract_apply_url(self, page: Page) -> str | None:
        ...

    @abstractmethod
    async def extract_description(self, page: Page) -> str | None:
        ...

    async def run(self) -> list[RawJob]:
        page, logged_in = await self.session_manager.ensure_logged_in(self.portal_name)
        if not logged_in:
            raise LoginRequiredError(f"{self.portal_name} requires manual login")

        collected: list[RawJob] = []
        try:
            cards = await self.search_jobs(page)
            log_event(logger, f"Found {len(cards)} job cards", portal=self.portal_name, action="search")
            for card in cards:
                if self.early_duplicate_check and self.early_duplicate_check(
                    card.source_job_id, card.portal_job_url or card.job_card_url
                ):
                    log_event(
                        logger,
                        f"Skipping duplicate (already in DB): {card.portal_job_url or card.job_card_url}",
                        portal=self.portal_name,
                        job_id=card.source_job_id or "-",
                        action="skip_duplicate",
                    )
                    continue
                try:
                    detail = await self.open_job(page, card)
                    raw = RawJob(
                        source_portal=self.portal_name,
                        source_job_id=detail.source_job_id or card.source_job_id,
                        job_card_title=card.job_card_title or detail.title,
                        job_card_company=card.job_card_company or detail.company,
                        job_card_location=card.job_card_location or detail.location,
                        job_card_salary=card.job_card_salary or detail.salary_text,
                        job_card_url=card.job_card_url,
                        portal_job_url=detail.portal_job_url or card.portal_job_url,
                        apply_url=detail.apply_url,
                        raw_html=detail.raw_html,
                        description_text=detail.description_text,
                    )
                    collected.append(raw)
                    await self._emit_job(raw)
                    log_event(
                        logger,
                        f"Extracted job: {raw.job_card_title}",
                        portal=self.portal_name,
                        job_id=raw.source_job_id or "-",
                        action="extract",
                    )
                except Exception as exc:
                    log_event(
                        logger,
                        f"Job extraction failed: {exc}",
                        portal=self.portal_name,
                        job_id=card.source_job_id or "-",
                        action="extract_error",
                        level=40,
                    )
        finally:
            try:
                if await self.session_manager._check_login(page, self.portal_name):
                    await self.session_manager.save_session(self.portal_name)
            except Exception:
                pass
            await page.close()
        return collected


class LoginRequiredError(Exception):
    pass
