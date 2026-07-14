"""Project path helpers."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
SESSIONS_DIR = PROJECT_ROOT / "sessions"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
DB_PATH = DATA_DIR / "jobs.sqlite"
RULES_PATH = CONFIG_DIR / "job_search_classify_rules.json"


def ensure_dirs() -> None:
    for path in (SESSIONS_DIR, DATA_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)
