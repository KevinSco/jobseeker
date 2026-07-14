"""Built In portal worker with card expand, industry/ban filtering, and detail ETL."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.async_api import Locator, Page

from job_automation.logging_config import get_logger, log_event
from job_automation.models.domain import Decision, JobDetail, RawJob
from job_automation.portals.base import BasePortalWorker
from job_automation.portals.utils import extract_job_id_from_url, normalize_whitespace, safe_inner_text

logger = get_logger(__name__)

BUILTIN_ORIGIN = "https://builtin.com"


class BuiltInWorker(BasePortalWorker):
    portal_name = "builtin"
    base_url = "https://builtin.com/jobs"

    def __init__(self, *args, banned_companies: set[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.banned_companies = {c.lower().strip() for c in (banned_companies or set()) if c}

    async def is_logged_in(self, page: Page) -> bool:
        content = (await page.content()).lower()
        return "sign in" not in content and "log in" not in content

    async def run(self) -> list[RawJob]:
        page, logged_in = await self.session_manager.ensure_logged_in(self.portal_name)
        if not logged_in:
            from job_automation.portals.base import LoginRequiredError

            raise LoginRequiredError(f"{self.portal_name} requires manual login")

        collected: list[RawJob] = []
        queries = self.config.queries_for_portal(self.portal_name)
        try:
            for query in queries:
                log_event(
                    logger,
                    f"Searching Built In keyword: {query}",
                    portal=self.portal_name,
                    action="search_query",
                )
                await self._open_jobs_board(page)
                await self._apply_default_filters(page)
                await self._submit_keyword_search(page, query)

                for page_num in range(self.config.max_pages_per_query):
                    cards = await self._job_cards(page)
                    if not cards:
                        log_event(
                            logger,
                            f"No cards for '{query}' page {page_num + 1}",
                            portal=self.portal_name,
                            action="search",
                        )
                        break

                    log_event(
                        logger,
                        f"Processing {len(cards)} cards for '{query}' page {page_num + 1}",
                        portal=self.portal_name,
                        action="search",
                    )

                    for index in range(len(cards)):
                        # Re-query cards each time — DOM changes after expand/save/navigation.
                        cards = await self._job_cards(page)
                        if index >= len(cards):
                            break
                        card = cards[index]
                        try:
                            raw = await self._process_card(page, card, query)
                            if raw is None:
                                continue
                            if self.early_duplicate_check and self.early_duplicate_check(
                                raw.source_job_id, raw.portal_job_url
                            ):
                                continue
                            collected.append(raw)
                            log_event(
                                logger,
                                f"Collected: {raw.job_card_title} ({raw.forced_decision or 'pending'})",
                                portal=self.portal_name,
                                job_id=raw.source_job_id or "-",
                                action="extract",
                            )
                        except Exception as exc:
                            log_event(
                                logger,
                                f"Card processing failed: {exc}",
                                portal=self.portal_name,
                                action="extract_error",
                                level=40,
                            )
                            try:
                                if "jobs" not in page.url:
                                    await page.go_back(wait_until="domcontentloaded", timeout=30000)
                                    await page.wait_for_timeout(1500)
                            except Exception:
                                await self._open_jobs_board(page)
                                await self._apply_default_filters(page)
                                await self._submit_keyword_search(page, query)

                    if not await self._go_next_page(page):
                        break

            return _dedupe_cards(collected)
        finally:
            try:
                if await self.session_manager._check_login(page, self.portal_name):
                    await self.session_manager.save_session(self.portal_name)
            except Exception:
                pass
            await page.close()

    async def search_jobs(self, page: Page) -> list[RawJob]:
        # Used by base interface; primary path is run().
        return []

    async def open_job(self, page: Page, raw_job: RawJob) -> JobDetail:
        url = raw_job.portal_job_url or raw_job.job_card_url
        if not url:
            raise ValueError("Missing job URL")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return await self._extract_detail(page, raw_job)

    async def extract_apply_url(self, page: Page) -> str | None:
        href = await page.locator("a#applyButton").first.get_attribute("href")
        if not href:
            return None
        if href.startswith("http"):
            return href
        return urljoin(BUILTIN_ORIGIN, href)

    async def extract_description(self, page: Page) -> str | None:
        for selector in [
            "[data-id='job-description']",
            ".job-description",
            "#job-description",
            "section.description",
            "article",
            "main",
        ]:
            text = await safe_inner_text(page, selector)
            if text and len(text) > 120:
                return text
        return await safe_inner_text(page, "body")

    async def _open_jobs_board(self, page: Page) -> None:
        await page.goto(self.base_url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2000)

    async def _apply_default_filters(self, page: Page) -> None:
        """Default: USA + Fully Remote + Past 24 hours."""
        await self._set_location_usa(page)
        await self._set_fully_remote(page)
        await self._set_past_24_hours(page)
        await page.wait_for_timeout(1200)

    async def _set_location_usa(self, page: Page) -> None:
        locator = page.locator("#locationDropdownInput-JobBoard").first
        if await locator.count() == 0:
            return
        try:
            await locator.click(timeout=5000)
            await locator.fill("")
            await locator.type("USA", delay=80)
            await page.wait_for_timeout(800)
            option = page.locator(
                "[role='option']:has-text('USA'), "
                "li:has-text('USA'), "
                "button:has-text('USA'), "
                "div:has-text('United States')"
            ).first
            if await option.count():
                await option.click(timeout=3000)
            else:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(600)
        except Exception as exc:
            log_event(logger, f"Location filter skipped: {exc}", portal=self.portal_name, action="filter", level=30)

    async def _set_fully_remote(self, page: Page) -> None:
        button = page.locator("#remotePreferenceDropdownButton").first
        if await button.count() == 0:
            return
        try:
            await button.click(timeout=5000)
            await page.wait_for_timeout(400)
            option = page.locator(
                "button:has-text('Fully Remote'), "
                "[role='option']:has-text('Fully Remote'), "
                "label:has-text('Fully Remote'), "
                "li:has-text('Fully Remote')"
            ).first
            if await option.count():
                await option.click(timeout=5000)
            await page.wait_for_timeout(600)
        except Exception as exc:
            log_event(logger, f"Remote filter skipped: {exc}", portal=self.portal_name, action="filter", level=30)

    async def _set_past_24_hours(self, page: Page) -> None:
        button = page.locator("#postedDateDropdownButton").first
        if await button.count() == 0:
            return
        try:
            await button.click(timeout=5000)
            await page.wait_for_timeout(400)
            option = page.locator(
                "button:has-text('Past 24 hours'), "
                "[role='option']:has-text('Past 24 hours'), "
                "label:has-text('Past 24 hours'), "
                "li:has-text('Past 24 hours'), "
                "button:has-text('Past 24 Hours'), "
                "[role='option']:has-text('Past 24 Hours')"
            ).first
            if await option.count():
                await option.click(timeout=5000)
            await page.wait_for_timeout(600)
        except Exception as exc:
            log_event(logger, f"Posted-date filter skipped: {exc}", portal=self.portal_name, action="filter", level=30)

    async def _submit_keyword_search(self, page: Page, query: str) -> None:
        # Prefer the main search bar on the jobs board.
        candidates = [
            "input[placeholder*='Search' i]",
            "input[type='search']",
            "input[name='search']",
            "#search",
        ]
        search = None
        for selector in candidates:
            locator = page.locator(selector).first
            if await locator.count():
                search = locator
                break
        if search is None:
            # Fallback: querystring navigation with common Built In params.
            from urllib.parse import quote_plus

            url = (
                f"{self.base_url}?search={quote_plus(query)}"
                f"&remote=true&country=USA&daysSinceUpdated=1"
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(2000)
            return

        await search.click(timeout=5000)
        await search.fill("")
        await search.press_sequentially(query, delay=120)
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2500)

    async def _job_cards(self, page: Page) -> list[Locator]:
        # Built In job cards typically have a dropdown button; use that as the card root.
        buttons = page.locator("#job-dropdown-button, button#job-dropdown-button")
        count = await buttons.count()
        cards: list[Locator] = []
        for i in range(count):
            btn = buttons.nth(i)
            # Walk up to a card-like container that also has a job title link.
            card = btn.locator(
                "xpath=ancestor::*[.//a[contains(@href,'/job/')]][1]"
            )
            if await card.count() == 0:
                card = btn.locator("xpath=ancestor::div[3]")
            cards.append(card)
        if cards:
            return cards

        # Fallback: any job title links as pseudo-cards.
        links = page.locator("a[href*='/job/']:not([href*='/company/'])")
        link_count = await links.count()
        return [links.nth(i) for i in range(min(link_count, 40))]

    async def _process_card(self, page: Page, card: Locator, query: str) -> RawJob | None:
        company = await self._card_company(card)
        title = await self._card_title(card)
        detail_href = await self._card_job_href(card)
        if not detail_href:
            return None
        detail_url = detail_href if detail_href.startswith("http") else urljoin(BUILTIN_ORIGIN, detail_href)
        location = await self._card_text_match(card, r"(United States|USA|Remote|[A-Za-z ]+, [A-Z]{2})")
        salary = await self._card_text_match(card, r"\$?\d[\d,]*K?(?:\s*-\s*\$?\d[\d,]*K?)?(?:\s*Annually)?")
        work_type = await self._card_work_type(card)

        industry = await self._expand_and_read_industry(card)
        ban_reason = self._card_reject_reason(company, industry)
        if ban_reason:
            await self._click_heart(card)
            return RawJob(
                source_portal=self.portal_name,
                source_job_id=extract_job_id_from_url(detail_url),
                job_card_title=title,
                job_card_company=company,
                job_card_location=location,
                job_card_salary=salary,
                job_card_url=detail_url,
                portal_job_url=detail_url,
                industry=industry,
                work_type=work_type,
                description_text=f"Query: {query}\nIndustry: {industry or ''}\n{ban_reason}",
                forced_decision=Decision.REJECTED,
                forced_decision_reason=ban_reason,
            )

        # Good card: save heart, then open job title (not company).
        await self._click_heart(card)
        await self._click_job_title(card)
        await page.wait_for_load_state("domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)

        detail = await self._extract_detail(
            page,
            RawJob(
                source_portal=self.portal_name,
                source_job_id=extract_job_id_from_url(detail_url),
                job_card_title=title,
                job_card_company=company,
                job_card_location=location,
                job_card_salary=salary,
                job_card_url=detail_url,
                portal_job_url=page.url or detail_url,
                industry=industry,
                work_type=work_type,
            ),
        )

        raw = RawJob(
            source_portal=self.portal_name,
            source_job_id=detail.source_job_id,
            job_card_title=detail.title or title,
            job_card_company=detail.company or company,
            job_card_location=detail.location or location,
            job_card_salary=detail.salary_text or salary,
            job_card_url=detail_url,
            portal_job_url=detail.portal_job_url or detail_url,
            apply_url=detail.apply_url,
            industry=industry,
            work_type=work_type or detail.location,
            raw_html=detail.raw_html,
            description_text=detail.description_text,
        )

        # Return to list for the next card.
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
        except Exception:
            await self._open_jobs_board(page)
            await self._apply_default_filters(page)
            await self._submit_keyword_search(page, query)

        return raw

    def _card_reject_reason(self, company: str | None, industry: str | None) -> str | None:
        if company and company.lower().strip() in self.banned_companies:
            return f"Banned company: {company}"
        if industry:
            text = industry.lower()
            for term in self.config.banned_industry_terms:
                token = term.lower().strip()
                if token and token in text:
                    return f"Banned industry: {industry}"
        return None

    async def _expand_and_read_industry(self, card: Locator) -> str | None:
        dropdown = card.locator("#job-dropdown-button, button#job-dropdown-button").first
        if await dropdown.count() == 0:
            dropdown = card.page.locator("#job-dropdown-button").first
        try:
            if await dropdown.count():
                await dropdown.click(timeout=4000)
                await card.page.wait_for_timeout(700)
        except Exception:
            pass

        industry_node = card.locator("div.mb-md.fs-xs.fw-bold").first
        if await industry_node.count() == 0:
            industry_node = card.page.locator("div.mb-md.fs-xs.fw-bold").first
        if await industry_node.count() == 0:
            return None
        return normalize_whitespace(await industry_node.inner_text())

    async def _click_heart(self, card: Locator) -> None:
        selectors = [
            "button[aria-label*='Save' i]",
            "button[aria-label*='Unsave' i]",
            "button[aria-label*='saved' i]",
            "button[title*='Save' i]",
            "[data-testid*='save' i]",
            "button:has(svg)",
        ]
        for selector in selectors:
            btn = card.locator(selector).first
            if await btn.count() == 0:
                continue
            try:
                await btn.click(timeout=3000)
                await card.page.wait_for_timeout(400)
                return
            except Exception:
                continue

    async def _click_job_title(self, card: Locator) -> None:
        # Prefer job detail links; avoid company profile links.
        title_link = card.locator("a[href*='/job/']:not([href*='/company/'])").first
        if await title_link.count() == 0:
            title_link = card.locator("h2 a, h3 a, a").first
        await title_link.click(timeout=8000)

    async def _card_company(self, card: Locator) -> str | None:
        for selector in [
            "a[href*='/company/']",
            "[data-id='company-title']",
            ".company-title",
            "span:has-text('')",
        ]:
            node = card.locator(selector).first
            if await node.count() == 0:
                continue
            text = normalize_whitespace(await node.inner_text())
            if text and len(text) < 120:
                return text
        # First short line heuristic
        text = normalize_whitespace(await card.inner_text())
        if not text:
            return None
        return text.split("\n")[0][:120]

    async def _card_title(self, card: Locator) -> str | None:
        link = card.locator("a[href*='/job/']:not([href*='/company/'])").first
        if await link.count():
            return normalize_whitespace(await link.inner_text())
        for selector in ["h2", "h3", "[data-id='job-title']"]:
            node = card.locator(selector).first
            if await node.count():
                return normalize_whitespace(await node.inner_text())
        return None

    async def _card_job_href(self, card: Locator) -> str | None:
        link = card.locator("a[href*='/job/']:not([href*='/company/'])").first
        if await link.count() == 0:
            return None
        return await link.get_attribute("href")

    async def _card_work_type(self, card: Locator) -> str | None:
        text = (await card.inner_text()).lower()
        if "fully remote" in text or re.search(r"\bremote\b", text):
            if "hybrid" in text or "in-office" in text:
                return "hybrid_or_remote"
            return "fully_remote"
        if "hybrid" in text:
            return "hybrid"
        return None

    async def _card_text_match(self, card: Locator, pattern: str) -> str | None:
        text = await card.inner_text()
        match = re.search(pattern, text, re.I)
        return normalize_whitespace(match.group(0)) if match else None

    async def _extract_detail(self, page: Page, raw_job: RawJob) -> JobDetail:
        title = await safe_inner_text(page, "h1, .job-title, [data-id='job-title']")
        company = await safe_inner_text(
            page, "a[href*='/company/'], .company-title, [data-company], [data-id='company-title']"
        )
        location = await safe_inner_text(page, ".job-location, .location, [data-id='job-location']")
        salary = await safe_inner_text(page, ".job-salary, .salary, [data-id='job-salary']")
        work_type = await safe_inner_text(
            page, "[data-id='job-remote'], .remote-badge, :text-matches('Remote|Hybrid', 'i')"
        )
        apply_url = await self.extract_apply_url(page)
        description = await self.extract_description(page)
        return JobDetail(
            source_portal=self.portal_name,
            source_job_id=raw_job.source_job_id or extract_job_id_from_url(page.url),
            title=title or raw_job.job_card_title,
            company=company or raw_job.job_card_company,
            location=location or raw_job.job_card_location,
            salary_text=salary or raw_job.job_card_salary,
            portal_job_url=page.url or raw_job.portal_job_url,
            apply_url=apply_url,
            raw_html=await page.content(),
            description_text=description,
        )

    async def _go_next_page(self, page: Page) -> bool:
        next_btn = page.locator(
            "a[rel='next'], "
            "button[aria-label*='Next' i], "
            "a[aria-label*='Next' i], "
            "button:has-text('›'), "
            "a:has-text('›')"
        ).first
        if await next_btn.count() == 0:
            return False
        try:
            disabled = await next_btn.get_attribute("disabled")
            aria_disabled = await next_btn.get_attribute("aria-disabled")
            if disabled is not None or aria_disabled == "true":
                return False
            await next_btn.click(timeout=5000)
            await page.wait_for_timeout(2500)
            return True
        except Exception:
            return False


def _dedupe_cards(cards: list[RawJob]) -> list[RawJob]:
    seen: set[str] = set()
    out: list[RawJob] = []
    for card in cards:
        key = card.portal_job_url or card.source_job_id or ""
        if key and key not in seen:
            seen.add(key)
            out.append(card)
    return out
