from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


JSON_OUTPUT_CONTRACT = """## 运行时 JSON 输出契约（系统追加，不属于核心资产原文）
仅输出合法 JSON，不要 Markdown 代码块、解释或前后缀。结构必须为：
{
  "schema_version": "1.0",
  "images": [
    {
      "route_symbol": "#@",
      "image_type": "图片类型",
      "picture_requirement": "完整画面需求",
      "copywriting_requirements": "完整文案需求"
    }
  ]
}
一期所有图片的 route_symbol 必须为 #@。不得省略任何字段。
每条 picture_requirement 必须显式包含本次运行时变量 ${aspect_ratio} 的实际值。"""


class ImagePromptItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    route_symbol: Literal["#@"]
    image_type: str = Field(min_length=1, max_length=120)
    picture_requirement: str = Field(min_length=1)
    copywriting_requirements: str = Field(min_length=1)

    @field_validator("image_type", "picture_requirement", "copywriting_requirements")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value


class MetaPromptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    images: list[ImagePromptItem] = Field(min_length=1, max_length=12)


class ProductFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"]
    product_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    visible_features: list[str] = Field(default_factory=list, max_length=30)
    materials: list[str] = Field(default_factory=list, max_length=20)
    colors: list[str] = Field(default_factory=list, max_length=20)
    sku_count: int = Field(ge=1, le=100)
    accessories: list[str] = Field(default_factory=list, max_length=30)
    labels_text: list[str] = Field(default_factory=list, max_length=30)
    uncertain: list[str] = Field(default_factory=list, max_length=30)


class ContentSafetyReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    passed: bool
    categories: list[str] = Field(default_factory=list, max_length=20)
    issues: list[str] = Field(default_factory=list, max_length=20)


def append_runtime_contract(source: str, expected_count: int) -> str:
    return f"{source.rstrip()}\n\n---\n\n{JSON_OUTPUT_CONTRACT}\n必须恰好输出 {expected_count} 项。\n"


def render_prompt_variables(source: str, values: dict[str, Any]) -> str:
    lines = ["## 运行时变量（本次任务）", "以下值优先于核心资产后文示例中的同名变量："]
    for key in ("platform", "market", "language", "input_language", "product_info", "brand_style"):
        if key not in values:
            raise ValueError(f"缺少 Prompt 变量：{key}")
        rendered = json.dumps(values[key], ensure_ascii=False) if isinstance(values[key], (dict, list)) else values[key]
        lines.append(f"${{{key}}}={rendered}")
    for key in ("product_facts", "aspect_ratio", "image_plan", "model_preference"):
        if key in values:
            rendered = json.dumps(values[key], ensure_ascii=False) if isinstance(values[key], (dict, list)) else values[key]
            lines.append(f"${{{key}}}={rendered}")
    return "\n".join(lines) + f"\n\n---\n\n{source}"


def parse_meta_prompt_plan(raw: str | dict[str, Any] | MetaPromptPlan, expected_count: int) -> MetaPromptPlan:
    if isinstance(raw, MetaPromptPlan):
        plan = raw
    elif isinstance(raw, str):
        plan = MetaPromptPlan.model_validate_json(raw)
    else:
        plan = MetaPromptPlan.model_validate(raw)
    if len(plan.images) != expected_count:
        raise ValueError(f"图片数量不符：期望 {expected_count}，实际 {len(plan.images)}")
    return plan


def plan_to_json(plan: MetaPromptPlan) -> str:
    return json.dumps(plan.model_dump(), ensure_ascii=False, indent=2)


def inject_runtime_aspect_ratio(plan: MetaPromptPlan, context: dict[str, Any]) -> MetaPromptPlan:
    ratio = str(context.get("aspect_ratio") or "").strip()
    if not ratio:
        return plan
    updated_images: list[ImagePromptItem] = []
    changed = False
    for item in plan.images:
        picture = item.picture_requirement.strip()
        if ratio in picture:
            updated_images.append(item)
            continue
        updated_images.append(item.model_copy(update={"picture_requirement": f"{ratio} 画面比例，{picture}"}))
        changed = True
    if not changed:
        return plan
    return plan.model_copy(update={"images": updated_images})


def parse_product_facts(raw: str | dict[str, Any] | ProductFacts) -> ProductFacts:
    if isinstance(raw, ProductFacts):
        return raw
    if isinstance(raw, str):
        return ProductFacts.model_validate_json(raw)
    return ProductFacts.model_validate(raw)


def parse_content_safety_review(raw: str | dict[str, Any] | ContentSafetyReview) -> ContentSafetyReview:
    if isinstance(raw, ContentSafetyReview):
        return raw
    if isinstance(raw, str):
        return ContentSafetyReview.model_validate_json(raw)
    return ContentSafetyReview.model_validate(raw)


def validate_meta_prompt_semantics(plan: MetaPromptPlan, context: dict[str, Any]) -> list[str]:
    """Turn the core Meta Prompt's highest-risk prose rules into deterministic gates."""
    errors: list[str] = []
    ratio = str(context.get("aspect_ratio") or "")
    no_text = str(context.get("language") or "").lower() in {"无文字", "无文案", "no text overlay"}
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(plan.images, start=1):
        picture = item.picture_requirement
        copy = item.copywriting_requirements
        if ratio and ratio not in picture:
            errors.append(f"第 {index} 张未显式声明画面比例 {ratio}")
        if not ({"产品", "商品"} & set(_tokenize_cn(picture))) or "保持" not in picture:
            errors.append(f"第 {index} 张缺少商品锁定要求")
        if no_text and not any(token in copy.lower() for token in ("no text overlay", "无文字", "无文案")):
            errors.append(f"第 {index} 张未遵守无文字策略")
        signature = (item.image_type.strip().lower(), " ".join(picture.lower().split()))
        if signature in seen:
            errors.append(f"第 {index} 张与前序图片职责和画面要求重复")
        seen.add(signature)

    platform = str(context.get("platform") or "").lower()
    if platform in {"amazon", "亚马逊"} and plan.images:
        first = plan.images[0].picture_requirement.lower()
        if not any(token in first for token in ("白底", "白色背景", "纯白", "white background")):
            errors.append("Amazon 首图必须明确纯白背景")

    if context.get("mode") == "custom":
        expected = context.get("custom_counts") or {}
        label_map = {
            "white_background": ("白底图", ("白底", "纯白")),
            "scene": ("场景图", ("场景", "生活方式", "人物")),
            "selling_point": ("卖点图", ("卖点", "功能", "细节", "材质")),
            "other": ("其他图", ("其他", "对比", "尺寸", "规格", "包装", "配件", "品牌")),
        }
        for key, (label, tokens) in label_map.items():
            actual = sum(any(token in item.image_type for token in tokens) for item in plan.images)
            target = int(expected.get(key, 0))
            if actual != target:
                errors.append(f"自定义数量不符：{label}要求 {target} 张，实际 {actual} 张")
    return errors


def _tokenize_cn(value: str) -> list[str]:
    # The validator only needs to detect explicit product-lock nouns, not perform NLP.
    return [token for token in ("产品", "商品") if token in value]
