"""Unit tests for rule engine, ETL, and dedupe."""

from job_automation.config.loader import load_rules
from job_automation.dedupe.deduplicate import DeduplicationEngine
from job_automation.dedupe.url_normalizer import normalize_url
from job_automation.etl.salary_parser import parse_salary
from job_automation.models.domain import NormalizedJob, RawJob
from job_automation.etl.pipeline import transform_raw_job
from job_automation.rules.rule_engine import RuleEngine


def test_normalize_url_strips_tracking_params():
    url = "https://example.com/jobs/1?utm_source=abc&ref=xyz&id=1"
    assert normalize_url(url) == "https://example.com/jobs/1?id=1"


def test_parse_annual_salary():
    result = parse_salary("$120,000 - $150,000 per year")
    assert result.min_annual == 120000
    assert result.max_annual == 150000


def test_parse_hourly_salary():
    result = parse_salary("$55/hr")
    assert result.min_hourly == 55.0


def test_rule_engine_rejects_clearance():
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="hiringcafe",
        title="Software Engineer Python",
        company="Example Corp",
        location="Remote, US",
        remote_policy="fully_remote_us",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=True,
        security_related_company_or_role=False,
        salary_text="$120,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Must have active clearance.",
    )
    result = engine.decide(job)
    assert result.decision.value == "rejected"


def test_rule_engine_needs_review_for_missing_salary():
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="hiringcafe",
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
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Fully remote software engineer role using Python.",
        apply_url="https://example.com/apply",
    )
    result = engine.decide(job)
    assert result.decision.value == "needs_review"


def test_rule_engine_eligible():
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="hiringcafe",
        title="Backend Software Engineer",
        company="Example Corp",
        location="Remote, United States",
        remote_policy="fully_remote_us",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=False,
        security_clearance_required=False,
        security_related_company_or_role=False,
        salary_text="$120,000 - $150,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Fully remote within the United States. Python required.",
        apply_url="https://example.com/apply",
    )
    result = engine.decide(job)
    assert result.decision.value == "eligible"


def test_transform_raw_job_extracts_fields():
    config = load_rules()
    raw = RawJob(
        source_portal="builtin",
        source_job_id="123",
        job_card_title="Software Engineer Python",
        job_card_company="Example Corp",
        job_card_location="Remote, US",
        job_card_salary="$130,000",
        description_text=(
            "This role is fully remote within the United States. "
            "No travel required. Python and JavaScript experience required."
        ),
        portal_job_url="https://builtin.com/job/123",
        apply_url="https://example.com/apply",
    )
    normalized = transform_raw_job(raw, config)
    assert normalized.role_match is True
    assert normalized.skill_match is True
    assert normalized.remote_policy == "fully_remote_us"


def test_deduplication_marks_duplicate():
    engine = DeduplicationEngine([])
    job = NormalizedJob(
        source_portal="builtin",
        title="Backend Engineer",
        company="Example Corp",
        location="Remote",
        apply_url="https://example.com/apply?utm_source=test",
        job_url="https://builtin.com/job/1",
        description_text="Same description",
    )
    first = engine.mark_duplicates(job)
    engine.existing_jobs.append(type("Row", (), {
        "canonical_url": first.canonical_url,
        "identity_hash": first.identity_hash,
        "description_hash": first.description_hash,
        "description_text": first.description_text,
    })())
    second = engine.mark_duplicates(
        NormalizedJob(
            source_portal="jobright",
            title="Backend Engineer",
            company="Example Corp",
            location="Remote",
            apply_url="https://example.com/apply?ref=abc",
            job_url="https://jobright.ai/job/2",
            description_text="Same description",
        )
    )
    assert second.is_duplicate is True
