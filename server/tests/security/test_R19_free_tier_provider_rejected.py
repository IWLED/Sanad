"""اختبار أمني إلزامي للقاعدة R-19:

يُمنع استخدام الطبقات المجانية لمزودي الذكاء الاصطناعي لمعالجة بيانات المستخدم الشخصية.
"""

import pytest

from app.core.llm.client import LLMClient
from app.core.llm.profiles import ChainEntry, ModelsConfig, PolicyConfig, ProfileConfig


@pytest.mark.asyncio
async def test_R19_free_tier_provider_rejected() -> None:
    """التحقق من تجاوز ورفض أي مدخل مصنف كـ tier='free' لحماية الخصوصية."""
    config = ModelsConfig(
        profiles={
            "fast": ProfileConfig(
                chain=[
                    ChainEntry(
                        base_url="https://api.free-provider.com/v1",
                        model="free-model",
                        tier="free",
                    )
                ],
                cloud=True,
            )
        },
        policy=PolicyConfig(
            forbid_free_tier=True,
        ),
    )

    client = LLMClient(config=config)

    with pytest.raises(RuntimeError) as exc_info:
        await client.chat(
            profile="fast",
            messages=[{"role": "user", "content": "مرحبا"}],
        )

    assert "All LLM chain entries failed" in str(exc_info.value)
