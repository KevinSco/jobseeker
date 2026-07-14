"""Main workflow orchestration."""

from __future__ import annotations

import asyncio
from typing import Callable

from sqlalchemy import select

from job_automation.browser.browser_manager import BrowserManager
from job_automation.browser.session_manager import SessionManager
from job_automation.config.loader import SearchConfig, load_rules
from job_automation.dedupe.deduplicate import DeduplicationEngine
from job_automation.etl.pipeline import transform_raw_job
from job_automation.logging_config import get_logger, log_event
from job_automation.models.domain import PortalRunStatus
from job_automation.portals import get_worker_class
from job_automation.portals.base import BasePortalWorker, LoginRequiredError
from job_automation.rules.rule_engine import RuleEngine
from job_automation.storage.database import init_db, session_scope
from job_automation.storage.models import JobRow
from job_automation.storage.repositories import JobRepository, PortalRunRepository

logger = get_logger(__name__)


class Orchestrator:
    def __init__(
        self,
        config: SearchConfig | None = None,
        *,
        headful: bool | None = None,
        guest: bool = False,
    ):
        self.config = config or load_rules()
        self.headful = headful
        self.guest = guest
        self.browser_manager = BrowserManager(self.config, headful=headful, guest=guest)
        self.session_manager = SessionManager(self.browser_manager)

    async def run(self, portals: list[str] | None = None) -> dict[str, int]:
        await init_db()
        portals = portals or list(self.config.portals)
        summary = {"found": 0, "saved": 0, "failed": 0}

        log_event(logger, "Run started", action="run_start")
        await self.browser_manager.start()
        try:
            existing_jobs = await self._load_existing_jobs()
            dedupe_engine = DeduplicationEngine(existing_jobs)
            rule_engine = RuleEngine(self.config)

            tasks = [self._run_portal(portal, dedupe_engine, rule_engine) for portal in portals]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for portal, result in zip(portals, results):
                if isinstance(result, Exception):
                    log_event(logger, f"Portal failed: {result}", portal=portal, action="portal_error", level=40)
                    summary["failed"] += 1
                else:
                    summary["found"] += result["found"]
                    summary["saved"] += result["saved"]
                    summary["failed"] += result["failed"]
        finally:
            await self.browser_manager.stop()
            log_event(logger, "Run completed", action="run_complete")

        return summary

    async def retry_failed(self) -> dict[str, int]:
        await init_db()
        async with session_scope() as session:
            repo = PortalRunRepository(session)
            portals = await repo.failed_portals()
        if not portals:
            log_event(logger, "No failed portals to retry", action="retry_failed")
            return {"found": 0, "saved": 0, "failed": 0}
        return await self.run(portals)

    async def _load_existing_jobs(self) -> list[JobRow]:
        async with session_scope() as session:
            result = await session.execute(select(JobRow))
            return list(result.scalars().all())

    async def _run_portal(
        self,
        portal: str,
        dedupe_engine: DeduplicationEngine,
        rule_engine: RuleEngine,
    ) -> dict[str, int]:
        stats = {"found": 0, "saved": 0, "failed": 0}
        async with session_scope() as session:
            run_repo = PortalRunRepository(session)
            run = await run_repo.start_run(portal)

        try:
            async with self.browser_manager.portal_slot():
                worker_cls = get_worker_class(portal)
                worker = worker_cls(
                    self.config,
                    self.browser_manager,
                    self.session_manager,
                    early_duplicate_check=dedupe_engine.is_early_duplicate,
                )
                raw_jobs = await worker.run()
                stats["found"] = len(raw_jobs)

                for raw in raw_jobs:
                    try:
                        normalized = transform_raw_job(raw, self.config)
                        normalized = dedupe_engine.mark_duplicates(normalized)
                        if not normalized.is_duplicate:
                            normalized = rule_engine.decide(normalized)
                        async with session_scope() as session:
                            job_repo = JobRepository(session)
                            row = await job_repo.upsert_job(normalized)
                            dedupe_engine.existing_jobs.append(row)
                        stats["saved"] += 1
                        log_event(
                            logger,
                            f"Saved job with decision {normalized.decision}",
                            portal=portal,
                            job_id=raw.source_job_id or "-",
                            action="save",
                        )
                    except Exception as exc:
                        stats["failed"] += 1
                        log_event(
                            logger,
                            f"Processing failed: {exc}",
                            portal=portal,
                            job_id=raw.source_job_id or "-",
                            action="process_error",
                            level=40,
                        )

            async with session_scope() as session:
                run_repo = PortalRunRepository(session)
                await run_repo.finish_run(
                    run.id,
                    status=PortalRunStatus.SUCCESS,
                    jobs_found=stats["found"],
                    jobs_saved=stats["saved"],
                    jobs_failed=stats["failed"],
                )
        except LoginRequiredError as exc:
            async with session_scope() as session:
                run_repo = PortalRunRepository(session)
                await run_repo.finish_run(
                    run.id,
                    status=PortalRunStatus.NEEDS_MANUAL_LOGIN,
                    jobs_found=stats["found"],
                    jobs_saved=stats["saved"],
                    jobs_failed=stats["failed"],
                    error_message=str(exc),
                )
            raise
        except Exception as exc:
            async with session_scope() as session:
                run_repo = PortalRunRepository(session)
                await run_repo.finish_run(
                    run.id,
                    status=PortalRunStatus.FAILED,
                    jobs_found=stats["found"],
                    jobs_saved=stats["saved"],
                    jobs_failed=stats["failed"],
                    error_message=str(exc),
                )
            raise

        return stats
