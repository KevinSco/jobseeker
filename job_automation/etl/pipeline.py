"""ETL pipeline: raw job to normalized job with evidence."""

from __future__ import annotations

from job_automation.config.loader import SearchConfig
from job_automation.etl.cleaner import clean_html, normalize_company, normalize_text
from job_automation.etl.parsers import (
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
    combined_text = "\n".join(
        filter(
            None,
            [
                raw.job_card_title,
                raw.job_card_company,
                raw.job_card_location,
                raw.job_card_salary,
                description,
            ],
        )
    )

    salary_source = raw.job_card_salary or _extract_salary_snippet(combined_text)
    salary = parse_salary(salary_source)
    remote = parse_remote_policy(combined_text, config.keywords)
    travel = parse_travel(combined_text, config.keywords)
    clearance = parse_clearance(combined_text, config.keywords)
    security_related = parse_security_related(combined_text, config.keywords)
    government = parse_government_industry(combined_text, config.keywords)
    role_match = parse_role_match(raw.job_card_title, config.target_roles)
    role_excluded = parse_excluded_role(raw.job_card_title, config.excluded_roles)
    skill_match = parse_skill_match(combined_text, config.target_skills)
    commitment = parse_commitment(combined_text, config.commitment_types)
    experience = parse_experience_level(combined_text, config.experience_levels)

    evidence: list[Evidence] = []
    _add_evidence(evidence, "remote_policy", remote.value, remote.evidence_text)
    _add_evidence(evidence, "travel_required", travel.value, travel.evidence_text)
    _add_evidence(evidence, "security_clearance_required", clearance.value, clearance.evidence_text)
    _add_evidence(evidence, "salary", salary.salary_text, salary.evidence_text)
    _add_evidence(evidence, "industry", government.value, government.evidence_text)
    _add_evidence(evidence, "role_match", role_match.value, role_match.evidence_text)
    _add_evidence(evidence, "skill_match", skill_match.value, skill_match.evidence_text)
    _add_evidence(
        evidence,
        "security_related_company_or_role",
        security_related.value,
        security_related.evidence_text,
    )
    _add_evidence(evidence, "role_excluded", role_excluded.value, role_excluded.evidence_text)

    return NormalizedJob(
        source_portal=raw.source_portal,
        source_job_id=raw.source_job_id,
        title=normalize_text(raw.job_card_title),
        company=normalize_company(raw.job_card_company),
        location=normalize_text(raw.job_card_location),
        remote_policy=str(remote.value) if remote.value is not None else None,
        commitment=str(commitment.value) if commitment.value else None,
        experience_level=str(experience.value) if experience.value else None,
        industry=normalize_text(raw.industry) or ("government" if government.value else None),
        salary_text=salary.salary_text,
        salary_min_annual=salary.min_annual,
        salary_max_annual=salary.max_annual,
        salary_min_hourly=salary.min_hourly,
        salary_max_hourly=salary.max_hourly,
        security_clearance_required=clearance.value if isinstance(clearance.value, bool) else None,
        travel_required=travel.value if isinstance(travel.value, bool) else None,
        security_related_company_or_role=bool(security_related.value),
        role_excluded=bool(role_excluded.value),
        role_match=bool(role_match.value),
        skill_match=bool(skill_match.value),
        job_url=raw.portal_job_url or raw.job_card_url,
        apply_url=raw.apply_url,
        description_text=description or None,
        raw_html=raw.raw_html,
        evidence=evidence,
        decision=raw.forced_decision,
        decision_reason=raw.forced_decision_reason,
    )


def _add_evidence(items: list[Evidence], field: str, value, evidence_text: str | None) -> None:
    if value is None and not evidence_text:
        return
    items.append(
        Evidence(
            field=field,
            value=value,
            evidence_text=evidence_text or str(value),
            source="job_description",
        )
    )


def _extract_salary_snippet(text: str) -> str | None:
    import re

    match = re.search(r"\$[\d,]+(?:\.\d+)?(?:\s*-\s*\$[\d,]+(?:\.\d+)?)?(?:\s*(?:/hr|per hour|annually|/year|k))?", text, re.I)
    return match.group(0) if match else None
