"""نقطة تشغيل عمال الخلفية والمهام المجدولة (Background Workers - Section 11.3)."""

import asyncio
import contextlib
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from app.config import settings
from app.core.audit import verify_audit_chain
from app.core.briefing.engine import generate_briefing
from app.core.safety.logging_filter import configure_logging, logger
from app.db.base import async_session_factory
from app.workers.jobs_dispatcher import process_due_jobs
from app.workers.retention import run_retention_cleanup


async def job_verify_audit_log() -> None:
    """التحقق الدوري من سلامة سلسلة التدقيق R-16."""
    async with async_session_factory() as session:
        is_valid, msg = await verify_audit_chain(session)
        if is_valid:
            logger.info("scheduled_audit_verification_ok", message=msg)
        else:
            logger.error("scheduled_audit_verification_tampered", message=msg)


async def job_morning_briefing() -> None:
    """توليد وتسليم الإيجاز الصباحي الساعة 07:30."""
    logger.info("scheduled_morning_briefing_started")
    await generate_briefing(kind="morning")


async def job_evening_briefing() -> None:
    """توليد وتسليم ملخص المساء الساعة 21:00."""
    logger.info("scheduled_evening_briefing_started")
    await generate_briefing(kind="on_demand")


async def main() -> None:
    """الحلقة المركزية لتشغيل الجدولة وإيقافها بنظافة."""
    configure_logging(settings.log_level)
    logger.info("sanad_worker_startup", env=settings.app_env, tz=settings.timezone)

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        job_verify_audit_log,
        "interval",
        hours=6,
        id="audit_verification",
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        run_retention_cleanup,
        "cron",
        hour=3,
        minute=30,
        id="daily_retention_cleanup",
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        job_morning_briefing,
        "cron",
        hour=7,
        minute=30,
        id="morning_briefing",
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        job_evening_briefing,
        "cron",
        hour=21,
        minute=0,
        id="evening_briefing",
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        process_due_jobs,
        "interval",
        seconds=30,
        id="dispatch_due_jobs",
        coalesce=True,
        misfire_grace_time=15,
    )
    scheduler.start()
    logger.info("sanad_worker_scheduler_started")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)
        logger.info("sanad_worker_shutdown")


if __name__ == "__main__":
    asyncio.run(main())
