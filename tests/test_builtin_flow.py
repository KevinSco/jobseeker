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
    """Easy Apply always needs review (does not become eligible)."""
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="builtin",
        title="Software Engineer Python",
        company="Example Corp",
        location="Remote, US",
        location_eligible="Yes",
        remote_policy="fully_remote_us",
        remote_eligible="Yes",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=False,
        onsite_onboarding=False,
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
        location_eligible="Yes",
        remote_policy="fully_remote_us",
        remote_eligible="Yes",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=False,
        onsite_onboarding=False,
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


def test_top_skills_over_half_matches():
    from job_automation.etl.parsers import parse_skill_match

    config = load_rules()
    # 3/4 > 50% (Unreal is not in the skill list)
    result = parse_skill_match(
        "",
        config.target_skills,
        top_skills=["React", "TypeScript", "Python", "Unreal Engine"],
    )
    assert result.value is True
    assert "3/4" in (result.evidence_text or "")


def test_top_skills_under_quarter_rejects():
    from job_automation.etl.parsers import parse_skill_match

    config = load_rules()
    # 0/4 < 25%
    result = parse_skill_match(
        "",
        config.target_skills,
        top_skills=["Fortran", "COBOL", "Ada", "Lisp"],
    )
    assert result.value is False


def test_top_skills_quarter_to_half_needs_review():
    from job_automation.etl.parsers import parse_skill_match
    from job_automation.rules.rule_engine import RuleEngine

    config = load_rules()
    # 1/4 = 25% → review band
    result = parse_skill_match(
        "",
        config.target_skills,
        top_skills=["React", "Fortran", "COBOL", "Ada"],
    )
    assert result.value is None

    job = NormalizedJob(
        source_portal="builtin",
        title="Frontend Engineer",
        company="Example",
        location="Remote, US",
        remote_policy="fully_remote_us",
        role_match=True,
        skill_match=None,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=False,
        security_related_company_or_role=False,
        salary_text="$120,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Fully remote frontend role.",
        apply_url="https://boards.greenhouse.io/example/jobs/1",
    )
    decided = RuleEngine(config).decide(job)
    assert decided.decision == Decision.NEEDS_REVIEW
    assert "Skills partially match" in (decided.decision_reason or "")


def test_transform_uses_top_skills_ratio():
    config = load_rules()
    raw = RawJob(
        source_portal="builtin",
        job_card_title="Frontend Engineer",
        job_card_company="Apkudo",
        portal_job_url="https://builtin.com/job/frontend-os-2",
        top_skills=["React", "TypeScript", "Python", "Node.js"],
        description_text="Fully remote role.",
        apply_url="https://boards.greenhouse.io/apkudo/jobs/123",
    )
    normalized = transform_raw_job(raw, config)
    assert normalized.skill_match is True


def test_role_match_accepts_sr_and_senior_software_titles():
    from job_automation.etl.parsers import parse_role_match

    config = load_rules()
    for title in [
        "Sr. Software Engineer",
        "Sr Software Engineer",
        "Senior Software Engineer",
        "Senior Software Developer",
        "Sr. Software Eng",
        "Sr. Software",
        "Senior Software",
        "Senior Full-Stack Engineer",
        "Sr. Full Stack Developer",
        "Full Stack Engineer",
    ]:
        result = parse_role_match(title, config.target_roles)
        assert result.value is True, title


def test_is_external_company_website():
    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None)
    assert worker._is_external_company_website("https://www.elevenlabs.io/?utm_source=BuiltIn") is True
    assert worker._is_external_company_website("https://builtin.com/company/elevenlabs") is False
    assert worker._is_external_company_website("/company/elevenlabs") is False


def test_looks_like_requirements_summary():
    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None)
    assert worker._looks_like_requirements_summary(
        "Ship device OS UI with TypeScript and React for a fully remote US team."
    )
    assert not worker._looks_like_requirements_summary("Top Skills:")
    assert not worker._looks_like_requirements_summary("Software • Fintech")


def test_fetch_company_website_from_profile_reads_view_website_link():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    config = load_rules()
    worker = BuiltInWorker(config, browser_manager=None, session_manager=None)

    link = MagicMock()
    link.count = AsyncMock(return_value=1)
    link.get_attribute = AsyncMock(
        return_value="https://www.elevenlabs.io/?utm_source=BuiltIn&utm_medium=BuiltIn&utm_campaign=BuiltIn"
    )

    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.locator = MagicMock(return_value=MagicMock(first=link))

    website = asyncio.run(
        worker._fetch_company_website_from_profile(page, "https://builtin.com/company/elevenlabs")
    )
    assert website and "elevenlabs.io" in website
    page.goto.assert_awaited()


def test_transform_prefers_builtin_detail_header_fields():
    config = load_rules()
    raw = RawJob(
        source_portal="builtin",
        job_card_title="Software Development Engineer/Features Engineering Lead Basemaps Team",
        job_card_company="Vantor",
        company_url="https://builtin.com/company/vantor",
        company_headline="Vantor is forging the new frontier of spatial intelligence to unlock a more autonomous, interoperable world.",
        job_card_location="Hiring Remotely in Westminster, CO, USA",
        job_card_salary="124K-209K Annually",
        industry="Aerospace • Artificial Intelligence • Computer Vision • Software • Analytics • Defense • Big Data Analytics",
        work_type="In-Office or Remote",
        experience_level="Senior level",
        posted_text="Posted 9 Hours Ago",
        portal_job_url="https://builtin.com/job/software-development-engineerfeatures-engineering-lead-basemaps-team/123",
        description_text="Build basemap features.",
        apply_url="https://example.com/apply",
    )
    normalized = transform_raw_job(raw, config)
    assert normalized.company_headline and "spatial intelligence" in normalized.company_headline
    assert normalized.work_type == "In-Office or Remote"
    assert normalized.experience_level == "Senior Level"
    assert normalized.posted_text == "Posted 9 Hours Ago"
    assert normalized.salary_min_annual == 124000
    assert normalized.salary_max_annual == 209000
    assert normalized.salary_text == "$124,000 – $209,000"
    # Defense in company industry → restricted per evidence rules (company industry, not job function).
    assert normalized.security_related_company_or_role is True
    assert "Aerospace" in (normalized.industry or "")
