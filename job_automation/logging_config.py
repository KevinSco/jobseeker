"""Structured logging for automation runs."""

import logging
from pathlib import Path

from job_automation.paths import LOGS_DIR, ensure_dirs


class PortalFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "portal"):
            record.portal = "-"
        if not hasattr(record, "job_id"):
            record.job_id = "-"
        if not hasattr(record, "action"):
            record.action = "-"
        return True


def setup_logging(level: int = logging.INFO) -> None:
    ensure_dirs()
    log_file = LOGS_DIR / "automation.log"
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(portal)s | %(job_id)s | %(action)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(PortalFilter())

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(PortalFilter())

    root.addHandler(console)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    message: str,
    *,
    level: int = logging.INFO,
    portal: str = "-",
    job_id: str = "-",
    action: str = "-",
) -> None:
    logger.log(level, message, extra={"portal": portal, "job_id": job_id, "action": action})
