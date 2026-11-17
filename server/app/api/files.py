"""نقطة نهاية رفع وتنزيل وتصدير الملفات والمستندات (Section 8.2 & Section 11.8)."""

import hashlib
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi import File as FastAPIFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_device_id
from app.config import settings
from app.db.base import get_db_session
from app.db.models import File

router = APIRouter(prefix="/v1/files", tags=["files"])


class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    mime_type: str
    extracted_text: str | None = None
    created_at: str


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> FileUploadResponse:
    """استقبال ورفع ملف أو مستند من الجوال وربطه بسياق السكرتير."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="الملف فارغ")

    size_bytes = len(content)
    if size_bytes > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم الملف يتجاوز الحد الأقصى المسموح (50MB)")

    sha256 = hashlib.sha256(content).hexdigest()
    raw_filename = file.filename or "uploaded_file"
    safe_filename = re.sub(r"[^\w\-.]", "_", raw_filename)
    file_id = f"file_{uuid.uuid4().hex[:12]}"

    upload_dir = Path(settings.exports_dir) / "uploads"
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        upload_dir = Path(tempfile.gettempdir()) / "exports" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / f"{file_id}_{safe_filename}"

    with open(target_path, "wb") as f:
        f.write(content)

    mime_type = file.content_type or "application/octet-stream"

    # محاولة استخراج نص مبدئي إذا كان الملف نصياً
    extracted_text: str | None = None
    if any(
        mime_type.startswith(p) for p in ("text/", "application/json", "application/javascript")
    ) or safe_filename.endswith(
        (".txt", ".md", ".json", ".csv", ".log", ".yaml", ".yml", ".py", ".xml")
    ):
        try:
            decoded = content.decode("utf-8", errors="ignore")
            extracted_text = decoded[:8000]
        except Exception:
            pass

    now = datetime.now(UTC)
    now_iso = now.isoformat()
    ttl_days = getattr(settings, "files_ttl_days", 30)
    expires_iso = (now + timedelta(days=ttl_days)).isoformat()

    db_file = File(
        id=file_id,
        path=str(target_path),
        mime=mime_type,
        sha256=sha256,
        size_bytes=size_bytes,
        created_at=now_iso,
        expires_at=expires_iso,
    )
    session.add(db_file)
    await session.commit()

    return FileUploadResponse(
        file_id=file_id,
        filename=raw_filename,
        size_bytes=size_bytes,
        mime_type=mime_type,
        extracted_text=extracted_text,
        created_at=now_iso,
    )


@router.get("/{file_id}/download", response_class=FileResponse)
async def download_file(
    file_id: str,
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    """تنزيل ملف رسمي تم توليده أو رفعه مسبقاً برابط آمن."""
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
    # إزالة معرف file_id من اسم الملف عند التنزيل
    clean_display_name = re.sub(r"^file_[a-f0-9]+_", "", filename)
    return FileResponse(
        path=file_record.path,
        media_type=file_record.mime,
        filename=clean_display_name,
    )
