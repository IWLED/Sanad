"""أداة اقتراح الرد على الرسائل والإشعارات (Section 10.4 & R-01..R-06)."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.hitl.engine import hitl_engine
from app.db.base import async_session_factory
from app.db.models import AppPolicy, Event
from app.tools.base import BaseTool


class ProposeReplyArgs(BaseModel):
    event_id: str = Field(..., description="معرف الحدث أو الرسالة المراد الرد عليها")
    draft_text: str = Field(..., description="نص مسودة الرد المقترح إرساله للمستقبل")


class ProposeReplyTool(BaseTool):
    """أداة اقتراح الرد على إشعار أو رسالة مع فرض التحقق البشري الصارم HITL (R-01, R-02)."""

    name: str = "propose_reply"
    description: str = "اقتراح مسودة رد على رسالة أو إشعار وارد ورفعها للمستخدم للاعتماد البشري"
    risk_tier: int = 2
    executor: str = "device"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = ProposeReplyArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, ProposeReplyArgs)
        device_id = ctx.get("device_id", "")

        async with async_session_factory() as session:
            # 1. استخراج الحدث الأصلي R-02 (Derived Destination)
            stmt = select(Event).where(Event.id == args.event_id)
            res = await session.execute(stmt)
            event = res.scalar_one_or_none()

            if not event:
                return {
                    "error": f"Event {args.event_id} not found",
                    "status": "REJECTED",
                }

            # 2. التحقق من سياسة التطبيق إن وُجدت
            if event.app_package:
                stmt_policy = select(AppPolicy).where(AppPolicy.package == event.app_package)
                res_policy = await session.execute(stmt_policy)
                policy = res_policy.scalar_one_or_none()
                if policy and policy.allow_reply == 0:
                    return {
                        "error": f"Replies are disabled for app {event.app_package}",
                        "status": "REJECTED",
                    }

            # 3. جلب سياق المحادثة للخيط
            stmt_thread = (
                select(Event)
                .where(Event.thread_key == event.thread_key)
                .order_by(Event.occurred_at.desc())
                .limit(5)
            )
            res_thread = await session.execute(stmt_thread)
            thread_events = list(reversed(res_thread.scalars().all()))

            thread_context = [
                {
                    "who": ev.sender_name or "Unknown",
                    "text": ev.content or "",
                    "ts": ev.occurred_at,
                }
                for ev in thread_events
            ]

            # 4. تسجيل الإجراء في محرك HITL وبناء المعاينة وإرسال بطاقة الاعتماد R-01..R-06
            action_args = {
                "event_id": event.id,
                "thread_key": event.thread_key,
                "app_package": event.app_package,
                "text": args.draft_text,
            }

            action = await hitl_engine.create_action(
                session=session,
                device_id=device_id,
                tool=self,
                args_dict=action_args,
                origin_event_ids=[event.id],
                session_tainted=True,
                recipient_info={"name": event.sender_name or "", "phone": None},
                thread_context=thread_context,
            )
            await session.commit()

            return {
                "action_id": action.id,
                "status": "PENDING_APPROVAL",
                "message": "جهّزت لك المسودة بانتظار اعتمادك",
            }
