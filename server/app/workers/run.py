"""نقطة تشغيل عمال الخلفية والمهام المجدولة (Background Workers - Section 11.3)."""

import asyncio
import contextlib
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from app.config import settings
from app.core.audit import verify_audit_chain
from app.core.safety.logging_filter import configure_logging, logger
from app.db.base import async_session_factory


async def job_verify_audit_log() -> None:
    """التحقق الدوري من سلامة سلسلة التدقيق R-16."""
    async with async_session_factory() as session:
        is_valid, msg = await verify_audit_chain(session)
        if is_valid:
            logger.info("scheduled_audit_verification_ok", message=msg)
        else:
            logger.error("scheduled_audit_verification_tampered", message=msg)


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
