"""End-to-end test: pipeline save + dashboard API."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from job_automation.config.loader import load_rules
from job_automation.dashboard.app import create_app
from job_automation.dedupe.deduplicate import DeduplicationEngine
from job_automation.etl.pipeline import transform_raw_job
from job_automation.models.domain import Decision, PortalRunStatus, RawJob
from job_automation.rules.rule_engine import RuleEngine
from job_automation.storage.database import init_db, session_scope
from job_automation.storage.repositories import JobRepository, PortalRunRepository


SAMPLE_JOBS = [
    RawJob(
        source_portal="hiringcafe",
        source_job_id="hc-001",
        job_card_title="Backend Software Engineer",
        job_card_company="Example Corp",
        job_card_location="Remote, United States",
        job_card_salary="$120,000 - $150,000",
        portal_job_url="https://hiring.cafe/job/hc-001",
        apply_url="https://example.com/careers/backend",
        description_text=(
            "Fully remote within the United States. Full-time role. "
            "Mid level software engineer using Python and JavaScript. "
            "No travel required. Salary range $120,000 - $150,000."
        ),
    ),
    RawJob(
        source_portal="builtin",
        source_job_id="bi-002",
        job_card_title="DevOps Engineer",
        job_card_company="Ops Inc",
        job_card_location="Remote",
        job_card_salary="$130,000",
        portal_job_url="https://builtin.com/job/bi-002",
        apply_url="https://ops.example/apply",
        description_text="Fully remote DevOps Engineer with Python experience.",
    ),
    RawJob(
        source_portal="jobright",
        source_job_id="jr-003",
        job_card_title="Software Engineer Python",
        job_card_company="Example Corp",
        job_card_location="Remote, US",
        portal_job_url="https://jobright.ai/job/jr-003",
        apply_url="https://example.com/careers/backend?utm_source=jobright",
        description_text=(
            "Fully remote within the United States. Python backend engineer. "
            "Duplicate of Example Corp backend role."
        ),
    ),
]


async def _seed_database() -> dict[str, int]:
    config = load_rules()
    dedupe = DeduplicationEngine([])
    rules = RuleEngine(config)
    counts = {"eligible": 0, "needs_review": 0, "rejected": 0, "duplicate": 0}

    await init_db()
    async with session_scope() as session:
        run_repo = PortalRunRepository(session)
        run = await run_repo.start_run("e2e-test")
        run_id = run.id

    for raw in SAMPLE_JOBS:
        normalized = transform_raw_job(raw, config)
        normalized = dedupe.mark_duplicates(normalized)
        if not normalized.is_duplicate:
            normalized = rules.decide(normalized)
        async with session_scope() as session:
            repo = JobRepository(session)
            row = await repo.upsert_job(normalized)
            dedupe.existing_jobs.append(row)
        decision = normalized.decision.value if normalized.decision else "unknown"
        counts[decision] = counts.get(decision, 0) + 1

    async with session_scope() as session:
        run_repo = PortalRunRepository(session)
        await run_repo.finish_run(
            run_id,
            status=PortalRunStatus.SUCCESS,
            jobs_found=len(SAMPLE_JOBS),
            jobs_saved=len(SAMPLE_JOBS),
        )

    return counts


@pytest.fixture(scope="module")
def seeded_client():
    asyncio.run(_seed_database())
    app = create_app()
    with TestClient(app) as client:
        yield client


def _ensure_signed_in(client: TestClient) -> None:
    email = "e2e-bot@example.com"
    password = "test-password-123"
    signup = client.post("/api/auth/signup", json={"email": email, "password": password})
    if signup.status_code == 409:
        signed = client.post("/api/auth/signin", json={"email": email, "password": password})
        assert signed.status_code == 200, signed.text
    else:
        assert signup.status_code == 200, signup.text


def test_e2e_dashboard_home(seeded_client: TestClient):
    response = seeded_client.get("/")
    assert response.status_code == 200
    assert "JobSeek Auto" in response.text
    assert "Search collected jobs" in response.text


def test_e2e_jobs_api_default_visible(seeded_client: TestClient):
    response = seeded_client.get("/api/jobs")
    assert response.status_code == 200
    data = response.json()
    decisions = {job["decision"] for job in data["jobs"]}
    assert decisions.issubset({Decision.ELIGIBLE.value, Decision.NEEDS_REVIEW.value})
    assert data["total"] >= 1


def test_e2e_jobs_search(seeded_client: TestClient):
    response = seeded_client.get("/api/jobs", params={"q": "Example"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any("Example" in (job.get("company") or "") for job in data["jobs"])


def test_e2e_show_hidden(seeded_client: TestClient):
    response = seeded_client.get("/api/jobs", params={"show_hidden": "true"})
    assert response.status_code == 200
    data = response.json()
    decisions = {job["decision"] for job in data["jobs"]}
    assert Decision.REJECTED.value in decisions or Decision.DUPLICATE.value in decisions


def test_e2e_job_detail_and_patch(seeded_client: TestClient):
    listing = seeded_client.get("/api/jobs", params={"show_hidden": "true"})
    job_id = listing.json()["jobs"][0]["id"]
    detail = seeded_client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["evidence"]

    patched = seeded_client.patch(
        f"/api/jobs/{job_id}",
        json={"decision": "needs_review", "manual_note": "e2e test note"},
    )
    assert patched.status_code == 200
    assert patched.json()["decision"] == "needs_review"
    assert patched.json()["manual_note"] == "e2e test note"


def test_search_start_api(seeded_client: TestClient):
    _ensure_signed_in(seeded_client)
    seeded_client.post("/api/search/reset")
    response = seeded_client.post(
        "/api/search/start",
        json={
            "portals": ["builtin"],
            "headful": True,
            "guest": True,
            "credentials": [
                {
                    "portal": "builtin",
                    "username": "test@example.com",
                    "password": "test-password",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("running") is True
    assert "builtin" in data.get("portals", [])

    stopped = seeded_client.post("/api/search/stop")
    assert stopped.status_code == 200, stopped.text
    stop_data = stopped.json()
    assert stop_data.get("running") is False
    assert stop_data.get("stopped") is True


def test_search_stop_when_idle(seeded_client: TestClient):
    _ensure_signed_in(seeded_client)
    seeded_client.post("/api/search/reset")
    response = seeded_client.post("/api/search/stop")
    assert response.status_code == 200
    data = response.json()
    assert data.get("running") is False
    assert data.get("stopped") is True


def test_health_api(seeded_client: TestClient):
    response = seeded_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_hide_job_excluded_from_list(seeded_client: TestClient):
    listing = seeded_client.get("/api/jobs?page=1&page_size=50&show_hidden=true")
    assert listing.status_code == 200
    jobs = listing.json()["jobs"]
    assert jobs, "expected seeded jobs"
    job_id = jobs[0]["id"]

    patched = seeded_client.patch(f"/api/jobs/{job_id}", json={"status": "hidden"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "hidden"

    after = seeded_client.get("/api/jobs?page=1&page_size=200&show_hidden=true")
    assert after.status_code == 200
    ids = [job["id"] for job in after.json()["jobs"]]
    assert job_id not in ids
    assert all(str(job.get("status") or "").lower() != "hidden" for job in after.json()["jobs"])

    # Rejected/eligible tabs must also keep user-hidden jobs out.
    for decision in ("eligible", "needs_review", "rejected"):
        filtered = seeded_client.get(
            f"/api/jobs?page=1&page_size=200&decision={decision}&show_hidden=true"
        )
        assert filtered.status_code == 200
        assert job_id not in [job["id"] for job in filtered.json()["jobs"]]


def test_delete_session_api(seeded_client: TestClient, tmp_path, monkeypatch):
    from job_automation import paths

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_file = sessions_dir / "builtin.json"
    session_file.write_text('{"cookies": []}', encoding="utf-8")
    monkeypatch.setattr(paths, "SESSIONS_DIR", sessions_dir)

    missing = seeded_client.delete("/api/credentials/sessions/hiringcafe")
    assert missing.status_code == 200
    assert missing.json()["session_deleted"] is False

    response = seeded_client.delete("/api/credentials/sessions/builtin")
    assert response.status_code == 200
    assert response.json()["session_deleted"] is True
    assert not session_file.exists()


def test_logs_api(seeded_client: TestClient, tmp_path, monkeypatch):
    from job_automation import paths
    from job_automation.dashboard import search_service

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "automation.log").write_text(
        "2026-07-15 00:00:00 | INFO | builtin | - | search | Searching Built In keyword: Python\n",
        encoding="utf-8",
    )
    search_log = tmp_path / "search_run.log"
    search_log.write_text("search subprocess started\n", encoding="utf-8")
    monkeypatch.setattr(paths, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(search_service, "LOG_PATH", search_log)

    response = seeded_client.get("/api/logs", params={"source": "all", "lines": 50})
    assert response.status_code == 200
    data = response.json()
    assert "Searching Built In keyword: Python" in data["content"]
    assert "search subprocess started" in data["content"]


def test_e2e_runs_api(seeded_client: TestClient):
    response = seeded_client.get("/api/runs")
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) >= 1
    assert runs[0]["source_portal"] == "e2e-test"
