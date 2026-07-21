"""Domain models and enums."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Decision(StrEnum):
    ELIGIBLE = "eligible"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class PortalRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_MANUAL_LOGIN = "needs_manual_login"


class Evidence(BaseModel):
    field: str
    value: Any
    evidence_text: str
    source: str = "job_description"


class RawJob(BaseModel):
    source_portal: str
    source_job_id: str | None = None
    job_card_title: str | None = None
    job_card_company: str | None = None
    company_url: str | None = None
    company_headline: str | None = None
    job_card_location: str | None = None
    job_card_salary: str | None = None
    job_card_url: str | None = None
    portal_job_url: str | None = None
    apply_url: str | None = None
    industry: str | None = None
    work_type: str | None = None
    experience_level: str | None = None
    posted_text: str | None = None
    posted_at: datetime | None = None
    is_reposted: bool = False
    top_skills: list[str] = Field(default_factory=list)
    skills_required: list[str] = Field(default_factory=list)
    match_background_text: str | None = None
    raw_html: str | None = None
    raw_text: str | None = None
    description_text: str | None = None
    forced_decision: Decision | None = None
    forced_decision_reason: str | None = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class JobDetail(BaseModel):
    source_portal: str
    source_job_id: str | None = None
    title: str | None = None
    company: str | None = None
    company_url: str | None = None
    company_headline: str | None = None
    location: str | None = None
    salary_text: str | None = None
    industry: str | None = None
    work_type: str | None = None
    experience_level: str | None = None
    posted_text: str | None = None
    posted_at: datetime | None = None
    is_reposted: bool = False
    skills_required: list[str] = Field(default_factory=list)
    match_background_text: str | None = None
    portal_job_url: str | None = None
    apply_url: str | None = None
    raw_html: str | None = None
    description_text: str | None = None


class NormalizedJob(BaseModel):
    source_portal: str
    source_job_id: str | None = None
    title: str | None = None
    company: str | None = None
    company_url: str | None = None
    company_headline: str | None = None
    location: str | None = None
    location_eligible: str | None = None  # Yes / No / Unknown (CT applicant)
    remote_policy: str | None = None
    remote_eligible: str | None = None  # Yes / No / Unknown
    work_type: str | None = None
    commitment: str | None = None
    experience_level: str | None = None
    industry: str | None = None
    salary_text: str | None = None
    salary_min_annual: int | None = None
    salary_max_annual: int | None = None
    salary_min_hourly: float | None = None
    salary_max_hourly: float | None = None
    posted_text: str | None = None
    posted_at: datetime | None = None
    is_reposted: bool = False
    security_clearance_required: bool | None = None
    travel_required: bool | None = None
    onsite_onboarding: bool | None = None
    security_related_company_or_role: bool | None = None
    role_excluded: bool | None = None
    role_match: bool | None = None
    skill_match: bool | None = None
    job_url: str | None = None
    apply_url: str | None = None
    canonical_url: str | None = None
    description_text: str | None = None
    raw_html: str | None = None
    description_hash: str | None = None
    identity_hash: str | None = None
    is_duplicate: bool = False
    decision: Decision | None = None
    decision_reason: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    status: str = "new"
    manual_note: str | None = None
