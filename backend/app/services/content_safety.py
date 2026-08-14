from __future__ import annotations

import json

from backend.app.models import Provider, PromptVersion
from backend.app.security import ApiKeyCipher
from backend.app.services.prompt_contract import ContentSafetyReview, parse_content_safety_review
from backend.app.services.providers import ProviderClient


TEXT_SAFETY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sexual": ("色情", "成人内容", "裸露", "淫秽", "低俗"),
    "gambling": ("赌博", "博彩", "赌场", "下注", "赌球"),
    "drugs": ("毒品", "冰毒", "大麻", "海洛因", "可卡因", "摇头丸"),
    "politics": (
        "政治领导人",
        "政治敏感",
        "习近平",
        "毛泽东",
        "邓小平",
        "江泽民",
        "胡锦涛",
        "拜登",
        "特朗普",
        "普京",
        "泽连斯基",
    ),
}


class ContentSafetyBlocked(Exception):
    def __init__(self, message: str, review: ContentSafetyReview | None = None) -> None:
        super().__init__(message)
        self.review = review


def content_safety_message(review: ContentSafetyReview, prefix: str = "内容安全拦截") -> str:
    reasons = review.issues or review.categories or ["命中安全规则"]
    return f"{prefix}：" + "；".join(reasons)


def run_local_text_safety_review(text: str) -> ContentSafetyReview:
    categories: list[str] = []
    issues: list[str] = []
    normalized = text.lower()
    for category, keywords in TEXT_SAFETY_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword.lower() in normalized]
        if hits:
            categories.append(category)
            issues.append(f"文本包含{category}风险词：{', '.join(hits[:3])}")
    return ContentSafetyReview(
        schema_version="1.0",
        passed=not issues,
        categories=categories,
        issues=issues,
    )


async def run_content_safety_review(
    client: ProviderClient,
    default_provider: Provider,
    fallback_provider: Provider,
    cipher: ApiKeyCipher,
    prompt_version: PromptVersion,
    *,
    subject: str,
    text: str = "",
    image_paths: list[str] | None = None,
) -> tuple[ContentSafetyReview, Provider]:
    payload = {
        "subject": subject,
        "text": text,
        "requirements": "只判断黄赌毒、政治内容、政治领导人、暴力极端、仇恨和违法犯罪安全风险。",
    }
    user_prompt = json.dumps(payload, ensure_ascii=False)
    providers: list[Provider] = []
    seen: set[str] = set()
    for provider in (default_provider, fallback_provider):
        if provider.code in seen:
            continue
        seen.add(provider.code)
        providers.append(provider)
    errors: list[str] = []
    for provider in providers:
        try:
            raw = await client.call_llm(
                provider,
                cipher.decrypt(provider.encrypted_api_key or ""),
                prompt_version.content,
                user_prompt,
                image_paths=image_paths,
                response_format="json_object",
            )
            return parse_content_safety_review(raw), provider
        except Exception as exc:
            errors.append(f"{provider.code}: {exc}")
    raise RuntimeError("内容安全审计失败：" + "；".join(errors))


def ensure_content_safe(review: ContentSafetyReview, prefix: str = "内容安全拦截") -> None:
    if not review.passed:
        raise ContentSafetyBlocked(content_safety_message(review, prefix), review)
