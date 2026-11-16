"""مطابقة جهات الاتصال والأرقام والألقاب
(Section 7.3 & shared/test-vectors/contact-matching.json)."""

from typing import Any

import phonenumbers

from app.core.text.normalize_ar import normalize_ar


def format_phone_e164(raw_phone: str, default_region: str = "SA") -> str | None:
    """تحويل وتطبيع رقم الهاتف إلى تنسيق E.164 الدولي القياسي."""
    if not raw_phone:
        return None

    try:
        parsed = phonenumbers.parse(raw_phone.strip(), default_region)
        if phonenumbers.is_possible_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass

    # إذا كان الرقم يبدأ بالفعل بـ + ويحوي أرقاماً فقط
    clean = raw_phone.replace(" ", "").replace("-", "").strip()
    if clean.startswith("+") and clean[1:].isdigit():
        return clean

    return None


def match_contact(search_term: str, contacts: list[Any]) -> Any | None:
    """مطابقة جهة الاتصال بالاسم أو الألقاب مع منع التخمين عند الالتباس (Section 7.3)."""
    norm_query = normalize_ar(search_term)
    if not norm_query:
        return None

    query_tokens = set(norm_query.split())

    exact_matches: list[Any] = []
    alias_matches: list[Any] = []
    partial_matches: list[Any] = []

    for contact in contacts:
        # استخراج الاسم المعروض والألقاب
        raw_val = (
            getattr(contact, "display_name", None)
            or getattr(contact, "raw_name", None)
            or getattr(contact, "name", "")
        )
        display_name: str = str(raw_val) if raw_val is not None else ""
        norm_val = getattr(contact, "normalized_name", None)
        norm_name: str = str(norm_val) if norm_val else normalize_ar(display_name)
        aliases = getattr(contact, "aliases", []) or []

        # 1. مطابقة تامة في الاسم أو الألقاب
        if norm_query == norm_name:
            exact_matches.append(contact)
            continue

        normalized_aliases = [normalize_ar(a) for a in aliases]
        if norm_query in normalized_aliases:
            alias_matches.append(contact)
            continue

        # 2. مطابقة بالرموز (Token set match)
        name_tokens = set(norm_name.split())
        if query_tokens.issubset(name_tokens) or name_tokens.issubset(query_tokens):
            partial_matches.append(contact)
            continue

        # فحص إذا كان أي لقب يطابق بالرموز
        for a in normalized_aliases:
            alias_tokens = set(a.split())
            if query_tokens.issubset(alias_tokens) or alias_tokens.issubset(query_tokens):
                alias_matches.append(contact)
                break

    # الأولوية للمطابقة التامة
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None  # حالة التباس (Ambiguity): لا تخمّن، دع الوكيل يسأل

    # ثم الألقاب
    if len(alias_matches) == 1:
        return alias_matches[0]
    if len(alias_matches) > 1:
        return None  # التباس

    # ثم المطابقة الجزئية
    if len(partial_matches) == 1:
        return partial_matches[0]

    return None
