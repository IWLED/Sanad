"""أداة استرجاع وتوليد الإيجاز اليومي الصباحي والمسائي للوكيل (Section 11.1)."""

from typing import Any, Literal
from pydantic import BaseModel, Field

from app.core.briefing.engine import generate_briefing
from app.db.base import async_session_factory
from app.tools.base import BaseTool


class GetDailyBriefingArgs(BaseModel):
    kind: Literal["morning", "evening", "on_demand"] = Field(
        default="morning",
        description="نوع الإيجاز المطلوب: morning (صباحي) | evening (مسائي) | on_demand (فوري حسب الطلب)",
    )
    hours_lookback: int = Field(
        default=24,
        description="عدد الساعات السابقة التي يتم مسح أحداثها ورسائلها (الافتراضي 24 ساعة)",
    )


class GetDailyBriefingTool(BaseTool):
    """أداة تلخيص الأحداث والرسائل والمكالمات الواردة وتقديم الإيجاز المجمع حسب الموضوع والأولوية."""

    name: str = "get_daily_briefing"
    description: str = (
        "توليد أو جلب الإيجاز والملخص المجمع لجميع ما وصل إلى الجوال (مكالمات، واتساب، SMS، إشعارات) "
        "موزعة حسب الأولوية والعائلة والردود المعلقة. استخدمها عند سؤال المستخدم: «وش صار اليوم؟» أو «لخص لي اليوم»."
    )
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = GetDailyBriefingArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = GetDailyBriefingArgs.model_validate(args.model_dump())
        session = ctx.get("session")

        if session:
            briefing = await generate_briefing(
                kind=params.kind,
                hours_lookback=params.hours_lookback,
                session=session,
            )
        else:
            async with async_session_factory() as sess:
                briefing = await generate_briefing(
                    kind=params.kind,
                    hours_lookback=params.hours_lookback,
                    session=sess,
                )

        return {
            "briefing_id": briefing.id,
            "kind": briefing.kind,
            "rendered_text": briefing.rendered_text,
            "generated_at": briefing.generated_at,
            "status": "ready",
        }
