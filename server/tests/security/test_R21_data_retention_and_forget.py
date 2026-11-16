"""اختبار أمني إلزامي للقاعدة R-21:

الاحتفاظ بالبيانات والحذف الدوري التلقائي وحذف بيانات جهة الاتصال (Right to be Forgotten).
"""

import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AuditLog, Contact, ContactIdentifier, Event
from app.workers.retention import forget_contact, run_retention_cleanup


@pytest.fixture
async def memory_db_session() -> AsyncGenerator[AsyncSession, None]:
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_R21_retention_cleanup_policy(memory_db_session: AsyncSession) -> None:
    """التحقق من حذف الأحداث العادية بعد 30 يوماً والأحداث الحساسة بعد 7 أيام R-21."""
    session = memory_db_session
    now = datetime.now(UTC)

    # 1. حدث عادي قديم جداً (35 يوماً) -> يجب حذفه
    evt_old_normal = Event(
        id=f"evt_{secrets.token_hex(8)}",
        source="notification",
        external_id=f"ext_{secrets.token_hex(8)}",
        thread_key="th_1",
        sensitivity="normal",
        occurred_at=(now - timedelta(days=35)).isoformat(),
        received_at=(now - timedelta(days=35)).isoformat(),
        content="رسالة عادية قديمة",
    )
    session.add(evt_old_normal)

    # 2. حدث عادي حديث (5 أيام) -> يجب الاحتفاظ به
    evt_fresh_normal = Event(
        id=f"evt_{secrets.token_hex(8)}",
        source="notification",
        external_id=f"ext_{secrets.token_hex(8)}",
        thread_key="th_2",
        sensitivity="normal",
        occurred_at=(now - timedelta(days=5)).isoformat(),
        received_at=(now - timedelta(days=5)).isoformat(),
        content="رسالة عادية جديدة",
    )
    session.add(evt_fresh_normal)

    # 3. حدث حساس قديم (8 أيام) -> يجب حذفه (سقف الحساس 7 أيام)
    evt_old_sens = Event(
        id=f"evt_{secrets.token_hex(8)}",
        source="sms",
        external_id=f"ext_{secrets.token_hex(8)}",
        thread_key="th_3",
        sensitivity="sensitive",
        occurred_at=(now - timedelta(days=8)).isoformat(),
        received_at=(now - timedelta(days=8)).isoformat(),
        content="إشعار بنكي قديم",
    )
    session.add(evt_old_sens)

    # 4. حدث حساس حديث (3 أيام) -> يجب الاحتفاظ به
    evt_fresh_sens = Event(
        id=f"evt_{secrets.token_hex(8)}",
        source="sms",
        external_id=f"ext_{secrets.token_hex(8)}",
        thread_key="th_4",
        sensitivity="sensitive",
        occurred_at=(now - timedelta(days=3)).isoformat(),
        received_at=(now - timedelta(days=3)).isoformat(),
        content="إشعار بنكي جديد",
    )
    session.add(evt_fresh_sens)
    await session.commit()

    # تشغيل عامل الحذف والاحتفاظ
    stats = await run_retention_cleanup(session=session)
    assert stats["deleted_normal"] == 1
    assert stats["deleted_sensitive"] == 1

    # التحقق من قاعدة البيانات
    remaining_ids = (await session.execute(select(Event.id))).scalars().all()
    assert evt_old_normal.id not in remaining_ids
    assert evt_old_sens.id not in remaining_ids
    assert evt_fresh_normal.id in remaining_ids
    assert evt_fresh_sens.id in remaining_ids


@pytest.mark.asyncio
async def test_R21_forget_contact_completely(memory_db_session: AsyncSession) -> None:
    """التحقق من الحذف الكامل لكافة بيانات وأحداث جهة الاتصال (حق النسيان R-21)."""
    session = memory_db_session
    now_iso = datetime.now(UTC).isoformat()
    phone = "+966509999999"
    contact_id = f"cnt_{secrets.token_hex(8)}"

    contact = Contact(
        id=contact_id,
        display_name="عبدالله العتيبي",
        created_at=now_iso,
        updated_at=now_iso,
    )
    session.add(contact)
    ident = ContactIdentifier(
        contact_id=contact_id,
        kind="phone",
        value_raw=phone,
        value_norm=phone,
    )
    session.add(ident)

    # إضافة أحداث تابعة لجهة الاتصال
    evt1 = Event(
        id=f"evt_{secrets.token_hex(8)}",
        source="notification",
        external_id=f"ext_{secrets.token_hex(8)}",
        thread_key="th_user",
        sender_contact_id=contact_id,
        sender_name="عبدالله العتيبي",
        occurred_at=now_iso,
        received_at=now_iso,
        content="رسالة 1 من عبدالله",
    )
    evt2 = Event(
        id=f"evt_{secrets.token_hex(8)}",
        source="sms",
        external_id=f"ext_{secrets.token_hex(8)}",
        thread_key="th_user_2",
        sender_contact_id=contact_id,
        sender_name="عبدالله العتيبي",
        occurred_at=now_iso,
        received_at=now_iso,
        content="رسالة 2 من عبدالله",
    )
    session.add_all([evt1, evt2])
    await session.commit()

    # تنفيذ أمر النسيان برقم الهاتف
    forgotten = await forget_contact(identifier=phone, session=session)
    assert forgotten is True

    # التحقق من حذف جهة الاتصال
    stmt_c = select(Contact).where(Contact.id == contact_id)
    c_check = (await session.execute(stmt_c)).scalar_one_or_none()
    assert c_check is None

    # التحقق من حذف كافة الأحداث المرتبطة
    stmt_e = select(Event).where(Event.sender_contact_id == contact_id)
    e_check = (await session.execute(stmt_e)).scalars().all()
    assert len(e_check) == 0

    # التحقق من تدوين الحدث في سجل التدقيق
    audits = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.event == "contact_forgotten_completely",
                    AuditLog.ref_id == contact_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) >= 1
