"""توليد المعاينة البرمجية لبطاقات الموافقة (R-04, Section 10.5).

تُبنى المعاينة برمجياً من الوسائط الفعلية وليس من مخرجات النموذج لتفادي التزييف.
"""

from typing import Any


def build_preview(
    title: str,
    draft_text: str,
    app_package: str = "app.secretary",
    recipient: dict[str, Any] | None = None,
    thread_context: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """بناء كائن المعاينة الصارم المعروض في بطاقة HitlCard."""
    return {
        "title": title,
        "app": app_package,
        "recipient": recipient or {"name": "غير محدد"},
        "thread_context": (thread_context or [])[:3],  # آخر 3 رسائل كحد أقصى للسياق
        "draft_text": draft_text,
        "warnings": warnings or [],
    }
