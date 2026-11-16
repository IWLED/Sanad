"""اختبار التوافق الذاتي عند الإقلاع لمزودي الذكاء الاصطناعي (Section 10.1, Spike S5)."""

import asyncio
from typing import Any

from app.core.llm.client import LLMClient
from app.core.llm.profiles import load_models_config


async def run_llm_selftest() -> dict[str, Any]:
    """تشغيل فحوصات التوافق على النماذج المعرفة في models.yaml."""
    config = load_models_config()
    client = LLMClient(config=config)
    results: dict[str, Any] = {}

    print("=" * 60)
    print("🧪 بدء الاختبار الذاتي لنماذج الذكاء الاصطناعي (LLM Selftest - S5)")
    print("=" * 60)

    for profile_name, p_conf in config.profiles.items():
        if not p_conf.enabled or not p_conf.chain:
            continue

        print(f"\nفحص ملف التعريف: {profile_name} (سلسلة من {len(p_conf.chain)} مدخل)...")
        profile_results: list[dict[str, Any]] = []

        for entry in p_conf.chain:
            entry_status = {"model": entry.model, "url": entry.base_url, "ok": False}
            try:
                # 1. اختبار استجابة عربية أساسية
                resp = await client.chat(
                    profile=profile_name,
                    messages=[
                        {"role": "system", "content": "أنت مساعد ذكي يتحدث بالعربية."},
                        {"role": "user", "content": "قل 'مرحباً بك في سند' فقط."},
                    ],
                )
                entry_status["arabic_test"] = "مرحباً" in resp.text or "سند" in resp.text
                entry_status["latency_ms"] = resp.latency_ms
                entry_status["ok"] = True
                txt = resp.text.strip()
                print(f"  ✅ النموذج {entry.model}: نجح في {resp.latency_ms}ms ({txt})")
            except Exception as e:
                entry_status["error"] = f"{type(e).__name__}: {e}"
                print(f"  ❌ النموذج {entry.model}: فشل ({entry_status['error']})")

            profile_results.append(entry_status)

        results[profile_name] = profile_results

    print("\n" + "=" * 60)
    return results


def main() -> None:
    asyncio.run(run_llm_selftest())


if __name__ == "__main__":
    main()
