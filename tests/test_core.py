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
    assert result.salary_text == "$120,000 – $150,000"


def test_parse_builtin_k_salary_without_dollar():
    result = parse_salary("124K-209K Annually")
    assert result.min_annual == 124000
    assert result.max_annual == 209000
    assert result.salary_text == "$124,000 – $209,000"


def test_parse_salary_ignores_stray_digit():
    result = parse_salary("7")
    assert result.min_annual is None
    assert result.max_annual is None
    assert result.salary_text == "Not listed"


def test_parse_hourly_salary():
    result = parse_salary("$55/hr")
    assert result.min_hourly == 55.0
    assert "per hour" in (result.salary_text or "")


def test_parse_ote_not_listed():
    result = parse_salary("Salary up to $250,000 OTE")
    assert result.salary_text == "Not listed"
    assert result.min_annual is None


def test_parse_funding_not_salary():
    result = parse_salary("We've raised $781M in funding")
    assert result.salary_text == "Not listed"
    assert result.min_annual is None
    assert parse_salary("$781").salary_text == "Not listed"


def test_location_us_remote_not_false_state_codes():
    from job_automation.etl.parsers import parse_location_eligible

    text = (
        "Hiring Remotely in United States. Gaps in our Observability product. "
        "Go (or similar) on the backend. Recruiters will only contact you from @company.com."
    )
    assert parse_location_eligible(text).value == "Yes"


def test_location_executed_globally():
    from job_automation.etl.parsers import parse_location_eligible

    text = "This role is remote and can be executed globally. In-Office or Remote. 15 Locations."
    assert parse_location_eligible(text).value == "Yes"


def test_travel_discretionary_stipend_not_required():
    from job_automation.etl.parsers import parse_travel

    config = load_rules()
    text = (
        "Social travel: We also provide an annual discretionary stipend to meet up "
        "with colleagues each year. Annual company offsite: past offsites have included Croatia."
    )
    assert parse_travel(text, config.keywords).value is False


def test_entry_level_not_junior():
    from job_automation.etl.parsers import parse_experience_level

    config = load_rules()
    result = parse_experience_level("Entry level", config.experience_levels)
    assert result.value == "Entry Level"


def test_rule_engine_rejects_clearance():
    config = load_rules()
    engine = RuleEngine(config)
    job = NormalizedJob(
        source_portal="hiringcafe",
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
        security_clearance_required=True,
        onsite_onboarding=False,
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
        salary_text="$120,000 – $150,000",
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
    assert normalized.location_eligible == "Yes"
    assert normalized.remote_eligible == "Yes"
    assert normalized.onsite_onboarding is False
    assert normalized.salary_text == "$130,000"


def test_deduplication_marks_duplicate():
    engine = DeduplicationEngine([])
    job = NormalizedJob(
        source_portal="builtin",
        source_job_id="backend-1",
        title="Backend Engineer",
        company="Example Corp",
        location="Remote, United States",
        apply_url="https://careers.example.com/jobs/backend-1",
        job_url="https://builtin.com/job/backend-1",
        description_text="Same description",
    )
    first = engine.mark_duplicates(job)
    engine.existing_jobs.append(type("Row", (), {
        "source_job_id": first.source_job_id,
        "canonical_url": first.canonical_url,
        "identity_hash": first.identity_hash,
        "description_hash": first.description_hash,
        "description_text": first.description_text,
        "company": first.company,
        "title": first.title,
        "location": first.location,
        "job_url": first.job_url,
    })())
    # Different job ID and URL, but same company + title + similar location → duplicate
    second = engine.mark_duplicates(
        NormalizedJob(
            source_portal="jobright",
            source_job_id="backend-1-other",
            title="Backend Engineer",
            company="Example Corp",
            location="Remote - USA",
            apply_url="https://careers.example.com/jobs/backend-other",
            job_url="https://jobright.ai/job/2",
            description_text="Completely different body text for this posting.",
        )
    )
    assert second.is_duplicate is True
    assert "similar location" in (second.decision_reason or "").lower()


def test_dedupe_same_company_title_different_location_not_duplicate():
    engine = DeduplicationEngine([])
    first = engine.mark_duplicates(
        NormalizedJob(
            source_portal="builtin",
            source_job_id="role-sf",
            title="Backend Engineer",
            company="Example Corp",
            location="San Francisco, CA",
            job_url="https://builtin.com/job/role-sf",
            apply_url="https://example.com/apply/sf",
            description_text="Role in SF",
        )
    )
    engine.existing_jobs.append(type("Row", (), {
        "source_job_id": first.source_job_id,
        "canonical_url": first.canonical_url,
        "identity_hash": first.identity_hash,
        "description_hash": first.description_hash,
        "description_text": first.description_text,
        "company": first.company,
        "title": first.title,
        "location": first.location,
        "job_url": first.job_url,
    })())
    second = engine.mark_duplicates(
        NormalizedJob(
            source_portal="builtin",
            source_job_id="role-ny",
            title="Backend Engineer",
            company="Example Corp",
            location="New York, NY",
            job_url="https://builtin.com/job/role-ny",
            apply_url="https://example.com/apply/ny",
            description_text="Role in NY",
        )
    )
    assert second.is_duplicate is False
    assert engine.has_same_role_different_location(second) is True


def test_multi_location_eligible_needs_review():
    config = load_rules()
    existing = type("Row", (), {
        "source_job_id": "role-sf",
        "company": "Example Corp",
        "title": "Backend Software Engineer",
        "location": "San Francisco, CA",
        "job_url": "https://builtin.com/job/role-sf",
        "canonical_url": "https://builtin.com/job/role-sf",
    })()
    dedupe = DeduplicationEngine([existing])
    engine = RuleEngine(config, dedupe_engine=dedupe)
    job = NormalizedJob(
        source_portal="builtin",
        source_job_id="role-ny",
        title="Backend Software Engineer",
        company="Example Corp",
        location="New York, NY",
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
        salary_text="$120,000 – $150,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Fully remote within the United States. Python required.",
        apply_url="https://example.com/apply",
    )
    result = engine.decide(job)
    assert result.decision.value == "needs_review"
    assert "different location" in (result.decision_reason or "").lower()


def test_multi_location_bad_fit_still_rejects():
    config = load_rules()
    existing = type("Row", (), {
        "source_job_id": "role-sf",
        "company": "Example Corp",
        "title": "Backend Software Engineer",
        "location": "San Francisco, CA",
        "job_url": "https://builtin.com/job/role-sf",
        "canonical_url": "https://builtin.com/job/role-sf",
    })()
    dedupe = DeduplicationEngine([existing])
    engine = RuleEngine(config, dedupe_engine=dedupe)
    job = NormalizedJob(
        source_portal="builtin",
        source_job_id="role-ny",
        title="Backend Software Engineer",
        company="Example Corp",
        location="New York, NY",
        location_eligible="Yes",
        remote_policy="fully_remote_us",
        remote_eligible="Yes",
        role_match=True,
        skill_match=True,
        role_excluded=False,
        travel_required=True,
        security_clearance_required=False,
        onsite_onboarding=False,
        security_related_company_or_role=False,
        salary_text="$120,000",
        salary_min_annual=120000,
        commitment="Full Time",
        experience_level="Mid Level",
        description_text="Travel required. Python.",
        apply_url="https://example.com/apply",
    )
    result = engine.decide(job)
    assert result.decision.value == "rejected"
    assert result.decision_reason == "Travel required"
