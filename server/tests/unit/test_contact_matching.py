"""اختبارات مطابقة جهات الاتصال والأرقام E.164
(Section 7.3 & shared/test-vectors/contact-matching.json)."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.contacts.matcher import format_phone_e164, match_contact


@dataclass
class DummyContact:
    name: str
    aliases: list[str]


def test_contact_matching_against_vectors() -> None:
    """التحقق من مطابقة الأرقام والأسماء والألقاب مع متجهات الاختبار الرسمية."""
    shared_dir = Path(__file__).resolve().parents[3] / "shared" / "test-vectors"
    vector_path = shared_dir / "contact-matching.json"
    with open(vector_path, encoding="utf-8") as f:
        data = json.load(f)

    for case in data["cases"]:
        if "input_phone" in case:
            phone = case["input_phone"]
            region = case.get("default_region", "SA")
            expected_e164 = case["expected_e164"]
            res = format_phone_e164(phone, region)
            assert res == expected_e164, f"Phone failed: got {res}, expected {expected_e164}"

        if "search_term" in case:
            term = case["search_term"]
            name = case["contact_display_name"]
            aliases = case["aliases"]
            expected_match = case["expected_match"]

            contact = DummyContact(name=name, aliases=aliases)
            match = match_contact(term, [contact])
            if expected_match:
                assert match is not None, f"Expected match for '{term}' in {name}"
                assert match.name == name
            else:
                assert match is None
