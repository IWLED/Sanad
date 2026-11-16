"""إعدادات الخادم وقراءة التكوينات والبيئة والأسرار."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def read_secret(file_path: Path | str | None, default: str = "") -> str:
    """قراءة السر من الملف إن وُجد (Docker Secrets) وإلا إرجاع القيمة الافتراضية."""
    if not file_path:
        return default
    p = Path(file_path)
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return default


class Settings(BaseSettings):
    """إعدادات النظام العامة مع قراءة Docker Secrets ومسارات التخزين."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="production", alias="APP_ENV")
    timezone: str = Field(default="Asia/Riyadh", alias="TIMEZONE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # قاعدة البيانات والتخزين
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/secretary.db",
        alias="DATABASE_URL",
    )
    exports_dir: Path = Field(default=Path("/exports"), alias="EXPORTS_DIR")

    # مسارات ملفات الأسرار (Docker Secrets)
    jwt_signing_key_file: Path | None = Field(default=None, alias="JWT_SIGNING_KEY_FILE")
    enc_key_file: Path | None = Field(default=None, alias="ENC_KEY_FILE")
    pepper_file: Path | None = Field(default=None, alias="PEPPER_FILE")
    fcm_service_account_file: Path | None = Field(default=None, alias="FCM_SERVICE_ACCOUNT_FILE")
    fcm_project_id: str = Field(default="", alias="FCM_PROJECT_ID")

    # أسرار كقيم مباشرة للبيئات المحلية والاختبار
    jwt_signing_key: str = Field(default="", alias="JWT_SIGNING_KEY")
    enc_key: str = Field(default="", alias="ENC_KEY")
    pepper: str = Field(default="sanad_default_pepper_for_test", alias="PEPPER")

    # المصادقة
    access_token_ttl_min: int = Field(default=15, alias="ACCESS_TOKEN_TTL_MIN")
    pairing_code_ttl_min: int = Field(default=10, alias="PAIRING_CODE_TTL_MIN")
    cf_access_required: bool = Field(default=False, alias="CF_ACCESS_REQUIRED")

    # الاحتفاظ بالبيانات (R-21)
    retention_events_days: int = Field(default=30, alias="RETENTION_EVENTS_DAYS")
    retention_sensitive_days: int = Field(default=7, alias="RETENTION_SENSITIVE_DAYS")

    # LLM
    llm_profiles_file: Path = Field(
        default=Path("config/models.yaml"),
        alias="LLM_PROFILES_FILE",
    )
    allow_cloud_for_sensitive: bool = Field(default=False, alias="ALLOW_CLOUD_FOR_SENSITIVE")
    llm_daily_token_budget: int = Field(default=2_000_000, alias="LLM_DAILY_TOKEN_BUDGET")

    def get_jwt_signing_key(self) -> str:
        """جلب مفتاح توقيع JWT من السر أو الإعداد المباشر."""
        return read_secret(self.jwt_signing_key_file, self.jwt_signing_key)

    def get_pepper(self) -> str:
        """جلب ملح التجزئة لرموز التحديث."""
        return read_secret(self.pepper_file, self.pepper)

    def get_enc_key(self) -> str:
        """جلب مفتاح التشفير المتناظر."""
        return read_secret(self.enc_key_file, self.enc_key)


settings = Settings()
