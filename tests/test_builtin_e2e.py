"""End-to-end Built In flow: filters, login-session gate, card filter, ETL decisions."""

from __future__ import annotations

import pytest
from playwright.async_api import Route, async_playwright

from job_automation.config.loader import load_rules
from job_automation.dedupe.deduplicate import DeduplicationEngine
from job_automation.etl.pipeline import transform_raw_job
from job_automation.models.domain import Decision, RawJob
from job_automation.portals.base import LoginRequiredError
from job_automation.portals.builtin import BuiltInWorker
from job_automation.rules.rule_engine import RuleEngine
from tests.fixtures.builtin_board import BUILTIN_LIST_HTML


DETAIL_FRONTEND = """
<!DOCTYPE html><html><body>
  <h1>Frontend Engineer, Device OS</h1>
  <a href="/company/apkudo" target="_blank" class="hover-underline text-pretty-blue font-barlow fw-medium fs-2xl">
    <h2 class="text-pretty-blue m-0">Apkudo</h2>
  </a>
  <div class="job-location">United States</div>
  <div class="job-salary">$100,000 - $130,000 Annually</div>
  <div data-id="job-remote">Fully Remote</div>
  <div id="job-post-body-9721993" x-ref="job-post-body-9721993" class="fs-md fw-regular mb-md html-parsed-content">
    Fully remote within the United States. Full-time Mid Level software engineer
    using TypeScript and React. Travel not required. Clearance not required.
    Python friendly frontend role.
  </div>
  <a id="applyButton" href="https://boards.greenhouse.io/apkudo/jobs/123">Apply</a>
</body></html>
"""

COMPANY_APKUDO = """
<!DOCTYPE html><html><body>
  <div class="d-flex align-items-center w-md-50">
    <i class="fa fa-sm fa-regular fa-arrow-up-right-from-square text-primary"></i>
    <a href="https://www.apkudo.com/?utm_source=BuiltIn&utm_medium=BuiltIn&utm_campaign=BuiltIn"
       target="_blank" rel="noopener nofollow" class="font-barlow ms-sm hover-underline">View Website</a>
  </div>
</body></html>
"""

DETAIL_EASY_APPLY = """
<!DOCTYPE html><html><body>
  <h1>Python Engineer</h1>
  <a href="/company/okco">OkCo</a>
  <div class="job-location">United States</div>
  <div class="job-salary">$140,000 Annually</div>
  <div id="job-post-body-9990001" class="fs-md fw-regular mb-md html-parsed-content">
    Fully remote Python backend engineer in the United States. Full Time Mid Level.
    No travel. No clearance.
  </div>
  <a id="applyButton" href="/apply/job/999">Easy Apply</a>
</body></html>
"""


class _FakeSessionManager:
    def __init__(self, logged_in: bool = True):
        self.logged_in = logged_in
        self.page = None
        self.saved = False

    async def ensure_logged_in(self, portal: str, *, allow_headful_recovery: bool = True):
        return self.page, self.logged_in

    async def _check_login(self, page, portal: str) -> bool:
        return self.logged_in

    async def save_session(self, portal: str) -> None:
        self.saved = True


async def _install_builtin_routes(page) -> None:
    async def handler(route: Route) -> None:
        url = route.request.url
        if "/company/apkudo" in url:
            await route.fulfill(status=200, content_type="text/html", body=COMPANY_APKUDO)
        elif "/job/frontend-os-2" in url:
            await route.fulfill(status=200, content_type="text/html", body=DETAIL_FRONTEND)
        elif "/job/python-easy" in url:
            await route.fulfill(status=200, content_type="text/html", body=DETAIL_EASY_APPLY)
        elif "/job/" in url:
            await route.fulfill(status=200, content_type="text/html", body="<html><body><h1>Other Job</h1></body></html>")
        else:
            await route.fulfill(status=200, content_type="text/html", body=BUILTIN_LIST_HTML)

    # Context-level so detail tabs opened by the worker also hit these mocks.
    await page.context.route("https://builtin.com/**", handler)


@pytest.mark.asyncio
async def test_e2e_builtin_login_search_filters_and_job_pipeline():
    config = load_rules()
    config.portal_search_queries = {"builtin": ["Python"]}
    config.max_pages_per_query = 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await _install_builtin_routes(page)
        await page.goto("https://builtin.com/jobs", wait_until="domcontentloaded")

        session_manager = _FakeSessionManager(logged_in=True)
        session_manager.page = page
        worker = BuiltInWorker(
            config,
            browser_manager=None,
            session_manager=session_manager,
            banned_companies={"bannedco"},
        )

        # Filters + keyword via durable URL search (not hidden header input).
        await worker._open_filtered_search(page, "Python")
        assert "search=Python" in page.url or "Python" in page.url
        status = await page.locator("#status").inner_text()
        assert "Past 24 hours" in status or await page.locator("#locationDropdownInput-JobBoard").input_value() == "United States"

        cards = await worker._job_cards(page)
        assert len(cards) >= 3

        # Card 1 — cybersecurity industry => reject + heart
        rejected = await worker._process_card(page, cards[0], "Python")
        assert rejected is not None
        assert rejected.forced_decision == Decision.REJECTED
        assert "Banned industry" in (rejected.forced_decision_reason or "")
        assert await page.locator(".job-card[data-card='1'] .heart").get_attribute("data-saved") == "1"

        # Stay on list; re-query cards
        cards = await worker._job_cards(page)
        assert len(cards) >= 2

        # Card 2 — good job => open detail, capture apply link, return to list
        good = await worker._process_card(page, cards[1], "Python")
        assert good is not None
        assert good.forced_decision is None
        assert "Frontend Engineer" in (good.job_card_title or "")
        assert good.apply_url and "greenhouse.io" in good.apply_url
        assert good.company_url and "apkudo.com" in good.company_url
        assert "builtin.com/company/" not in (good.company_url or "")
        assert good.industry == "Software"
        assert good.top_skills and "TypeScript" in good.top_skills
        assert good.match_background_text and "device OS" in good.match_background_text
        assert good.description_text and "Fully remote" in good.description_text
        assert "builtin.com/jobs" in page.url or await page.locator(".job-card").count() > 0

        # Ensure list is available again
        if await page.locator(".job-card").count() == 0:
            await page.goto("https://builtin.com/jobs", wait_until="domcontentloaded")
        cards = await worker._job_cards(page)

        # Card 3 — banned company => reject
        banned = await worker._process_card(page, cards[2], "Python")
        assert banned is not None
        assert banned.forced_decision == Decision.REJECTED
        assert "Banned company" in (banned.forced_decision_reason or "")

        await browser.close()

    # ETL + rule engine on collected jobs
    engine = RuleEngine(config)
    dedupe = DeduplicationEngine([])
    outcomes = []
    for raw in (rejected, good, banned):
        normalized = transform_raw_job(raw, config)
        if raw.work_type and "fully_remote" in (raw.work_type or ""):
            normalized.remote_policy = normalized.remote_policy or "fully_remote_us"
        normalized = dedupe.mark_duplicates(normalized)
        if raw.forced_decision:
            normalized.decision = raw.forced_decision
            normalized.decision_reason = raw.forced_decision_reason
        elif not normalized.is_duplicate:
            normalized = engine.decide(normalized)
        outcomes.append((normalized.decision, normalized.decision_reason))

    assert outcomes[0][0] == Decision.REJECTED
    assert outcomes[2][0] == Decision.REJECTED
    assert outcomes[1][0] in {Decision.ELIGIBLE, Decision.NEEDS_REVIEW}, outcomes[1]


@pytest.mark.asyncio
async def test_e2e_easy_apply_link_needs_review_after_etl():
    config = load_rules()
    raw = RawJob(
        source_portal="builtin",
        job_card_title="Software Engineer Python",
        job_card_company="Example",
        job_card_location="United States",
        job_card_salary="$140,000 Annually",
        portal_job_url="https://builtin.com/job/python-easy",
        apply_url="https://builtin.com/apply/job/999",
        description_text=(
            "Fully remote within the United States. Full Time Mid Level software engineer "
            "using Python. Travel not required. Clearance not required."
        ),
        work_type="fully_remote",
    )
    normalized = transform_raw_job(raw, config)
    normalized.remote_policy = "fully_remote_us"
    normalized.location_eligible = "Yes"
    normalized.remote_eligible = "Yes"
    normalized.role_match = True
    normalized.skill_match = True
    normalized.role_excluded = False
    normalized.travel_required = False
    normalized.security_clearance_required = False
    normalized.onsite_onboarding = False
    normalized.security_related_company_or_role = False
    normalized.commitment = "Full Time"
    normalized.experience_level = "Mid Level"
    normalized.salary_min_annual = 140000
    normalized.salary_text = "$140,000"
    decided = RuleEngine(config).decide(normalized)
    assert decided.decision == Decision.NEEDS_REVIEW
    assert decided.decision_reason == "easy apply"


@pytest.mark.asyncio
async def test_e2e_login_required_blocks_search():
    config = load_rules()
    config.portal_search_queries = {"builtin": ["Python"]}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        session_manager = _FakeSessionManager(logged_in=False)
        session_manager.page = page
        worker = BuiltInWorker(config, browser_manager=None, session_manager=session_manager)
        with pytest.raises(LoginRequiredError):
            await worker.run()
        await browser.close()
