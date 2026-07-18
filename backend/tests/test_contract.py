import pytest
from pydantic import ValidationError

from backend.app.services.prompt_contract import (
    JSON_OUTPUT_CONTRACT,
    ImagePromptItem,
    MetaPromptPlan,
    append_runtime_contract,
    parse_meta_prompt_plan,
    render_prompt_variables,
)


def test_meta_prompt_contract_accepts_only_hash_at_and_exact_count() -> None:
    raw = {
        "schema_version": "1.0",
        "images": [
            {
                "route_symbol": "#@",
                "image_type": f"场景图 {index + 1}",
                "picture_requirement": "真实商品场景，保持产品外观不变",
                "copywriting_requirements": "No Text Overlay",
            }
            for index in range(7)
        ],
    }

    plan = parse_meta_prompt_plan(raw, expected_count=7)

    assert plan.schema_version == "1.0"
    assert len(plan.images) == 7
    assert all(item.route_symbol == "#@" for item in plan.images)


def test_meta_prompt_contract_rejects_unknown_symbol_and_count() -> None:
    with pytest.raises(ValidationError):
        ImagePromptItem(
            route_symbol="#V",
            image_type="视频",
            picture_requirement="动效",
            copywriting_requirements="无",
        )

    with pytest.raises(ValueError, match="数量"):
        parse_meta_prompt_plan(
            MetaPromptPlan(
                schema_version="1.0",
                images=[
                    ImagePromptItem(
                        route_symbol="#@",
                        image_type="主图",
                        picture_requirement="白底",
                        copywriting_requirements="无文字",
                    )
                ],
            ),
            expected_count=7,
        )


def test_runtime_contract_is_appended_without_mutating_source() -> None:
    original = "核心 Meta Prompt 原文\n"

    combined = append_runtime_contract(original, expected_count=8)

    assert original == "核心 Meta Prompt 原文\n"
    assert combined.startswith(original)
    assert JSON_OUTPUT_CONTRACT in combined
    assert "必须恰好输出 8 项" in combined


def test_prompt_variables_are_bound_before_live_llm_call() -> None:
    source = "平台=${platform}; 市场=${market}; 语言=${language}; 商品=${product_info}; 风格=${brand_style}"
    rendered = render_prompt_variables(
        source,
        {
            "platform": "Shopee",
            "market": "东南亚",
            "language": "English",
            "input_language": "中文",
            "product_info": "双层保温",
            "brand_style": "清爽蓝白",
            "image_plan": "白底图1张、场景图2张、卖点图2张、其他图2张",
            "model_preference": "商品保持优先",
        },
    )

    assert source in rendered
    assert "${platform}=Shopee" in rendered
    assert "${market}=东南亚" in rendered
    assert "${product_info}=双层保温" in rendered
    assert "${image_plan}=白底图1张、场景图2张、卖点图2张、其他图2张" in rendered
    assert rendered.index("${platform}=Shopee") < rendered.index(source)
