"""اختبار أمني إلزامي للقاعدة R-08:

المحتوى sensitive لا يغادر الخادم نحو سحابة LLM ما لم يكن ALLOW_CLOUD_FOR_SENSITIVE=true صراحة.
يُمنع الاعتماد على النموذج لحماية نفسه، المنع يُفرض برمجياً في طبقة العميل.
"""

import pytest

from app.core.llm.client import LLMClient, SecurityPolicyViolationError
from app.core.llm.profiles import ChainEntry, ModelsConfig, PolicyConfig, ProfileConfig


def create_test_config(allow_cloud_for_sensitive: bool = False) -> ModelsConfig:
    return ModelsConfig(
        profiles={
            "reasoner": ProfileConfig(
                chain=[
                    ChainEntry(
                        base_url="https://api.openai.com/v1",
                        model="gpt-4o",
                        api_key_env="",
                    )
                ],
                cloud=True,  # سحابي
            ),
            "sensitive_local": ProfileConfig(
                chain=[
                    ChainEntry(
                        base_url="http://localhost:11434/v1",
                        model="qwen2.5:7b",
                        api_key_env="",
                    )
                ],
                cloud=False,  # محلي داخل الخادم
            ),
        },
        policy=PolicyConfig(
            allow_cloud_for_sensitive=allow_cloud_for_sensitive,
        ),
    )


@pytest.mark.asyncio
async def test_R08_sensitive_content_never_sent_to_cloud_llm() -> None:
    """التحقق من الرفض البرمجي الفوري لأي طلب يحمل محتوى sensitive نحو نموذج سحابي."""
    client = LLMClient(config=create_test_config(allow_cloud_for_sensitive=False))

    messages = [
        {"role": "user", "content": "هذا ملخص لرسالة بنكية تحوي رصيداً وحساباً"},
    ]

    # محاولة الإرسال لملف reasoner السحابي بمستوى حساسية sensitive
    with pytest.raises(SecurityPolicyViolationError) as exc_info:
        await client.chat(
            profile="reasoner",
            messages=messages,
            sensitivity_max="sensitive",
        )

    assert "R-08: Cloud LLM forbidden for sensitive content" in str(exc_info.value)
