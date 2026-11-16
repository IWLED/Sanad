"""الفئة الأساسية للأدوات في نظام الوكيل وسجل المخاطر (Section 10.4)."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class BaseTool(ABC):
    """الواجهة الأساسية لكل أداة يستدعيها الوكيل."""

    name: str
    description: str
    args_model: type[BaseModel]
    risk_tier: int  # 0: قراءة, 1: داخلي قابل للعكس, 2: تواصل خارجي, 3: عالي الخطورة
    executor: str  # device | server | none
    returns_untrusted: bool = False

    def to_openai_tool(self) -> dict[str, Any]:
        """تحويل مواصفات الأداة إلى صيغة OpenAI Function Calling."""
        schema = self.args_model.model_json_schema()
        # تنظيف الحقول غير المطلوبة في OpenAI
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    @abstractmethod
    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        """تنفيذ الأداة أو إعداد مسودة الإجراء لـ HITL."""
        pass
