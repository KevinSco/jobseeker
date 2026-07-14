"""Portal worker registry."""

from job_automation.portals.base import BasePortalWorker
from job_automation.portals.builtin import BuiltInWorker
from job_automation.portals.glassdoor import GlassdoorWorker
from job_automation.portals.hiringcafe import HiringCafeWorker
from job_automation.portals.jobright import JobrightWorker

WORKER_CLASSES: dict[str, type[BasePortalWorker]] = {
    "hiringcafe": HiringCafeWorker,
    "builtin": BuiltInWorker,
    "jobright": JobrightWorker,
    "glassdoor": GlassdoorWorker,
}


def get_worker_class(portal: str) -> type[BasePortalWorker]:
    if portal not in WORKER_CLASSES:
        raise ValueError(f"Unknown portal: {portal}")
    return WORKER_CLASSES[portal]
