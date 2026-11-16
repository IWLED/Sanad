"""أدوات جدولة التذكيرات والرسائل المؤجلة (Section 10.4 & Section 11.3)."""

import json
import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.hitl.engine import HITLEngine
from app.db.base import async_session_factory
from app.db.models import AppPolicy, Event, Job
from app.tools.base import BaseTool


class ScheduleReminderArgs(BaseModel):
    title: str = Field(..., description="عنوان التذكير أو المهمة")
    remind_at: str = Field(..., description="تاريخ ووقت التنبيه بصيغة ISO 8601")
    notes: str | None = Field(default=None, description="ملاحظات أو تفاصيل إضافية")


class ScheduleReminderTool(BaseTool):
    """أداة جدولة تذكير داخلي للمستخدم في وقت محدد (Tier 1, Server)."""

    name: str = "schedule_reminder"
    description: str = "جدولة تذكير أو تنبيه شخصي للمستخدم في وقت وتاريخ محدد"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = ScheduleReminderArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = ScheduleReminderArgs.model_validate(args.model_dump())
        device_id = ctx.get("device_id", "")
        session = ctx.get("session")

        async def _execute(s: Any) -> dict[str, Any]:
            job_id = f"job_rem_{secrets.token_hex(6)}"
            now_iso = datetime.now(UTC).isoformat()
            payload = {
                "title": params.title,
                "notes": params.notes,
                "device_id": device_id,
            }
            job = Job(
                id=job_id,
                kind="reminder",
                run_at=params.remind_at,
                payload_json=json.dumps(payload, ensure_ascii=False),
                status="scheduled",
                created_at=now_iso,
            )
            s.add(job)
            await s.flush()
            return {
                "job_id": job.id,
                "status": "scheduled",
                "title": params.title,
                "remind_at": params.remind_at,
            }

        if session:
            return await _execute(session)
        async with async_session_factory() as sess:
            res = await _execute(sess)
            await sess.commit()
            return res


class ScheduleMessageArgs(BaseModel):
    event_id: str = Field(..., description="معرف الحدث الأصلي للرد عليه (R-02)")
    draft_text: str = Field(..., description="صيغة الرد المراد جدولتها وتجميدها")
    run_at: str = Field(..., description="تاريخ ووقت الإرسال المجدول بصيغة ISO 8601")


class ScheduleMessageTool(BaseTool):
    """أداة جدولة رسالة رد مؤجلة تتطلب اعتماداً وتُجمَّد صيغتها (Tier 2, Device)."""

    name: str = "schedule_message"
    description: str = "جدولة إرسال رد على رسالة أو إشعار في وقت لاحق بعد موافقة المستخدم"
    risk_tier: int = 2
    executor: str = "device"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = ScheduleMessageArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = ScheduleMessageArgs.model_validate(args.model_dump())
        device_id = ctx.get("device_id", "")
        session = ctx.get("session")

        async def _execute(s: Any) -> dict[str, Any]:
            # 1. جلب الحدث والتحقق من R-02
            stmt = select(Event).where(Event.id == params.event_id)
            res = await s.execute(stmt)
            event = res.scalar_one_or_none()
            if not event:
                return {"error": f"Event {params.event_id} not found", "status": "REJECTED"}

            if event.app_package:
                stmt_p = select(AppPolicy).where(AppPolicy.package == event.app_package)
                res_p = await s.execute(stmt_p)
                policy = res_p.scalar_one_or_none()
                if policy and policy.allow_reply == 0:
                    return {
                        "error": f"Replies disabled for app {event.app_package}",
                        "status": "REJECTED",
                    }

            # 2. إنشاء بطاقة اعتماد عبر HITLEngine
            target_device = device_id or event.device_id or ""
            action_args = {
                "event_id": event.id,
                "draft_text": params.draft_text,
                "app_package": event.app_package,
                "thread_key": event.thread_key,
                "scheduled_run_at": params.run_at,
                "device_id": target_device,
            }
            action = await HITLEngine.create_action(
                session=s,
                device_id=target_device,
                tool=self,
                args_dict=action_args,
                origin_event_ids=[event.id],
                session_tainted=True,
                recipient_info={
                    "name": event.sender_name or "المستلم",
                    "app": event.app_package or event.source,
                },
            )

            # 3. تسجيل المهمة المجدولة المرتبطة بالـ Action
            job_id = f"job_msg_{secrets.token_hex(6)}"
            job = Job(
                id=job_id,
                kind="scheduled_message",
                run_at=params.run_at,
                payload_json=json.dumps(action_args, ensure_ascii=False),
                status="pending_approval",
                action_id=action.id,
                created_at=datetime.now(UTC).isoformat(),
            )
            s.add(job)
            await s.flush()

            return {
                "action_id": action.id,
                "job_id": job.id,
                "status": "PENDING_APPROVAL",
                "scheduled_at": params.run_at,
            }

        if session:
            return await _execute(session)
        async with async_session_factory() as sess:
            res = await _execute(sess)
            await sess.commit()
            return res


class TodoCreateArgs(BaseModel):
    title: str = Field(..., description="عنوان المهمة أو الإجراء")
    due_date: str | None = Field(default=None, description="تاريخ الاستحقاق إن وُجد")
    priority: Literal["low", "normal", "high"] = Field(
        default="normal", description="أولوية المهمة"
    )


class TodoCreateTool(BaseTool):
    """أداة حفظ مهمة في قائمة المهام الشخصية للمستخدم (Tier 1, Server)."""

    name: str = "todo_create"
    description: str = "إنشاء مهمة جديدة في قائمة مهام المستخدم اليومية"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = TodoCreateArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = TodoCreateArgs.model_validate(args.model_dump())
        device_id = ctx.get("device_id", "")
        session = ctx.get("session")

        async def _execute(s: Any) -> dict[str, Any]:
            job_id = f"todo_{secrets.token_hex(6)}"
            payload = {
                "title": params.title,
                "due_date": params.due_date,
                "priority": params.priority,
                "device_id": device_id,
            }
            job = Job(
                id=job_id,
                kind="todo",
                run_at=params.due_date or datetime.now(UTC).isoformat(),
                payload_json=json.dumps(payload, ensure_ascii=False),
                status="pending",
                created_at=datetime.now(UTC).isoformat(),
            )
            s.add(job)
            await s.flush()
            return {
                "todo_id": job.id,
                "title": params.title,
                "status": "created",
                "priority": params.priority,
            }

        if session:
            return await _execute(session)
        async with async_session_factory() as sess:
            res = await _execute(sess)
            await sess.commit()
            return res
