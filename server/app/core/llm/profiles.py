"""نماذج إعدادات مزودي وملفات تعريف الذكاء الاصطناعي (Section 10.1)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.config import settings


class ChainEntry(BaseModel):
    """مدخل في سلسلة النماذج والبدائل."""

    base_url: str = Field(..., description="عنوان نقطة النهاية المتوافقة مع OpenAI")
    model: str = Field(..., description="معرف النموذج لدى المزود")
    api_key_env: str = Field(default="", description="اسم متغير البيئة لمفتاح API")
    api_key: str | None = Field(default=None, description="مفتاح API المباشر إن وُجد")
    timeout_s: int = Field(default=60, description="المهلة القصوى بالثواني")
    tier: str = Field(default="paid", description="تصنيف الحساب paid | free (R-19)")


class ProfileConfig(BaseModel):
    """ملف تعريف استخدام النموذج (reasoner, fast, sensitive_local, stt)."""

    chain: list[ChainEntry] = Field(default_factory=list)
    max_context_tokens: int = Field(default=128000)
    tools: bool = Field(default=False)
    cloud: bool = Field(default=True)
    enabled: bool = Field(default=True)
    provider: str | None = Field(default=None)


class PolicyConfig(BaseModel):
    """السياسات الأمنية للنماذج."""

    allow_cloud_for_sensitive: bool = Field(default=False)  # R-08
    forbid_free_tier: bool = Field(default=True)  # R-19
    daily_token_budget: int = Field(default=2000000)  # R-18


class ModelsConfig(BaseModel):
    """الهيكل الكامل لملف models.yaml."""

    profiles: dict[str, ProfileConfig]
    policy: PolicyConfig = Field(default_factory=PolicyConfig)


def load_models_config(config_path: Path | str | None = None) -> ModelsConfig:
    """قراءة وتحليل ملف config/models.yaml."""
    path = Path(config_path or settings.llm_profiles_file)
    if not path.is_file():
        # استخدام إعداد افتراضي إن لم يوجد الملف
        return ModelsConfig(
            profiles={
                "reasoner": ProfileConfig(
                    chain=[
                        ChainEntry(
                            base_url="http://192.168.100.28:20128/v1",
                            model="gpt-4o",
                            api_key_env="LLM_KEY_A",
                        )
                    ],
                    tools=True,
                    cloud=True,
                ),
                "fast": ProfileConfig(
                    chain=[
                        ChainEntry(
                            base_url="http://192.168.100.28:20128/v1",
                            model="gpt-4o-mini",
                            api_key_env="LLM_KEY_A",
                        )
                    ],
                    tools=False,
                    cloud=True,
                ),
            },
            policy=PolicyConfig(
                allow_cloud_for_sensitive=settings.allow_cloud_for_sensitive,
                daily_token_budget=settings.llm_daily_token_budget,
            ),
        )

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ModelsConfig.model_validate(data)


def save_models_config(config: ModelsConfig, config_path: Path | str | None = None) -> None:
    """حفظ وتحديث ملف config/models.yaml بتنسيق سليم."""
    path = Path(config_path or settings.llm_profiles_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(exclude_none=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
