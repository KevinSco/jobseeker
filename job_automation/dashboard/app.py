"""FastAPI dashboard application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from job_automation.models.domain import Decision
from job_automation.browser.credentials import CredentialStore, PortalCredential, SUPPORTED_PORTALS
from job_automation.dashboard.search_service import (
    get_search_status,
    reset_search_status,
    save_credentials_for_search,
    schedule_search,
)
from job_automation.storage.database import init_db, session_scope
from job_automation.storage.repositories import JobRepository, PortalRunRepository

DASHBOARD_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))


class JobUpdateRequest(BaseModel):
    decision: str | None = None
    manual_note: str | None = None
    status: str | None = None


class JobDeleteRequest(BaseModel):
    job_ids: list[int]


class CredentialSaveRequest(BaseModel):
    username: str
    password: str
    login_url: str | None = None
    email_app_password: str | None = None


class PortalCredentialPayload(CredentialSaveRequest):
    portal: str


class SearchStartRequest(BaseModel):
    portals: list[str] | None = None
    headful: bool = True
    guest: bool = False
    credentials: list[PortalCredentialPayload] = []


def create_app() -> FastAPI:
    app = FastAPI(title="Job Search Automation Dashboard")
    static_dir = DASHBOARD_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    @app.on_event("startup")
    async def startup() -> None:
        await init_db()

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.2.0",
            "search_start": "/api/search/start",
            "credentials_sessions": "/api/credentials/sessions",
            "portals": list(SUPPORTED_PORTALS),
        }

    @app.get("/api/credentials/sessions")
    async def credential_sessions() -> dict[str, Any]:
        from job_automation.paths import SESSIONS_DIR

        return {
            "portals": [
                {
                    "portal": portal,
                    "has_session": (SESSIONS_DIR / f"{portal}.json").exists(),
                }
                for portal in SUPPORTED_PORTALS
            ]
        }

    @app.put("/api/credentials/{portal}")
    async def save_credentials(portal: str, payload: CredentialSaveRequest) -> dict[str, Any]:
        if portal not in SUPPORTED_PORTALS:
            raise HTTPException(status_code=400, detail=f"Unsupported portal: {portal}")
        store = CredentialStore()
        store.save(
            portal,
            PortalCredential(
                username=payload.username.strip(),
                password=payload.password,
                login_url=payload.login_url,
                email_app_password=payload.email_app_password,
            ),
        )
        return {"portal": portal, "saved": True, "username": payload.username.strip()}

    @app.delete("/api/credentials/{portal}")
    async def delete_credentials(portal: str) -> dict[str, Any]:
        if portal not in SUPPORTED_PORTALS:
            raise HTTPException(status_code=400, detail=f"Unsupported portal: {portal}")
        CredentialStore().delete(portal)
        return {"portal": portal, "deleted": True}

    @app.delete("/api/credentials/sessions/{portal}")
    async def delete_session(portal: str) -> dict[str, Any]:
        if portal not in SUPPORTED_PORTALS:
            raise HTTPException(status_code=400, detail=f"Unsupported portal: {portal}")
        from job_automation.paths import SESSIONS_DIR

        session_path = SESSIONS_DIR / f"{portal}.json"
        deleted = False
        if session_path.exists():
            session_path.unlink()
            deleted = True
        return {"portal": portal, "session_deleted": deleted}

    @app.get("/api/search/status")
    async def search_status() -> dict[str, Any]:
        return get_search_status()

    @app.post("/api/search/reset")
    async def search_reset() -> dict[str, Any]:
        return reset_search_status()

    @app.post("/api/search/start")
    async def search_start(payload: SearchStartRequest) -> dict[str, Any]:
        if payload.credentials:
            save_credentials_for_search([cred.model_dump() for cred in payload.credentials])
        try:
            return schedule_search(
                payload.portals,
                headful=payload.headful,
                guest=payload.guest,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"decisions": [Decision.ELIGIBLE.value, Decision.NEEDS_REVIEW.value]},
        )

    @app.get("/api/jobs")
    async def list_jobs(
        q: str | None = None,
        decision: str | None = Query(default=None),
        portal: str | None = None,
        show_hidden: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        decisions = [decision] if decision else None
        async with session_scope() as session:
            repo = JobRepository(session)
            rows, total = await repo.search_jobs(
                q=q,
                decision=decisions,
                portal=portal,
                show_hidden=show_hidden,
                page=page,
                page_size=page_size,
            )
            jobs = [_serialize_job(row) for row in rows]
        return {"jobs": jobs, "total": total, "page": page, "page_size": page_size}

    @app.post("/api/jobs/clear")
    async def clear_jobs() -> dict[str, Any]:
        async with session_scope() as session:
            repo = JobRepository(session)
            result = await repo.clear_all_jobs()
        return {"cleared": True, **result}

    @app.post("/api/jobs/delete")
    async def delete_jobs(payload: JobDeleteRequest) -> dict[str, Any]:
        async with session_scope() as session:
            repo = JobRepository(session)
            deleted = await repo.delete_jobs(payload.job_ids)
        return {"deleted": True, "jobs_deleted": deleted, "job_ids": payload.job_ids}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: int) -> dict[str, Any]:
        async with session_scope() as session:
            repo = JobRepository(session)
            row = await repo.get_job(job_id)
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
            return _serialize_job(row, include_description=True)

    @app.patch("/api/jobs/{job_id}")
    async def update_job(job_id: int, payload: JobUpdateRequest) -> dict[str, Any]:
        async with session_scope() as session:
            repo = JobRepository(session)
            fields = payload.model_dump(exclude_none=True)
            row = await repo.update_job(job_id, **fields)
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
            return _serialize_job(row, include_description=True)

    @app.post("/api/jobs/{job_id}/delete")
    async def delete_job(job_id: int) -> dict[str, Any]:
        async with session_scope() as session:
            repo = JobRepository(session)
            deleted = await repo.delete_job(job_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Job not found")
        return {"deleted": True, "job_id": job_id}

    @app.get("/api/runs")
    async def list_runs(limit: int = 10) -> dict[str, Any]:
        async with session_scope() as session:
            repo = PortalRunRepository(session)
            runs = await repo.recent_runs(limit=limit)
        return {
            "runs": [
                {
                    "id": run.id,
                    "source_portal": run.source_portal,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "status": run.status,
                    "jobs_found": run.jobs_found,
                    "jobs_saved": run.jobs_saved,
                    "jobs_failed": run.jobs_failed,
                    "error_message": run.error_message,
                }
                for run in runs
            ]
        }

    @app.get("/api/logs")
    async def worker_logs(
        source: str = Query(default="automation"),
        lines: int = Query(default=300, ge=20, le=2000),
    ) -> dict[str, Any]:
        from job_automation.dashboard.search_service import LOG_PATH
        from job_automation.paths import LOGS_DIR

        sources = {
            "automation": LOGS_DIR / "automation.log",
            "search": LOG_PATH,
        }
        if source not in {"automation", "search", "all"}:
            raise HTTPException(status_code=400, detail="source must be automation, search, or all")

        selected = list(sources.items()) if source == "all" else [(source, sources[source])]
        chunks: list[str] = []
        files: list[dict[str, Any]] = []
        for name, path in selected:
            exists = path.exists()
            files.append({"name": name, "path": str(path), "exists": exists})
            if not exists:
                chunks.append(f"===== {name} =====\n(no log file yet)\n")
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                chunks.append(f"===== {name} =====\n(error reading log: {exc})\n")
                continue
            tail = "\n".join(text.splitlines()[-lines:])
            chunks.append(f"===== {name} =====\n{tail}\n")

        return {
            "source": source,
            "lines": lines,
            "files": files,
            "content": "\n".join(chunks).rstrip() + "\n",
        }

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def _serialize_job(row, *, include_description: bool = False) -> dict[str, Any]:
    evidence = json.loads(row.evidence_json) if row.evidence_json else []
    data = {
        "id": row.id,
        "source_portal": row.source_portal,
        "title": row.title,
        "company": row.company,
        "company_url": row.company_url,
        "location": row.location,
        "remote_policy": row.remote_policy,
        "salary_text": row.salary_text,
        "decision": row.decision,
        "decision_reason": row.decision_reason,
        "apply_url": row.apply_url,
        "job_url": row.job_url,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "manual_note": row.manual_note,
        "evidence": evidence,
    }
    if include_description:
        data["description_text"] = row.description_text
    return data
