"""اختبار أمني إلزامي للقاعدة R-18:

القيود والحدود القصوى لدورات الوكيل واستدعاء الأدوات ومقترحات الردود.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.agent.loop import AgentRunner
from app.core.agent.policy import AgentSessionState, policy
from app.core.llm.client import LLMResponse, LLMToolCall
from app.db.base import async_session_factory
from app.db.models import Device
from app.tools.registry import tool_registry


@pytest.mark.asyncio
async def test_R18_policy_tool_and_proposal_caps() -> None:
    """التحقق من حظر تجاوز سقف 12 أداة أو سقف 10 مقترحات رد."""
    tool = tool_registry.get("mock_t2")
    assert tool is not None

    # 1. فحص سقف استدعاءات الأدوات (12)
    session_tool_limit = AgentSessionState(device_id="dev_r18")
    session_tool_limit.tool_calls_count = 12
    dec_tool = policy.authorize(tool, {}, session_tool_limit)
    assert dec_tool.allowed is False
    assert "السقف الأقصى" in dec_tool.reason

    # 2. فحص سقف مقترحات الرد (10)
    session_prop_limit = AgentSessionState(device_id="dev_r18")
    session_prop_limit.reply_proposals_count = 10
    dec_prop = policy.authorize(tool, {}, session_prop_limit)
    assert dec_prop.allowed is False
    assert "سقف مقترحات الرد" in dec_prop.reason or "الحد الأقصى" in dec_prop.reason


@pytest.mark.asyncio
async def test_R18_agent_step_cap_breaks_loop() -> None:
    """التحقق من أن تجاوز 8 خطوات يكسر الحلقة ويعيد رسالة اعتذار أمنية دون تعليق النظام."""
    mock_llm = AsyncMock()
    # المحاكي يُعيد دائماً استدعاء أداة لإجبار الوكيل على تكرار الخطوات
    mock_llm.chat.return_value = LLMResponse(
        text="",
        tool_calls=[
            LLMToolCall(
                id="call_inf_1",
                name="mock_t2",
                arguments='{"recipient": "+966500000000", "message": "تجربة"}',
            )
        ],
        model_used="test-mock-model",
        profile="reasoner",
    )

    runner = AgentRunner(llm_client=mock_llm)
    async with async_session_factory() as session:
        dev = Device(
            id="dev_step_cap",
            name="Step Cap Device",
            pubkey_pem="fake_pem",
            created_at=datetime.now(UTC).isoformat(),
        )
        await session.merge(dev)
        await session.commit()

        result = await runner.run(
            device_id="dev_step_cap",
            user_message="كرر الاستدعاء بلا توقف",
            session=session,
        )

    # يجب أن تتوقف الحلقة بعد الخطوات المسموحة R-18
    assert "اعتذر" in result or "أكثر من الحد المسموح به" in result
    assert mock_llm.chat.call_count <= 8
