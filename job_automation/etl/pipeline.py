"""ETL pipeline: raw job to normalized job with evidence."""

from __future__ import annotations

from job_automation.config.loader import SearchConfig
from job_automation.etl.cleaner import clean_html, normalize_company, normalize_text
from job_automation.etl.parsers import (
    ParseResult,
    parse_clearance,
    parse_commitment,
    parse_excluded_role,
    parse_experience_level,
    parse_government_industry,
    parse_remote_policy,
    parse_role_match,
    parse_security_related,
    parse_skill_match,
    parse_travel,
)
from job_automation.etl.salary_parser import parse_salary
from job_automation.models.domain import Evidence, NormalizedJob, RawJob


def transform_raw_job(raw: RawJob, config: SearchConfig) -> NormalizedJob:
    description = raw.description_text or clean_html(raw.raw_html)
    description = normalize_text(description)

    # Fields already working well from Built In job head / title — keep those sources.
    header_bits = [
        raw.job_card_title,
        raw.job_card_company,
        raw.company_headline,
        raw.job_card_location,
        raw.job_card_salary,
        raw.work_type,
        raw.experience_level,
        raw.industry,
        raw.posted_text,
    ]
    # Remaining evidence (remote/travel/clearance/salary/security/commitment) must
    # use job head + match-background + job-post-body + Skills Required.
    skills_required = raw.skills_required or raw.top_skills
    skills_blob = ", ".join(skills_required) if skills_required else None
    evidence_corpus = "\n".join(
        filter(
            None,
            [
                *header_bits,
                raw.match_background_text,
                description,
                skills_blob,
            ],
        )
    )

    salary_source = raw.job_card_salary or _extract_salary_snippet(evidence_corpus)
    salary = parse_salary(salary_source)
    remote = _remote_from_work_type(raw.work_type) or parse_remote_policy(evidence_corpus, config.keywords)
    travel = parse_travel(evidence_corpus, config.keywords)
    clearance = parse_clearance(evidence_corpus, config.keywords)
    security_related = parse_security_related(evidence_corpus, config.keywords)
    government = parse_government_industry(evidence_corpus, config.keywords)
    # Keep proven title-based role flags.
    role_match = parse_role_match(raw.job_card_title, config.target_roles)
    role_excluded = parse_excluded_role(raw.job_card_title, config.excluded_roles)
    # Prefer detail-page Skills Required list; fall back to list-card top skills / text.
    skill_match = parse_skill_match(
        evidence_corpus,
        config.target_skills,
        top_skills=skills_required,
    )
    commitment = parse_commitment(evidence_corpus, config.commitment_types)
    experience = parse_experience_level(
        raw.experience_level or evidence_corpus,
        config.experience_levels,
    )

    evidence: list[Evidence] = []
    _add_evidence(evidence, "remote_policy", remote.value, remote.evidence_text, source="job_head_and_body")
    _add_evidence(evidence, "work_type", raw.work_type, raw.work_type, source="job_head")
    _add_evidence(evidence, "travel_required", travel.value, travel.evidence_text, source="job_head_and_body")
    _add_evidence(
        evidence,
        "security_clearance_required",
        clearance.value,
        clearance.evidence_text,
        source="job_head_and_body",
    )
    _add_evidence(evidence, "salary", salary.salary_text, salary.evidence_text, source="job_head_and_body")
    _add_evidence(
        evidence,
        "industry",
        raw.industry or government.value,
        raw.industry or government.evidence_text,
        source="job_head",
    )
    _add_evidence(
        evidence,
        "experience_level",
        experience.value,
        experience.evidence_text,
        source="job_head",
    )
    _add_evidence(evidence, "posted_text", raw.posted_text, raw.posted_text, source="job_head")
    _add_evidence(
        evidence,
        "company_headline",
        raw.company_headline,
        raw.company_headline,
        source="job_head",
    )
    _add_evidence(evidence, "role_match", role_match.value, role_match.evidence_text, source="job_title")
    _add_evidence(
        evidence,
        "skill_match",
        skill_match.value,
        skill_match.evidence_text,
        source="skills_required",
    )
    _add_evidence(
        evidence,
        "skills_required",
        skills_required or None,
        ", ".join(skills_required) if skills_required else None,
        source="skills_required",
    )
    _add_evidence(
        evidence,
        "match_background",
        bool(raw.match_background_text) if raw.match_background_text else None,
        raw.match_background_text,
        source="match_background",
    )
    _add_evidence(
        evidence,
        "security_related_company_or_role",
        security_related.value,
        security_related.evidence_text,
        source="job_head_and_body",
    )
    _add_evidence(
        evidence,
        "role_excluded",
        role_excluded.value,
        role_excluded.evidence_text,
        source="job_title",
    )
    _add_evidence(
        evidence,
        "commitment",
        commitment.value,
        commitment.evidence_text,
        source="job_head_and_body",
    )

    return NormalizedJob(
        source_portal=raw.source_portal,
        source_job_id=raw.source_job_id,
        title=normalize_text(raw.job_card_title),
        company=normalize_company(raw.job_card_company),
        company_url=normalize_text(raw.company_url),
        company_headline=normalize_text(raw.company_headline),
        location=normalize_text(raw.job_card_location),
        remote_policy=str(remote.value) if remote.value is not None else None,
        work_type=normalize_text(raw.work_type),
        commitment=str(commitment.value) if commitment.value else None,
        experience_level=str(experience.value) if experience.value else None,
        industry=normalize_text(raw.industry) or ("government" if government.value else None),
        salary_text=salary.salary_text,
        salary_min_annual=salary.min_annual,
        salary_max_annual=salary.max_annual,
        salary_min_hourly=salary.min_hourly,
        salary_max_hourly=salary.max_hourly,
        posted_text=normalize_text(raw.posted_text),
        security_clearance_required=clearance.value if isinstance(clearance.value, bool) else None,
        travel_required=travel.value if isinstance(travel.value, bool) else None,
        security_related_company_or_role=bool(security_related.value),
        role_excluded=bool(role_excluded.value),
        role_match=bool(role_match.value),
        skill_match=skill_match.value if isinstance(skill_match.value, bool) else None,
        job_url=raw.portal_job_url or raw.job_card_url,
        apply_url=raw.apply_url,
        description_text=description or None,
        raw_html=raw.raw_html,
        evidence=evidence,
        decision=raw.forced_decision,
        decision_reason=raw.forced_decision_reason,
    )


def _remote_from_work_type(work_type: str | None) -> ParseResult | None:
    if not work_type:
        return None
    lowered = work_type.lower().strip()
    if "fully_remote" in lowered or lowered in {"fully remote", "remote"}:
        return ParseResult("fully_remote_us", work_type, False)
    if "in-office or remote" in lowered or ("in-office" in lowered and "remote" in lowered):
        return ParseResult("hybrid_possible_remote", work_type, True)
    if "hybrid" in lowered or "hybrid_or_remote" in lowered:
        return ParseResult(
            "hybrid_required" if "or remote" not in lowered else "hybrid_possible_remote",
            work_type,
            False,
        )
    if "in-office" in lowered or "on-site" in lowered or "onsite" in lowered:
        return ParseResult("onsite_required", work_type, False)
    if "remote" in lowered:
        return ParseResult("fully_remote_us", work_type, False)
    return None


def _add_evidence(
    items: list[Evidence],
    field: str,
    value,
    evidence_text: str | None,
    *,
    source: str = "job_description",
) -> None:
    if value is None and not evidence_text:
        return
    items.append(
        Evidence(
            field=field,
            value=value,
            evidence_text=evidence_text or str(value),
            source=source,
        )
    )


def _extract_salary_snippet(text: str) -> str | None:
    import re

    match = re.search(
        r"(?:\$[\d,]+(?:\.\d+)?(?:\s*-\s*\$?[\d,]+(?:\.\d+)?)?\s*K?(?:\s*(?:/hr|per hour|annually|/year))?|"
        r"\d{2,3}K(?:\s*-\s*\d{2,3}K)?(?:\s*Annually)?)",
        text,
        re.I,
    )
    return match.group(0) if match else None
