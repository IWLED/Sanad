"""عميل الذكاء الاصطناعي الموحد والمتوافق مع OpenAI.

يفرض بوابات الأمان R-08 و R-19 وميزانية R-18.
"""

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.budget import check_budget_available
from app.core.llm.profiles import ChainEntry, ModelsConfig, load_models_config
from app.core.safety.logging_filter import logger
from app.db.models import LLMUsage


class SecurityPolicyViolationError(Exception):
    """خطأ انتهاك السياسة الأمنية (مثل إرسال بيانات حساسة لسحابة LLM)."""

    pass


class LLMToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class LLMResponse(BaseModel):
    text: str
    tool_calls: list[LLMToolCall] = []
    model_used: str
    profile: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class LLMClient:
    """العميل الرئيسي للنماذج الذكية مع سلسلة البدائل وبوابات الحساسية."""

    def __init__(self, config: ModelsConfig | None = None) -> None:
        self.config = config or load_models_config()

    def get_api_key(self, entry: ChainEntry) -> str:
        """استخراج مفتاح API من الإدخال المباشر أو أسرار Docker أو متغيرات البيئة."""
        if entry.api_key:
            return entry.api_key.strip()
        if not entry.api_key_env:
            return "no-key-required"

        # 1. البحث في Docker Secrets (/run/secrets/<api_key_env>)
        secret_path = Path(f"/run/secrets/{entry.api_key_env.lower()}")
        if secret_path.is_file():
            val = secret_path.read_text(encoding="utf-8").strip()
            if val:
                return val

        # 2. البحث في المتغيرات البيئية
        env_val = os.environ.get(entry.api_key_env, "").strip()
        if env_val:
            return env_val

        # 3. إذا كان الرابط محلياً (Ollama/vLLM)
        if (
            "localhost" in entry.base_url
            or "127.0.0.1" in entry.base_url
            or "192.168." in entry.base_url
        ):
            return "local-no-key"

        return "dummy-key"

    async def chat(
        self,
        profile: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        sensitivity_max: str = "normal",
        session: AsyncSession | None = None,
    ) -> LLMResponse:
        """إرسال طلب محادثة للنموذج مع التحقق من الحساسية والميزانية وتفعيل سلسلة البدائل."""
        if profile not in self.config.profiles:
            raise ValueError(f"Unknown LLM profile: {profile}")

        profile_config = self.config.profiles[profile]
        if not profile_config.chain:
            raise ValueError(f"Profile {profile} has no configured chain entries")

        # 1. التحقق من ميزانية التوكنات اليومية إن توفرت جلسة قاعدة البيانات (R-18)
        if session:
            budget_ok, remaining = await check_budget_available(
                session, self.config.policy.daily_token_budget
            )
            if not budget_ok:
                raise ValueError("Daily LLM token budget exceeded (R-18)")

        errors: list[str] = []

        # 2. المرور عبر سلسلة البدائل (Fallback Chain)
        for entry in profile_config.chain:
            # 3. بوابة الحساسية R-08: منع إرسال محتوى sensitive للسحابة
            if (
                sensitivity_max == "sensitive"
                and profile_config.cloud
                and not self.config.policy.allow_cloud_for_sensitive
            ):
                raise SecurityPolicyViolationError(
                    "R-08: Cloud LLM forbidden for sensitive content"
                )

            # 4. بوابة R-19: منع الطبقات المجانية
            if self.config.policy.forbid_free_tier and entry.tier.lower() == "free":
                logger.warning(
                    "skipping_free_tier_entry_by_r19",
                    profile=profile,
                    model=entry.model,
                )
                continue

            api_key = self.get_api_key(entry)
            client = AsyncOpenAI(
                base_url=entry.base_url,
                api_key=api_key,
                timeout=entry.timeout_s,
            )

            t0 = time.time()
            try:
                kwargs: dict[str, Any] = {
                    "model": entry.model,
                    "messages": messages,
                }
                if tools and profile_config.tools:
                    kwargs["tools"] = tools
                if response_format:
                    kwargs["response_format"] = response_format

                resp = await client.chat.completions.create(**kwargs)
                latency_ms = int((time.time() - t0) * 1000)

                choice = resp.choices[0]
                text_content = choice.message.content or ""

                tool_calls: list[LLMToolCall] = []
                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        tool_calls.append(
                            LLMToolCall(
                                id=tc.id,
                                name=tc.function.name,
                                arguments=tc.function.arguments,
                            )
                        )

                tokens_in = resp.usage.prompt_tokens if resp.usage else 0
                tokens_out = resp.usage.completion_tokens if resp.usage else 0

                # تسجيل الاستهلاك في llm_usage بدون تسجيل محتوى (R-07)
                if session:
                    usage_entry = LLMUsage(
                        ts=datetime.now(UTC).isoformat(),
                        purpose=profile,
                        profile=profile,
                        model=entry.model,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        latency_ms=latency_ms,
                        sensitivity_max=sensitivity_max,
                        ok=1,
                    )
                    session.add(usage_entry)
                    await session.commit()

                return LLMResponse(
                    text=text_content,
                    tool_calls=tool_calls,
                    model_used=entry.model,
                    profile=profile,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                )

            except Exception as e:
                latency_ms = int((time.time() - t0) * 1000)
                err_msg = f"{type(e).__name__}: {e}"
                errors.append(f"Entry {entry.model} failed: {err_msg}")
                logger.error(
                    "llm_chain_entry_failed",
                    profile=profile,
                    model=entry.model,
                    error=err_msg,
                )

                if session:
                    usage_entry = LLMUsage(
                        ts=datetime.now(UTC).isoformat(),
                        purpose=profile,
                        profile=profile,
                        model=entry.model,
                        tokens_in=0,
                        tokens_out=0,
                        latency_ms=latency_ms,
                        sensitivity_max=sensitivity_max,
                        ok=0,
                        error=err_msg[:255],
                    )
                    session.add(usage_entry)
                    await session.commit()

        raise RuntimeError(
            f"All LLM chain entries failed for profile '{profile}': {'; '.join(errors)}"
        )


async def test_model_connection(
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_s: int = 15,
) -> dict[str, Any]:
    """اختبار توافق واستجابة نموذج ذكاء اصطناعي محدد وفحص سرعته وجودة العربية."""
    effective_key = (api_key or "").strip() or "dummy-key"
    client = AsyncOpenAI(
        base_url=base_url.rstrip("/"),
        api_key=effective_key,
        timeout=float(timeout_s),
    )
    start_t = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "أنت السكرتير الشخصي الذكي (سند). أجب باقتضاب شديد."},
                {"role": "user", "content": "مرحباً سند، هل أنت متصل وجاهز للعمل؟"},
            ],
            max_tokens=60,
        )
        latency_ms = int((time.perf_counter() - start_t) * 1000)
        content = resp.choices[0].message.content or ""
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "sample_response": content.strip(),
            "model_reported": resp.model or model,
        }
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_t) * 1000)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "error": f"{type(e).__name__}: {e}",
        }
