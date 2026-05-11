"""
Close Command Scheduler.
Manages scheduled pipeline runs using APScheduler.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _current_period() -> str:
    """Return current period in YYYY-MM format."""
    return datetime.utcnow().strftime("%Y-%m")


class CloseCommandScheduler:
    """
    Manages scheduled and manual pipeline runs using APScheduler.

    Args:
        graph_runner: Callable — the run_close_pipeline function.
                      If None, imports lazily on first use.
    """

    def __init__(self, graph_runner: Optional[Callable] = None) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler(
                timezone="UTC",
                job_defaults={"coalesce": True, "max_instances": 1},
            )
        except ImportError as exc:
            logger.warning("APScheduler not installed — scheduler will be non-functional: %s", exc)
            self._scheduler = None

        self._graph_runner = graph_runner
        self._last_run: Optional[datetime] = None
        self._last_run_status: str = "NEVER_RUN"
        self._run_history: list[dict] = []

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler."""
        try:
            if self._scheduler is None:
                logger.error("Scheduler not initialised — APScheduler may not be installed")
                return
            if not self._scheduler.running:
                self._scheduler.start()
                logger.info("CloseCommandScheduler started")
            else:
                logger.info("CloseCommandScheduler already running")
        except Exception as exc:
            logger.error("Failed to start scheduler: %s", exc)

    def stop(self) -> None:
        """Shut down the background scheduler."""
        try:
            if self._scheduler and self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                logger.info("CloseCommandScheduler stopped")
        except Exception as exc:
            logger.error("Failed to stop scheduler: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Scheduled jobs
    # ──────────────────────────────────────────────────────────────────────

    def add_daily_run(
        self,
        hour: int = 6,
        minute: int = 0,
        period_fn: Optional[Callable[[], str]] = None,
    ) -> None:
        """
        Add a daily matching run at a configurable time.

        Args:
            hour:      Hour of day (UTC, 0-23)
            minute:    Minute (0-59)
            period_fn: Callable that returns current period string (YYYY-MM).
                       Defaults to returning the current month.
        """
        try:
            if self._scheduler is None:
                logger.error("Scheduler not initialised")
                return

            from apscheduler.triggers.cron import CronTrigger

            _period_fn = period_fn or _current_period

            def _daily_job():
                period = _period_fn() if callable(_period_fn) else _current_period()
                batch_id = f"DAILY-{period}-{str(uuid.uuid4())[:8]}"
                logger.info("Daily scheduled run starting: batch_id=%s period=%s", batch_id, period)
                self._run_pipeline(batch_id=batch_id, period=period, scenario="ACTUAL", job_type="DAILY")

            self._scheduler.add_job(
                _daily_job,
                trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
                id="daily_matching_run",
                name=f"Daily IC Matching Run ({hour:02d}:{minute:02d} UTC)",
                replace_existing=True,
            )
            logger.info("Daily run scheduled at %02d:%02d UTC", hour, minute)

        except Exception as exc:
            logger.error("add_daily_run failed: %s", exc)

    def add_exception_recheck(self, interval_hours: int = 4) -> None:
        """
        Add a recurring exception re-check every N hours during close window.

        Args:
            interval_hours: Interval between re-checks (default 4 hours)
        """
        try:
            if self._scheduler is None:
                logger.error("Scheduler not initialised")
                return

            from apscheduler.triggers.interval import IntervalTrigger

            def _recheck_job():
                period = _current_period()
                batch_id = f"RECHECK-{period}-{str(uuid.uuid4())[:8]}"
                logger.info("Exception recheck starting: batch_id=%s", batch_id)
                self._run_pipeline(batch_id=batch_id, period=period, scenario="ACTUAL", job_type="EXCEPTION_RECHECK")

            self._scheduler.add_job(
                _recheck_job,
                trigger=IntervalTrigger(hours=interval_hours),
                id="exception_recheck",
                name=f"Exception Re-check (every {interval_hours}h)",
                replace_existing=True,
            )
            logger.info("Exception recheck scheduled every %dh", interval_hours)

        except Exception as exc:
            logger.error("add_exception_recheck failed: %s", exc)

    def add_continuation_control_check(self, interval_hours: int = 24) -> None:
        """
        Add a daily continuation control re-check.

        Args:
            interval_hours: Interval between checks (default 24 hours)
        """
        try:
            if self._scheduler is None:
                logger.error("Scheduler not initialised")
                return

            from apscheduler.triggers.interval import IntervalTrigger

            def _continuation_job():
                period = _current_period()
                logger.info("Continuation control check starting for period=%s", period)
                try:
                    from close_command.database.persistence import CloseCommandDB
                    from close_command.rag.vectorstore import CloseCommandVectorStore
                    from close_command.rag.retriever import CloseCommandRetriever
                    from close_command.agents.validation_agent import ValidationAgent

                    db = CloseCommandDB("close_command.db")
                    vs = CloseCommandVectorStore()
                    retriever = CloseCommandRetriever(vs)
                    va = ValidationAgent(db=db, retriever=retriever)

                    batch_id = f"CONTCHECK-{period}-{str(uuid.uuid4())[:8]}"
                    cont_result = va.run_continuation_control(batch_id=batch_id, period=period)

                    if not cont_result.passed:
                        logger.warning(
                            "Continuation control FAILED for period=%s: %s",
                            period, cont_result.issues,
                        )
                    else:
                        logger.info("Continuation control PASSED for period=%s", period)

                    self._record_run(batch_id, period, "ACTUAL", "CONTINUATION_CHECK",
                                     "PASSED" if cont_result.passed else "FAILED")

                except Exception as inner_exc:
                    logger.error("Continuation control job failed: %s", inner_exc)

            self._scheduler.add_job(
                _continuation_job,
                trigger=IntervalTrigger(hours=interval_hours),
                id="continuation_control_check",
                name=f"Continuation Control Check (every {interval_hours}h)",
                replace_existing=True,
            )
            logger.info("Continuation control check scheduled every %dh", interval_hours)

        except Exception as exc:
            logger.error("add_continuation_control_check failed: %s", exc)

    def add_escalation_reminder(self, interval_hours: int = 2) -> None:
        """
        Log and notify about pending escalations every N hours.

        Args:
            interval_hours: Interval between reminders (default 2 hours)
        """
        try:
            if self._scheduler is None:
                logger.error("Scheduler not initialised")
                return

            from apscheduler.triggers.interval import IntervalTrigger

            def _escalation_reminder_job():
                try:
                    from close_command.database.persistence import CloseCommandDB
                    db = CloseCommandDB("close_command.db")

                    with db._connect() as conn:
                        unresolved = conn.execute(
                            "SELECT COUNT(*) as cnt FROM escalations WHERE resolved = 0"
                        ).fetchone()
                        count = dict(unresolved).get("cnt", 0) if unresolved else 0

                    if count > 0:
                        logger.warning(
                            "ESCALATION REMINDER: %d unresolved escalation(s) require attention. "
                            "Check the Close Command dashboard.",
                            count,
                        )
                    else:
                        logger.info("Escalation reminder: no pending escalations")

                except Exception as inner_exc:
                    logger.error("Escalation reminder job failed: %s", inner_exc)

            self._scheduler.add_job(
                _escalation_reminder_job,
                trigger=IntervalTrigger(hours=interval_hours),
                id="escalation_reminder",
                name=f"Escalation Reminder (every {interval_hours}h)",
                replace_existing=True,
            )
            logger.info("Escalation reminder scheduled every %dh", interval_hours)

        except Exception as exc:
            logger.error("add_escalation_reminder failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Manual trigger
    # ──────────────────────────────────────────────────────────────────────

    def trigger_manual_run(
        self,
        period: str,
        scenario: str,
        raw_data=None,
        source_file: str = "",
    ) -> str:
        """
        Immediately trigger a pipeline run.

        Returns:
            batch_id of the triggered run.
        """
        try:
            batch_id = f"MANUAL-{period}-{str(uuid.uuid4())[:8]}"
            logger.info(
                "Manual run triggered: batch_id=%s period=%s scenario=%s",
                batch_id, period, scenario,
            )
            self._run_pipeline(
                batch_id=batch_id,
                period=period,
                scenario=scenario,
                job_type="MANUAL",
                raw_data=raw_data,
                source_file=source_file,
            )
            return batch_id

        except Exception as exc:
            logger.error("trigger_manual_run failed: %s", exc)
            error_batch_id = f"MANUAL-ERROR-{str(uuid.uuid4())[:8]}"
            return error_batch_id

    # ──────────────────────────────────────────────────────────────────────
    # Status / info
    # ──────────────────────────────────────────────────────────────────────

    def get_scheduled_jobs(self) -> list[dict]:
        """Return list of scheduled job info dicts."""
        try:
            if self._scheduler is None:
                return []

            jobs = []
            for job in self._scheduler.get_jobs():
                next_run = None
                try:
                    next_run = job.next_run_time.isoformat() if job.next_run_time else None
                except Exception:
                    pass

                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": next_run,
                    "trigger": str(job.trigger),
                })
            return jobs

        except Exception as exc:
            logger.warning("get_scheduled_jobs failed: %s", exc)
            return []

    def get_last_run_info(self) -> dict:
        """Return info about the last pipeline run."""
        try:
            next_run = None
            if self._scheduler and self._scheduler.running:
                jobs = self._scheduler.get_jobs()
                daily_job = next((j for j in jobs if j.id == "daily_matching_run"), None)
                if daily_job and daily_job.next_run_time:
                    next_run = daily_job.next_run_time.isoformat()

            return {
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "next_run": next_run,
                "status": self._last_run_status,
                "run_count": len(self._run_history),
                "recent_runs": self._run_history[-5:] if self._run_history else [],
            }

        except Exception as exc:
            logger.warning("get_last_run_info failed: %s", exc)
            return {"last_run": None, "next_run": None, "status": "UNKNOWN"}

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _run_pipeline(
        self,
        batch_id: str,
        period: str,
        scenario: str,
        job_type: str = "SCHEDULED",
        raw_data=None,
        source_file: str = "",
    ) -> None:
        """Execute the pipeline and update internal run tracking."""
        started_at = datetime.utcnow()
        try:
            runner = self._graph_runner
            if runner is None:
                from close_command.orchestrator.graph import run_close_pipeline
                runner = run_close_pipeline

            result = runner(
                batch_id=batch_id,
                period=period,
                scenario=scenario,
                raw_data=raw_data,
                source_file=source_file,
            )

            status = result.get("overall_status", "UNKNOWN")
            self._last_run = datetime.utcnow()
            self._last_run_status = status

            run_record = {
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "job_type": job_type,
                "status": status,
                "started_at": started_at.isoformat(),
                "completed_at": self._last_run.isoformat(),
            }
            self._run_history.append(run_record)

            # Keep only last 100 run records
            if len(self._run_history) > 100:
                self._run_history = self._run_history[-100:]

            logger.info(
                "Pipeline run complete: batch_id=%s status=%s",
                batch_id, status,
            )

        except Exception as exc:
            self._last_run = datetime.utcnow()
            self._last_run_status = "ERROR"
            logger.error("Pipeline run failed batch_id=%s: %s", batch_id, exc)
            self._run_history.append({
                "batch_id": batch_id,
                "period": period,
                "scenario": scenario,
                "job_type": job_type,
                "status": "ERROR",
                "error": str(exc),
                "started_at": started_at.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            })

    def _record_run(
        self,
        batch_id: str,
        period: str,
        scenario: str,
        job_type: str,
        status: str,
    ) -> None:
        """Record a non-full-pipeline run result."""
        self._last_run = datetime.utcnow()
        self._last_run_status = status
        self._run_history.append({
            "batch_id": batch_id,
            "period": period,
            "scenario": scenario,
            "job_type": job_type,
            "status": status,
            "completed_at": self._last_run.isoformat(),
        })
