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


class GetRecentMessagesArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=30, description="عدد الرسائل الأخيرة المطلوب استرجاعها")
    source: str | None = Field(default=None, description="تصفية حسب المصدر مثل: sms أو notification أو call")
    app_package: str | None = Field(default=None, description="تصفية حسب تطبيق محدد مثل: com.whatsapp أو com.samsung.android.messaging")


class GetRecentMessagesTool(BaseTool):
    """استرجاع أحدث الرسائل والإشعارات الواردة مرتبة من الأحدث للأقدم."""

    name: str = "get_recent_messages"
    description: str = "استرجاع أحدث الرسائل والإشعارات الواردة مرتبة زمنياً، لمعرفة آخر رسالة SMS أو إشعار واتساب أو أي تنبيه وصل للجهاز"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = True
    args_model: type[BaseModel] = GetRecentMessagesArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, GetRecentMessagesArgs)
        async with async_session_factory() as session:
            stmt = select(Event).order_by(Event.occurred_at.desc())
            if args.source:
                stmt = stmt.where(Event.source == args.source)
            if args.app_package:
                stmt = stmt.where(Event.app_package == args.app_package)
            stmt = stmt.limit(args.limit)

            res = await session.execute(stmt)
            events = res.scalars().all()

            results = []
            for ev in events:
                content_safe = wrap_untrusted(
                    ev.content or "", source=ev.source or "event", ref=ev.id
                )
                results.append(
                    {
                        "event_id": ev.id,
                        "source": ev.source,
                        "app": ev.app_package,
                        "sender": ev.sender_name,
                        "title": ev.context_title,
                        "content": content_safe,
                        "occurred_at": ev.occurred_at,
                        "thread_key": ev.thread_key,
                        "reply_capable": bool(ev.reply_capable),
                    }
                )

            return {"count": len(results), "messages": results}


class ReadDocumentArgs(BaseModel):
    file_id: str = Field(..., description="معرف الملف المراد قراءته (e.g. file_123456)")
    max_chars: int = Field(default=6000, description="الحد الأقصى لعدد الأحرف المراد قراءتها")


class ReadDocumentTool(BaseTool):
    """قراءة محتوى ملف أو مستند تم رفعه من المستخدم لتحليله وتلخيصه."""

    name: str = "read_document"
    description: str = "قراءة محتوى ملف أو مستند نصي تم رفعه إلى السكرتير لتحليله والإجابة عن محتواه"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = True
    args_model: type[BaseModel] = ReadDocumentArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, ReadDocumentArgs)
        import os
        from app.db.models import File

        async with async_session_factory() as session:
            stmt = select(File).where(File.id == args.file_id)
            res = await session.execute(stmt)
            file_rec = res.scalar_one_or_none()
            if not file_rec or not os.path.exists(file_rec.path):
                return {"error": "الملف غير موجود على السيرفر"}

            try:
                with open(file_rec.path, "r", encoding="utf-8", errors="ignore") as f:
                    text_content = f.read(args.max_chars)
                safe_text = wrap_untrusted(text_content, source="file_upload", ref=file_rec.id)
                return {
                    "file_id": file_rec.id,
                    "filename": os.path.basename(file_rec.path),
                    "size_bytes": file_rec.size_bytes,
                    "mime": file_rec.mime,
                    "content": safe_text,
                }
            except Exception as e:
                return {"error": f"تعذر قراءة محتوى الملف: {e}"}
