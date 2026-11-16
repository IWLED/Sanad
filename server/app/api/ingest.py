"""نقطة استقبال واستيعاب أحداث الإشعارات والرسائل والمكالمات (/v1/ingest/events)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_device_id
from app.core.audit import append_audit_log
from app.core.safety.logging_filter import logger
from app.core.safety.redactor import classify_and_redact
from app.core.text.normalize_ar import normalize_ar
from app.db.base import get_db_session
from app.db.models import AppPolicy, Event

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


class IngestEventItem(BaseModel):
    """عنصر حدث فردي وارد من الجوال أو المصادر الخارجية."""

    source: str = Field(
        ...,
        description="missed_call | call | sms | notification | email | calendar",
    )
    external_id: str = Field(..., description="معرّف خارجي فريد على الجهاز لمنع التكرار")
    thread_key: str = Field(..., description="مفتاح سلسلة المحادثة (e.g. pkg:threadId)")
    app_package: str | None = Field(default=None, description="اسم حزمة التطبيق")
    sender_name: str | None = Field(default=None, description="اسم أو رقم المرسل")
    is_group: bool = Field(default=False, description="هل الحدث من مجموعة أو قناة")
    context_title: str | None = Field(default=None, description="اسم المجموعة أو الموضوع")
    content: str | None = Field(default=None, description="نص الرسالة أو محتوى الإشعار")
    sensitivity: str = Field(default="normal", description="normal | sensitive | secret")
    media_hint: str | None = Field(default=None, description="نوع المرفق إن وجد")
    reply_capable: bool = Field(default=False, description="هل يدعم الرد عبر RemoteInput")
    reply_expires_hint: str | None = Field(default=None, description="تاريخ انتهاء صلاحية الرد")
    occurred_at: str = Field(default="", description="الختم الزمني لحدوث الحدث")


class IngestEventResultItem(BaseModel):
    """نتيجة معالجة الحدث الفردي."""

    external_id: str
    status: str  # "created" | "duplicate" | "rejected"
    event_id: str | None = None
    reason: str | None = None


class IngestEventsResponse(BaseModel):
    """استجابة دفعة الأحداث."""

    results: list[IngestEventResultItem]
    created_count: int
    duplicate_count: int


@router.post(
    "/events",
    response_model=IngestEventsResponse,
    status_code=status.HTTP_200_OK,
    summary="استقبال دفعة أحداث من الجوال وتطهيرها وتخزينها بفهرس FTS5 (Section 8.2)",
)
async def ingest_events(
    events: list[IngestEventItem],
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> IngestEventsResponse:
    """استقبال مجمّع للأحداث مع كشف التكرار (Idempotency) وحجب الأسرار R-09 وفهرسة FTS5."""
    now_iso = datetime.now(UTC).isoformat()
    results: list[IngestEventResultItem] = []
    created_count = 0
    duplicate_count = 0

    for item in events:
        # 1. فحص منع التكرار (Idempotency) بـ (source, external_id)
        stmt_dup = select(Event).where(
            Event.source == item.source,
            Event.external_id == item.external_id,
        )
        res_dup = await session.execute(stmt_dup)
        existing_event = res_dup.scalar_one_or_none()

        if existing_event:
            duplicate_count += 1
            results.append(
                IngestEventResultItem(
                    external_id=item.external_id,
                    status="duplicate",
                    event_id=existing_event.id,
                )
            )
            continue

        # 2. فحص سياسة التطبيقات المراقبة (App Policies)
        reply_capable = 1 if item.reply_capable else 0
        sensitivity_floor = "normal"
        if item.app_package:
            stmt_policy = select(AppPolicy).where(AppPolicy.package == item.app_package)
            res_policy = await session.execute(stmt_policy)
            policy = res_policy.scalar_one_or_none()
            if policy:
                if policy.monitor == 0:
                    results.append(
                        IngestEventResultItem(
                            external_id=item.external_id,
                            status="rejected",
                            reason="app_package_blocked_by_policy",
                        )
                    )
                    continue
                if policy.allow_reply == 0:
                    reply_capable = 0
                sensitivity_floor = policy.sensitivity_floor

        # 3. فحص الحساسية والحجب (Redactor & R-09)
        raw_text = item.content or ""
        redaction = classify_and_redact(raw_text)

        # القاعدة R-09: الأسرار الصريحة والـ OTP لا تُخزن في قاعدة البيانات إطلاقاً
        stored_content = None if not redaction.should_store_content else redaction.redacted_text

        final_sensitivity = redaction.classification
        if sensitivity_floor == "sensitive" and final_sensitivity == "normal":
            final_sensitivity = "sensitive"

        # 4. التطبيع العربي للفهرسة والبحث (normalize_ar)
        content_norm = normalize_ar(stored_content or "")
        sender_norm = normalize_ar(item.sender_name or "")
        title_norm = normalize_ar(item.context_title or "")

        # 5. حفظ الحدث في جدول events
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        occurred_time = item.occurred_at if item.occurred_at else now_iso

        new_event = Event(
            id=event_id,
            device_id=device_id,
            source=item.source,
            app_package=item.app_package,
            external_id=item.external_id,
            thread_key=item.thread_key,
            sender_name=item.sender_name,
            is_group=1 if item.is_group else 0,
            context_title=item.context_title,
            content=stored_content,
            content_norm=content_norm,
            sensitivity=final_sensitivity,
            media_hint=item.media_hint,
            reply_capable=reply_capable,
            reply_expires_hint=item.reply_expires_hint,
            occurred_at=occurred_time,
            received_at=now_iso,
        )
        session.add(new_event)
        await session.flush()

        # 6. إضافة الفهرسة إلى جدول البحث النصي FTS5
        res_rowid = await session.execute(
            text("SELECT rowid FROM events WHERE id = :id"),
            {"id": event_id},
        )
        rowid = res_rowid.scalar_one()

        await session.execute(
            text(
                """
                INSERT INTO events_fts(rowid, content_norm, sender_norm, title_norm)
                VALUES (:rowid, :content_norm, :sender_norm, :title_norm)
                """
            ),
            {
                "rowid": rowid,
                "content_norm": content_norm,
                "sender_norm": sender_norm,
                "title_norm": title_norm,
            },
        )

        created_count += 1
        results.append(
            IngestEventResultItem(
                external_id=item.external_id,
                status="created",
                event_id=event_id,
            )
        )

    # 7. توثيق الاستقبال في سجل التدقيق R-16 (العدد فقط دون أي محتوى رسائل R-07)
    if created_count > 0:
        await append_audit_log(
            session=session,
            actor=f"device:{device_id}",
            event="events_ingested",
            details={"created_count": created_count, "duplicate_count": duplicate_count},
        )
        logger.info(
            "events_ingested_batch_success",
            created_count=created_count,
            duplicate_count=duplicate_count,
        )

    return IngestEventsResponse(
        results=results,
        created_count=created_count,
        duplicate_count=duplicate_count,
    )
