"""مرشّح السجلات وحماية الخصوصية الإلزامي (القاعدة الأمنية R-07).

يمنع تسجيل نصوص الرسائل أو أرقام الهواتف أو أسماء جهات الاتصال أو الإيميلات في أي سجل.
"""

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

# الحقول المحظورة تماماً من الظهور في السجلات بموجب القاعدة R-07
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "content",
        "text",
        "message",
        "raw_body",
        "sender_name",
        "recipient_name",
        "phone",
        "phone_number",
        "email",
        "caller_id",
        "contact_name",
        "draft_text",
        "edited_text",
    }
)


def sanitize_log_event(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """معالج structlog إلزامي يفحص جميع مفاتيح السجل ويحذف/يحجب أي حقول حساسة."""
    keys_to_clean = list(event_dict.keys())

    for key in keys_to_clean:
        value = event_dict[key]
        k_lower = key.lower()
        if any(f_key in k_lower for f_key in FORBIDDEN_KEYS):
            del event_dict[key]
            if isinstance(value, str):
                event_dict[f"{key}_len"] = len(value)
            else:
                event_dict[f"{key}_redacted"] = "[REDACTED_BY_R07]"
        elif isinstance(value, dict):
            event_dict[key] = sanitize_dict(value)
        elif isinstance(value, list):
            event_dict[key] = [
                sanitize_dict(item) if isinstance(item, dict) else item for item in value
            ]

    return event_dict


def sanitize_dict(d: dict[str, Any]) -> dict[str, Any]:
    """تعقيم القواميس المتداخلة."""
    res: dict[str, Any] = {}
    for k, v in d.items():
        k_lower = k.lower()
        if any(f_key in k_lower for f_key in FORBIDDEN_KEYS):
            if isinstance(v, str):
                res[f"{k}_len"] = len(v)
            else:
                res[f"{k}_redacted"] = "[REDACTED_BY_R07]"
        elif isinstance(v, dict):
            res[k] = sanitize_dict(v)
        else:
            res[k] = v
    return res


def configure_logging(log_level: str = "INFO") -> None:
    """تهيئة نظام structlog مع المرشّح الأمني R-07."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            sanitize_log_event,  # R-07 Filter
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
