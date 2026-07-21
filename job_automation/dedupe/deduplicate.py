"""Deduplication engine.

Duplicate when:
- same portal job ID or same job/apply URL, or
- same company + title with a similar location (different posting of the same role).

Same company + title with a clearly different location is NOT a duplicate —
those go through filtering; eligible ones become needs_review in the rule engine.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from job_automation.dedupe.hash_builder import (
    build_description_hash,
    build_identity_hash,
    canonical_apply_url,
)
from job_automation.models.domain import NormalizedJob
from job_automation.storage.models import JobRow

LOCATION_SIMILARITY_THRESHOLD = 0.85


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9+#.\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_location(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower().strip()
    text = text.replace("united states", "usa").replace("u.s.a.", "usa").replace("u.s.", "usa")
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def locations_similar(left: str | None, right: str | None, threshold: float = LOCATION_SIMILARITY_THRESHOLD) -> bool:
    a = normalize_location(left)
    b = normalize_location(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def same_company_and_title(job: NormalizedJob, row: JobRow) -> bool:
    company_a = normalize_name(job.company)
    company_b = normalize_name(row.company)
    title_a = normalize_name(job.title)
    title_b = normalize_name(row.title)
    if not company_a or not company_b or not title_a or not title_b:
        return False
    return company_a == company_b and title_a == title_b


class DeduplicationEngine:
    def __init__(self, existing_jobs: list[JobRow] | None = None):
        self.existing_jobs = existing_jobs or []

    def enrich_hashes(self, job: NormalizedJob) -> NormalizedJob:
        job.canonical_url = canonical_apply_url(job.apply_url, job.job_url)
        job.identity_hash = build_identity_hash(
            job.company, job.title, job.location, job.remote_policy
        )
        job.description_hash = build_description_hash(job.description_text)
        return job

    def is_early_duplicate(self, source_job_id: str | None, job_url: str | None) -> bool:
        """Early list skip: same job ID or same job URL only (never same-company alone)."""
        url = canonical_apply_url(job_url, job_url)
        for row in self.existing_jobs:
            if source_job_id and row.source_job_id and row.source_job_id == source_job_id:
                return True
            if url and row.canonical_url and row.canonical_url == url:
                return True
            if job_url and row.job_url and row.job_url.rstrip("/") == job_url.rstrip("/"):
                return True
            if url and row.job_url and canonical_apply_url(row.job_url, row.job_url) == url:
                return True
        return False

    def mark_duplicates(self, job: NormalizedJob) -> NormalizedJob:
        job = self.enrich_hashes(job)
        for row in self.existing_jobs:
            if job.source_job_id and row.source_job_id and job.source_job_id == row.source_job_id:
                return self._duplicate(job, "Same job ID")
            if job.canonical_url and row.canonical_url and job.canonical_url == row.canonical_url:
                return self._duplicate(job, "Same job URL")
            if job.job_url and row.job_url and job.job_url.rstrip("/") == row.job_url.rstrip("/"):
                return self._duplicate(job, "Same job URL")
            if same_company_and_title(job, row) and locations_similar(job.location, row.location):
                return self._duplicate(
                    job,
                    "Same company and title with similar location",
                )
        return job

    def has_same_role_different_location(self, job: NormalizedJob) -> bool:
        """True when another saved job has same company+title but a different location."""
        for row in self.existing_jobs:
            if not same_company_and_title(job, row):
                continue
            # Different posting identity
            same_id = (
                job.source_job_id
                and row.source_job_id
                and job.source_job_id == row.source_job_id
            )
            if same_id:
                continue
            if locations_similar(job.location, row.location):
                continue
            # Require both locations present and clearly different
            if normalize_location(job.location) and normalize_location(row.location):
                return True
        return False

    @staticmethod
    def _duplicate(job: NormalizedJob, reason: str) -> NormalizedJob:
        from job_automation.models.domain import Decision, Evidence

        job.is_duplicate = True
        job.decision = Decision.DUPLICATE
        job.decision_reason = reason
        job.evidence.append(
            Evidence(field="decision", value="duplicate", evidence_text=reason, source="dedupe")
        )
        return job
