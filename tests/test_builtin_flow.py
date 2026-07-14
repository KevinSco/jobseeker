"""Tests for Built In card filtering and apply-link review rules."""

from job_automation.config.loader import load_rules
from job_automation.etl.pipeline import transform_raw_job
from job_automation.models.domain import Decision, NormalizedJob, RawJob
from job_automation.portals.builtin import BuiltInWorker
from job_automation.rules.rule_engine import RuleEngine


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
