"""Data access layer."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from job_automation.models.domain import Decision, Evidence, NormalizedJob, PortalRunStatus
from job_automation.storage.models import BannedCompanyRow, JobRow, JobSourceRow, PortalRunRow


def _evidence_to_json(evidence: list[Evidence]) -> str:
    return json.dumps([e.model_dump() for e in evidence], ensure_ascii=False)


def _evidence_from_json(raw: str | None) -> list[Evidence]:
    if not raw:
        return []
    return [Evidence.model_validate(item) for item in json.loads(raw)]


def job_row_to_normalized(row: JobRow) -> NormalizedJob:
    return NormalizedJob(
        source_portal=row.source_portal or "",
        source_job_id=row.source_job_id,
        title=row.title,
        company=row.company,
        location=row.location,
        remote_policy=row.remote_policy,
        commitment=row.commitment,
        experience_level=row.experience_level,
        industry=row.industry,
        salary_text=row.salary_text,
        salary_min_annual=row.salary_min_annual,
        salary_max_annual=row.salary_max_annual,
        salary_min_hourly=row.salary_min_hourly,
        salary_max_hourly=row.salary_max_hourly,
        security_clearance_required=row.security_clearance_required,
        travel_required=row.travel_required,
        security_related_company_or_role=row.security_related_company_or_role,
        role_excluded=row.role_excluded,
        job_url=row.job_url,
        apply_url=row.apply_url,
        canonical_url=row.canonical_url,
        description_text=row.description_text,
        raw_html=row.raw_html,
        description_hash=row.description_hash,
        identity_hash=row.identity_hash,
        is_duplicate=row.is_duplicate,
        decision=Decision(row.decision) if row.decision else None,
        decision_reason=row.decision_reason,
        evidence=_evidence_from_json(row.evidence_json),
        status=row.status,
        manual_note=row.manual_note,
    )


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_identity_hash(self, identity_hash: str) -> JobRow | None:
        result = await self.session.execute(
            select(JobRow).where(JobRow.identity_hash == identity_hash).limit(1)
        )
        return result.scalar_one_or_none()

    async def find_by_canonical_url(self, canonical_url: str) -> JobRow | None:
        result = await self.session.execute(
            select(JobRow).where(JobRow.canonical_url == canonical_url).limit(1)
        )
        return result.scalar_one_or_none()

    async def find_by_source(self, portal: str, source_job_id: str) -> JobRow | None:
        result = await self.session.execute(
            select(JobRow)
            .where(JobRow.source_portal == portal, JobRow.source_job_id == source_job_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_job(self, job: NormalizedJob) -> JobRow:
        existing: JobRow | None = None
        if job.identity_hash:
            existing = await self.find_by_identity_hash(job.identity_hash)
        if existing is None and job.canonical_url:
            existing = await self.find_by_canonical_url(job.canonical_url)
        if existing is None and job.source_job_id:
            existing = await self.find_by_source(job.source_portal, job.source_job_id)

        if existing and job.is_duplicate:
            row = existing
            row.updated_at = datetime.utcnow()
            await self.add_source(
                row.id,
                job.source_portal,
                job.source_job_id,
                job.job_url,
                job.apply_url,
            )
            await self.session.flush()
            return row

        if existing:
            row = existing
            row.updated_at = datetime.utcnow()
        else:
            row = JobRow()
            self.session.add(row)

        row.source_portal = job.source_portal
        row.source_job_id = job.source_job_id
        row.title = job.title
        row.company = job.company
        row.location = job.location
        row.remote_policy = job.remote_policy
        row.commitment = job.commitment
        row.experience_level = job.experience_level
        row.industry = job.industry
        row.salary_text = job.salary_text
        row.salary_min_annual = job.salary_min_annual
        row.salary_max_annual = job.salary_max_annual
        row.salary_min_hourly = job.salary_min_hourly
        row.salary_max_hourly = job.salary_max_hourly
        row.security_clearance_required = job.security_clearance_required
        row.travel_required = job.travel_required
        row.security_related_company_or_role = job.security_related_company_or_role
        row.role_excluded = job.role_excluded
        row.job_url = job.job_url
        row.apply_url = job.apply_url
        row.canonical_url = job.canonical_url
        row.description_text = job.description_text
        row.raw_html = job.raw_html
        row.description_hash = job.description_hash
        row.identity_hash = job.identity_hash
        row.is_duplicate = job.is_duplicate
        row.decision = job.decision.value if job.decision else None
        row.decision_reason = job.decision_reason
        row.evidence_json = _evidence_to_json(job.evidence)
        row.status = job.status
        row.manual_note = job.manual_note

        await self.session.flush()
        await self.add_source(
            row.id,
            job.source_portal,
            job.source_job_id,
            job.job_url,
            job.apply_url,
        )
        return row

    async def add_source(
        self,
        job_id: int,
        portal: str,
        source_job_id: str | None,
        job_url: str | None,
        apply_url: str | None,
    ) -> None:
        result = await self.session.execute(
            select(JobSourceRow).where(
                JobSourceRow.job_id == job_id,
                JobSourceRow.source_portal == portal,
                JobSourceRow.source_job_id == source_job_id,
            )
        )
        if result.scalar_one_or_none():
            return
        self.session.add(
            JobSourceRow(
                job_id=job_id,
                source_portal=portal,
                source_job_id=source_job_id,
                job_url=job_url,
                apply_url=apply_url,
            )
        )

    async def get_job(self, job_id: int) -> JobRow | None:
        result = await self.session.execute(select(JobRow).where(JobRow.id == job_id))
        return result.scalar_one_or_none()

    async def search_jobs(
        self,
        *,
        q: str | None = None,
        decision: list[str] | None = None,
        portal: str | None = None,
        show_hidden: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[JobRow], int]:
        stmt: Select[tuple[JobRow]] = select(JobRow)
        if decision:
            stmt = stmt.where(JobRow.decision.in_(decision))
        elif not show_hidden:
            stmt = stmt.where(
                JobRow.decision.in_([Decision.ELIGIBLE.value, Decision.NEEDS_REVIEW.value])
            )
        if portal:
            stmt = stmt.where(JobRow.source_portal == portal)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    JobRow.title.ilike(pattern),
                    JobRow.company.ilike(pattern),
                    JobRow.location.ilike(pattern),
                    JobRow.description_text.ilike(pattern),
                )
            )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(JobRow.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def update_job(self, job_id: int, **fields: Any) -> JobRow | None:
        row = await self.get_job(job_id)
        if not row:
            return None
        for key, value in fields.items():
            if key == "evidence" and isinstance(value, list):
                row.evidence_json = _evidence_to_json(value)
            elif hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        await self.session.flush()
        return row

    async def clear_all_jobs(self) -> dict[str, int]:
        sources = await self.session.execute(delete(JobSourceRow))
        jobs = await self.session.execute(delete(JobRow))
        runs = await self.session.execute(delete(PortalRunRow))
        return {
            "jobs_deleted": jobs.rowcount or 0,
            "sources_deleted": sources.rowcount or 0,
            "runs_deleted": runs.rowcount or 0,
        }


class PortalRunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def start_run(self, portal: str) -> PortalRunRow:
        row = PortalRunRow(
            source_portal=portal,
            started_at=datetime.utcnow(),
            status=PortalRunStatus.RUNNING.value,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def finish_run(
        self,
        run_id: int,
        *,
        status: PortalRunStatus,
        jobs_found: int = 0,
        jobs_saved: int = 0,
        jobs_failed: int = 0,
        error_message: str | None = None,
    ) -> None:
        await self.session.execute(
            update(PortalRunRow)
            .where(PortalRunRow.id == run_id)
            .values(
                finished_at=datetime.utcnow(),
                status=status.value,
                jobs_found=jobs_found,
                jobs_saved=jobs_saved,
                jobs_failed=jobs_failed,
                error_message=error_message,
            )
        )

    async def recent_runs(self, limit: int = 10) -> list[PortalRunRow]:
        result = await self.session.execute(
            select(PortalRunRow).order_by(PortalRunRow.started_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def failed_portals(self) -> list[str]:
        result = await self.session.execute(
            select(PortalRunRow.source_portal)
            .where(PortalRunRow.status.in_([PortalRunStatus.FAILED.value, PortalRunStatus.NEEDS_MANUAL_LOGIN.value]))
            .order_by(PortalRunRow.started_at.desc())
        )
        seen: set[str] = set()
        portals: list[str] = []
        for portal in result.scalars().all():
            if portal not in seen:
                seen.add(portal)
                portals.append(portal)
        return portals


def _normalize_company_name(name: str) -> str:
    import re

    return re.sub(r"\s+", " ", name).strip().lower()


class BannedCompanyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_banned(self, company_name: str | None) -> bool:
        if not company_name or not company_name.strip():
            return False
        normalized = _normalize_company_name(company_name)
        result = await self.session.execute(
            select(BannedCompanyRow)
            .where(BannedCompanyRow.company_name_normalized == normalized)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_normalized_names(self) -> set[str]:
        result = await self.session.execute(select(BannedCompanyRow.company_name_normalized))
        return {row for row in result.scalars().all()}

    async def add(self, company_name: str, reason: str | None = None) -> BannedCompanyRow:
        normalized = _normalize_company_name(company_name)
        existing = await self.session.execute(
            select(BannedCompanyRow)
            .where(BannedCompanyRow.company_name_normalized == normalized)
            .limit(1)
        )
        row = existing.scalar_one_or_none()
        if row:
            return row
        row = BannedCompanyRow(
            company_name=company_name.strip(),
            company_name_normalized=normalized,
            reason=reason,
        )
        self.session.add(row)
        await self.session.flush()
        return row
