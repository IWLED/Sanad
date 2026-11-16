"""أدوات إدارة التقويم والمواعيد (Calendar Tools) (Section 10.4 & Section 11.5)."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.hitl.engine import HITLEngine
from app.core.safety.sanitize import wrap_untrusted
from app.db.base import async_session_factory
from app.db.models import Event
from app.tools.base import BaseTool


class CalendarListArgs(BaseModel):
    days_ahead: int = Field(default=7, description="عدد الأيام القادمة للاستعلام عن المواعيد")


class CalendarListTool(BaseTool):
    """أداة استعراض الأحداث والمواعيد القادمة في التقويم (Tier 0)."""

    name: str = "calendar_list"
    description: str = "عرض قائمة المواعيد والاجتماعات المجدولة في التقويم للأيام القادمة"
    risk_tier: int = 0
    executor: str = "server"
    returns_untrusted: bool = True
    args_model: type[BaseModel] = CalendarListArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = CalendarListArgs.model_validate(args.model_dump())
        session = ctx.get("session")

        now = datetime.now(UTC)
        cutoff = (now + timedelta(days=params.days_ahead)).isoformat()
        now_iso = now.isoformat()

        async def _query(s: Any) -> list[dict[str, Any]]:
            stmt = (
                select(Event)
                .where(Event.source == "calendar")
                .where(Event.occurred_at >= now_iso)
                .where(Event.occurred_at <= cutoff)
                .order_by(Event.occurred_at.asc())
            )
            res = await s.execute(stmt)
            events = res.scalars().all()
            return [
                {
                    "id": ev.id,
                    "title": wrap_untrusted(ev.content or "موعد بدون عنوان", "calendar", ev.id),
                    "start_time": ev.occurred_at,
                    "sender": ev.sender_name,
                }
                for ev in events
            ]

        if session:
            events_list = await _query(session)
        else:
            async with async_session_factory() as sess:
                events_list = await _query(sess)

        return {"events": events_list, "count": len(events_list)}


class CalendarCreateArgs(BaseModel):
    title: str = Field(..., description="عنوان الموعد أو الاجتماع")
    start_time: str = Field(..., description="تاريخ ووقت البدء بصيغة ISO 8601")
    end_time: str = Field(..., description="تاريخ ووقت الانتهاء بصيغة ISO 8601")
    description: str | None = Field(default=None, description="تفاصيل إضافية أو رابط الاجتماع")
    attendees: list[str] = Field(default_factory=list, description="قائمة المدعوين (إيميلاتهم)")


class CalendarCreateTool(BaseTool):
    """أداة إنشاء موعد جديد في التقويم (Tier 1 إذا بلا مدعوين، Tier 3 إذا بمدعوين).

    (Section 10.4)
    """

    name: str = "calendar_create"
    description: str = "إضافة موعد أو اجتماع جديد في التقويم (يتطلب اعتماداً بالبصمة إذا وُجد مدعوون)"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = CalendarCreateArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = CalendarCreateArgs.model_validate(args.model_dump())
        device_id = ctx.get("device_id", "")
        session = ctx.get("session")

        # إذا وُجد مدعوون، يُعد إجراءً عالي الخطورة Tier 3 ويتطلب اعتماداً بشرياً صريحاً
        if params.attendees and len(params.attendees) > 0:

            async def _create_hitl(s: Any) -> dict[str, Any]:
                action = await HITLEngine.create_action(
                    session=s,
                    device_id=device_id,
                    tool=self,
                    args_dict=params.model_dump(),
                    session_tainted=True,
                    recipient_info={"attendees": params.attendees},
                    extra_warnings=[f"إرسال دعوات خارجية إلى {len(params.attendees)} مدعو"],
                )
                return {
                    "action_id": action.id,
                    "status": "PENDING_APPROVAL",
                    "requires_biometric": True,
                    "preview": f"إنشاء موعد '{params.title}' ودعوة {len(params.attendees)} مدعو",
                }

            if session:
                return await _create_hitl(session)
            async with async_session_factory() as sess:
                res = await _create_hitl(sess)
                await sess.commit()
                return res

        # بلا مدعوين: يُنشأ الموعد مباشرة (Tier 1)
        async def _create_direct(s: Any) -> dict[str, Any]:
            event_id = f"cal_{secrets.token_hex(6)}"
            now_iso = datetime.now(UTC).isoformat()
            event = Event(
                id=event_id,
                device_id=device_id,
                source="calendar",
                external_id=f"ext_{secrets.token_hex(6)}",
                thread_key=f"calendar:{event_id}",
                sender_name="المستخدم",
                content=params.title,
                reply_capable=0,
                occurred_at=params.start_time,
                received_at=now_iso,
            )
            s.add(event)
            await s.flush()
            return {
                "event_id": event.id,
                "title": params.title,
                "start_time": params.start_time,
                "end_time": params.end_time,
                "status": "created",
            }

        if session:
            return await _create_direct(session)
        async with async_session_factory() as sess:
            res = await _create_direct(sess)
            await sess.commit()
            return res
