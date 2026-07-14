"""Glassdoor portal worker."""

from __future__ import annotations

from urllib.parse import quote_plus

from playwright.async_api import Page

from job_automation.logging_config import get_logger, log_event
from job_automation.models.domain import JobDetail, RawJob
from job_automation.portals.base import BasePortalWorker
from job_automation.portals.utils import (
    click_apply_and_get_url,
    extract_job_id_from_url,
    normalize_whitespace,
    safe_inner_text,
)

logger = get_logger(__name__)


class GlassdoorWorker(BasePortalWorker):
    portal_name = "glassdoor"
    base_url = "https://www.glassdoor.com/Job/index.htm"

    async def is_logged_in(self, page: Page) -> bool:
        content = (await page.content()).lower()
        return "sign in" not in content or "my jobs" in content

    async def search_jobs(self, page: Page) -> list[RawJob]:
        results: list[RawJob] = []
        for query in self.config.search_queries:
            log_event(logger, f"Searching: {query}", portal=self.portal_name, action="search_query")
            url = f"{self.base_url}?keyword={quote_plus(query)}&remoteWorkType=1"
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(3000)
            cards = page.locator("[data-test='jobListing'], li[data-id], .react-job-listing")
            count = await cards.count()
            for i in range(min(count, 20)):
                card = cards.nth(i)
                link = card.locator("a[href*='/job-listing/'], a.jobLink").first
                if await link.count() == 0:
                    continue
                href = await link.get_attribute("href")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://www.glassdoor.com" + href
                title = normalize_whitespace(await link.inner_text()) or "Unknown"
                results.append(
                    RawJob(
                        source_portal=self.portal_name,
                        source_job_id=extract_job_id_from_url(href),
                        job_card_title=title,
                        portal_job_url=href,
                        job_card_url=href,
                    )
                )
        return _dedupe_cards(results)

    async def open_job(self, page: Page, raw_job: RawJob) -> JobDetail:
        url = raw_job.portal_job_url or raw_job.job_card_url
        if not url:
            raise ValueError("Missing job URL")
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2000)
        title = await safe_inner_text(page, "[data-test='job-title'], h1")
        company = await safe_inner_text(page, "[data-test='employer-name'], .employerName")
        location = await safe_inner_text(page, "[data-test='location'], .location")
        salary = await safe_inner_text(page, "[data-test='detailSalary'], .salary")
        apply_url = await self.extract_apply_url(page)
        description = await self.extract_description(page)
        return JobDetail(
            source_portal=self.portal_name,
            source_job_id=raw_job.source_job_id or extract_job_id_from_url(url),
            title=title or raw_job.job_card_title,
            company=company or raw_job.job_card_company,
            location=location or raw_job.job_card_location,
            salary_text=salary or raw_job.job_card_salary,
            portal_job_url=url,
            apply_url=apply_url,
            raw_html=await page.content(),
            description_text=description,
        )

    async def extract_apply_url(self, page: Page) -> str | None:
        return await click_apply_and_get_url(
            page,
            ["a:has-text('Apply on employer site')", "a:has-text('Apply')", "button:has-text('Apply')"],
        )

    async def extract_description(self, page: Page) -> str | None:
        for selector in ["[data-test='description'], .jobDescriptionContent", "div.desc", "main"]:
            text = await safe_inner_text(page, selector)
            if text and len(text) > 200:
                return text
        return await safe_inner_text(page, "body")


def _dedupe_cards(cards: list[RawJob]) -> list[RawJob]:
    seen: set[str] = set()
    out: list[RawJob] = []
    for card in cards:
        key = card.portal_job_url or card.source_job_id or ""
        if key and key not in seen:
            seen.add(key)
            out.append(card)
    return out
