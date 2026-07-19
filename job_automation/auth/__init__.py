"""Auth helpers and FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select

from job_automation.auth.sessions import COOKIE_NAME, parse_session_token
from job_automation.storage.database import session_scope
from job_automation.storage.models import UserRow


@dataclass
class AuthUser:
    id: int
    email: str


async def get_optional_user(request: Request) -> AuthUser | None:
    token = request.cookies.get(COOKIE_NAME)
    payload = parse_session_token(token)
    if not payload:
        return None
    async with session_scope() as session:
        row = await session.scalar(select(UserRow).where(UserRow.id == int(payload["uid"])))
        if not row:
            return None
        return AuthUser(id=row.id, email=row.email)


async def require_user(request: Request) -> AuthUser:
    user = await get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required to use the job search bot.")
    return user
