"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_portal: Mapped[str | None] = mapped_column(String(64))
    source_job_id: Mapped[str | None] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(512))
    company: Mapped[str | None] = mapped_column(String(512))
    location: Mapped[str | None] = mapped_column(String(512))
    remote_policy: Mapped[str | None] = mapped_column(String(128))
    commitment: Mapped[str | None] = mapped_column(String(64))
    experience_level: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(256))
    salary_text: Mapped[str | None] = mapped_column(String(256))
    salary_min_annual: Mapped[int | None] = mapped_column(Integer)
    salary_max_annual: Mapped[int | None] = mapped_column(Integer)
    salary_min_hourly: Mapped[float | None] = mapped_column(Float)
    salary_max_hourly: Mapped[float | None] = mapped_column(Float)
    security_clearance_required: Mapped[bool | None] = mapped_column(Boolean)
    travel_required: Mapped[bool | None] = mapped_column(Boolean)
    security_related_company_or_role: Mapped[bool | None] = mapped_column(Boolean)
    role_excluded: Mapped[bool | None] = mapped_column(Boolean)
    job_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    description_hash: Mapped[str | None] = mapped_column(String(64))
    identity_hash: Mapped[str | None] = mapped_column(String(64))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str | None] = mapped_column(String(32))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="new")
    manual_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    sources: Mapped[list[JobSourceRow]] = relationship(back_populates="job")


class JobSourceRow(Base):
    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    source_portal: Mapped[str | None] = mapped_column(String(64))
    source_job_id: Mapped[str | None] = mapped_column(String(256))
    job_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped[JobRow] = relationship(back_populates="sources")


class PortalRunRow(Base):
    __tablename__ = "portal_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_portal: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str | None] = mapped_column(String(32))
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_saved: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
