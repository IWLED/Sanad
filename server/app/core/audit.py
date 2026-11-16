"""سجل التدقيق متسلسل التجزئة المشفّر (Hash-chained Audit Log) تنفيذاً للقاعدة R-16."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

GENESIS_HASH = "0" * 64


def compute_audit_hash(
    prev_hash: str,
    ts: str,
    actor: str,
    event: str,
    ref_id: str | None,
    details_json: str,
) -> str:
    """حساب التجزئة لصف التدقيق بربطه بـ prev_hash."""
    canonical_ref = ref_id or ""
    payload = f"{prev_hash}|{ts}|{actor}|{event}|{canonical_ref}|{details_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def append_audit_log(
    session: AsyncSession,
    actor: str,
    event: str,
    ref_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """إضافة سجل تدقيق جديد متسلسل مع الصف السابق بشكل ذري."""
    # جلب آخر تجزئة مسجلة في الجدول
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
    result = await session.execute(stmt)
    last_entry = result.scalar_one_or_none()

    prev_hash = last_entry.hash if last_entry else GENESIS_HASH
    ts = datetime.now(UTC).isoformat()
    details_json = json.dumps(details or {}, sort_keys=True, ensure_ascii=False)

    entry_hash = compute_audit_hash(
        prev_hash=prev_hash,
        ts=ts,
        actor=actor,
        event=event,
        ref_id=ref_id,
        details_json=details_json,
    )

    audit_entry = AuditLog(
        ts=ts,
        actor=actor,
        event=event,
        ref_id=ref_id,
        details_json=details_json,
        prev_hash=prev_hash,
        hash=entry_hash,
    )

    session.add(audit_entry)
    await session.flush()
    return audit_entry


async def verify_audit_chain(session: AsyncSession) -> tuple[bool, str]:
    """التحقق من سلامة وتسلسل كامل سجل التدقيق وعدم العبث بأي إدخال."""
    stmt = select(AuditLog).order_by(AuditLog.id.asc())
    result = await session.execute(stmt)
    entries = result.scalars().all()

    if not entries:
        return True, "السجل فارغ وسليم."

    expected_prev = GENESIS_HASH
    for entry in entries:
        if entry.prev_hash != expected_prev:
            return False, f"انقطاع في السلسلة عند السجل رقم {entry.id}: prev_hash غير مطابق."

        recomputed_hash = compute_audit_hash(
            prev_hash=entry.prev_hash,
            ts=entry.ts,
            actor=entry.actor,
            event=entry.event,
            ref_id=entry.ref_id,
            details_json=entry.details_json,
        )

        if entry.hash != recomputed_hash:
            return False, f"تلاعب بالتجزئة عند السجل رقم {entry.id}: hash غير مطابق."

        expected_prev = entry.hash

    return True, f"تم التحقق بنجاح من سلامة {len(entries)} سجل تدقيق."
