"""أدوات البحث واسترجاع الأحداث من صندوق الوارد الموحد (Section 10.4 & T-2.6)."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.core.safety.sanitize import wrap_untrusted
from app.core.text.normalize_ar import normalize_ar
from app.db.base import async_session_factory
from app.db.models import Event
from app.tools.base import BaseTool


class SearchInboxArgs(BaseModel):
    query: str = Field(..., description="كلمات البحث في رسائل وإشعارات الوارد")
    limit: int = Field(default=5, ge=1, le=20, description="العدد الأقصى للنتائج")


class SearchInboxTool(BaseTool):
    """أداة البحث في صندوق الوارد الموحد عبر FTS5 مع تطبيع النص والتغليف الأمني."""

    name: str = "search_inbox"
    description: str = "البحث في الرسائل والإشعارات الواردة السابقة عبر الكلمات المفتاحية"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = True  # تلوّث الجلسة R-03 لأنها نصوص طرف ثالث
    args_model: type[BaseModel] = SearchInboxArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, SearchInboxArgs)
        norm_query = normalize_ar(args.query)
        if not norm_query:
            return {"count": 0, "results": []}

        fts_query = " ".join([f'"{token}"*' for token in norm_query.split()])

        async with async_session_factory() as session:
            sql = text(
                """
                SELECT e.id, e.source, e.app_package, e.sender_name, e.context_title,
                       e.content, e.occurred_at, e.thread_key
                FROM events_fts f
                JOIN events e ON e.rowid = f.rowid
                WHERE events_fts MATCH :q
                ORDER BY e.occurred_at DESC
                LIMIT :limit
                """
            )
            res = await session.execute(sql, {"q": fts_query, "limit": args.limit})
            rows = res.fetchall()

            results = []
            for r in rows:
                content_safe = wrap_untrusted(r.content or "", source=r.source or "inbox", ref=r.id)
                results.append(
                    {
                        "event_id": r.id,
                        "source": r.source,
                        "app": r.app_package,
                        "sender": r.sender_name,
                        "title": r.context_title,
                        "content": content_safe,
                        "occurred_at": r.occurred_at,
                        "thread_key": r.thread_key,
                    }
                )

            return {"count": len(results), "results": results}


class GetThreadArgs(BaseModel):
    thread_key: str = Field(..., description="مفتاح السلسلة (thread_key)")
    limit: int = Field(default=10, ge=1, le=30, description="أقصى عدد رسائل")


class GetThreadTool(BaseTool):
    """استرجاع سياق محادثة كاملة مرتبة زمنياً."""

    name: str = "get_thread"
    description: str = "استرجاع سجل الرسائل لسلسلة محادثة معينة"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = True
    args_model: type[BaseModel] = GetThreadArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, GetThreadArgs)
        async with async_session_factory() as session:
            stmt = (
                select(Event)
                .where(Event.thread_key == args.thread_key)
                .order_by(Event.occurred_at.asc())
                .limit(args.limit)
            )
            res = await session.execute(stmt)
            events = res.scalars().all()

            results = []
            for ev in events:
                content_safe = wrap_untrusted(
                    ev.content or "", source=ev.source or "thread", ref=ev.id
                )
                results.append(
                    {
                        "event_id": ev.id,
                        "sender": ev.sender_name,
                        "content": content_safe,
                        "occurred_at": ev.occurred_at,
                    }
                )

            return {"thread_key": args.thread_key, "count": len(results), "messages": results}


class GetEventArgs(BaseModel):
    event_id: str = Field(..., description="معرّف الحدث")


class GetEventTool(BaseTool):
    """استرجاع تفاصيل حدث معين بالمعرّف."""

    name: str = "get_event"
    description: str = "استرجاع تفاصيل حدث أو رسالة معينة عبر معرفها"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = True
    args_model: type[BaseModel] = GetEventArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, GetEventArgs)
        async with async_session_factory() as session:
            stmt = select(Event).where(Event.id == args.event_id)
            res = await session.execute(stmt)
            ev = res.scalar_one_or_none()
            if not ev:
                return {"found": False}

            return {
                "found": True,
                "event_id": ev.id,
                "source": ev.source,
                "app": ev.app_package,
                "sender": ev.sender_name,
                "content": wrap_untrusted(ev.content or "", source=ev.source or "event", ref=ev.id),
                "occurred_at": ev.occurred_at,
                "thread_key": ev.thread_key,
                "reply_capable": bool(ev.reply_capable),
            }
