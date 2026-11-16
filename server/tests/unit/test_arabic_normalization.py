"""اختبارات التطبيع العربي المشترك مع متجهات الاختبار الرسمية (Section 7.3)."""

import json
from pathlib import Path

from app.core.text.normalize_ar import normalize_ar


def test_arabic_normalization_test_vectors() -> None:
    """التحقق من تطابق نتائج normalize_ar مع متجهات الاختبار الرسمية."""
    shared_dir = Path(__file__).resolve().parents[3] / "shared" / "test-vectors"
    vector_path = shared_dir / "arabic-normalization.json"
    with open(vector_path, encoding="utf-8") as f:
        data = json.load(f)

    for case in data["cases"]:
        inp = case["input"]
        exp = case["expected"]
        note = case["note"]
        res = normalize_ar(inp)
        assert res == exp, f"Failed case: {note} -> got '{res}', expected '{exp}'"
