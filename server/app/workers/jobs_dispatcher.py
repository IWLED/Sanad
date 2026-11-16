"""معالج المهام والتذكيرات المجدولة المستحقة (Scheduled Jobs Dispatcher) (Section 11.3)."""

import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.safety.logging_filter import logger
from app.core.ws.connection_manager import connection_manager
from app.db.base import async_session_factory
from app.db.models import Action, Device, Job, OutboundMessage


async def process_due_jobs() -> int:
    """فحص وتنفيذ المهام والتذكيرات التي حان وقت استحقاقها."""
    now_iso = datetime.now(UTC).isoformat()
    processed_count = 0

    async with async_session_factory() as session:
        # جلب المهام المستحقة
        stmt = (
            select(Job)
            .where(Job.run_at <= now_iso)
            .where(Job.status.in_(["scheduled", "approved"]))
        )
        res = await session.execute(stmt)
        due_jobs = res.scalars().all()

        for job in due_jobs:
            try:
                payload = json.loads(job.payload_json) if job.payload_json else {}

                if job.kind == "reminder":
                    title = payload.get("title", "تذكير")
                    device_id = payload.get("device_id")
                    logger.info("reminder_due", job_id=job.id, title=title)

                    # إدراج إشعار في outbound_messages
                    if device_id:
                        outbound = OutboundMessage(
                            device_id=device_id,
                            type="reminder_alert",
                            payload_json=json.dumps(
                                {
                                    "title": title,
                                    "notes": payload.get("notes"),
                                    "job_id": job.id,
                                    "due_time": job.run_at,
                                },
                                ensure_ascii=False,
                            ),
                            created_at=now_iso,
                        )
                        session.add(outbound)

                    job.status = "completed"
                    processed_count += 1

                elif job.kind == "scheduled_message":
                    # التحقق من حالة إجراء الاعتماد المرتبط
                    if job.action_id:
                        stmt_act = select(Action).where(Action.id == job.action_id)
                        res_act = await session.execute(stmt_act)
                        action = res_act.scalar_one_or_none()

                        if action and action.status == "APPROVED":
                            logger.info(
                                "scheduled_message_dispatching", job_id=job.id, action_id=action.id
                            )
                            # إرسال أمر التنفيذ للجهاز
                            exec_payload = {
                                "command": "reply",
                                "action_id": action.id,
                                "app_package": payload.get("app_package"),
                                "thread_key": payload.get("thread_key"),
                                "text": payload.get("draft_text"),
                            }
                            target_device_id = action.decided_by_device or str(
                                payload.get("device_id") or ""
                            )
                            if not target_device_id:
                                stmt_dev = (
                                    select(Device.id)
                                    .where(Device.revoked_at.is_(None))
                                    .limit(1)
                                )
                                res_dev = await session.execute(stmt_dev)
                                target_device_id = res_dev.scalar_one_or_none() or ""

                            if not target_device_id:
                                continue

                            outbound = OutboundMessage(
                                device_id=target_device_id,
                                type="exec_command",
                                payload_json=json.dumps(exec_payload, ensure_ascii=False),
                                created_at=now_iso,
                            )
                            session.add(outbound)
                            action.status = "EXECUTING"
                            job.status = "completed"
                            processed_count += 1
                        elif action and action.status in ["REJECTED", "EXPIRED", "CANCELLED"]:
                            job.status = "cancelled"
                            processed_count += 1
                        # إذا كان ما يزال PENDING_APPROVAL ولم يوافق عليه بعد، نتركه حتى يتغير وضعه

                elif job.kind == "todo":
                    job.status = "completed"
                    processed_count += 1

            except Exception as e:
                logger.error("due_job_processing_failed", job_id=job.id, error=str(e))

        if processed_count > 0:
            await session.commit()
            # إشعار المتصلين عبر WebSocket بوجود تحديث
            await connection_manager.broadcast_json(
                {"type": "due_jobs_processed", "count": processed_count}
            )

    return processed_count
