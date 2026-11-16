"""فحص تسريب البيانات ومنع كشف الأسرار في المسودات (DLP Scan - Section 10.2)."""

import re

# أنماط الأسرار الصريحة (API keys, Tokens, Private Keys)
SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "مفتاح OpenAI سري"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "مفتاح AWS سري"),
    (re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}"), "رمز JWT مضمن"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"), "مفتاح تشفير خاص"),
    (
        re.compile(r"\b(?:OTP|رمز التحقق|رمز التأكيد)\s*[:=]?\s*\d{4,8}\b", re.IGNORECASE),
        "رمز تحقق مؤقت OTP",
    ),
]

# أنماط البيانات الحساسة (IBAN, بطاقات, هوية)
SENSITIVE_PATTERNS = [
    (re.compile(r"\bSA\d{2}[0-9A-Z]{20}\b"), "رقم آيبان بنكي سعودي"),
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "رقم بطاقة دفع بنكية"),
    (re.compile(r"\b[12]\d{9}\b"), "رقم هوية وطنية أو إقامة"),
]


def dlp_scan(draft_text: str) -> tuple[bool, str, list[str]]:
    """فحص مسودة الرد أو الإجراء بحثاً عن أسرار أو بيانات حساسة.

    Returns:
        (is_safe, processed_text, warnings)
    """
    warnings: list[str] = []
    processed = draft_text

    # 1. الأسرار الصريحة: يتم حجبها فوراً لسلامة المستخدم
    for pattern, desc in SECRET_PATTERNS:
        if pattern.search(processed):
            warnings.append(f"تم اكتشاف وحجب سر أمني: {desc}")
            processed = pattern.sub("[تم الحجب بواسطة DLP]", processed)

    # 2. البيانات الحساسة: يتم إضافة تحذير للمستخدم في البطاقة
    for pattern, desc in SENSITIVE_PATTERNS:
        if pattern.search(processed):
            warnings.append(f"تنبيه: المسودة تحتوي على {desc}")

    is_safe = len(warnings) == 0 or all("تنبيه:" in w for w in warnings)
    return is_safe, processed, warnings
