"""اختبار أمني إلزامي للقاعدة R-16:

سجل تدقيق متسلسل التجزئة (hash-chained) لكل فعل/قرار/انتقال حالة.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit import append_audit_log, verify_audit_chain
from app.db.base import Base


@pytest.fixture
async def memory_db_session() -> AsyncSession:
    """قاعدة بيانات SQLite في الذاكرة للاختبارات السريعة والمستقلة."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_R16_audit_log_hash_chained(memory_db_session: AsyncSession) -> None:
    """التحقق من صحة ترابط وتتابع تجزئة سجل التدقيق واكتشاف أي تلاعب."""
    session = memory_db_session

    # 1. إضافة سجلات متتالية
    entry1 = await append_audit_log(
        session=session,
        actor="device:dev_01",
        event="device_paired",
        ref_id="dev_01",
        details={"app_version": "1.0.0"},
    )
    assert entry1.id == 1
    assert entry1.prev_hash == "0" * 64
    assert len(entry1.hash) == 64

    entry2 = await append_audit_log(
        session=session,
        actor="user",
        event="action_approved",
        ref_id="act_01",
        details={"version": 1},
    )
    assert entry2.id == 2
    assert entry2.prev_hash == entry1.hash

    entry3 = await append_audit_log(
        session=session,
        actor="agent",
        event="reply_proposed",
        ref_id="act_02",
        details={"tier": 2},
    )
    assert entry3.prev_hash == entry2.hash

    await session.commit()

    # 2. التحقق من سلامة السلسلة بالكامل
    is_valid, msg = await verify_audit_chain(session)
    assert is_valid is True
    assert "تم التحقق بنجاح" in msg

    # 3. محاكاة التلاعب بصف سابق (Tampering Attack)
    entry2.details_json = '{"version": 999}'
    await session.commit()

    is_valid_after_tamper, tamper_msg = await verify_audit_chain(session)
    assert is_valid_after_tamper is False
    assert "تلاعب بالتجزئة" in tamper_msg or "انقطاع في السلسلة" in tamper_msg
