"""مسار واجهة الويب ولوحة التحكم المركزية لسند (Web Dashboard & Pairing Hub)."""

import secrets
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit_log, verify_audit_chain
from app.core.crypto import hash_with_pepper
from app.db.base import get_db_session
from app.db.models import AppPolicy, Device, Event, PairingCode

router = APIRouter(tags=["web"])


class NewPairingCodeResponse(BaseModel):
    """بيانات رمز الاقتران الجديد المتولد من لوحة الويب."""

    code: str
    server_url: str
    expires_at: str
    qr_payload: str


class WebStatsResponse(BaseModel):
    """إحصائيات النظام ولوحة التحكم."""

    status: str
    database: str
    devices_count: int
    policies_count: int
    events_count: int
    audit_chain_valid: bool
    audit_chain_message: str


@lru_cache
def get_dashboard_html() -> str:
    """قراءة قالب واجهة المستخدم التنفيذية من الملف."""
    html_file = Path(__file__).parent / "index.html"
    return html_file.read_text(encoding="utf-8")


@router.post(
    "/v1/web/pairing-code",
    response_model=NewPairingCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_web_pairing_code(
    session: AsyncSession = Depends(get_db_session),
) -> NewPairingCodeResponse:
    """توليد كود اقتران مؤقت جديد لربط تطبيق الجوال مباشرة من لوحة التحكم."""
    raw_code = secrets.token_hex(16).upper()
    code_hash = hash_with_pepper(raw_code)

    now = datetime.now(UTC)
    expires = datetime.fromtimestamp(now.timestamp() + 10 * 60, tz=UTC)

    pairing_entry = PairingCode(
        code_hash=code_hash,
        created_at=now.isoformat(),
        expires_at=expires.isoformat(),
    )
    session.add(pairing_entry)

    await append_audit_log(
        session,
        actor="web_dashboard",
        event="web_pairing_code_generated",
        details={"expires_at": expires.isoformat()},
    )
    await session.commit()

    qr_payload = f'{{"server_url":"","code":"{raw_code}"}}'

    return NewPairingCodeResponse(
        code=raw_code,
        server_url="",
        expires_at=expires.isoformat(),
        qr_payload=qr_payload,
    )


@router.get("/v1/web/stats", response_model=WebStatsResponse)
async def get_web_stats(
    session: AsyncSession = Depends(get_db_session),
) -> WebStatsResponse:
    """إرجاع إحصائيات الخادم وصحة السجل والأجهزة المقترنة."""
    dev_count = await session.scalar(select(func.count(Device.id))) or 0
    pol_count = await session.scalar(select(func.count(AppPolicy.package))) or 0
    evt_count = await session.scalar(select(func.count(Event.id))) or 0

    is_valid, chain_msg = await verify_audit_chain(session)

    return WebStatsResponse(
        status="running",
        database="connected",
        devices_count=dev_count,
        policies_count=pol_count,
        events_count=evt_count,
        audit_chain_valid=is_valid,
        audit_chain_message=chain_msg,
    )


@router.get("/v1/web/devices")
async def get_web_devices(
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """قائمة الأجهزة المقترنة بالخادم."""
    stmt = select(Device).order_by(Device.created_at.desc())
    res = await session.execute(stmt)
    devices = res.scalars().all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "created_at": d.created_at,
            "last_seen_at": d.last_seen_at,
            "app_version": d.app_version,
            "android_sdk": d.android_sdk,
        }
        for d in devices
    ]


@router.get("/download/app", response_class=FileResponse)
@router.get("/app-debug.apk", response_class=FileResponse)
async def download_apk() -> FileResponse:
    """تحميل ملف APK لتطبيق الجوال المحدث مباشرة من الخادم."""
    candidates = [
        Path("/data/app-debug.apk"),
        Path("/exports/app-debug.apk"),
        Path("/app/app-debug.apk"),
    ]
    for p in candidates:
        if p.is_file():
            return FileResponse(
                path=str(p),
                filename="Sanad-v0.1.0.apk",
                media_type="application/vnd.android.package-archive",
            )
    raise HTTPException(status_code=404, detail="APK file not found on server")


@router.get("/", response_class=HTMLResponse)
async def serve_dashboard() -> str:
    """الصفحة الرئيسية للوحة تحكم سند التنفيذية المركزية (Material Design 3)."""
    return get_dashboard_html()
