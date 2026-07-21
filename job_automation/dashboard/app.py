"""FastAPI dashboard application."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from dotenv import load_dotenv

from job_automation.auth import get_optional_user, require_user
from job_automation.auth.passwords import hash_password, verify_password
from job_automation.auth.sessions import COOKIE_NAME, SESSION_TTL_SEC, create_session_token
from job_automation.browser.credentials import CredentialStore, PortalCredential, SUPPORTED_PORTALS
from job_automation.browser.kasm_client import KasmConfig
from job_automation.dashboard.search_service import (
    get_search_status,
    reset_search_status,
    save_credentials_for_search,
    schedule_search,
    stop_search,
)
from job_automation.models.domain import Decision
from job_automation.paths import PROJECT_ROOT
from job_automation.storage.database import init_db, session_scope
from job_automation.storage.models import UserRow
from job_automation.storage.repositories import JobRepository, PortalCredentialRepository, PortalRunRepository

load_dotenv(PROJECT_ROOT / ".env")

DASHBOARD_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class JobUpdateRequest(BaseModel):
    decision: str | None = None
    manual_note: str | None = None
    status: str | None = None


class JobDeleteRequest(BaseModel):
    job_ids: list[int]


class CredentialSaveRequest(BaseModel):
    username: str
    password: str | None = None
    login_url: str | None = None
    email_app_password: str | None = None


class PortalCredentialPayload(CredentialSaveRequest):
    portal: str
    password: str = ""


class SearchStartRequest(BaseModel):
    portals: list[str] | None = None
    headful: bool = True
    guest: bool = False
    credentials: list[PortalCredentialPayload] = []


class AuthCredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_email(email: str) -> str:
    normalized = _normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return normalized


def _set_session_cookie(response: Response, *, user_id: int, email: str) -> None:
    token = create_session_token(user_id=user_id, email=email)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SEC,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _kasm_view_targets() -> list[dict[str, str]]:
    cfg = KasmConfig.from_env()
    targets: list[dict[str, str]] = []
    # Offline mode: one shared Chrome for everyone (first view URL only).
    urls = list(cfg.view_urls)
    if not urls and cfg.view_url:
        urls = [cfg.view_url]
    if cfg.is_offline and urls:
        urls = urls[:1]
    for index, url in enumerate(urls):
        label = "Shared browser" if cfg.is_offline else f"Browser {index + 1}"
        targets.append({"slot": str(index), "label": label, "url": url})
    return targets


def _shared_kasm_sessions() -> list[dict[str, Any]]:
    """Always-available Watch targets for the shared offline Chrome."""
    cfg = KasmConfig.from_env()
    if not cfg.enabled:
        return []
    return [
        {
            "portal": target["label"],
            "kasm_id": f"shared-{target['slot']}",
            "user_id": "shared",
            "view_url": target["url"],
            "status": "shared",
        }
        for target in _kasm_view_targets()
    ]


def _watch_url_for_session(session: dict[str, Any], index: int) -> str:
    """Prefer JobSeek-gated watch page over raw Kasm URL."""
    portal = (session.get("portal") or f"browser-{index + 1}").strip()
    # Offline shared browser always maps to slot 0.
    cfg = KasmConfig.from_env()
    slot = 0 if cfg.is_offline else index
    return f"/watch/{slot}?portal={portal}"


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
            "version": "0.3.0",
            "search_start": "/api/search/start",
            "search_stop": "/api/search/stop",
            "auth": "/api/auth/me",
            "credentials": "/api/credentials",
            "credentials_sessions": "/api/credentials/sessions",
            "portals": list(SUPPORTED_PORTALS),
        }

    @app.get("/api/auth/me")
    async def auth_me(request: Request) -> dict[str, Any]:
        user = await get_optional_user(request)
        if not user:
            return {"authenticated": False, "user": None}
        return {"authenticated": True, "user": {"id": user.id, "email": user.email}}

    @app.post("/api/auth/signup")
    async def auth_signup(payload: AuthCredentialsRequest, response: Response) -> dict[str, Any]:
        email = _validate_email(payload.email)
        if len(payload.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
        async with session_scope() as session:
            existing = await session.scalar(select(UserRow).where(UserRow.email == email))
            if existing:
                raise HTTPException(status_code=409, detail="An account with this email already exists.")
            row = UserRow(email=email, password_hash=hash_password(payload.password))
            session.add(row)
            await session.flush()
            user_id = row.id
        _set_session_cookie(response, user_id=user_id, email=email)
        return {"authenticated": True, "user": {"id": user_id, "email": email}}

    @app.post("/api/auth/signin")
    async def auth_signin(payload: AuthCredentialsRequest, response: Response) -> dict[str, Any]:
        email = _validate_email(payload.email)
        async with session_scope() as session:
            row = await session.scalar(select(UserRow).where(UserRow.email == email))
            if not row or not verify_password(payload.password, row.password_hash):
                raise HTTPException(status_code=401, detail="Invalid email or password.")
            user_id = row.id
            user_email = row.email
        _set_session_cookie(response, user_id=user_id, email=user_email)
        return {"authenticated": True, "user": {"id": user_id, "email": user_email}}

    @app.post("/api/auth/signout")
    async def auth_signout(response: Response) -> dict[str, Any]:
        _clear_session_cookie(response)
        return {"authenticated": False}

    @app.get("/api/credentials")
    async def list_credentials(request: Request) -> dict[str, Any]:
        user = await require_user(request)
        async with session_scope() as session:
            repo = PortalCredentialRepository(session)
            portals = await repo.list_status(user.id)
        return {"portals": portals, "supported_portals": list(SUPPORTED_PORTALS)}

    @app.get("/api/credentials/sessions")
    async def credential_sessions(request: Request) -> dict[str, Any]:
        await require_user(request)
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
    async def save_credentials(
        portal: str, payload: CredentialSaveRequest, request: Request
    ) -> dict[str, Any]:
        user = await require_user(request)
        if portal not in SUPPORTED_PORTALS:
            raise HTTPException(status_code=400, detail=f"Unsupported portal: {portal}")
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")
        password = payload.password if payload.password else None
        try:
            async with session_scope() as session:
                repo = PortalCredentialRepository(session)
                existing = await repo.get(user.id, portal)
                if existing is None and not password and portal != "builtin":
                    raise HTTPException(status_code=400, detail="Password is required")
                row = await repo.upsert(
                    user.id,
                    portal,
                    username=username,
                    password=password or ("magic-link-placeholder" if portal == "builtin" and not existing else None),
                    login_url=(payload.login_url.strip() if payload.login_url else None),
                    email_app_password=payload.email_app_password or None,
                )
                # Also stage into runner CredentialStore for immediate use.
                cred = repo.to_portal_credential(row)
                CredentialStore().save(portal, cred)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "portal": portal,
            "saved": True,
            "username": username,
            "stored_on": "account",
        }

    @app.delete("/api/credentials/{portal}")
    async def delete_credentials(portal: str, request: Request) -> dict[str, Any]:
        user = await require_user(request)
        if portal not in SUPPORTED_PORTALS:
            raise HTTPException(status_code=400, detail=f"Unsupported portal: {portal}")
        async with session_scope() as session:
            deleted = await PortalCredentialRepository(session).delete(user.id, portal)
        # Clear machine runner cache for this portal too.
        CredentialStore().delete(portal)
        return {"portal": portal, "deleted": deleted}

    @app.delete("/api/credentials/sessions/{portal}")
    async def delete_session(portal: str, request: Request) -> dict[str, Any]:
        await require_user(request)
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
    async def search_status(request: Request) -> dict[str, Any]:
        status = get_search_status()
        kasm = KasmConfig.from_env()
        status = {**status, "kasm_enabled": bool(status.get("kasm_enabled") or kasm.enabled)}
        user = await get_optional_user(request)
        if user:
            sessions = status.get("kasm_sessions") or []
            # One shared Chrome: fall back to configured Watch URL when search
            # is idle, and collapse live sessions to a single Watch link.
            if not sessions:
                sessions = _shared_kasm_sessions()
            elif kasm.is_offline and kasm.enabled:
                sessions = sessions[:1] or _shared_kasm_sessions()
            status = {
                **status,
                "kasm_sessions": [
                    {
                        **session,
                        "view_url": _watch_url_for_session(session, index),
                        "kasm_url": session.get("view_url"),
                    }
                    for index, session in enumerate(sessions)
                    if isinstance(session, dict)
                ],
            }
            return status
        # Free users see progress but not Watch links.
        return {**status, "kasm_sessions": []}

    @app.post("/api/search/reset")
    async def search_reset() -> dict[str, Any]:
        return reset_search_status()

    @app.post("/api/search/start")
    async def search_start(request: Request, payload: SearchStartRequest) -> dict[str, Any]:
        user = await require_user(request)
        if payload.credentials:
            save_credentials_for_search([cred.model_dump() for cred in payload.credentials])
        else:
            # Load portal logins saved on this JobSeek account.
            async with session_scope() as session:
                repo = PortalCredentialRepository(session)
                rows = await repo.list_for_user(user.id)
                if rows:
                    save_credentials_for_search(
                        [
                            {
                                "portal": row.portal,
                                **repo.to_portal_credential(row).model_dump(),
                            }
                            for row in rows
                        ]
                    )
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

    @app.post("/api/search/stop")
    async def search_stop(request: Request) -> dict[str, Any]:
        await require_user(request)
        return stop_search()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"decisions": [Decision.ELIGIBLE.value, Decision.NEEDS_REVIEW.value]},
        )

    @app.get("/watch/{slot}", response_class=HTMLResponse)
    async def watch_browser(request: Request, slot: int, portal: str | None = None) -> HTMLResponse:
        user = await get_optional_user(request)
        next_path = f"/watch/{slot}"
        if portal:
            next_path = f"{next_path}?portal={portal}"
        if not user:
            return RedirectResponse(url=f"/?auth=1&next={next_path}", status_code=302)
        targets = _kasm_view_targets()
        if slot < 0 or slot >= len(targets):
            raise HTTPException(
                status_code=404,
                detail="Watch target not found. Run ./scripts/start_kasm_local.sh and set KASM_VIEW_URLS.",
            )
        target = targets[slot]
        label = portal or target["label"]
        # Prefer a top-level open of KasmVNC (iframe is blocked by COOP/COEP).
        return TEMPLATES.TemplateResponse(
            request,
            "watch.html",
            {
                "label": label,
                "embed_url": target["url"],
                "slot": slot,
                "user_email": user.email,
            },
        )

    @app.get("/api/jobs")
    async def list_jobs(
        q: str | None = None,
        decision: str | None = Query(default=None),
        portal: str | None = None,
        show_hidden: bool = False,
        sort: str = Query(default="relevance"),
        page: int = 1,
        page_size: int = 48,
    ) -> dict[str, Any]:
        decisions = [decision] if decision else None
        async with session_scope() as session:
            repo = JobRepository(session)
            rows, total, companies = await repo.search_jobs(
                q=q,
                decision=decisions,
                portal=portal,
                show_hidden=show_hidden,
                sort=sort,
                page=page,
                page_size=page_size,
            )
            jobs = [_serialize_job(row) for row in rows]
        return {
            "jobs": jobs,
            "total": total,
            "companies": companies,
            "sort": sort,
            "page": page,
            "page_size": page_size,
        }

    @app.post("/api/jobs/clear")
    async def clear_jobs(request: Request) -> dict[str, Any]:
        await require_user(request)
        async with session_scope() as session:
            repo = JobRepository(session)
            result = await repo.clear_all_jobs()
        return {"cleared": True, **result}

    @app.post("/api/jobs/delete")
    async def delete_jobs(request: Request, payload: JobDeleteRequest) -> dict[str, Any]:
        await require_user(request)
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
            if "status" in fields and fields["status"] is not None:
                fields["status"] = str(fields["status"]).strip().lower()
                allowed = {"new", "saved", "applied", "hidden"}
                if fields["status"] not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid status. Allowed: {', '.join(sorted(allowed))}",
                    )
            row = await repo.update_job(job_id, **fields)
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
            await session.flush()
            return _serialize_job(row, include_description=True)

    @app.post("/api/jobs/{job_id}/delete")
    async def delete_job(request: Request, job_id: int) -> dict[str, Any]:
        await require_user(request)
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
    top_skills = _skills_from_row(row, evidence)
    requirements_summary = (
        getattr(row, "requirements_summary", None)
        or _evidence_text_value(evidence, "requirements_summary")
        or _evidence_text_value(evidence, "match_background")
    )
    data = {
        "id": row.id,
        "source_portal": row.source_portal,
        "title": row.title,
        "company": row.company,
        "company_url": row.company_url,
        "company_headline": getattr(row, "company_headline", None),
        "requirements_summary": requirements_summary,
        "match_background": requirements_summary,
        "top_skills": top_skills,
        "skills_required": top_skills,
        "location": row.location,
        "location_eligible": getattr(row, "location_eligible", None),
        "remote_policy": row.remote_policy,
        "remote_eligible": getattr(row, "remote_eligible", None),
        "work_type": getattr(row, "work_type", None),
        "commitment": getattr(row, "commitment", None),
        "experience_level": row.experience_level,
        "industry": row.industry,
        "salary_text": row.salary_text,
        "posted_text": getattr(row, "posted_text", None),
        "posted_at": f"{row.posted_at.isoformat()}Z" if getattr(row, "posted_at", None) else None,
        "is_reposted": bool(getattr(row, "is_reposted", False)),
        "decision": row.decision,
        "decision_reason": row.decision_reason,
        "is_easy_apply": _is_easy_apply_job(row, evidence),
        "status": row.status or "new",
        "apply_url": row.apply_url,
        "job_url": row.job_url,
        "created_at": f"{row.created_at.isoformat()}Z" if row.created_at else None,
        "manual_note": row.manual_note,
        "evidence": evidence,
    }
    if include_description:
        data["description_text"] = row.description_text
    return data


def _is_easy_apply_job(row: Any, evidence: list[Any]) -> bool:
    reason = str(getattr(row, "decision_reason", None) or "").strip().lower()
    if reason == "easy apply" or "easy apply" in reason:
        return True
    for item in evidence or []:
        if isinstance(item, dict) and str(item.get("field") or "").lower() == "easy_apply":
            return True
    apply_url = str(getattr(row, "apply_url", None) or "").strip().lower()
    return "builtin.com" in apply_url and "/apply/" in apply_url


def _skills_from_row(row: Any, evidence: list[Any]) -> list[str]:
    raw = getattr(row, "top_skills_json", None)
    if raw:
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                skills = [str(part).strip() for part in value if str(part).strip()]
                if skills:
                    return skills
        except json.JSONDecodeError:
            pass
    return (
        _evidence_list_value(evidence, "top_skills")
        or _evidence_list_value(evidence, "skills_required")
    )


def _evidence_text_value(evidence: list[Any], field: str) -> str | None:
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("field") or "").lower() != field:
            continue
        text = item.get("evidence_text") or item.get("value")
        if text is None:
            return None
        if isinstance(text, list):
            return ", ".join(str(part) for part in text if part)
        return str(text)
    return None


def _evidence_list_value(evidence: list[Any], field: str) -> list[str]:
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("field") or "").lower() != field:
            continue
        value = item.get("value")
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()]
        text = item.get("evidence_text") or value
        if not text:
            return []
        return [part.strip() for part in re.split(r"\s*,\s*", str(text)) if part.strip()]
    return []
