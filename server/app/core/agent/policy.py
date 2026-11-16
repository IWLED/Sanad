"""سياسة التلوّث (Taint Policy) وفرض القواعد الأمنية R-02 و R-03 خارج النموذج."""

from typing import Any

from pydantic import BaseModel

from app.tools.base import BaseTool
from app.tools.registry import tool_registry


class PolicyDecision(BaseModel):
    """قرار السياسة الأمنية عند محاولة استدعاء أداة."""

    allowed: bool
    elevated_tier: int | None = None
    warning: str | None = None
    reason: str = ""

    def as_tool_error(self) -> dict[str, Any]:
        return {"error": f"SecurityPolicyDenied: {self.reason}"}


class AgentSessionState:
    """حالة جلسة الوكيل خلال جولة المحادثة."""

    def __init__(self, device_id: str, tainted: bool = False) -> None:
        self.device_id = device_id
        self.tainted: bool = tainted
        self.steps: int = 0
        self.tool_calls_count: int = 0
        self.reply_proposals_count: int = 0


class SecurityPolicy:
    """تطبيق قواعد R-02 و R-03 وسياسة التلوث الحتمية."""

    @staticmethod
    def visible_tools(session: AgentSessionState) -> list[dict[str, Any]]:
        """الأدوات المتاحة للنموذج في هذه الخطوة."""
        tools = tool_registry.list_tools()
        # إن كانت الجلسة tainted يُمنع تسجيل أدوات الشبكة والمصادر الخارجية
        if session.tainted:
            tools = [t for t in tools if not getattr(t, "is_network_tool", False)]
        return [t.to_openai_tool() for t in tools]

    @staticmethod
    def authorize(
        tool: BaseTool,
        args_dict: dict[str, Any],
        session: AgentSessionState,
    ) -> PolicyDecision:
        """فحص حتمي لاستدعاء الأداة خارج النموذج (R-03)."""
        # 1. فحص سقف استدعاءات الأدوات (R-18)
        if session.tool_calls_count >= 12:
            return PolicyDecision(
                allowed=False,
                reason="تجاوز السقف الأقصى لاستدعاءات الأدوات في الجولة (12 أداة)",
            )

        # 2. فحص سقف مقترحات الرد (R-18)
        if tool.name in ("mock_t2", "propose_reply") and session.reply_proposals_count >= 10:
            return PolicyDecision(
                allowed=False,
                reason="تجاوز الحد الأقصى لمقترحات الرد في الساعة (10 مقترحات)",
            )

        # 3. قواعد التلوث (Tainted Session - R-03)
        if session.tainted and tool.name in ("remember", "update_contact"):
            return PolicyDecision(
                allowed=True,
                elevated_tier=2,
                warning="تم رفع مستوى حفظ المعلومة لاعتمادك لأن الجلسة لامست محتوى غير موثوق",
            )

        return PolicyDecision(allowed=True)


policy = SecurityPolicy()
