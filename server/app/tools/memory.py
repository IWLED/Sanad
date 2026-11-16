"""أدوات حفظ واسترجاع الذاكرة للوكيل (Section 11.2 & R-03-د)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.agent.memory import remember, search_memories
from app.db.base import async_session_factory
from app.tools.base import BaseTool


class RememberArgs(BaseModel):
    category: Literal["preference", "fact", "project", "style", "person"] = Field(
        ...,
        description=(
            "فئة المعلومة: preference (تفضيل) | fact (حقيقة) | "
            "project (مشروع) | style (أسلوب رد) | person (عن شخص)"
        ),
    )
    content: str = Field(..., description="نص المعلومة أو التفضيل المراد حفظه في الذاكرة الدائمة")


class RememberTool(BaseTool):
    """أداة حفظ معلومة أو تفضيل دائم للمستخدم."""

    name: str = "remember"
    description: str = "حفظ تفضيل أو حقيقة أو أسلوب دائم عن المستخدم في الذاكرة طويلة الأمد"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = RememberArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, RememberArgs)
        async with async_session_factory() as session:
            mem = await remember(
                category=args.category,
                content=args.content,
                source="agent",
                session=session,
            )
            await session.commit()
            return {"status": "saved", "memory_id": mem.id, "category": mem.category}


class SearchMemoryArgs(BaseModel):
    query: str = Field(..., description="كلمات البحث في الذاكرة والتفضيلات السابقة")
    limit: int = Field(default=5, ge=1, le=10, description="العدد الأقصى للنتائج")


class SearchMemoryTool(BaseTool):
    """أداة البحث في الذاكرة والتفضيلات المخزنة مسبقاً."""

    name: str = "search_memory"
    description: str = "البحث في تفضيلات وحقائق المستخدم المخزنة في الذاكرة"
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = SearchMemoryArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        assert isinstance(args, SearchMemoryArgs)
        results = await search_memories(query=args.query, limit=args.limit)
        return {"count": len(results), "memories": results}
