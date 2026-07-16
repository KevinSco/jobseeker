"""Job search execution and status for the dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

from job_automation.browser.credentials import CredentialStore, PortalCredential
from job_automation.browser.portal_login import normalize_login_url
from job_automation.paths import DATA_DIR, PROJECT_ROOT, ensure_dirs

STATUS_PATH = DATA_DIR / "search_status.json"
LOG_PATH = DATA_DIR / "search_run.log"
SUPPORTED_PORTALS = ["hiringcafe", "builtin", "jobright", "glassdoor"]


def _read_status() -> dict:
    if not STATUS_PATH.exists():
        return {"running": False}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"running": False}


def _write_status(data: dict) -> None:
    ensure_dirs()
    STATUS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_search_status() -> dict:
    status = _read_status()
    if status.get("running") and not _process_alive(status.get("pid")):
        status["running"] = False
        if not status.get("finished_at"):
            status["finished_at"] = datetime.utcnow().isoformat()
            status["error"] = status.get("error") or "Search process ended unexpectedly"
        _write_status(status)
    return status


def reset_search_status() -> dict:
    _write_status({"running": False, "reset_at": datetime.utcnow().isoformat()})
    return get_search_status()


def save_credentials_for_search(credentials: list[dict]) -> None:
    store = CredentialStore()
    for cred in credentials:
        portal = cred["portal"]
        login_url = normalize_login_url(portal, cred.get("login_url"))
        store.save(
            portal,
            PortalCredential(
                username=cred["username"].strip(),
                password=cred["password"],
                login_url=login_url,
                email_app_password=cred.get("email_app_password"),
            ),
        )


def schedule_search(
    portals: list[str] | None = None,
    *,
    headful: bool = True,
    guest: bool = False,
) -> dict:
    current = get_search_status()
    if current.get("running"):
        raise RuntimeError("A job search is already running")

    portals = portals or SUPPORTED_PORTALS
    invalid = [p for p in portals if p not in SUPPORTED_PORTALS]
    if invalid:
        raise ValueError(f"Unknown portals: {invalid}")

    cmd = [sys.executable, "-m", "job_automation.main", "run"]
    if headful:
        cmd.append("--headful")
    if guest:
        cmd.append("--guest")
    for portal in portals:
        cmd.extend(["--portal", portal])

    ensure_dirs()
    log_file = open(LOG_PATH, "w", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    log_file.close()

    status = {
        "running": True,
        "pid": proc.pid,
        "portals": portals,
        "headful": headful,
        "guest": guest,
        "found": 0,
        "saved": 0,
        "started_at": datetime.utcnow().isoformat(),
        "command": " ".join(cmd),
        "log_file": str(LOG_PATH),
    }
    _write_status(status)
    return status


def mark_search_finished(summary: dict | None = None, *, error: str | None = None) -> None:
    status = _read_status()
    status["running"] = False
    status["finished_at"] = datetime.utcnow().isoformat()
    if summary is not None:
        status["summary"] = summary
        status["found"] = summary.get("found", status.get("found", 0))
        status["saved"] = summary.get("saved", status.get("saved", 0))
    if error:
        status["error"] = error
    _write_status(status)


def update_search_progress(
    *,
    found: int | None = None,
    saved: int | None = None,
    last_job_title: str | None = None,
    last_decision: str | None = None,
) -> None:
    status = _read_status()
    if not status.get("running"):
        return
    if found is not None:
        status["found"] = found
    if saved is not None:
        status["saved"] = saved
    if last_job_title is not None:
        status["last_job_title"] = last_job_title
    if last_decision is not None:
        status["last_decision"] = last_decision
    status["updated_at"] = datetime.utcnow().isoformat()
    _write_status(status)
