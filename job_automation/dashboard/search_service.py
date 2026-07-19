"""Job search execution and status for the dashboard."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

from job_automation.browser.credentials import CredentialStore, PortalCredential
from job_automation.browser.kasm_client import KasmConfig
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
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_process(pid: int) -> None:
    """Stop the search process and its children."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return

    # Prefer process group (spawned with start_new_session=True).
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return

    for _ in range(30):
        if not _process_alive(pid):
            return
        time.sleep(0.1)

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def get_search_status() -> dict:
    status = _read_status()
    if status.get("running") and not _process_alive(status.get("pid")):
        status["running"] = False
        if not status.get("finished_at"):
            status["finished_at"] = datetime.utcnow().isoformat()
            if not status.get("stopped"):
                status["error"] = status.get("error") or "Search process ended unexpectedly"
        _write_status(status)
    return status


def reset_search_status() -> dict:
    _write_status({"running": False, "reset_at": datetime.utcnow().isoformat()})
    return get_search_status()


def stop_search() -> dict:
    """Stop a running search bot process (if any) and mark status as stopped."""
    status = _read_status()
    pid = status.get("pid")
    was_running = bool(status.get("running")) or _process_alive(pid)

    if pid and _process_alive(pid):
        _terminate_process(int(pid))

    status = _read_status()
    status["running"] = False
    status["stopped"] = True
    status["finished_at"] = datetime.utcnow().isoformat()
    status["kasm_sessions"] = []
    # Clear hard error so the UI treats this as an intentional stop.
    status.pop("error", None)
    status["stop_message"] = "Stopped by user" if was_running else "No search was running"
    status["updated_at"] = datetime.utcnow().isoformat()
    _write_status(status)
    return get_search_status()


def update_search_kasm_sessions(sessions: list[dict[str, Any]]) -> None:
    status = _read_status()
    status["kasm_sessions"] = sessions
    status["updated_at"] = datetime.utcnow().isoformat()
    _write_status(status)


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

    kasm = KasmConfig.from_env()
    # When Kasm is enabled, Playwright drives remote Chrome via CDP — no local headful window.
    if kasm.enabled:
        headful = False
        guest = False

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
    popen_kwargs: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "creationflags": creationflags,
    }
    if sys.platform != "win32":
        # Own process group so Stop can terminate Playwright children cleanly.
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    log_file.close()

    status = {
        "running": True,
        "pid": proc.pid,
        "portals": portals,
        "headful": headful,
        "guest": guest,
        "kasm_enabled": kasm.enabled,
        "kasm_sessions": [],
        "found": 0,
        "saved": 0,
        "stopped": False,
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
    status["kasm_sessions"] = []
    status.pop("stopped", None)
    status.pop("stop_message", None)
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
