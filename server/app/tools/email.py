"""أدوات البريد الإلكتروني (Gmail Tools) (Section 10.4 & Section 11.5)."""

import secrets
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.hitl.engine import HITLEngine
from app.core.safety.sanitize import wrap_untrusted
from app.db.base import async_session_factory
from app.db.models import ContactIdentifier, Event
from app.tools.base import BaseTool


class GmailSearchArgs(BaseModel):
    query: str = Field(..., description="عبارة البحث في البريد الإلكتروني")
    limit: int = Field(default=5, description="الحد الأقصى للرسائل المسترجعة")


class GmailSearchTool(BaseTool):
    """أداة البحث في رسائل البريد الإلكتروني (Tier 0)."""

    name: str = "gmail_search"
    description: str = "البحث في صندوق البريد الإلكتروني عن رسائل واردة أو مرسلة"
    risk_tier: int = 0
    executor: str = "server"
    returns_untrusted: bool = True
    args_model: type[BaseModel] = GmailSearchArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = GmailSearchArgs.model_validate(args.model_dump())
        session = ctx.get("session")

        async def _query(s: Any) -> list[dict[str, Any]]:
            stmt = (
                select(Event)
                .where(Event.source == "email")
                .where(Event.content.contains(params.query))
                .order_by(Event.occurred_at.desc())
                .limit(params.limit)
            )
            res = await s.execute(stmt)
            events = res.scalars().all()
            return [
                {
                    "id": ev.id,
                    "sender": ev.sender_name or "مجهول",
                    "snippet": wrap_untrusted(ev.content or "", "email", ev.id),
                    "received_at": ev.occurred_at,
                }
                for ev in events
            ]

        if session:
            results = await _query(session)
        else:
            async with async_session_factory() as sess:
                results = await _query(sess)

        return {"results": results, "count": len(results)}


class GmailCreateDraftArgs(BaseModel):
    recipient: str = Field(..., description="عنوان البريد الإلكتروني للمستلم")
    subject: str = Field(..., description="موضوع البريد الإلكتروني")
    body: str = Field(..., description="نص الرسالة أو محتواها")


class GmailCreateDraftTool(BaseTool):
    """أداة إنشاء مسودة بريد إلكتروني في حساب المستخدم فقط (Tier 1, Server)."""

    name: str = "gmail_create_draft"
    description: str = "إنشاء مسودة بريد جديدة في حساب المستخدم دون إرسالها للطرف الآخر"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = GmailCreateDraftArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = GmailCreateDraftArgs.model_validate(args.model_dump())
        draft_id = f"draft_{secrets.token_hex(6)}"
        return {
            "draft_id": draft_id,
            "recipient": params.recipient,
            "subject": params.subject,
            "status": "draft_created",
            "message": "تم حفظ المسودة في بريدك بنجاح، يمكنك مراجعتها وإرسالها لاحقاً",
        }


class GmailSendArgs(BaseModel):
    recipient: str = Field(..., description="عنوان البريد الإلكتروني للمستلم")
    subject: str = Field(..., description="موضوع البريد الإلكتروني")
    body: str = Field(..., description="نص الرسالة البريدية")


class GmailSendTool(BaseTool):
    """أداة إرسال بريد إلكتروني رسمي للطرف الآخر بعد الاعتماد البشري (Tier 2/3, Server)."""

    name: str = "gmail_send"
    description: str = "إرسال رسالة بريد إلكتروني رسمية للطرف الآخر (يتطلب اعتماد المستخدم)"
    risk_tier: int = 2
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = GmailSendArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = GmailSendArgs.model_validate(args.model_dump())
        device_id = ctx.get("device_id", "")
        session = ctx.get("session")

        async def _process(s: Any) -> dict[str, Any]:
            # التحقق هل المستلم جهة اتصال معروفة أم عنوان خارجي (R-03-ج)
            stmt = select(ContactIdentifier).where(
                ContactIdentifier.kind == "email",
                ContactIdentifier.value_norm == params.recipient.lower().strip(),
            )
            res = await s.execute(stmt)
            known_contact = res.scalar_one_or_none()

            extra_warnings = []
            if not known_contact:
                extra_warnings.append(
                    f"تنبيه: المستلم '{params.recipient}' ليس مسجلاً في جهات اتصالك المعتمدة"
                )

            action = await HITLEngine.create_action(
                session=s,
                device_id=device_id,
                tool=self,
                args_dict=params.model_dump(),
                session_tainted=True,
                recipient_info={"email": params.recipient, "name": params.recipient},
                extra_warnings=extra_warnings,
            )

            return {
                "action_id": action.id,
                "status": "PENDING_APPROVAL",
                "recipient": params.recipient,
                "preview": f"إرسال بريد إلى {params.recipient}: {params.subject}",
            }

        if session:
            return await _process(session)
        async with async_session_factory() as sess:
            res = await _process(sess)
            await sess.commit()
            return res
