"""سجل الأدوات المتاحة وإدارتها وأدوات الاختبار الوهمية للمرحلة 1 (Section 10.4, T-1.4)."""

from typing import Any

from pydantic import BaseModel, Field

from app.tools.base import BaseTool


class MockT2Args(BaseModel):
    """مدخلات أداة المراسلة الخارجية التجريبية (Tier 2)."""

    recipient: str = Field(..., description="اسم أو معرف المستلم")
    message: str = Field(..., description="نص الرسالة المراد إرسالها بعد موافقة المستخدم")


class MockT2Tool(BaseTool):
    """أداة وهمية لمحاكاة إرسال رسالة خارجية (Tier 2, Executor: Device)."""

    name = "mock_t2"
    description = "اقتراح إرسال رسالة خارجية للطرف الآخر بعد اعتماد المستخدم (Tier 2)."
    args_model = MockT2Args
    risk_tier = 2
    executor = "device"
    returns_untrusted = False

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        data = args.model_dump()
        return {
            "action_kind": "mock_send_message",
            "preview_title": f"إرسال رسالة إلى {data.get('recipient')}",
            "text": data.get("message"),
            "recipient": data.get("recipient"),
        }


class MockT3Args(BaseModel):
    """مدخلات إجراء عالي الخطورة تجريبي (Tier 3)."""

    target: str = Field(..., description="الهدف أو الحساب الخارجي المعني")
    action_detail: str = Field(..., description="تفاصيل الإجراء الحساس")


class MockT3Tool(BaseTool):
    """أداة وهمية لمحاكاة إجراء حساس عالي الخطورة يتطلب بصمة (Tier 3, Executor: Server)."""

    name = "mock_t3"
    description = "طلب تنفيذ إجراء حساس خارج النظام يتطلب اعتماداً صريحاً بالبصمة (Tier 3)."
    args_model = MockT3Args
    risk_tier = 3
    executor = "server"
    returns_untrusted = False

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        data = args.model_dump()
        return {
            "action_kind": "mock_critical_action",
            "preview_title": f"إجراء عالي الخطورة على {data.get('target')}",
            "text": data.get("action_detail"),
            "target": data.get("target"),
        }


class ToolRegistry:
    """سجل مركزي لجميع الأدوات المسجلة في النظام."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        # تسجيل الأدوات الوهمية للمرحلة 1
        self.register(MockT2Tool())
        self.register(MockT3Tool())

        # تسجيل أدوات صندوق الوارد والذاكرة والرد (المرحلة 2 و 3)
        from app.tools.calendar import CalendarCreateTool, CalendarListTool
        from app.tools.email import GmailCreateDraftTool, GmailSearchTool, GmailSendTool
        from app.tools.inbox import GetEventTool, GetThreadTool, SearchInboxTool
        from app.tools.memory import RememberTool, SearchMemoryTool
        from app.tools.office.tool import GenerateDocumentTool
        from app.tools.reminders import (
            ScheduleMessageTool,
            ScheduleReminderTool,
            TodoCreateTool,
        )
        from app.tools.reply import ProposeReplyTool

        self.register(SearchInboxTool())
        self.register(GetThreadTool())
        self.register(GetEventTool())
        self.register(RememberTool())
        self.register(SearchMemoryTool())
        self.register(ProposeReplyTool())
        self.register(ScheduleReminderTool())
        self.register(ScheduleMessageTool())
        self.register(TodoCreateTool())
        self.register(GenerateDocumentTool())
        self.register(CalendarListTool())
        self.register(CalendarCreateTool())
        self.register(GmailSearchTool())
        self.register(GmailCreateDraftTool())
        self.register(GmailSendTool())

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]


tool_registry = ToolRegistry()
