"""اختبار أمني إلزامي للقاعدة R-06:

منع تكرار تنفيذ الإجراء (Idempotency & Replay Defense).
الإجراء لا يُنفّذ أكثر من مرة واحدة مطلقاً.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.hitl.engine import hitl_engine
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
async def test_R06_action_executed_once_idempotency(
    memory_db_session: AsyncSession,
) -> None:
    """التحقق من أن الإجراء المعتمد أو المنفذ لا يمكن إعادة اعتماده أو تنفيذه مرة ثانية."""
    session = memory_db_session
    device_id = "dev_test_r06"
    tool = tool_registry.get("mock_t2")
    assert tool is not None

    args = {"recipient": "+966500000000", "message": "رسالة اختبار التكرار"}
    action = await hitl_engine.create_action(
        session=session,
        device_id=device_id,
        tool=tool,
        args_dict=args,
    )

    action_id = action.id
    version = action.version
    args_hash = action.args_hash

    # المرة الأولى: الاعتماد بنجاح
    approved_action = await hitl_engine.process_decision(
        session=session,
        device_id=device_id,
        action_id=action_id,
        version=version,
        args_hash=args_hash,
        decision="APPROVE",
    )
    assert approved_action.status in ("APPROVED", "EXECUTING", "EXECUTED")

    # المرة الثانية: محاولة إعادة الاعتماد لنفس الإجراء (هجوم إعادة Replay Attack)
    with pytest.raises(ValueError, match="Action is not pending approval"):
        await hitl_engine.process_decision(
            session=session,
            device_id=device_id,
            action_id=action_id,
            version=version,
            args_hash=args_hash,
            decision="APPROVE",
        )
