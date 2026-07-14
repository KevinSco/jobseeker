"""Scheduler helpers for local automation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from job_automation.paths import PROJECT_ROOT


def build_daily_command() -> list[str]:
    return [sys.executable, "-m", "job_automation.main", "run"]


def print_windows_task_scheduler_instructions() -> str:
    command = " ".join(build_daily_command())
    script = PROJECT_ROOT / "scripts" / "run_daily.bat"
    return f"""
Windows Task Scheduler setup:
1. Open Task Scheduler -> Create Basic Task
2. Trigger: Daily (e.g. 8:00 AM)
3. Action: Start a program
4. Program/script: {script}
5. Start in: {PROJECT_ROOT}

Manual equivalent:
  cd {PROJECT_ROOT}
  {command}
"""


def run_daily_subprocess() -> subprocess.CompletedProcess[str]:
    return subprocess.run(build_daily_command(), cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
