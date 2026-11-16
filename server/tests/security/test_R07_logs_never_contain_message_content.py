"""اختبار أمني إلزامي للقاعدة R-07:

يُمنع تسجيل نص الرسائل أو أسماء جهات الاتصال أو أرقام الهواتف بمستوى INFO أو أدنى.
سجّل المعرّفات والأطوال والحالات فقط.
"""

import json

from app.core.safety.logging_filter import sanitize_log_event


def test_R07_logs_never_contain_message_content() -> None:
    """التحقق من حجب نصوص الرسائل والبيانات الشخصية الحساسة من السجلات."""
    sensitive_message = "السلام عليكم، هذا رمز التحقق السري 482930 لا تخبر أحداً"
    secret_phone = "+966501234567"
    secret_sender = "أبو فهد الخالدي"
    secret_email = "waleed@example.com"

    raw_event = {
        "event": "message_received",
        "event_id": "01JXYZ...",
        "content": sensitive_message,
        "text": sensitive_message,
        "sender_name": secret_sender,
        "phone": secret_phone,
        "email": secret_email,
        "metadata": {
            "draft_text": "مسودة رد خاصة",
            "caller_id": secret_phone,
            "status": "pending",
        },
    }

    sanitized = sanitize_log_event(None, "info", raw_event)
    sanitized_json = json.dumps(sanitized, ensure_ascii=False)

    # التحقق من خلو السجل تماماً من النصوص الحساسة
    assert sensitive_message not in sanitized_json
    assert secret_phone not in sanitized_json
    assert secret_sender not in sanitized_json
    assert secret_email not in sanitized_json
    assert "مسودة رد خاصة" not in sanitized_json

    # التحقق من أن ما ظهر هو أطوال النصوص أو علامات الحجب
    assert sanitized.get("content_len") == len(sensitive_message)
    assert sanitized.get("sender_name_len") == len(secret_sender)
    assert sanitized["metadata"].get("draft_text_len") == len("مسودة رد خاصة")
    assert sanitized["metadata"].get("status") == "pending"
