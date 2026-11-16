"""وحدة تحويل الصوت إلى نص (STT Provider) (Section 11.4)."""

import io
import os
from typing import Any

import httpx
import yaml

from app.config import settings
from app.core.safety.logging_filter import logger


class STTProvider:
    """مزود تحويل الصوت إلى نص عبر واجهات متوافقة مع Whisper / OpenAI."""

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path or settings.llm_profiles_file
        self.base_url = "http://192.168.100.28:20128/v1"
        self.model = "whisper-1"
        self.api_key = ""
        self._load_config()

    def _load_config(self) -> None:
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            stt_conf = data.get("profiles", {}).get("stt", {})
            chain = stt_conf.get("chain", [])
            if chain:
                entry = chain[0]
                self.base_url = entry.get("base_url", self.base_url).rstrip("/")
                self.model = entry.get("model", self.model)
                key_env = entry.get("api_key_env", "")
                self.api_key = os.environ.get(key_env, "")
        except Exception as e:
            logger.warning("stt_config_load_failed", error=str(e))

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice.m4a",
        lang_hint: str = "ar",
    ) -> dict[str, Any]:
        """تحويل التسجيل الصوتي إلى نص وتفريغه.

        الصوت لا يُحفظ نهائياً بعد انتهاء الاستدعاء (Section 11.4).
        """
        if not audio_bytes:
            return {"text": "", "duration": 0.0, "language": lang_hint}

        url = f"{self.base_url}/audio/transcriptions"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {
            "file": (filename, io.BytesIO(audio_bytes), "application/octet-stream"),
        }
        data = {
            "model": self.model,
            "language": lang_hint,
            "response_format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, data=data, files=files)
                if resp.status_code == 200:
                    res_json = resp.json()
                    text = res_json.get("text", "").strip()
                    logger.info(
                        "audio_transcription_success",
                        audio_bytes_len=len(audio_bytes),
                        model=self.model,
                    )
                    return {
                        "text": text,
                        "duration": res_json.get("duration"),
                        "language": lang_hint,
                    }
                else:
                    logger.error(
                        "audio_transcription_http_error",
                        status_code=resp.status_code,
                        model=self.model,
                    )
                    raise RuntimeError(f"STT upstream error: {resp.status_code}")
        except Exception as e:
            logger.error("audio_transcription_failed", error=str(e), model=self.model)
            raise


stt_provider = STTProvider()
