"""Main workflow orchestration."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from job_automation.browser.browser_manager import BrowserManager
from job_automation.browser.kasm_client import KasmConfig, KasmSessionBroker
from job_automation.browser.session_manager import SessionManager
from job_automation.config.loader import SearchConfig, load_rules
from job_automation.dashboard.search_service import update_search_kasm_sessions, update_search_progress
from job_automation.dedupe.deduplicate import DeduplicationEngine
from job_automation.etl.pipeline import transform_raw_job
from job_automation.logging_config import get_logger, log_event
from job_automation.models.domain import PortalRunStatus, RawJob
from job_automation.portals import get_worker_class
from job_automation.portals.base import LoginRequiredError
from job_automation.rules.rule_engine import RuleEngine
from job_automation.storage.database import init_db, session_scope
from job_automation.storage.models import JobRow
from job_automation.storage.repositories import BannedCompanyRepository, JobRepository, PortalRunRepository

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
        kasm_cfg = KasmConfig.from_env()
        if kasm_cfg.enabled:
            return await self._run_with_kasm(portals, kasm_cfg)
        return await self._run_local(portals)

    async def _run_local(self, portals: list[str]) -> dict[str, int]:
        summary = {"found": 0, "saved": 0, "failed": 0}

        log_event(logger, "Run started (local browser)", action="run_start")
        await self.browser_manager.start()
        try:
            existing_jobs = await self._load_existing_jobs()
            dedupe_engine = DeduplicationEngine(existing_jobs)
            rule_engine = RuleEngine(self.config)
            await self._run_portal_batch(portals, dedupe_engine, rule_engine, summary)
        finally:
            await self.browser_manager.stop()
            log_event(logger, "Run completed", action="run_complete")

        return summary

    async def _run_with_kasm(self, portals: list[str], kasm_cfg: KasmConfig) -> dict[str, int]:
        kasm_cfg.validate()
        summary = {"found": 0, "saved": 0, "failed": 0}
        broker = KasmSessionBroker(kasm_cfg)
        batch_size = kasm_cfg.max_sessions

        # At most 2 concurrent portal workers while Kasm sessions are live.
        self.config.portal_concurrency = min(self.config.portal_concurrency, batch_size)

        log_event(
            logger,
            f"Run started (Kasm {kasm_cfg.mode}, max_sessions={batch_size})",
            action="run_start",
        )

        existing_jobs = await self._load_existing_jobs()
        dedupe_engine = DeduplicationEngine(existing_jobs)
        rule_engine = RuleEngine(self.config)

        try:
            for offset in range(0, len(portals), batch_size):
                batch = portals[offset : offset + batch_size]
                sessions = broker.create_sessions(batch)
                update_search_kasm_sessions(broker.status_payload())

                cdp_map: dict[str, str] = {}
                for portal, session in sessions.items():
                    if not session.cdp_url:
                        raise RuntimeError(
                            f"Kasm session for {portal} has no CDP URL. "
                            "For offline mode set KASM_CDP_ENDPOINTS or KASM_CDP_BY_PORTAL. "
                            "Chrome must expose remote debugging "
                            "(e.g. --remote-debugging-port=9333 --remote-debugging-address=0.0.0.0)."
                        )
                    cdp_map[portal] = session.cdp_url

                self.browser_manager = BrowserManager(
                    self.config,
                    headful=False,
                    guest=False,
                    kasm_cdp_by_portal=cdp_map,
                )
                self.session_manager = SessionManager(self.browser_manager)

                await self.browser_manager.start()
                try:
                    await self._run_portal_batch(batch, dedupe_engine, rule_engine, summary)
                finally:
                    await self.browser_manager.stop()
                    broker.destroy_all()
                    update_search_kasm_sessions([])
        except Exception:
            broker.destroy_all()
            update_search_kasm_sessions([])
            raise
        finally:
            log_event(logger, "Run completed", action="run_complete")

        return summary

    async def _run_portal_batch(
        self,
        portals: list[str],
        dedupe_engine: DeduplicationEngine,
        rule_engine: RuleEngine,
        summary: dict[str, int],
    ) -> None:
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

    async def _load_banned_companies(self) -> set[str]:
        async with session_scope() as session:
            repo = BannedCompanyRepository(session)
            return await repo.list_normalized_names()

    async def _persist_raw_job(
        self,
        raw: RawJob,
        *,
        dedupe_engine: DeduplicationEngine,
        rule_engine: RuleEngine,
        stats: dict[str, int],
        portal: str,
    ) -> None:
        stats["found"] += 1
        try:
            normalized = transform_raw_job(raw, self.config)
            if raw.work_type and (
                not normalized.remote_policy or normalized.remote_policy in {"unclear", "remote_unclear"}
            ):
                lowered = raw.work_type.lower()
                if "fully_remote" in lowered or lowered.strip() in {"fully remote", "remote"}:
                    normalized.remote_policy = "fully_remote_us"
                elif "in-office or remote" in lowered or ("in-office" in lowered and "remote" in lowered):
                    normalized.remote_policy = "hybrid_possible_remote"
                elif "hybrid" in lowered:
                    normalized.remote_policy = "hybrid_required"
            if raw.work_type and not normalized.work_type:
                normalized.work_type = raw.work_type
            normalized = dedupe_engine.mark_duplicates(normalized)
            # Duplicate job-filter rule: do not save / continue processing duplicates.
            if normalized.is_duplicate:
                log_event(
                    logger,
                    f"Duplicate filter hit — skip save, move to next: {normalized.decision_reason}",
                    portal=portal,
                    job_id=raw.source_job_id or "-",
                    action="skip_duplicate",
                )
                update_search_progress(
                    found=stats["found"],
                    saved=stats["saved"],
                    last_job_title=normalized.title or raw.job_card_title,
                    last_decision="duplicate",
                )
                return
            if raw.forced_decision:
                normalized.decision = raw.forced_decision
                normalized.decision_reason = raw.forced_decision_reason
            else:
                normalized = rule_engine.decide(normalized)
            async with session_scope() as session:
                job_repo = JobRepository(session)
                row = await job_repo.upsert_job(normalized)
                dedupe_engine.existing_jobs.append(row)
            stats["saved"] += 1
            update_search_progress(
                found=stats["found"],
                saved=stats["saved"],
                last_job_title=normalized.title or raw.job_card_title,
                last_decision=normalized.decision.value if normalized.decision else None,
            )
            log_event(
                logger,
                f"Saved job with decision {normalized.decision}",
                portal=portal,
                job_id=raw.source_job_id or "-",
                action="save",
            )
        except Exception as exc:
            stats["failed"] += 1
            update_search_progress(found=stats["found"], saved=stats["saved"])
            log_event(
                logger,
                f"Processing failed: {exc}",
                portal=portal,
                job_id=raw.source_job_id or "-",
                action="process_error",
                level=40,
            )

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
                banned_companies = await self._load_banned_companies()
                processed_keys: set[str] = set()

                async def on_job_collected(raw: RawJob) -> None:
                    key = raw.portal_job_url or raw.source_job_id or ""
                    if key and key in processed_keys:
                        return
                    if key:
                        processed_keys.add(key)
                    await self._persist_raw_job(
                        raw,
                        dedupe_engine=dedupe_engine,
                        rule_engine=rule_engine,
                        stats=stats,
                        portal=portal,
                    )

                worker_kwargs = {
                    "early_duplicate_check": dedupe_engine.is_early_duplicate,
                    "on_job_collected": on_job_collected,
                }
                worker_cls = get_worker_class(portal)
                if portal == "builtin":
                    worker = worker_cls(
                        self.config,
                        self.browser_manager,
                        self.session_manager,
                        banned_companies=banned_companies,
                        **worker_kwargs,
                    )
                else:
                    worker = worker_cls(
                        self.config,
                        self.browser_manager,
                        self.session_manager,
                        **worker_kwargs,
                    )
                raw_jobs = await worker.run()

                # Fallback for any jobs not emitted live (should be rare).
                for raw in raw_jobs:
                    key = raw.portal_job_url or raw.source_job_id or ""
                    if key and key in processed_keys:
                        continue
                    if key:
                        processed_keys.add(key)
                    await self._persist_raw_job(
                        raw,
                        dedupe_engine=dedupe_engine,
                        rule_engine=rule_engine,
                        stats=stats,
                        portal=portal,
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
