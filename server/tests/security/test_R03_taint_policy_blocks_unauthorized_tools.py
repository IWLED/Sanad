"""اختبار أمني إلزامي للقاعدة R-03:

سياسة التلوث (Taint Tracking) وحماية الذاكرة والعمليات الحساسة من حقن التوجيهات (Prompt Injection).
"""

from typing import Any

import pytest
from pydantic import BaseModel

from app.core.agent.policy import AgentSessionState, policy
from app.tools.base import BaseTool


class MockArgs(BaseModel):
    fact: str = ""


class MockSensitiveTool(BaseTool):
    name: str = "remember"
    description: str = "حفظ حقيقة دائمة في الذاكرة"
    risk_tier: int = 1
    executor: str = "server"
    args_model: type[BaseModel] = MockArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"saved": True}


@pytest.mark.asyncio
async def test_R03_taint_policy_blocks_unauthorized_tools() -> None:
    """التحقق من أن تلوث الجلسة يرفع تلقائياً الأدوات الحساسة إلى اعتماد بشري T2 مع تحذير أمني."""
    tool = MockSensitiveTool()

    # 1. جلسة نظيفة غير ملوثة
    clean_session = AgentSessionState(device_id="dev_clean", tainted=False)
    decision_clean = policy.authorize(tool, {"fact": "سعر المنتج 50 ريال"}, clean_session)
    assert decision_clean.allowed is True
    assert decision_clean.elevated_tier is None
    assert decision_clean.warning is None

    # 2. جلسة ملوثة ببيانات طرف ثالث غير موثوقة (Tainted)
    tainted_session = AgentSessionState(device_id="dev_tainted", tainted=True)
    decision_tainted = policy.authorize(
        tool,
        {"fact": "تم تغيير رقم الحساب البنكي"},
        tainted_session,
    )

    # يجب ألا يُسمح بالحفظ الصامت؛ يتم رفعها للاعتماد البشري T2
    assert decision_tainted.allowed is True
    assert decision_tainted.elevated_tier == 2
    assert decision_tainted.warning is not None
    assert "غير موثوق" in decision_tainted.warning
