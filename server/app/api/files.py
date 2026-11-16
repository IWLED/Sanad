"""نقطة نهاية تنزيل وتصدير الملفات والمستندات المولدة (Section 8.2 & Section 11.8)."""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_device_id
from app.db.base import get_db_session
from app.db.models import File

router = APIRouter(prefix="/v1/files", tags=["files"])


@router.get("/{file_id}/download", response_class=FileResponse)
async def download_file(
    file_id: str,
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    """تنزيل ملف رسمي تم توليده مسبقاً (Word, Excel, PowerPoint) برابط آمن."""
    stmt = select(File).where(File.id == file_id)
    res = await session.execute(stmt)
    file_record = res.scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الملف غير موجود أو منتهي الصلاحية",
        )

    if not os.path.exists(file_record.path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الملف غير موجود على القرص التخزيني",
        )

    filename = os.path.basename(file_record.path)
    return FileResponse(
        path=file_record.path,
        media_type=file_record.mime,
        filename=filename,
    )
