from __future__ import annotations

import asyncio
import base64
import json

import httpx
from sqlalchemy import select

from backend.app.models import Prompt, Provider
from backend.app.services.prompt_contract import (
    ImagePromptItem,
    MetaPromptPlan,
    parse_product_facts,
    render_prompt_variables,
    validate_meta_prompt_semantics,
)
from backend.app.services.execution import validate_plan_with_one_replan
from backend.app.services.providers import ProviderClient
from backend.app.services.workflow_registry import default_workflow_json, validate_workflow_graph, workflow_preset_dicts


def _plan(*images: ImagePromptItem) -> MetaPromptPlan:
    return MetaPromptPlan(schema_version="1.0", images=list(images))


def test_runtime_variables_include_product_facts_ratio_and_generation_strategy() -> None:
    rendered = render_prompt_variables(
        "核心提示词",
        {
            "platform": "Amazon",
            "market": "美国",
            "language": "英语",
            "input_language": "中文",
            "product_info": "保温杯",
            "product_facts": {"product_name": "保温杯", "sku_count": 1},
            "brand_style": "现代、克制",
            "aspect_ratio": "4:5",
            "image_plan": "智能匹配 8 张",
            "model_preference": "商品保持优先",
        },
    )
    assert "${aspect_ratio}=4:5" in rendered
    assert "${product_facts}=" in rendered
    assert '"sku_count": 1' in rendered
    assert "${model_preference}=商品保持优先" in rendered


def test_semantic_validator_enforces_ratio_no_text_product_lock_and_custom_counts() -> None:
    invalid = _plan(
        ImagePromptItem(route_symbol="#@", image_type="白底图 1", picture_requirement="白底展示商品", copywriting_requirements="添加英文标题"),
        ImagePromptItem(route_symbol="#@", image_type="场景图 1", picture_requirement="生活场景", copywriting_requirements="添加卖点"),
    )
    errors = validate_meta_prompt_semantics(
        invalid,
        {
            "platform": "Amazon", "language": "无文字", "aspect_ratio": "4:5", "mode": "custom",
            "custom_counts": {"white_background": 1, "scene": 1, "selling_point": 0, "other": 0},
        },
    )
    assert any("画面比例" in error for error in errors)
    assert any("无文字" in error for error in errors)
    assert any("商品锁定" in error for error in errors)

    valid = _plan(
        ImagePromptItem(route_symbol="#@", image_type="白底图 1", picture_requirement="4:5 纯白背景，产品为第一视觉主体，保持商品外观、颜色、结构、标签与配件关系不变。", copywriting_requirements="No Text Overlay"),
        ImagePromptItem(route_symbol="#@", image_type="场景图 1", picture_requirement="4:5 生活场景，产品为第一视觉主体，保持商品外观、颜色、结构、标签与配件关系不变。", copywriting_requirements="无文字"),
    )
    assert validate_meta_prompt_semantics(
        valid,
        {
            "platform": "Amazon", "language": "无文字", "aspect_ratio": "4:5", "mode": "custom",
            "custom_counts": {"white_background": 1, "scene": 1, "selling_point": 0, "other": 0},
        },
    ) == []


def test_custom_other_count_accepts_prompt_engineering_subtypes() -> None:
    plan = _plan(ImagePromptItem(
        route_symbol="#@",
        image_type="尺寸信息图",
        picture_requirement="1:1 尺寸信息图，产品为第一视觉主体，保持商品外观、颜色、结构、标签与配件关系不变。",
        copywriting_requirements="使用简体中文，仅标注用户明确提供的尺寸。",
    ))
    assert validate_meta_prompt_semantics(plan, {
        "platform": "淘宝/天猫", "language": "简体中文", "aspect_ratio": "1:1", "mode": "custom",
        "custom_counts": {"white_background": 0, "scene": 0, "selling_point": 0, "other": 1},
    }) == []


def test_product_facts_have_strict_contracts() -> None:
    facts = parse_product_facts({
        "schema_version": "1.0", "product_name": "保温杯", "category": "饮水器具",
        "visible_features": ["杯盖", "防滑杯身"], "materials": ["无法仅凭图片确认"], "colors": ["白色"],
        "sku_count": 1, "accessories": [], "labels_text": [], "uncertain": ["容量"],
    })
    assert facts.sku_count == 1


def test_openai_llm_can_receive_product_images_as_multimodal_input(tmp_path) -> None:
    source = tmp_path / "product.png"
    source.write_bytes(b"png-bytes")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    provider = Provider(code="vision-llm", label="Vision LLM", capability="llm", adapter="openai_chat", base_url="https://example.test/v1/chat/completions", model_name="vision-model", enabled=True, is_default=True, is_fallback=False, config_json=json.dumps({"timeout_seconds": 30, "response_format": "json_object"}))

    async def run() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).call_llm(provider, "key", "system", "inspect product", image_paths=[str(source)])

    assert asyncio.run(run()) == '{"ok":true}'
    user_content = seen["messages"][1]["content"]  # type: ignore[index]
    assert user_content[0] == {"type": "text", "text": "inspect product"}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(b"png-bytes").decode()


def test_seed_exposes_all_prompt_engineering_assets(client) -> None:
    with client.app.state.session_factory() as session:
        codes = set(session.scalars(select(Prompt.code)).all())
    assert {"ecommerce-meta", "product-vision", "copywriting-assist", "edit-rewrite", "content-safety-review"}.issubset(codes)


def test_default_workflow_registers_visual_facts_semantic_validation_and_image_generation() -> None:
    graph = json.loads(default_workflow_json())
    node_types = [node["type"] for node in graph["nodes"]]
    assert node_types == ["input", "product_vision", "meta_prompt", "llm", "contract", "semantic_validator", "image_generate", "aggregate"]
    assert validate_workflow_graph(graph) == []


def test_workflow_registry_exposes_suite_video_and_aplus_assets() -> None:
    presets = workflow_preset_dicts()
    assert [preset["code"] for preset in presets] == ["product-suite-v1", "video-v1", "aplus-detail-v1"]
    assert all(validate_workflow_graph(preset["graph"]) == [] for preset in presets)


def test_semantic_plan_is_replanned_only_once() -> None:
    invalid = _plan(ImagePromptItem(route_symbol="#@", image_type="主图", picture_requirement="商品图", copywriting_requirements="标题"))
    valid = _plan(ImagePromptItem(route_symbol="#@", image_type="主图", picture_requirement="4:5 纯白背景，产品为第一视觉主体，保持商品外观、颜色、结构、标签与配件关系不变。", copywriting_requirements="No Text Overlay"))
    calls: list[list[str]] = []

    async def replan(_plan: MetaPromptPlan, errors: list[str]) -> MetaPromptPlan:
        calls.append(errors)
        return valid

    result = asyncio.run(validate_plan_with_one_replan(
        invalid,
        {"platform": "Amazon", "language": "无文字", "aspect_ratio": "4:5", "mode": "smart"},
        replan,
    ))
    assert result == valid
    assert len(calls) == 1


def test_semantic_plan_auto_injects_missing_ratio_without_replan() -> None:
    plan = _plan(ImagePromptItem(
        route_symbol="#@",
        image_type="场景图",
        picture_requirement="生活场景，产品为第一视觉主体，保持商品外观、颜色、结构、标签与配件关系不变。",
        copywriting_requirements="使用简体中文标题",
    ))
    calls = 0

    async def replan(_plan: MetaPromptPlan, _errors: list[str]) -> MetaPromptPlan:
        nonlocal calls
        calls += 1
        return _plan

    result = asyncio.run(validate_plan_with_one_replan(
        plan,
        {"platform": "Shopee", "language": "简体中文", "aspect_ratio": "1:1", "mode": "smart"},
        replan,
    ))

    assert calls == 0
    assert result.images[0].picture_requirement.startswith("1:1 画面比例，")
    assert validate_meta_prompt_semantics(result, {"platform": "Shopee", "language": "简体中文", "aspect_ratio": "1:1", "mode": "smart"}) == []


def test_semantic_replan_output_also_gets_missing_ratio_injected() -> None:
    invalid = _plan(ImagePromptItem(route_symbol="#@", image_type="场景图", picture_requirement="生活场景", copywriting_requirements="标题"))
    replanned_without_ratio = _plan(ImagePromptItem(
        route_symbol="#@",
        image_type="场景图",
        picture_requirement="生活场景，产品为第一视觉主体，保持商品外观、颜色、结构、标签与配件关系不变。",
        copywriting_requirements="使用简体中文标题",
    ))

    async def replan(_plan: MetaPromptPlan, _errors: list[str]) -> MetaPromptPlan:
        return replanned_without_ratio

    result = asyncio.run(validate_plan_with_one_replan(
        invalid,
        {"platform": "Shopee", "language": "简体中文", "aspect_ratio": "1:1", "mode": "smart"},
        replan,
    ))

    assert result.images[0].picture_requirement.startswith("1:1 画面比例，")
    assert validate_meta_prompt_semantics(result, {"platform": "Shopee", "language": "简体中文", "aspect_ratio": "1:1", "mode": "smart"}) == []


def test_semantic_plan_fails_when_single_replan_is_still_invalid() -> None:
    invalid = _plan(ImagePromptItem(route_symbol="#@", image_type="主图", picture_requirement="商品图", copywriting_requirements="标题"))

    async def replan(_plan: MetaPromptPlan, _errors: list[str]) -> MetaPromptPlan:
        return invalid

    try:
        asyncio.run(validate_plan_with_one_replan(
            invalid,
            {"platform": "Amazon", "language": "无文字", "aspect_ratio": "4:5", "mode": "smart"},
            replan,
        ))
    except ValueError as exc:
        assert "语义重规划后仍不合格" in str(exc)
    else:
        raise AssertionError("invalid replanned output should fail")
