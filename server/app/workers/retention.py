"""عامل الاحتفاظ بالبيانات وحذف السجلات القديمة وأمر النسيان (Section 11.3 & R-21)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import append_audit_log
from app.core.safety.logging_filter import logger
from app.db.base import async_session_factory
from app.db.models import Contact, ContactIdentifier, Event


async def run_retention_cleanup(session: AsyncSession | None = None) -> dict[str, int]:
    """تنفيذ سياسة الاحتفاظ وحذف الأحداث المنتهية (R-21)."""
    now = datetime.now(UTC)
    cutoff_normal = (now - timedelta(days=settings.retention_events_days)).isoformat()
    cutoff_sensitive = (now - timedelta(days=settings.retention_sensitive_days)).isoformat()

    async def _cleanup(s: AsyncSession) -> dict[str, int]:
        # 1. حذف الأحداث العادية التي تجاوزت 30 يوماً
        stmt_norm = delete(Event).where(
            Event.sensitivity == "normal",
            Event.occurred_at < cutoff_normal,
        )
        res_norm = await s.execute(stmt_norm)
        deleted_normal: int = int(getattr(res_norm, "rowcount", 0) or 0)

        # 2. حذف الأحداث الحساسة التي تجاوزت 7 أيام
        stmt_sens = delete(Event).where(
            Event.sensitivity.in_(["sensitive", "secret"]),
            Event.occurred_at < cutoff_sensitive,
        )
        res_sens = await s.execute(stmt_sens)
        deleted_sensitive: int = int(getattr(res_sens, "rowcount", 0) or 0)

        total_deleted = deleted_normal + deleted_sensitive
        if total_deleted > 0:
            await append_audit_log(
                session=s,
                actor="worker:retention",
                event="retention_cleanup_completed",
                details={
                    "deleted_normal": deleted_normal,
                    "deleted_sensitive": deleted_sensitive,
                },
            )
            await s.commit()

        logger.info(
            "retention_cleanup_done",
            deleted_normal=deleted_normal,
            deleted_sensitive=deleted_sensitive,
        )
        return {"deleted_normal": deleted_normal, "deleted_sensitive": deleted_sensitive}

    if session:
        return await _cleanup(session)

    async with async_session_factory() as sess:
        return await _cleanup(sess)


async def forget_contact(identifier: str, session: AsyncSession | None = None) -> bool:
    """حذف شامل لجهة اتصال وكافة أحداثها استجابة لطلب المستخدم (R-21 Forget)."""

    async def _forget(s: AsyncSession) -> bool:
        # البحث بالمعرف أو بالاسم أو بالرقم/اللقب من جدول المعرفات
        stmt = (
            select(Contact)
            .outerjoin(ContactIdentifier, Contact.id == ContactIdentifier.contact_id)
            .where(
                (Contact.id == identifier)
                | (Contact.display_name == identifier)
                | (ContactIdentifier.value_norm == identifier)
                | (ContactIdentifier.value_raw == identifier)
            )
        )
        res = await s.execute(stmt)
        contact = res.scalars().first()

        if not contact:
            logger.warning("forget_contact_not_found", identifier_prefix=identifier[:4])
            return False

        contact_id = contact.id
        display_name = contact.display_name

        # حذف كافة الأحداث المرتبطة بجهة الاتصال
        stmt_del_events = delete(Event).where(
            (Event.sender_contact_id == contact_id) | (Event.sender_name == display_name)
        )
        await s.execute(stmt_del_events)

        # حذف جهة الاتصال نفسها
        stmt_del_contact = delete(Contact).where(Contact.id == contact_id)
        await s.execute(stmt_del_contact)

        await append_audit_log(
            session=s,
            actor="admin:forget",
            event="contact_forgotten_completely",
            ref_id=contact_id,
            details={"status": "all_events_and_contact_wiped"},
        )
        await s.commit()
        logger.info("contact_forgotten_success", contact_id=contact_id)
        return True

    if session:
        return await _forget(session)

    async with async_session_factory() as sess:
        return await _forget(sess)
