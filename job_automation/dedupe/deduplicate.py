"""Deduplication engine."""

from __future__ import annotations

from job_automation.dedupe.hash_builder import (
    build_description_hash,
    build_identity_hash,
    canonical_apply_url,
)
from job_automation.dedupe.similarity import is_duplicate_description
from job_automation.models.domain import NormalizedJob
from job_automation.storage.models import JobRow


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
        url = canonical_apply_url(job_url, job_url)
        for row in self.existing_jobs:
            if source_job_id and row.source_job_id == source_job_id:
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
            if job.canonical_url and row.canonical_url == job.canonical_url:
                return self._duplicate(job, "Canonical apply URL match")
            if job.identity_hash and row.identity_hash == job.identity_hash:
                return self._duplicate(job, "Company/title/location hash match")
            if job.description_hash and row.description_hash == job.description_hash:
                return self._duplicate(job, "Description hash match")
            if is_duplicate_description(job.description_text, row.description_text):
                return self._duplicate(job, "Description similarity match")
        return job

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
