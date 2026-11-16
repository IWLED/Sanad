"""نقطة نهاية تفريغ وتحويل الصوت إلى نص (Section 11.4 & Section 8.2)."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_authenticated_device_id
from app.core.audio.stt import stt_provider
from app.core.safety.logging_filter import logger

router = APIRouter(prefix="/v1/audio", tags=["audio"])

MAX_AUDIO_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB (~120 ثانية)


@router.post("/transcribe", status_code=status.HTTP_200_OK)
async def transcribe_audio(
    file: UploadFile = File(...),
    lang: str = Form("ar"),
    device_id: str = Depends(get_authenticated_device_id),
) -> dict[str, str | float | None]:
    """استقبال ملف صوتي وتفريغه إلى نص عربي/إنجليزي دون تخزينه (Section 11.4)."""
    try:
        content = await file.read()
        if len(content) > MAX_AUDIO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="حجم الملف الصوتي يتجاوز الحد الأقصى المسموح (120 ثانية / 15 ميجابايت)",
            )

        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="الملف الصوتي فارغ",
            )

        filename = file.filename or "recording.m4a"
        result = await stt_provider.transcribe(
            audio_bytes=content,
            filename=filename,
            lang_hint=lang,
        )
        logger.info(
            "audio_transcription_completed",
            device_id=device_id,
            bytes=len(content),
        )
        return {
            "text": str(result.get("text", "")),
            "duration": result.get("duration"),
            "language": str(result.get("language", lang)),
        }
    finally:
        await file.close()
