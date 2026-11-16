"""نظام تصنيف الحساسية والحجب وحماية الأسرار (Section 9.7 & R-08, R-09)."""

import re
from dataclasses import dataclass

# 1. أنماط رموز التحقق والـ OTP (Secret - حظر التخزين التام R-09)
OTP_ARABIC_PATTERN = re.compile(
    r"(?:رمز\s+(?:التحقق|التأكيد|التفعيل)|كود\s+(?:التحقق|التفعيل)|كلمة\s+المرور\s+المؤقتة).*?\b([0-9]{4,8})\b",
    re.IGNORECASE | re.DOTALL,
)
OTP_ENGLISH_PATTERN = re.compile(
    r"(?:verification\s+code|security\s+code|one[- ]time\s+password|otp).*?\b([0-9]{4,8})\b",
    re.IGNORECASE | re.DOTALL,
)

# 2. أنماط البيانات الحساسة (Sensitive - حجب جزئي مع السماح بالتخزين)
SAUDI_IBAN_PATTERN = re.compile(r"\b(SA\d{2})[0-9A-Z]{16}([0-9A-Z]{4})\b")
NATIONAL_ID_PATTERN = re.compile(r"\b([12]\d{5})(\d{4})\b")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}(\d{4})\b")
BANK_TRANSACTION_PATTERN = re.compile(
    r"(?:تم\s+خصم|تم\s+إيداع|سحب\s+نقدي|عملية\s+شراء|رصيدك|الرصيد\s+المتبقي|مدى).*?(\d+(?:\.\d+)?\s*(?:ر\.س|ريال))",
    re.IGNORECASE,
)


@dataclass
class RedactionResult:
    """نتيجة فحص وتصنيف الحساسية."""

    classification: str  # "secret" | "sensitive" | "normal"
    should_store_content: bool  # False للـ OTP والأسرار الصريحة R-09
    redacted_text: str
    summary: str
    is_otp: bool


def classify_and_redact(text: str) -> RedactionResult:
    """فحص وتصنيف وحجب البيانات الحساسة والأسرار في النصوص الواردة."""
    if not text:
        return RedactionResult(
            classification="normal",
            should_store_content=True,
            redacted_text="",
            summary="",
            is_otp=False,
        )

    # 1. فحص رموز التحقق OTP (Secret - حظر الحفظ التام R-09)
    if OTP_ARABIC_PATTERN.search(text):
        return RedactionResult(
            classification="secret",
            should_store_content=False,
            redacted_text="",
            summary="رمز تحقق OTP",
            is_otp=True,
        )

    if OTP_ENGLISH_PATTERN.search(text):
        return RedactionResult(
            classification="secret",
            should_store_content=False,
            redacted_text="",
            summary="OTP verification code",
            is_otp=True,
        )

    # 2. فحص البيانات الحساسة (Sensitive)
    is_sensitive = False
    redacted = text

    # حجب الآيبان (إبقاء آخر 4 خانات)
    if SAUDI_IBAN_PATTERN.search(redacted):
        is_sensitive = True
        redacted = SAUDI_IBAN_PATTERN.sub(r"••••\2", redacted)

    # حجب الهوية الوطنية والإقامة (إبقاء آخر 4 خانات)
    if NATIONAL_ID_PATTERN.search(redacted):
        is_sensitive = True
        redacted = NATIONAL_ID_PATTERN.sub(r"••••\2", redacted)

    # حجب أرقام البطاقات الائتمانية
    if CREDIT_CARD_PATTERN.search(redacted):
        is_sensitive = True
        redacted = CREDIT_CARD_PATTERN.sub(r"••••\1", redacted)

    # حجب تفاصيل المبالغ والعمليات البنكية
    if "مدى" in text or "خصم" in text or "رصيدك" in text or BANK_TRANSACTION_PATTERN.search(text):
        is_sensitive = True
        # إذا كانت رسالة بنكية تحتوي رصيداً أو مبالغ
        redacted = re.sub(
            r"(\d+(?:\.\d+)?\s*(?:ر\.س|ريال))",
            "[مخفي]",
            redacted,
        )
        if "[مخفي]" not in redacted and ("مدى" in text or "خصم" in text):
            redacted = f"{redacted} [مخفي]"

    if is_sensitive:
        return RedactionResult(
            classification="sensitive",
            should_store_content=True,
            redacted_text=redacted,
            summary="بيانات حساسة محجوبة جزئياً",
            is_otp=False,
        )

    return RedactionResult(
        classification="normal",
        should_store_content=True,
        redacted_text=text,
        summary="",
        is_otp=False,
    )
