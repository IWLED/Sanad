"""أداة توليد المستندات المكتبية للوكيل (Generate Document Tool) (Section 10.4 & Section 11.8)."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.base import async_session_factory
from app.db.models import File
from app.tools.base import BaseTool
from app.tools.office.generator import create_office_document


class GenerateDocumentArgs(BaseModel):
    kind: Literal["docx", "xlsx", "pptx"] = Field(
        ...,
        description=(
            "نوع الملف المراد إنشاؤه: docx (مستند Word) | xlsx (جدول Excel) | pptx (عرض شرائح)"
        ),
    )
    spec: dict[str, Any] = Field(
        ...,
        description="المخطط التفصيلي لمحتوى المستند والعناوين والجداول والفقرات",
    )


class GenerateDocumentTool(BaseTool):
    """أداة إنشاء وتوليد ملفات Office المهيأة باللغة العربية واتجاه RTL (Tier 1, Server)."""

    name: str = "generate_document"
    description: str = (
        "توليد ملف Word أو Excel أو PowerPoint مهيأ بالكامل للغة العربية وتوفير رابط تنزيله"
    )
    risk_tier: int = 1
    executor: str = "server"
    returns_untrusted: bool = False
    args_model: type[BaseModel] = GenerateDocumentArgs

    async def run(self, args: BaseModel, ctx: dict[str, Any]) -> dict[str, Any]:
        params = GenerateDocumentArgs.model_validate(args.model_dump())
        session = ctx.get("session")

        doc_meta = create_office_document(kind=params.kind, spec_data=params.spec)

        now = datetime.now(UTC)
        expires_at = (now + timedelta(days=30)).isoformat()

        async def _save_record(s: Any) -> None:
            file_rec = File(
                id=doc_meta["file_id"],
                path=doc_meta["path"],
                mime=doc_meta["mime"],
                sha256=doc_meta["sha256"],
                size_bytes=doc_meta["size_bytes"],
                created_at=now.isoformat(),
                expires_at=expires_at,
            )
            s.add(file_rec)
            await s.flush()

        if session:
            await _save_record(session)
        else:
            async with async_session_factory() as sess:
                await _save_record(sess)
                await sess.commit()

        return {
            "file_id": doc_meta["file_id"],
            "filename": doc_meta["filename"],
            "download_url": f"/v1/files/{doc_meta['file_id']}/download",
            "size_bytes": doc_meta["size_bytes"],
            "mime": doc_meta["mime"],
            "status": "ready",
        }
