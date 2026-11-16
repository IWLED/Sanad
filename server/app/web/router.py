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
from app.core.llm.client import LLMClient, test_model_connection
from app.core.llm.profiles import ModelsConfig, ProfileConfig, load_models_config, save_models_config
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


class TestModelRequest(BaseModel):
    """طلب فحص نموذج الذكاء الاصطناعي."""

    base_url: str
    model: str
    api_key: str | None = None
    timeout_s: int = 15


class UpdateModelsRequest(BaseModel):
    """طلب تحديث نماذج وسياسات السكرتير."""

    profiles: dict[str, Any]
    policy: dict[str, Any]


class WebChatRequest(BaseModel):
    """طلب محادثة من لوحة الويب."""

    message: str


class WebChatResponse(BaseModel):
    """رد السكرتير في محادثة الويب."""

    reply: str
    model_used: str
    latency_ms: int


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


@router.get("/v1/web/models")
async def get_web_models() -> dict[str, Any]:
    """جلب إعدادات النماذج الحالية مع القوالب الجاهزة."""
    config = load_models_config()
    dumped = config.model_dump(exclude_none=True)

    for _, p_val in dumped.get("profiles", {}).items():
        for entry in p_val.get("chain", []):
            if "api_key" in entry and entry["api_key"]:
                raw = entry["api_key"]
                if len(raw) > 8:
                    entry["api_key_masked"] = raw[:4] + "••••" + raw[-4:]
                else:
                    entry["api_key_masked"] = "••••••••"
            else:
                entry["api_key_masked"] = ""

    presets = [
        {
            "id": "openrouter",
            "name": "OpenRouter (Claude 3.5 Sonnet / DeepSeek / GPT-4o)",
            "base_url": "https://openrouter.ai/api/v1",
            "reasoner_model": "anthropic/claude-3.5-sonnet",
            "fast_model": "anthropic/claude-3.5-haiku",
            "requires_key": True,
        },
        {
            "id": "openai",
            "name": "OpenAI الرسمي (GPT-4o)",
            "base_url": "https://api.openai.com/v1",
            "reasoner_model": "gpt-4o",
            "fast_model": "gpt-4o-mini",
            "requires_key": True,
        },
        {
            "id": "gemini",
            "name": "Google Gemini (عبر OpenAI-Compat)",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "reasoner_model": "gemini-1.5-pro",
            "fast_model": "gemini-1.5-flash",
            "requires_key": True,
        },
        {
            "id": "ollama",
            "name": "Ollama محلي (بدون إنترنت وبخصوصية 100%)",
            "base_url": "http://localhost:11434/v1",
            "reasoner_model": "qwen2.5:7b",
            "fast_model": "qwen2.5:3b",
            "requires_key": False,
        },
    ]

    return {
        "config": dumped,
        "presets": presets,
    }


@router.post("/v1/web/models")
async def update_web_models(
    req: UpdateModelsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """تحديث ملف models.yaml وتطبيق الإعدادات على السكرتير فوراً."""
    try:
        new_config = ModelsConfig.model_validate(
            {"profiles": req.profiles, "policy": req.policy}
        )
        save_models_config(new_config)

        from app.core.agent.loop import agent_runner

        agent_runner.client = LLMClient(config=new_config)

        await append_audit_log(
            session,
            actor="web_dashboard",
            event="llm_models_config_updated",
            details={
                "reasoner_models": [
                    e.model
                    for e in new_config.profiles.get("reasoner", ProfileConfig()).chain
                ],
                "fast_models": [
                    e.model
                    for e in new_config.profiles.get("fast", ProfileConfig()).chain
                ],
            },
        )
        await session.commit()
        return {
            "status": "ok",
            "message": "تم حفظ الإعدادات وتحديث نماذج السكرتير بنجاح!",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"فشل التحقق من الإعدادات: {e}",
        )


@router.post("/v1/web/models/test")
async def test_web_model(req: TestModelRequest) -> dict[str, Any]:
    """فحص استجابة وسرعة نموذج الذكاء الاصطناعي المحدد قبل الحفظ."""
    result = await test_model_connection(
        base_url=req.base_url,
        model=req.model,
        api_key=req.api_key,
        timeout_s=req.timeout_s,
    )
    return result


@router.post("/v1/web/chat", response_model=WebChatResponse)
async def web_chat(req: WebChatRequest) -> WebChatResponse:
    """إرسال رسالة مباشرة للسكرتير من لوحة التحكم لتجربة النموذج الفعلي."""
    msg = req.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="الرسالة فارغة")

    client = LLMClient()
    try:
        resp = await client.chat(
            profile="reasoner",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "أنت (سند)، السكرتير الشخصي الذكي للمستخدم. "
                        "تتحدث بلباقة وباللغة العربية الفصحى أو بلهجة سعودية مهذبة. "
                        "أنت تعمل من الخادم المنزلي للمستخدم لحفظ خصوصيته."
                    ),
                },
                {"role": "user", "content": msg},
            ],
        )
        return WebChatResponse(
            reply=resp.text,
            model_used=resp.model_used,
            latency_ms=resp.latency_ms,
        )
    except Exception as e:
        return WebChatResponse(
            reply=f"عذراً، حدث خطأ أثناء الاتصال بنموذج الذكاء الاصطناعي: {e}. يرجى التحقق من إعدادات النماذج ومفتاح API في تبويب (إعدادات النماذج).",
            model_used="none",
            latency_ms=0,
        )


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
