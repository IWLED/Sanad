"""اختبار أمني إلزامي للقاعدة R-09:

حظر تخزين الأسرار (OTP، كلمات المرور، المفاتيح) في قاعدة البيانات إطلاقاً.
التحقق من كافة متجهات shared/test-vectors/redaction.json.
"""

import json
from pathlib import Path

from app.core.safety.redactor import classify_and_redact


def test_R09_secrets_never_stored_against_vectors() -> None:
    """التحقق من أن الـ Redactor يطابق تصنيفات متجهات الاختبار ويمنع تخزين نصوص الـ OTP."""
    vector_path = Path(__file__).resolve().parents[3] / "shared" / "test-vectors" / "redaction.json"
    with open(vector_path, encoding="utf-8") as f:
        data = json.load(f)

    for case in data["cases"]:
        inp = case["input"]
        expected_class = case["classification"]
        should_store = case["should_store_content"]
        note = case["note"]

        res = classify_and_redact(inp)

        assert res.classification == expected_class, (
            f"Failed class on {note}: got {res.classification}, expected {expected_class}"
        )
        assert res.should_store_content == should_store, (
            f"Failed should_store on {note}: got {res.should_store_content}"
        )

        if not should_store:
            # الأسرار الصريحة R-09: يجب ألا يُخزن النص الأصلي إطلاقاً
            assert res.redacted_text == ""
            assert res.is_otp is True
            if "expected_summary" in case:
                assert res.summary == case["expected_summary"]

        if "redacted_contains" in case:
            for item in case["redacted_contains"]:
                assert item in res.redacted_text, (
                    f"Expected '{item}' in redacted text for {note}: {res.redacted_text}"
                )
