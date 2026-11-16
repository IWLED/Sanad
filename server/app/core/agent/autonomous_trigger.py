"""محرك الاقتراح الذاتي للردود (Autonomous Proactive Reply Suggester).

(Section 9.2 & Section 10.3)
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.loop import AgentRunner
from app.core.safety.logging_filter import logger
from app.db.base import async_session_factory
from app.db.models import AppPolicy, Device, Event


async def evaluate_and_trigger_reply_suggestion(
    event_id: str,
    device_id: str | None = None,
    session: AsyncSession | None = None,
) -> bool:
    """تقييم الحدث الوارد وتوليد مسودة رد ذاتية واقتراحها على المستخدم إذا كان مؤهلاً."""

    async def _process(s: AsyncSession) -> bool:
        stmt = select(Event).where(Event.id == event_id)
        res = await s.execute(stmt)
        event = res.scalar_one_or_none()

        if not event:
            return False

        # 1. شروط الأهلية: يجب أن يدعم الرد، وألا يكون سراً أو OTP R-09
        if not event.reply_capable or event.sensitivity == "secret":
            return False

        if not event.content or len(event.content.strip()) < 2:
            return False

        # 2. فحص سياسة التطبيق
        if event.app_package:
            stmt_p = select(AppPolicy).where(AppPolicy.package == event.app_package)
            res_p = await s.execute(stmt_p)
            policy = res_p.scalar_one_or_none()
            if policy and policy.allow_reply == 0:
                logger.info("autonomous_trigger_skipped_app_policy", app=event.app_package)
                return False

        # 3. تحديد الجهاز المستهدف لاستلام بطاقة الاعتماد
        target_device_id = device_id or event.device_id
        if not target_device_id:
            stmt_dev = select(Device.id).where(Device.revoked_at.is_(None)).limit(1)
            res_dev = await s.execute(stmt_dev)
            target_device_id = res_dev.scalar_one_or_none()

        if not target_device_id:
            logger.warning("autonomous_trigger_no_target_device")
            return False

        # 4. تشغيل حلقة الوكيل لصياغة الرد واقتراحه عبر propose_reply
        runner = AgentRunner()
        try:
            logger.info("autonomous_trigger_started", event_id=event.id, app=event.app_package)
            await runner.run(
                device_id=target_device_id,
                user_message="اقتراح رد مناسب",
                session=s,
                trigger_event_id=event.id,
            )
            await s.commit()
            return True
        except Exception as e:
            logger.error("autonomous_trigger_failed", error=str(e), event_id=event.id)
            return False

    if session:
        return await _process(session)

    async with async_session_factory() as sess:
        return await _process(sess)
