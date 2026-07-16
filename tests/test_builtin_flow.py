"""Tests for Built In card filtering and apply-link review rules."""

from job_automation.config.loader import load_rules
from job_automation.etl.pipeline import transform_raw_job
from job_automation.models.domain import Decision, NormalizedJob, RawJob
from job_automation.portals.builtin import BuiltInWorker
from job_automation.rules.rule_engine import RuleEngine


def test_early_duplicate_check_matches_existing_job_url():
    from job_automation.dedupe.deduplicate import DeduplicationEngine
    from job_automation.storage.models import JobRow

    existing = JobRow(
        source_portal="builtin",
        source_job_id="frontend-os-2",
        job_url="https://builtin.com/job/frontend-os-2",
        canonical_url="https://builtin.com/job/frontend-os-2",
        title="Frontend Engineer",
        company="Apkudo",
    )
    engine = DeduplicationEngine([existing])
    assert engine.is_early_duplicate("frontend-os-2", "https://builtin.com/job/frontend-os-2") is True
    assert engine.is_early_duplicate("other-id", "https://builtin.com/job/other") is False


def test_builtin_search_url_uses_query_param():
    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None)
    url = worker._search_url("Python")
    assert url.startswith("https://builtin.com/jobs?search=Python")
    assert "daysSinceUpdated" not in url


def test_builtin_description_selector_is_job_post_body():
    """Description must come from div[id^=job-post-body], not generic .job-description."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None)

    body = MagicMock()
    body.count = AsyncMock(return_value=1)
    body.inner_text = AsyncMock(return_value="Real job description from job-post-body.")

    other = MagicMock()
    other.count = AsyncMock(return_value=1)
    other.inner_text = AsyncMock(return_value="Wrong description from old selector.")

    page = MagicMock()

    def locator(selector: str):
        loc = MagicMock()
        if "job-post-body" in selector:
            loc.first = body
        else:
            loc.first = other
        return loc

    page.locator = locator
    text = asyncio.run(worker.extract_description(page))
    assert text == "Real job description from job-post-body."
    body.inner_text.assert_awaited()
    other.inner_text.assert_not_awaited()


def test_past_24_hours_skipped_when_already_selected():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None)

    button = MagicMock()
    button.count = AsyncMock(return_value=1)
    button.inner_text = AsyncMock(return_value="Past 24 hours")
    button.click = AsyncMock()

    page = MagicMock()
    page.locator = MagicMock(return_value=MagicMock(first=button))

    asyncio.run(worker._set_past_24_hours(page))
    button.click.assert_not_awaited()


def test_builtin_search_keywords_start_with_python():
    config = load_rules()
    queries = config.queries_for_portal("builtin")
    assert queries[0] == "Python"
    assert "frontend" in queries
    assert "full-stack" in queries


def test_banned_industry_rejects_on_card_reason():
    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None, banned_companies=set())
    reason = worker._card_reject_reason("Acme", "Cybersecurity Platforms")
    assert reason is not None
    assert "Banned industry" in reason


def test_banned_company_rejects_on_card_reason():
    config = load_rules()
    worker = BuiltInWorker(
        config,
        browser_manager=None,
        session_manager=None,
        banned_companies={"apkudo"},
    )
    reason = worker._card_reject_reason("Apkudo", "Software")
    assert reason == "Banned company: Apkudo"


def test_easy_apply_link_needs_review():
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="builtin",
        title="Software Engineer Python",
        company="Example Corp",
        location="Remote, US",
        remote_policy="fully_remote_us",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=False,
        security_related_company_or_role=False,
        salary_text="$120,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Fully remote software engineer role using Python.",
        apply_url="https://builtin.com/apply/job/12345",
    )
    result = engine.decide(job)
    assert result.decision == Decision.NEEDS_REVIEW
    assert result.decision_reason == "easy apply"


def test_missing_apply_link_needs_review():
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="builtin",
        title="Software Engineer Python",
        company="Example Corp",
        location="Remote, US",
        remote_policy="fully_remote_us",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=False,
        security_related_company_or_role=False,
        salary_text="$120,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Fully remote software engineer role using Python.",
        apply_url=None,
    )
    result = engine.decide(job)
    assert result.decision == Decision.NEEDS_REVIEW
    assert result.decision_reason == "apply link error"


def test_forced_industry_reject_survives_transform():
    config = load_rules()
    raw = RawJob(
        source_portal="builtin",
        job_card_title="Frontend Engineer",
        job_card_company="SecCorp",
        portal_job_url="https://builtin.com/job/abc",
        industry="Defense & Security",
        description_text="Industry reject",
        forced_decision=Decision.REJECTED,
        forced_decision_reason="Banned industry: Defense & Security",
    )
    normalized = transform_raw_job(raw, config)
    assert normalized.decision == Decision.REJECTED
    assert normalized.industry == "Defense & Security"
    engine = RuleEngine(config)
    decided = engine.decide(normalized)
    assert decided.decision == Decision.REJECTED
    assert "Banned industry" in (decided.decision_reason or "")
