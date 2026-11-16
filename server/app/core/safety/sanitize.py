"""تطهير وتغليف البيانات غير الموثوقة لمنع حقن الأوامر (Section 10.2)."""

import html
import re

# إزالة محارف Unicode Tag ومحارف التحكم وتجاوزات الاتجاه Bidi
CLEAN_CHARS_REGEX = re.compile(
    r"[\uE0000-\uE007F\u202A-\u202E\u2066-\u2069\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)


def sanitize_untrusted(text: str, max_chars: int = 4000) -> str:
    """تطهير النصوص الواردة من أطراف ثالثة وإزالة المحارف الخبيثة والاقتطاع للحد الأقصى."""
    if not text:
        return ""

    # 1. إزالة محارف التحكم ومحارف Tag المضللة
    cleaned = CLEAN_CHARS_REGEX.sub("", text)

    # 2. تحويل أي وسوم HTML لنص عادي
    cleaned = html.unescape(cleaned)

    # 3. الاقتطاع إذا تجاوز الحد الأقصى
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + " [مقتطع لزيادة الطول]"

    return cleaned


def wrap_untrusted(text: str, source: str, ref: str = "") -> str:
    """تغليف النص غير الموثوق داخل وسوم مميزة مع تهريب أي وسوم إغلاق احتيالية."""
    safe_text = sanitize_untrusted(text)
    # منع كسر الوسم عبر تهريب </untrusted>
    escaped_body = safe_text.replace("</untrusted>", "<\\/untrusted>")
    return f'<untrusted source="{source}" ref="{ref}">\n{escaped_body}\n</untrusted>'
