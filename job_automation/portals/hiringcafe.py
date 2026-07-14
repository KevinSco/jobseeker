"""HiringCafe portal worker."""

from __future__ import annotations

import re

from playwright.async_api import Page

from job_automation.logging_config import get_logger, log_event
from job_automation.models.domain import JobDetail, RawJob
from job_automation.portals.base import BasePortalWorker
from job_automation.portals.utils import (
    click_apply_and_get_url,
    extract_job_id_from_url,
    normalize_whitespace,
    safe_attr,
    safe_inner_text,
)

logger = get_logger(__name__)


class HiringCafeWorker(BasePortalWorker):
    portal_name = "hiringcafe"
    base_url = "https://hiring.cafe/"

    async def is_logged_in(self, page: Page) -> bool:
        content = (await page.content()).lower()
        return "sign in" not in content and "log in" not in content

    async def search_jobs(self, page: Page) -> list[RawJob]:
        results: list[RawJob] = []
        for query in self.config.search_queries:
            log_event(logger, f"Searching: {query}", portal=self.portal_name, action="search_query")
            search_url = f"{self.base_url}?q={query.replace(' ', '+')}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)

            for page_num in range(self.config.max_pages_per_query):
                cards = page.locator("[data-testid='job-card'], article, .job-card, a[href*='/job/']")
                count = await cards.count()
                if count == 0:
                    break

                for i in range(min(count, 30)):
                    card = cards.nth(i)
                    title = normalize_whitespace(await card.inner_text()) or "Unknown"
                    href = await card.get_attribute("href")
                    if href and not href.startswith("http"):
                        href = self.base_url.rstrip("/") + href
                    if not href:
                        link = card.locator("a").first
                        if await link.count():
                            href = await link.get_attribute("href")
                            if href and not href.startswith("http"):
                                href = self.base_url.rstrip("/") + href
                    if not href:
                        continue
                    company = None
                    location = None
                    salary = None
                    text = title
                    parts = [p.strip() for p in re.split(r"\n|\|", text) if p.strip()]
                    if parts:
                        title = parts[0]
                    if len(parts) > 1:
                        company = parts[1]
                    if len(parts) > 2:
                        location = parts[2]
                    results.append(
                        RawJob(
                            source_portal=self.portal_name,
                            source_job_id=extract_job_id_from_url(href),
                            job_card_title=title,
                            job_card_company=company,
                            job_card_location=location,
                            job_card_salary=salary,
                            job_card_url=href,
                            portal_job_url=href,
                        )
                    )

                next_btn = page.locator("a:has-text('Next'), button:has-text('Next')").first
                if await next_btn.count() == 0 or page_num + 1 >= self.config.max_pages_per_query:
                    break
                await next_btn.click()
                await page.wait_for_timeout(2000)
        return self._dedupe_cards(results)

    async def open_job(self, page: Page, raw_job: RawJob) -> JobDetail:
        url = raw_job.portal_job_url or raw_job.job_card_url
        if not url:
            raise ValueError("Missing job URL")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)

        title = await safe_inner_text(page, "h1, [data-testid='job-title'], .job-title")
        company = await safe_inner_text(page, "[data-testid='company-name'], .company-name, a[href*='company']")
        location = await safe_inner_text(page, "[data-testid='location'], .location")
        salary = await safe_inner_text(page, "[data-testid='salary'], .salary")
        apply_url = await self.extract_apply_url(page)
        description = await self.extract_description(page)
        raw_html = await page.content()

        return JobDetail(
            source_portal=self.portal_name,
            source_job_id=raw_job.source_job_id or extract_job_id_from_url(url),
            title=title or raw_job.job_card_title,
            company=company or raw_job.job_card_company,
            location=location or raw_job.job_card_location,
            salary_text=salary or raw_job.job_card_salary,
            portal_job_url=url,
            apply_url=apply_url,
            raw_html=raw_html,
            description_text=description,
        )

    async def extract_apply_url(self, page: Page) -> str | None:
        selectors = [
            "a:has-text('Apply')",
            "a:has-text('Apply Now')",
            "a:has-text('Original')",
            "button:has-text('Apply')",
        ]
        return await click_apply_and_get_url(page, selectors)

    async def extract_description(self, page: Page) -> str | None:
        selectors = [
            "[data-testid='job-description']",
            ".job-description",
            "article",
            "main",
        ]
        for selector in selectors:
            text = await safe_inner_text(page, selector)
            if text and len(text) > 200:
                return text
        return await safe_inner_text(page, "body")

    @staticmethod
    def _dedupe_cards(cards: list[RawJob]) -> list[RawJob]:
        seen: set[str] = set()
        unique: list[RawJob] = []
        for card in cards:
            key = card.portal_job_url or card.source_job_id or card.job_card_title or ""
            if key in seen:
                continue
            seen.add(key)
            unique.append(card)
        return unique
