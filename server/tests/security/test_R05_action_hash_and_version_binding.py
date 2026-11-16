"""اختبار أمني إلزامي للقاعدة R-05:

ربط الموافقة بتجزئة الوسائط (args_hash) والإصدار (version) ورفض أي تلاعب أو اختلاف.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.hitl.engine import compute_args_hash, hitl_engine
from app.db.base import Base
from app.tools.registry import tool_registry


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
async def test_R05_action_hash_and_version_binding(
    memory_db_session: AsyncSession,
) -> None:
    """التحقق من إحباط تزوير المعاملات أو عدم تطابق التجزئة وتوليد نسخة جديدة عند التعديل."""
    session = memory_db_session
    device_id = "dev_test_r05"
    tool = tool_registry.get("mock_t2")
    assert tool is not None

    args = {"recipient": "+966500000000", "message": "المبلغ المطلوب 100 ريال"}
    action = await hitl_engine.create_action(
        session=session,
        device_id=device_id,
        tool=tool,
        args_dict=args,
    )

    correct_hash = action.args_hash
    fake_hash = compute_args_hash({"recipient": "+966500000000", "message": "المبلغ 1000 ريال"})

    # 1. محاولة الاعتماد بتجزئة مزورة أو غير متطابقة
    with pytest.raises(ValueError, match="Arguments hash mismatch"):
        await hitl_engine.process_decision(
            session=session,
            device_id=device_id,
            action_id=action.id,
            version=action.version,
            args_hash=fake_hash,
            decision="APPROVE",
        )

    # 2. محاولة الاعتماد برقم إصدار خاطئ
    with pytest.raises(ValueError, match="Version mismatch"):
        await hitl_engine.process_decision(
            session=session,
            device_id=device_id,
            action_id=action.id,
            version=99,
            args_hash=correct_hash,
            decision="APPROVE",
        )

    # 3. محاولة الاعتماد بعد انتهاء الصلاحية
    action.expires_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await session.commit()
    with pytest.raises(ValueError, match="expired"):
        await hitl_engine.process_decision(
            session=session,
            device_id=device_id,
            action_id=action.id,
            version=action.version,
            args_hash=correct_hash,
            decision="APPROVE",
        )

    # إعادة تمديد الصلاحية لاختبار التعديل النصي (Edit)
    action.expires_at = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    action.status = "PENDING_APPROVAL"
    await session.commit()

    # 4. تعديل النص من المستخدم: يجب أن يُلغى الإجراء الحالي وتنشأ نسخة version+1 معتمدة
    new_action = await hitl_engine.process_decision(
        session=session,
        device_id=device_id,
        action_id=action.id,
        version=action.version,
        args_hash=correct_hash,
        decision="APPROVE",
        edited_text="المبلغ المطلوب 150 ريال بعد التعديل",
    )

    assert action.status == "SUPERSEDED"
    assert new_action.version == 2
    assert new_action.supersedes_id == action.id
    assert new_action.status in ("APPROVED", "EXECUTED", "EXECUTING")
    assert new_action.args_hash != correct_hash
