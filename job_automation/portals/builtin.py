"""Built In portal worker with card expand, industry/ban filtering, and detail ETL."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

from playwright.async_api import Locator, Page

from job_automation.etl.cleaner import normalize_job_location
from job_automation.etl.posted_parser import parse_posted_relative
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
        self._current_list_url: str | None = None

    async def is_logged_in(self, page: Page) -> bool:
        content = (await page.content()).lower()
        return "sign in" not in content and "log in" not in content

    async def run(self) -> list[RawJob]:
        page, logged_in = await self.session_manager.ensure_logged_in(self.portal_name)
        if not logged_in:
            from job_automation.portals.base import LoginRequiredError

            raise LoginRequiredError(f"{self.portal_name} requires manual login")

        collected: list[RawJob] = []
        seen_urls: set[str] = set()
        queries = self.config.queries_for_portal(self.portal_name)
        try:
            for query in queries:
                log_event(
                    logger,
                    f"Searching Built In keyword: {query}",
                    portal=self.portal_name,
                    action="search_query",
                )
                try:
                    await self._open_filtered_search(page, query)
                except Exception as exc:
                    log_event(
                        logger,
                        f"Search setup failed for '{query}': {exc}",
                        portal=self.portal_name,
                        action="search_error",
                        level=40,
                    )
                    continue

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
                            href = await self._card_job_href(card)
                            if not href:
                                continue
                            detail_url = href if href.startswith("http") else urljoin(BUILTIN_ORIGIN, href)
                            source_job_id = extract_job_id_from_url(detail_url)
                            url_key = detail_url.rstrip("/")

                            # Duplicate filter: skip before heart/detail/ETL — just move to next card.
                            # Keep mark_duplicates rule in orchestrator for near-duplicates that still open.
                            if url_key in seen_urls or (
                                self.early_duplicate_check
                                and self.early_duplicate_check(source_job_id, detail_url)
                            ):
                                log_event(
                                    logger,
                                    f"Skipping duplicate — move to next job: {detail_url}",
                                    portal=self.portal_name,
                                    job_id=source_job_id or "-",
                                    action="skip_duplicate",
                                )
                                continue

                            # One job at a time: expand/identify → save → then next dropdown.
                            raw = await self._process_card(page, card, query)
                            if raw is None:
                                log_event(
                                    logger,
                                    f"Card produced no job — move to next: {detail_url}",
                                    portal=self.portal_name,
                                    job_id=source_job_id or "-",
                                    action="skip_empty",
                                    level=30,
                                )
                                continue
                            seen_urls.add(url_key)
                            collected.append(raw)
                            await self._emit_job(raw)
                            log_event(
                                logger,
                                f"Identified and saved — move to next job: {raw.job_card_title} "
                                f"({raw.forced_decision or 'pending'})",
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
                            # List page should still be open (detail uses a new tab).
                            try:
                                if "jobs" not in (page.url or ""):
                                    await self._return_to_list(page, query)
                            except Exception:
                                await self._return_to_list(page, query)

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
        apply_url, _is_easy = await self._resolve_apply(page)
        return apply_url

    async def _resolve_apply(self, page: Page) -> tuple[str | None, bool]:
        """Return (external_apply_url, is_easy_apply).

        Easy Apply uses Built In's internal /apply/job/ flow — do not save that link.
        Detect via sticky-bar buttons (class contains job-post-sticky-bar-btn) or badges
        without waiting on a missing #applyButton (that hang was several seconds).
        """
        # 1) Sticky footer: apply vs save — Easy Apply text means internal apply.
        sticky = page.locator("[class*='job-post-sticky-bar-btn']")
        sticky_count = await sticky.count()
        for i in range(sticky_count):
            btn = sticky.nth(i)
            text = (normalize_whitespace(await btn.inner_text()) or "").lower()
            if "save" in text and "apply" not in text:
                continue
            if "easy apply" in text or "easyapply" in text.replace(" ", ""):
                log_event(
                    logger,
                    "Easy Apply detected on sticky bar — skipping internal apply link",
                    portal=self.portal_name,
                    action="easy_apply",
                )
                return None, True
            if "apply" in text:
                href = await self._href_from_apply_control(btn)
                if href and self._is_builtin_easy_apply_url(href):
                    return None, True
                if href and self._is_external_apply_url(href):
                    return href, False

        # 2) Header / body Easy Apply badge (lightning + "Easy Apply").
        badge = page.locator(
            "text=/^\\s*Easy Apply\\s*$/i, "
            "[class*='easy-apply'], "
            "[class*='EasyApply'], "
            "span:has-text('Easy Apply'), "
            "div:has-text('Easy Apply')"
        )
        # Prefer a tight match: short badge text, not the whole page.
        badge_count = min(await badge.count(), 12)
        for i in range(badge_count):
            text = (normalize_whitespace(await badge.nth(i).inner_text()) or "").lower()
            if text == "easy apply" or text.startswith("easy apply"):
                if len(text) <= 24:
                    log_event(
                        logger,
                        "Easy Apply badge detected — skipping internal apply link",
                        portal=self.portal_name,
                        action="easy_apply",
                    )
                    return None, True

        # 3) Classic apply anchor (external ATS). Use count() so missing nodes don't wait.
        for selector in (
            "a#applyButton",
            "a[id*='apply' i]",
            "a[href*='greenhouse.io']",
            "a[href*='lever.co']",
            "a[href*='ashbyhq.com']",
            "a[href*='workday']",
            "a[href*='jobs.']",
            "a[href*='careers.']",
        ):
            links = page.locator(selector)
            if await links.count() == 0:
                continue
            href = await links.first.get_attribute("href")
            if not href:
                continue
            absolute = href if href.startswith("http") else urljoin(BUILTIN_ORIGIN, href)
            if self._is_builtin_easy_apply_url(absolute):
                return None, True
            if self._is_external_apply_url(absolute):
                return absolute, False

        return None, False

    @staticmethod
    def _is_builtin_easy_apply_url(href: str) -> bool:
        lowered = href.lower().strip()
        return "builtin.com" in lowered and "/apply/" in lowered

    @staticmethod
    def _is_external_apply_url(href: str) -> bool:
        lowered = href.lower().strip()
        if not lowered.startswith("http"):
            return False
        if "builtin.com" in lowered:
            return False
        return True

    async def _href_from_apply_control(self, control: Locator) -> str | None:
        href = await control.get_attribute("href")
        if href:
            return href if href.startswith("http") else urljoin(BUILTIN_ORIGIN, href)
        link = control.locator("a[href]").first
        if await link.count() == 0:
            # Control may itself be nested inside an <a>.
            parent_link = control.locator("xpath=ancestor::a[@href][1]").first
            if await parent_link.count() == 0:
                return None
            href = await parent_link.get_attribute("href")
        else:
            href = await link.get_attribute("href")
        if not href:
            return None
        return href if href.startswith("http") else urljoin(BUILTIN_ORIGIN, href)

    async def extract_description(self, page: Page) -> str | None:
        # Built In job body is always in a div whose id starts with "job-post-body-".
        text = await safe_inner_text(page, "div[id^='job-post-body']")
        if text:
            return text
        return None

    async def _open_jobs_board(self, page: Page) -> None:
        await page.goto(self.base_url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2000)

    def _search_url(self, query: str) -> str:
        # Keyword only via URL; job type / location / posted date are applied in order after.
        return f"{self.base_url}?search={quote_plus(query)}"

    async def _open_filtered_search(self, page: Page, query: str) -> None:
        url = self._search_url(query)
        log_event(logger, f"Opening search URL: {url}", portal=self.portal_name, action="search_query")
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2500)
        self._current_list_url = page.url
        await self._apply_default_filters(page)
        self._current_list_url = page.url
        await page.wait_for_timeout(1000)

    async def _return_to_list(self, page: Page, query: str) -> None:
        target = self._current_list_url or self._search_url(query)
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(1500)
        except Exception:
            await self._open_filtered_search(page, query)

    async def _safe_click(self, locator: Locator, *, timeout: int = 5000) -> bool:
        try:
            if await locator.count() == 0:
                return False
            await locator.scroll_into_view_if_needed(timeout=timeout)
            await locator.click(timeout=timeout, force=False)
            return True
        except Exception:
            try:
                # Sticky Built In header often intercepts normal clicks.
                await locator.click(timeout=timeout, force=True)
                return True
            except Exception:
                return False

    async def _apply_default_filters(self, page: Page) -> None:
        """Filter order after keyword: job type → location → posted date."""
        await self._set_fully_remote(page)
        await self._set_location_usa(page)
        await self._set_past_24_hours(page)
        await page.wait_for_timeout(800)

    async def _set_location_usa(self, page: Page) -> None:
        locator = page.locator("#locationDropdownInput-JobBoard").first
        if await locator.count() == 0:
            return
        try:
            # Skip if already set to United States / USA.
            current = normalize_whitespace(await locator.input_value()) or ""
            if current.lower() in {"united states", "usa", "us"}:
                log_event(
                    logger,
                    f"Location already {current} — skip",
                    portal=self.portal_name,
                    action="filter",
                )
                return

            await self._safe_click(locator)
            await locator.fill("")
            await locator.type("United States", delay=70)
            # Wait for Alpine location dropdown results to render.
            menu = page.locator(
                "ul[x-ref='locationDropdownMenu'], "
                "ul.dropdown-menu[aria-labelledby='locationDropdownInput-JobBoard'], "
                "ul.dropdown-menu"
            ).first
            try:
                await menu.wait_for(state="visible", timeout=1000)
            except Exception:
                await page.wait_for_timeout(500)

            # Built In renders results as label.list-group-item-action inside the menu.
            option = page.locator(
                "ul[x-ref='locationDropdownMenu'] label.list-group-item-action:has-text('United States'), "
                "ul.dropdown-menu label.list-group-item-action:has-text('United States'), "
                "label.list-group-item-action:has-text('United States'), "
                "ul.dropdown-menu >> text=United States"
            ).first
            if await option.count() == 0:
                option = page.locator(
                    "ul[x-ref='locationDropdownMenu'] label.list-group-item-action:has-text('USA'), "
                    "label.list-group-item-action:has-text('USA')"
                ).first

            if await option.count():
                await option.scroll_into_view_if_needed(timeout=3000)
                await self._safe_click(option, timeout=4000)
                log_event(
                    logger,
                    "Location filter set via dropdown menu: United States",
                    portal=self.portal_name,
                    action="filter",
                )
            else:
                # Fallback: arrow-down + enter on first suggestion.
                await page.keyboard.press("ArrowDown")
                await page.wait_for_timeout(200)
                await page.keyboard.press("Enter")
                log_event(
                    logger,
                    "Location dropdown label not found — used keyboard select",
                    portal=self.portal_name,
                    action="filter",
                    level=30,
                )
            await page.wait_for_timeout(600)
        except Exception as exc:
            log_event(logger, f"Location filter skipped: {exc}", portal=self.portal_name, action="filter", level=30)

    async def _set_fully_remote(self, page: Page) -> None:
        button = page.locator("#remotePreferenceDropdownButton").first
        if await button.count() == 0:
            return
        try:
            if not await self._safe_click(button):
                raise RuntimeError("remote dropdown not clickable")
            await page.wait_for_timeout(400)
            option = page.locator(
                "button:has-text('Fully Remote'), "
                "[role='option']:has-text('Fully Remote'), "
                "label:has-text('Fully Remote'), "
                "li:has-text('Fully Remote')"
            ).first
            if await option.count():
                await self._safe_click(option)
            await page.wait_for_timeout(500)
        except Exception as exc:
            log_event(logger, f"Remote filter skipped: {exc}", portal=self.portal_name, action="filter", level=30)

    async def _set_past_24_hours(self, page: Page) -> None:
        button = page.locator("#postedDateDropdownButton").first
        if await button.count() == 0:
            return
        try:
            # Re-clicking when already selected resets the filter on Built In.
            label = normalize_whitespace(await button.inner_text()) or ""
            if "past 24 hour" in label.lower():
                log_event(
                    logger,
                    "Posted date already Past 24 hours — skip click",
                    portal=self.portal_name,
                    action="filter",
                )
                return
            if not await self._safe_click(button):
                raise RuntimeError("posted-date dropdown not clickable")
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
                await self._safe_click(option)
            await page.wait_for_timeout(500)
        except Exception as exc:
            log_event(logger, f"Posted-date filter skipped: {exc}", portal=self.portal_name, action="filter", level=30)

    async def _submit_keyword_search(self, page: Page, query: str) -> None:
        """Deprecated path kept for compatibility; URL search is preferred."""
        await self._open_filtered_search(page, query)

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
        company_profile_url = await self._card_company_url(card)
        title = await self._card_title(card)
        detail_href = await self._card_job_href(card)
        if not detail_href:
            return None
        detail_url = detail_href if detail_href.startswith("http") else urljoin(BUILTIN_ORIGIN, detail_href)
        location = await self._card_location(card)
        # Prefer explicit salary shapes ($120K, 124K-209K Annually); avoid lone digits.
        salary = await self._card_text_match(
            card,
            r"(?:\$\d[\d,]*(?:\.\d+)?(?:\s*-\s*\$?\d[\d,]*(?:\.\d+)?)?\s*K?(?:\s*Annually)?|"
            r"\d{2,3}K(?:\s*-\s*\d{2,3}K)?(?:\s*Annually)?)",
        )
        work_type = await self._card_work_type(card)
        card_posted_text = await self._card_posted_text(card)
        card_posted = parse_posted_relative(card_posted_text)

        # Expand job-card dropdown for industry / requirements / top skills (ban check).
        industry, requirements_summary, top_skills = await self._expand_and_read_card_meta(card)
        ban_reason = self._card_reject_reason(company, industry)
        if ban_reason:
            await self._click_heart(card)
            return RawJob(
                source_portal=self.portal_name,
                source_job_id=extract_job_id_from_url(detail_url),
                job_card_title=title,
                job_card_company=company,
                company_url=company_profile_url,
                company_headline=None,
                job_card_location=location,
                job_card_salary=salary,
                job_card_url=detail_url,
                portal_job_url=detail_url,
                industry=industry,
                work_type=work_type,
                posted_text=card_posted.raw_text or card_posted_text,
                posted_at=card_posted.posted_at,
                is_reposted=card_posted.is_reposted,
                top_skills=top_skills,
                match_background_text=requirements_summary,
                description_text=f"Query: {query}\nIndustry: {industry or ''}\n{ban_reason}",
                forced_decision=Decision.REJECTED,
                forced_decision_reason=ban_reason,
            )

        # Good card: company profile → View Website (side tab), stay on list, then open detail.
        company_url = await self._fetch_company_website_from_profile(page, company_profile_url)
        if not company_url:
            company_url = company_profile_url

        await self._click_heart(card)
        detail = await self._extract_detail_in_new_tab(
            page,
            detail_url,
            RawJob(
                source_portal=self.portal_name,
                source_job_id=extract_job_id_from_url(detail_url),
                job_card_title=title,
                job_card_company=company,
                company_url=company_url,
                company_headline=None,
                job_card_location=location,
                job_card_salary=salary,
                job_card_url=detail_url,
                portal_job_url=detail_url,
                industry=industry,
                work_type=work_type,
                posted_text=card_posted.raw_text or card_posted_text,
                posted_at=card_posted.posted_at,
                is_reposted=card_posted.is_reposted,
                top_skills=top_skills,
                match_background_text=requirements_summary,
            ),
        )

        detail_posted = parse_posted_relative(detail.posted_text)
        posted_text = detail.posted_text or card_posted.raw_text or card_posted_text
        posted_at = detail_posted.posted_at or detail.posted_at or card_posted.posted_at
        is_reposted = bool(detail_posted.is_reposted or detail.is_reposted or card_posted.is_reposted)

        # Prefer list-card industry / requirements / top skills over detail-page values.
        list_skills = top_skills or []
        return RawJob(
            source_portal=self.portal_name,
            source_job_id=detail.source_job_id,
            job_card_title=detail.title or title,
            job_card_company=detail.company or company,
            company_url=detail.company_url or company_url,
            # company_headline = company mission; requirements stay in match_background_text.
            company_headline=detail.company_headline,
            job_card_location=detail.location or location,
            job_card_salary=detail.salary_text or salary,
            job_card_url=detail_url,
            portal_job_url=detail.portal_job_url or detail_url,
            apply_url=detail.apply_url,
            is_easy_apply=bool(detail.is_easy_apply),
            industry=industry or detail.industry,
            work_type=detail.work_type or work_type,
            experience_level=detail.experience_level,
            posted_text=posted_text,
            posted_at=posted_at,
            is_reposted=is_reposted,
            top_skills=list_skills,
            skills_required=list_skills or detail.skills_required,
            # Requirements summary must only ever come from the list-card dropdown, never the detail page.
            match_background_text=requirements_summary,
            raw_html=detail.raw_html,
            description_text=detail.description_text,
        )

    async def _extract_detail_in_new_tab(self, list_page: Page, detail_url: str, raw_job: RawJob) -> JobDetail:
        """Open job detail in a new tab, scrape it, then close — keep the list tab."""
        detail_page = await list_page.context.new_page()
        try:
            await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=90000)
            await detail_page.wait_for_timeout(1500)
            return await self._extract_detail(detail_page, raw_job)
        finally:
            try:
                await detail_page.close()
            except Exception:
                pass
            try:
                await list_page.bring_to_front()
            except Exception:
                pass

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

    async def _expand_and_read_card_meta(
        self, card: Locator
    ) -> tuple[str | None, str | None, list[str]]:
        """Expand list-card dropdown and read industry, requirements summary, top skills."""
        dropdown = card.locator("#job-dropdown-button, button#job-dropdown-button").first
        try:
            if await dropdown.count():
                await dropdown.scroll_into_view_if_needed(timeout=4000)
                await self._safe_click(dropdown, timeout=4000)
                await card.page.wait_for_timeout(800)
        except Exception as exc:
            log_event(
                logger,
                f"Job dropdown expand failed: {exc}",
                portal=self.portal_name,
                action="expand_card",
                level=30,
            )

        industry = await self._card_industry(card)
        requirements = await self._card_requirements_summary(card)
        top_skills = await self._card_top_skills(card)
        return industry, requirements, top_skills

    async def _expand_and_read_industry(self, card: Locator) -> str | None:
        """Compatibility wrapper — prefer _expand_and_read_card_meta."""
        industry, _, _ = await self._expand_and_read_card_meta(card)
        return industry

    async def _card_industry(self, card: Locator) -> str | None:
        # Industry is inside the expanded drop-data panel; do not read from other cards.
        industry_node = card.locator(
            "[id^='drop-data-'] div.mb-md.fs-xs.fw-bold, "
            "div.collapse.show div.mb-md.fs-xs.fw-bold, "
            "div.mb-md.fs-xs.fw-bold, "
            "div.fs-xs.fw-bold.mb-md, "
            ".industry, "
            "[data-id='industry']"
        ).first
        if await industry_node.count() == 0:
            return None
        text = normalize_whitespace(await industry_node.inner_text())
        if not text or text.lower().startswith("top skill"):
            return None
        return text

    async def _card_requirements_summary(self, card: Locator) -> str | None:
        """Job requirements summary — full text from the expanded drop-data-* list card.

        Exact Built In markup (from the card's own dropdown, never the detail page):
            <div id="drop-data-{jobId}" class="collapse show">
              ...
              <div class="fs-sm fw-regular mb-md text-gray-04">FULL REQUIREMENTS TEXT</div>
        Take the entire string as-is — no truncation or heuristic rejection.
        """
        node = card.locator(
            "[id^='drop-data-'] div.fs-sm.fw-regular.mb-md.text-gray-04"
        ).first
        if await node.count() == 0:
            return None
        text = normalize_whitespace(await node.inner_text())
        return text or None

    @staticmethod
    def _looks_like_requirements_summary(text: str | None) -> bool:
        if not text:
            return False
        lowered = text.lower().strip()
        if len(lowered) < 24:
            return False
        if lowered.startswith("top skill"):
            return False
        if lowered in {"industry", "company", "skills required"}:
            return False
        # Reject whole-card dumps mistakenly scraped as summary.
        if "be an early applicant" in lowered:
            return False
        if lowered.count("posted") >= 2:
            return False
        if re.search(r"\b(?:posted|reposted)\b.+\b(?:ago|yesterday|today)\b", lowered) and len(text) > 220:
            return False
        # Industry tags are usually short bullet lists without sentences.
        if "•" in text and "." not in text and len(text) < 80:
            return False
        return True

    async def _card_top_skills(self, card: Locator) -> list[str]:
        """Read Built In list-card Top Skills chips from the expanded drop-data-* panel.

        Exact Built In markup:
            <span class="fs-xs fw-bold text-uppercase text-gray-04 flex-shrink-0">Top Skills:</span>
            <span class="d-md-inline ps-md-sm">
              <span class="fs-xs text-gray-04 mx-sm">Skill</span>...
            </span>
        The chips' parent is `span.d-md-inline.ps-md-sm` — read every child span's full text.
        """
        skills: list[str] = []
        container = card.locator("[id^='drop-data-'] span.d-md-inline.ps-md-sm").first
        if await container.count() == 0:
            return skills
        chips = container.locator("span")
        count = await chips.count()
        for i in range(count):
            text = normalize_whitespace(await chips.nth(i).inner_text())
            if not text:
                continue
            if text not in skills:
                skills.append(text)
        return skills

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
            if await self._safe_click(btn, timeout=3000):
                await card.page.wait_for_timeout(400)
                return

    async def _click_job_title(self, card: Locator) -> None:
        # Prefer job detail links; avoid company profile links.
        title_link = card.locator("a[href*='/job/']:not([href*='/company/'])").first
        if await title_link.count() == 0:
            title_link = card.locator("h2 a, h3 a, a").first
        await title_link.click(timeout=8000)

    async def _card_company(self, card: Locator) -> str | None:
        for selector in [
            "#company-title",
            "a#company-title",
            "[id='company-title']",
            "a[href*='/company/']",
            "[data-id='company-title']",
            ".company-title",
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

    async def _card_company_url(self, card: Locator) -> str | None:
        # Built In list cards expose the company link as id="company-title".
        link = card.locator("#company-title, a#company-title, [id='company-title']").first
        if await link.count() == 0:
            link = card.locator("a[href*='/company/']").first
        if await link.count() == 0:
            return None
        href = await link.get_attribute("href")
        if not href:
            return None
        if href.startswith("http"):
            return href
        return urljoin(BUILTIN_ORIGIN, href)

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

    async def _card_location(self, card: Locator) -> str | None:
        """Read location from Built In list card; expand multi-location tooltip when needed."""
        multi = await self._read_multi_locations(card, card.page)
        if multi:
            return multi

        # Single-location row (pin icon).
        icon = card.locator("i.fa-location-dot, i[class*='fa-location']").first
        if await icon.count():
            row = icon.locator(
                "xpath=ancestor::div[contains(@class,'d-flex') and contains(@class,'align-items')][1]"
            )
            if await row.count() == 0:
                row = icon.locator("xpath=ancestor::div[contains(@class,'d-flex')][1]")
            if await row.count():
                text = normalize_whitespace(await row.inner_text())
                cleaned = normalize_job_location(text)
                if cleaned:
                    return cleaned

        # Fallback patterns on card text.
        text_hit = await self._card_text_match(
            card,
            r"Hiring Remotely in [A-Za-z ,]+|"
            r"Remote(?:ly)? in [A-Za-z ,]+|"
            r"United States|USA|"
            r"[A-Za-z .]+,\s*[A-Z]{2}(?:,\s*USA)?",
        )
        return normalize_job_location(text_hit)

    async def _page_location(self, page: Page) -> str | None:
        """Location from job detail page (supports multi-location hover)."""
        multi = await self._read_multi_locations(page, page)
        if multi:
            return multi
        location = await self._detail_icon_row_text(page, "fa-location-dot")
        if not location:
            location = await safe_inner_text(page, ".job-location, .location, [data-id='job-location']")
        return normalize_job_location(location)

    async def _read_multi_locations(self, root: Locator | Page, page: Page) -> str | None:
        """If UI shows 'N Locations', hover and collect places from the opened tooltip."""
        trigger = root.locator(
            "a:has-text('Locations'), "
            "button:has-text('Locations'), "
            "span:has-text('Locations'), "
            "div:has-text('Locations')"
        ).filter(has_text=re.compile(r"^\s*\d+\s+Locations?\s*$", re.I)).first
        if await trigger.count() == 0:
            # Broader: any control whose visible text is like "8 Locations".
            candidates = root.locator("a, button, span, div")
            count = min(await candidates.count(), 40)
            trigger = None
            for i in range(count):
                node = candidates.nth(i)
                try:
                    text = normalize_whitespace(await node.inner_text()) or ""
                except Exception:
                    continue
                if re.fullmatch(r"\d+\s+Locations?", text, flags=re.I):
                    trigger = node
                    break
            if trigger is None:
                return None

        try:
            await trigger.scroll_into_view_if_needed(timeout=3000)
            await trigger.hover(timeout=3000)
            await page.wait_for_timeout(500)
        except Exception as exc:
            log_event(
                logger,
                f"Multi-location hover failed: {exc}",
                portal=self.portal_name,
                action="location",
                level=30,
            )
            return None

        tip = page.locator(
            ".tippy-content:visible, "
            "[data-popper-placement]:visible, "
            "[role='tooltip']:visible, "
            ".tooltip.show, "
            ".popover.show, "
            "div[class*='tooltip']:visible, "
            "div[class*='Popover']:visible, "
            "div[class*='popover']:visible"
        ).last
        places: list[str] = []
        try:
            if await tip.count():
                tip_text = normalize_whitespace(await tip.inner_text()) or ""
                for line in re.split(r"[\n•|/]+", tip_text):
                    cleaned = normalize_job_location(line)
                    if cleaned and cleaned not in places:
                        # tip may return joined string; split again
                        for part in cleaned.split(";"):
                            token = part.strip()
                            if token and token not in places:
                                places.append(token)
                # Prefer individual child nodes when available.
                children = tip.locator("li, a, span, div, p")
                child_count = min(await children.count(), 40)
                child_places: list[str] = []
                for i in range(child_count):
                    child_text = normalize_whitespace(await children.nth(i).inner_text())
                    cleaned = normalize_job_location(child_text)
                    if not cleaned or ";" in cleaned:
                        continue
                    if len(cleaned) > 80:
                        continue
                    if cleaned not in child_places:
                        child_places.append(cleaned)
                if len(child_places) >= 2:
                    places = child_places
        except Exception:
            places = []

        try:
            await page.mouse.move(0, 0)
        except Exception:
            pass

        if len(places) >= 2:
            log_event(
                logger,
                f"Resolved {len(places)} locations from tooltip",
                portal=self.portal_name,
                action="location",
            )
            return "; ".join(places)
        if len(places) == 1:
            return places[0]
        return None

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
        # Built In detail header is a 3-column row: company/title/posted | meta | industry/headline.
        title = await safe_inner_text(page, "h1.fw-extrabold span, h1.fw-extrabold, h1, .job-title")
        company = await safe_inner_text(
            page,
            "a[href*='/company/'] h2, h2.text-pretty-blue, "
            "a[href*='/company/'].text-pretty-blue, .company-title, [data-id='company-title']",
        )
        # Prefer website already resolved from the list-card company profile.
        if raw_job.company_url and self._is_external_company_website(raw_job.company_url):
            company_url = raw_job.company_url
        else:
            company_profile_url = await self._detail_company_profile_url(page) or raw_job.company_url
            company_url = await self._fetch_company_website_from_profile(page, company_profile_url)
            if not company_url:
                company_url = company_profile_url
        posted_text = await self._detail_posted_text(page)
        posted = parse_posted_relative(posted_text)
        if posted.posted_at is None and raw_job.posted_at:
            posted.posted_at = raw_job.posted_at
        if raw_job.is_reposted:
            posted.is_reposted = True
        location = await self._page_location(page)
        if not location:
            location = raw_job.job_card_location
        work_type = await self._detail_icon_row_text(page, "fa-house-building")
        salary = await self._detail_icon_row_text(page, "fa-sack-dollar")
        if not salary:
            salary = await safe_inner_text(page, ".job-salary, .salary, [data-id='job-salary']")
        experience_level = await self._detail_icon_row_text(page, "fa-trophy")
        industry, company_headline = await self._detail_industry_and_headline(page)
        apply_url, is_easy_apply = await self._resolve_apply(page)
        # Evidence sources on Built In detail:
        # 1) job head (above), 2) match-background, 3) job-post-body-*, 4) Skills Required card.
        body = await self.extract_description(page)
        skills_required, skills_text = await self._detail_skills_required(page)
        description = "\n\n".join(
            part for part in [body, skills_text] if part
        ) or None
        return JobDetail(
            source_portal=self.portal_name,
            source_job_id=raw_job.source_job_id or extract_job_id_from_url(page.url),
            title=title or raw_job.job_card_title,
            company=company or raw_job.job_card_company,
            company_url=company_url,
            company_headline=company_headline,
            location=normalize_job_location(location or raw_job.job_card_location),
            salary_text=salary or raw_job.job_card_salary,
            industry=industry or raw_job.industry,
            work_type=work_type or raw_job.work_type,
            experience_level=experience_level or raw_job.experience_level,
            posted_text=posted.raw_text or posted_text or raw_job.posted_text,
            posted_at=posted.posted_at or raw_job.posted_at,
            is_reposted=bool(posted.is_reposted or raw_job.is_reposted),
            skills_required=skills_required,
            # Requirements summary is never sourced from the detail page — list-card only.
            match_background_text=None,
            portal_job_url=page.url or raw_job.portal_job_url,
            apply_url=None if is_easy_apply else apply_url,
            is_easy_apply=is_easy_apply,
            raw_html=await page.content(),
            description_text=description,
        )

    async def _detail_skills_required(self, page: Page) -> tuple[list[str], str | None]:
        """Read the Skills Required white card on Built In detail."""
        section = page.locator(
            "div.bg-white.rounded-3.p-md:has-text('Skills Required'), "
            "div.col-12.col-lg-6:has-text('Skills Required'), "
            "div.bg-white.rounded-3.p-md.mb-sm.full-size:has-text('Skill')"
        ).first
        if await section.count() == 0:
            return [], None
        full_text = normalize_whitespace(await section.inner_text())
        skills: list[str] = []
        # Prefer chip/badge spans inside the skills card.
        chips = section.locator(
            "span.badge, span.rounded-pill, a.badge, "
            "div.d-flex.flex-wrap span, li, "
            "span.fw-semibold, span.fw-medium"
        )
        count = await chips.count()
        for i in range(min(count, 40)):
            text = normalize_whitespace(await chips.nth(i).inner_text())
            if not text or len(text) > 60:
                continue
            lowered = text.lower()
            if lowered in {"skills required", "skill required", "skills", "required"}:
                continue
            if text not in skills:
                skills.append(text)
        if not skills and full_text:
            # Fallback: split on bullets / commas after the heading.
            payload = re.sub(r"(?i)^skills?\s*required[:\s]*", "", full_text).strip()
            for part in re.split(r"[•·|,/\n]+", payload):
                token = normalize_whitespace(part)
                if token and len(token) < 60 and token.lower() not in {"skills required", "required"}:
                    skills.append(token)
        return skills, full_text

    async def _detail_company_profile_url(self, page: Page) -> str | None:
        """Built In job detail links to /company/slug — not the external website."""
        link = page.locator(
            "a[href*='/company/'].text-pretty-blue, "
            "a.hover-underline[href*='/company/'], "
            "a[href*='/company/']:has(h2), "
            "a[href*='/company/']"
        ).first
        if await link.count() == 0:
            return None
        href = await link.get_attribute("href")
        if not href:
            return None
        if href.startswith("http"):
            return href
        return urljoin(BUILTIN_ORIGIN, href)

    async def _fetch_company_website_from_profile(self, page: Page, profile_url: str | None) -> str | None:
        """Open Built In company page in a side tab, save View Website, close tab.

        Never navigates the caller's page away (list or job detail stays put).
        """
        if not profile_url:
            return None
        if self._is_external_company_website(profile_url):
            return profile_url
        url = profile_url if profile_url.startswith("http") else urljoin(BUILTIN_ORIGIN, profile_url)
        company_page = await page.context.new_page()
        try:
            await company_page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await company_page.wait_for_timeout(600)
            await self._pass_builtin_security_captcha(company_page)
            link = company_page.locator(
                "a.hover-underline:has-text('View Website'), "
                "a.font-barlow:has-text('View Website'), "
                "a:has-text('View Website'), "
                "a[href*='utm_source=BuiltIn'][target='_blank'], "
                "a[rel*='noopener'][href^='http']:has-text('Website')"
            ).first
            # After captcha, content may load a beat later.
            if await link.count() == 0:
                await company_page.wait_for_timeout(1200)
            if await link.count() == 0:
                # Fallback: first external http(s) link that is not Built In.
                candidates = company_page.locator("a[href^='http']")
                count = await candidates.count()
                href = None
                for i in range(min(count, 30)):
                    candidate = await candidates.nth(i).get_attribute("href")
                    if candidate and self._is_external_company_website(candidate):
                        href = candidate
                        break
                if not href:
                    log_event(
                        logger,
                        f"No View Website link on company page: {url}",
                        portal=self.portal_name,
                        action="company_website",
                        level=30,
                    )
                    return None
            else:
                href = await link.get_attribute("href")
            if not href or not self._is_external_company_website(href):
                return None
            website = href if href.startswith("http") else urljoin(BUILTIN_ORIGIN, href)
            if not self._is_external_company_website(website):
                return None
            log_event(
                logger,
                f"Resolved company website: {website}",
                portal=self.portal_name,
                action="company_website",
            )
            return website
        except Exception as exc:
            log_event(
                logger,
                f"Company website lookup failed for {url}: {exc}",
                portal=self.portal_name,
                action="company_website",
                level=30,
            )
            return None
        finally:
            try:
                await company_page.close()
            except Exception:
                pass
            try:
                await page.bring_to_front()
            except Exception:
                pass

    async def _pass_builtin_security_captcha(self, page: Page) -> bool:
        """Click Built In analytics/security captcha checkbox when it blocks the company page.

        Common widgets: reCAPTCHA checkbox, Cloudflare Turnstile, hCaptcha checkbox,
        or an on-page "verify you are human" style checkbox.
        """
        clicked = False

        # 1) On-page verify checkbox (non-iframe).
        page_checks = page.locator(
            "input[type='checkbox']:not([disabled]), "
            "[role='checkbox'], "
            "label:has-text('not a robot'), "
            "label:has-text('Verify'), "
            "label:has-text('human'), "
            "button:has-text('Verify'), "
            "div.cf-turnstile, "
            "[class*='captcha'] input[type='checkbox'], "
            "[id*='captcha'] input[type='checkbox']"
        )
        count = min(await page_checks.count(), 8)
        for i in range(count):
            control = page_checks.nth(i)
            try:
                if await control.is_visible(timeout=800):
                    await control.click(timeout=2500, force=True)
                    clicked = True
                    break
            except Exception:
                continue

        # 2) reCAPTCHA / hCaptcha / Turnstile iframes — click the checkbox inside.
        if not clicked:
            iframe_selectors = (
                "iframe[src*='recaptcha']",
                "iframe[title*='reCAPTCHA']",
                "iframe[src*='hcaptcha']",
                "iframe[title*='hCaptcha']",
                "iframe[src*='turnstile']",
                "iframe[src*='challenges.cloudflare']",
                "iframe[title*='Widget containing a Cloudflare']",
            )
            for iframe_sel in iframe_selectors:
                frames = page.locator(iframe_sel)
                try:
                    if await frames.count() == 0:
                        continue
                except Exception:
                    continue
                try:
                    frame = page.frame_locator(iframe_sel).first
                    box = frame.locator(
                        "#recaptcha-anchor, "
                        ".recaptcha-checkbox-border, "
                        ".recaptcha-checkbox, "
                        "#checkbox, "
                        ".mark, "
                        "input[type='checkbox'], "
                        "[role='checkbox'], "
                        "body"
                    ).first
                    await box.click(timeout=3500, force=True)
                    clicked = True
                    break
                except Exception:
                    continue

        if clicked:
            log_event(
                logger,
                "Clicked Built In security/analytics captcha checkbox",
                portal=self.portal_name,
                action="captcha",
            )
            await page.wait_for_timeout(1800)
            # Wait briefly for challenge to clear / company content to render.
            try:
                await page.locator(
                    "a:has-text('View Website'), a[href*='utm_source=BuiltIn']"
                ).first.wait_for(state="visible", timeout=8000)
            except Exception:
                await page.wait_for_timeout(1200)
        return clicked

    @staticmethod
    def _is_external_company_website(href: str) -> bool:
        lowered = href.lower().strip()
        if not lowered.startswith("http"):
            return False
        if "builtin.com" in lowered:
            return False
        return True

    async def _card_posted_text(self, card: Locator) -> str | None:
        """Pull Posted/Reposted relative time from Built In list card text."""
        text = normalize_whitespace(await card.inner_text()) or ""
        match = re.search(
            r"((?:Reposted|Posted)\s+)?(?:\d+\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?)\s*ago|yesterday|today|just\s*now)",
            text,
            re.I,
        )
        if match:
            return normalize_whitespace(match.group(0))
        # Fallback: first token before a middle-dot separator (e.g. "3 Hours Ago · Remote").
        first = text.split("·")[0].strip()
        if re.search(r"\bago\b|yesterday|today", first, re.I):
            return first
        return None

    async def _detail_posted_text(self, page: Page) -> str | None:
        posted = await safe_inner_text(
            page,
            "i.fa-clock ~ span.font-barlow, "
            "span.font-barlow:text-matches('Posted|Reposted', 'i')",
        )
        if posted:
            return posted
        clock = page.locator("i.fa-clock, i[class*='fa-clock']").first
        if await clock.count() == 0:
            return None
        title = await clock.get_attribute("title")
        if not title:
            return None
        text = title.strip()
        if text.lower().startswith("job "):
            text = text[4:]
        return normalize_whitespace(text)

    async def _detail_icon_row_text(self, page: Page, icon_fragment: str) -> str | None:
        icon = page.locator(f"i[class*='{icon_fragment}']").first
        if await icon.count() == 0:
            return None
        row = icon.locator(
            "xpath=ancestor::div[contains(@class,'d-flex') and contains(@class,'align-items-start')][1]"
        )
        if await row.count() == 0:
            row = icon.locator("xpath=ancestor::div[contains(@class,'d-flex')][1]")
        if await row.count() == 0:
            return None
        # Prefer the text container (may include nested spans like location).
        text_node = row.locator(".font-barlow, span.font-barlow").first
        if await text_node.count() == 0:
            text_node = row.locator("span").last
        if await text_node.count():
            text = normalize_whitespace(await text_node.inner_text())
            if text:
                return text
        return normalize_whitespace(await row.inner_text())

    async def _detail_industry_and_headline(self, page: Page) -> tuple[str | None, str | None]:
        industry = await safe_inner_text(page, "div.font-barlow.fw-medium.mb-md, div.font-barlow.fw-medium")
        if industry and "•" not in industry and "·" not in industry:
            # Avoid grabbing unrelated medium-weight Barlow text.
            industry = None
        headline = await safe_inner_text(
            page,
            "div.bg-white.rounded-3.p-md.h-100 > div.fs-md.fw-regular, "
            "div.font-barlow.fw-medium.mb-md + div.fs-md.fw-regular, "
            "div.fw-medium.mb-md + div.fs-md.fw-regular",
        )
        return industry, headline

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
