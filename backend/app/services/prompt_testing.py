from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.config import Settings
from backend.app.models import (
    AplusItem,
    AplusJob,
    Asset,
    GenerationItem,
    GenerationJob,
    Prompt,
    PromptTestRun,
    PromptVersion,
    VideoItem,
    VideoJob,
    Workflow,
)
from backend.app.schemas import (
    AplusGenerationJobCreate,
    AplusOutputTarget,
    AplusPlanJobCreate,
    CopywritingAssistCreate,
    GenerationJobCreate,
    PromptTestRunCreate,
    VideoJobCreate,
)
from backend.app.security import ApiKeyCipher
from backend.app.services.aplus_jobs import (
    _aplus_json_execution_contract,
    _module_text,
    _normalize_module_selections,
    _parse_aplus_plan,
    _planning_canvas,
    _replace_prompt_variables,
    create_aplus_generation_job_from_plan,
    run_aplus_generation_job,
    run_aplus_plan_job,
)
from backend.app.services.jobs import (
    _call_llm_with_fallback,
    _enabled_provider,
    custom_count_instruction,
    image_provider_route,
    prompt_platform_name,
    run_generation_job,
)
from backend.app.services.prompt_contract import (
    append_runtime_contract,
    parse_content_safety_review,
    parse_meta_prompt_plan,
    parse_product_facts,
    plan_to_json,
    render_prompt_variables,
    validate_meta_prompt_semantics,
)
from backend.app.services.provider_routing import route_provider_codes
from backend.app.services.providers import ProviderClient
from backend.app.services.redaction import safe_json
from backend.app.services.video_jobs import (
    build_video_script_user_prompt,
    public_asset_url,
    run_video_job,
    seedance_prompt_from_script,
)


LLM_TEST_TYPE = "llm_output"
FULL_CHAIN_TEST_TYPE = "full_chain"
FULL_CHAIN_PROMPT_CODES = {"ecommerce-meta", "ecommerce-video-meta-15s", "aplus-meta"}
TERMINAL_STATUSES = {"succeeded", "failed", "partial_failed"}


def _json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()


def _active_prompt_version(session: Session, code: str) -> PromptVersion:
    prompt = session.scalar(select(Prompt).where(Prompt.code == code))
    version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    if not version:
        raise RuntimeError(f"Prompt {code} 未启用")
    return version


def _assets_for_inputs(session: Session, inputs: dict[str, Any]) -> list[Asset]:
    asset_ids = [str(item) for item in inputs.get("asset_ids", []) if str(item)]
    if not asset_ids:
        return []
    assets = session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
    if len(assets) != len(set(asset_ids)):
        raise ValueError("测试输入包含无效商品图")
    by_id = {asset.id: asset for asset in assets}
    return [by_id[asset_id] for asset_id in asset_ids]


def _asset_paths(assets: list[Asset]) -> list[str]:
    return [asset.file_path for asset in assets]


def _suite_payload(inputs: dict[str, Any], *, dry_run: bool) -> GenerationJobCreate:
    mode = str(inputs.get("mode") or "smart")
    count = int(inputs.get("count") or 7)
    custom_counts = inputs.get("custom_counts")
    return GenerationJobCreate(
        asset_ids=[str(item) for item in inputs.get("asset_ids", [])],
        platform=str(inputs.get("platform") or "亚马逊"),
        market=str(inputs.get("market") or "美国"),
        language=str(inputs.get("language") or "英语"),
        aspect_ratio=str(inputs.get("aspect_ratio") or "4:5"),
        selling_points=str(inputs.get("selling_points") or "突出商品外观、核心功能和使用场景。"),
        product_name=str(inputs.get("product_name") or ""),
        category=str(inputs.get("category") or ""),
        specifications=str(inputs.get("specifications") or ""),
        sku_info=str(inputs.get("sku_info") or ""),
        accessories=str(inputs.get("accessories") or ""),
        certifications=str(inputs.get("certifications") or ""),
        target_audience=str(inputs.get("target_audience") or ""),
        brand_style=str(inputs.get("brand_style") or ""),
        mode=mode,  # type: ignore[arg-type]
        count=count,
        custom_counts=custom_counts,
        model_preference=str(inputs.get("model_preference") or "fidelity"),  # type: ignore[arg-type]
        dry_run=dry_run,
    )


def _video_payload(inputs: dict[str, Any], *, dry_run: bool) -> VideoJobCreate:
    video_types = inputs.get("video_types") or ["UGC 种草"]
    if isinstance(video_types, str):
        video_types = [video_types]
    return VideoJobCreate(
        asset_ids=[str(item) for item in inputs.get("asset_ids", [])],
        platform=str(inputs.get("platform") or "亚马逊"),
        market=str(inputs.get("market") or "美国"),
        country=str(inputs.get("country") or "美国"),
        language=str(inputs.get("language") or "英语"),
        aspect_ratio=str(inputs.get("aspect_ratio") or "9:16"),
        product_name=str(inputs.get("product_name") or ""),
        target_audience=str(inputs.get("target_audience") or ""),
        selling_points=str(inputs.get("selling_points") or "突出商品核心卖点和真实使用场景。"),
        video_types=[str(item) for item in video_types],
        duration=int(inputs.get("duration") or 15),
        resolution=str(inputs.get("resolution") or "1080p"),
        dry_run=dry_run,
    )


def _aplus_payload(inputs: dict[str, Any], *, dry_run: bool) -> AplusPlanJobCreate:
    output_targets = inputs.get("output_targets") or [{"mode": "detail", "aspect_ratio": "1:1"}]
    module_selections = inputs.get("module_selections") or [{"name": "商品主视觉", "count": 1}, {"name": "卖点拆解", "count": 1}]
    return AplusPlanJobCreate(
        asset_ids=[str(item) for item in inputs.get("asset_ids", [])],
        platform=str(inputs.get("platform") or "亚马逊"),
        market=str(inputs.get("market") or "美国"),
        language=str(inputs.get("language") or "英语"),
        product_info=str(inputs.get("product_info") or "根据商品图识别产品，并围绕核心卖点规划详情页。"),
        module_selections=module_selections,
        selected_modules=None,
        output_targets=[AplusOutputTarget.model_validate(item) for item in output_targets],
        dry_run=dry_run,
    )


def _copywriting_user_prompt(inputs: dict[str, Any]) -> str:
    payload = CopywritingAssistCreate(
        asset_ids=[str(item) for item in inputs.get("asset_ids", [])],
        platform=str(inputs.get("platform") or "亚马逊"),
        market=str(inputs.get("market") or "美国"),
        language=str(inputs.get("language") or "英语"),
        selling_points=str(inputs.get("selling_points") or ""),
        dry_run=False,
    )
    input_mode = "image_with_text" if payload.selling_points.strip() else "image_only"
    return json.dumps(
        {
            "input_mode": input_mode,
            "platform": payload.platform,
            "market": payload.market,
            "image_text_language": payload.language,
            "output_language": "简体中文",
            "selling_points": payload.selling_points,
            "instruction": "必须使用简体中文输出 AI 帮写候选内容；不得补造参数、功效、认证或竞品结论。",
        },
        ensure_ascii=False,
    )


def _default_product_facts(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "product_name": str(inputs.get("product_name") or "测试商品"),
        "category": str(inputs.get("category") or "电商商品"),
        "visible_features": ["以商品图可见事实为准"],
        "materials": ["无法仅凭测试输入确认"],
        "colors": ["以商品图可见颜色为准"],
        "sku_count": 1,
        "accessories": [],
        "labels_text": [],
        "uncertain": ["运营测试样例"],
    }


async def _run_llm_test(
    session: Session,
    run: PromptTestRun,
    prompt: Prompt,
    inputs: dict[str, Any],
    cipher: ApiKeyCipher,
) -> None:
    llm_default = _enabled_provider(session, "llm", "default")
    llm_fallback = _enabled_provider(session, "llm", "fallback")
    assets = _assets_for_inputs(session, inputs)
    image_paths = _asset_paths(assets)
    system_prompt, user_prompt, response_format = _build_llm_test_prompts(prompt, run.prompt_content_snapshot, inputs, assets)
    run.status = "running"
    run.progress = 20
    session.flush()
    try:
        raw, provider = await _call_llm_with_fallback(
            ProviderClient(),
            llm_default,
            llm_fallback,
            cipher,
            system_prompt,
            user_prompt,
            image_paths=image_paths,
            response_format=response_format,
        )
        parsed, validation_errors = _parse_llm_output(prompt.code, raw, inputs)
        run.raw_output = raw
        run.parsed_output_json = _json_dumps(parsed)
        run.validation_errors_json = _json_dumps(validation_errors)
        run.provider_code = provider.code
        run.status = "succeeded"
        run.progress = 100
        run.error = None
    except Exception as exc:
        run.status = "failed"
        run.progress = 100
        run.error = str(exc)


def _build_llm_test_prompts(
    prompt: Prompt,
    prompt_content: str,
    inputs: dict[str, Any],
    assets: list[Asset],
) -> tuple[str, str, str | None]:
    code = prompt.code
    if code == "ecommerce-meta":
        payload = _suite_payload({**inputs, "asset_ids": [asset.id for asset in assets] or inputs.get("asset_ids") or ["prompt-test-placeholder"]}, dry_run=False)
        image_plan = (
            custom_count_instruction(payload.custom_counts.model_dump() if payload.custom_counts else None)
            if payload.mode == "custom"
            else f"由核心提示词智能匹配，共 {payload.count} 张"
        )
        product_facts = inputs.get("product_facts") if isinstance(inputs.get("product_facts"), dict) else _default_product_facts(inputs)
        product_info = "\n".join(
            [
                f"商品名称：{payload.product_name or product_facts.get('product_name')}",
                f"商品品类：{payload.category or product_facts.get('category')}",
                f"核心卖点：{payload.selling_points}",
                f"画面比例：{payload.aspect_ratio}",
                f"套图数量指令：{image_plan}",
            ]
        )
        prompt_variables = {
            "platform": prompt_platform_name(payload.platform),
            "market": payload.market,
            "language": payload.language,
            "input_language": str(inputs.get("input_language") or "中文"),
            "product_info": product_info,
            "product_facts": product_facts,
            "brand_style": payload.brand_style or "由商品品类、目标市场和可见包装风格推导",
            "aspect_ratio": payload.aspect_ratio,
            "image_plan": image_plan,
            "model_preference": "视觉排版优先" if payload.model_preference == "layout" else "商品保持优先",
        }
        return (
            append_runtime_contract(render_prompt_variables(prompt_content, prompt_variables), payload.count),
            json.dumps({**prompt_variables, "count": payload.count}, ensure_ascii=False),
            "json_object",
        )
    if code == "ecommerce-video-meta-15s":
        payload = _video_payload({**inputs, "asset_ids": [asset.id for asset in assets] or inputs.get("asset_ids") or ["prompt-test-placeholder"]}, dry_run=False)
        item = SimpleNamespace(video_type=payload.video_types[0])
        image_urls = [asset.url for asset in assets] or [str(inputs.get("product_image_url") or "")]
        return (
            prompt_content,
            build_video_script_user_prompt(payload.model_dump(), item, image_urls),
            None,
        )
    if code == "aplus-meta":
        payload = _aplus_payload({**inputs, "asset_ids": [asset.id for asset in assets] or inputs.get("asset_ids") or ["prompt-test-placeholder"]}, dry_run=False)
        params = payload.model_dump()
        module_selections = _normalize_module_selections(params)
        canvas = _planning_canvas(params["output_targets"])
        facts = inputs.get("product_facts") if isinstance(inputs.get("product_facts"), dict) else _default_product_facts(inputs)
        variables = {
            "product_info": payload.product_info,
            "platform": payload.platform,
            "market": payload.market,
            "language": payload.language,
            "input_language": str(inputs.get("input_language") or "中文"),
            "modules": _module_text(module_selections),
            "selected_modules": _module_text(module_selections),
            "brand_style": str(inputs.get("brand_style") or ""),
            "reference_assets": json.dumps(facts, ensure_ascii=False),
            "module_selections": json.dumps(module_selections, ensure_ascii=False),
            "canvas": json.dumps({"width": canvas["width"], "height": canvas["height"], "proportion": canvas["proportion"]}, ensure_ascii=False),
            "output_targets": json.dumps(params["output_targets"], ensure_ascii=False),
            "width": canvas["width"],
            "height": canvas["height"],
            "proportion": canvas["proportion"],
            "aspect_ratio": ", ".join(target["aspect_ratio"] for target in params["output_targets"]),
        }
        user_prompt = json.dumps(
            {
                "input_mode": "image_with_text" if payload.product_info.strip() else "image_only",
                "product_info": payload.product_info,
                "product_facts": facts,
                "module_selections": module_selections,
                "canvas": {"width": canvas["width"], "height": canvas["height"], "proportion": canvas["proportion"]},
                "output_targets": params["output_targets"],
            },
            ensure_ascii=False,
        )
        return _replace_prompt_variables(prompt_content, variables) + _aplus_json_execution_contract(module_selections), user_prompt, "json_object"
    if code == "product-vision":
        return prompt_content, json.dumps({"product_info": inputs.get("product_info", ""), "instruction": "输出结构化商品视觉事实 JSON。"}, ensure_ascii=False), "json_object"
    if code == "copywriting-assist":
        return prompt_content, _copywriting_user_prompt(inputs), None
    if code == "edit-rewrite":
        return (
            prompt_content,
            json.dumps(
                {
                    "instruction": inputs.get("instruction") or "把画面改为更适合移动端信息流的构图，保持商品不变。",
                    "original_prompt": inputs.get("original_prompt")
                    or {
                        "image_type": "主图",
                        "picture_requirement": "商品居中，保持外观、颜色、结构一致。",
                        "copywriting_requirements": "使用简洁标题。",
                    },
                },
                ensure_ascii=False,
            ),
            "json_object",
        )
    if code == "content-safety-review":
        return (
            prompt_content,
            json.dumps({"subject": inputs.get("subject") or "prompt_test", "text": inputs.get("text") or "测试一段普通电商商品描述。"}, ensure_ascii=False),
            "json_object",
        )
    return prompt_content, json.dumps(inputs, ensure_ascii=False), None


def _parse_llm_output(code: str, raw: str, inputs: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if code == "ecommerce-meta":
        count = int(inputs.get("count") or 7)
        try:
            plan = parse_meta_prompt_plan(raw, count)
            context = {
                "platform": prompt_platform_name(str(inputs.get("platform") or "亚马逊")),
                "language": str(inputs.get("language") or "英语"),
                "aspect_ratio": str(inputs.get("aspect_ratio") or "4:5"),
                "mode": str(inputs.get("mode") or "smart"),
                "custom_counts": inputs.get("custom_counts"),
            }
            errors.extend(validate_meta_prompt_semantics(plan, context))
            return {"plan": json.loads(plan_to_json(plan))}, errors
        except Exception as exc:
            return {}, [str(exc)]
    if code == "product-vision":
        try:
            facts = parse_product_facts(raw)
            return {"product_facts": facts.model_dump()}, []
        except Exception as exc:
            return {}, [str(exc)]
    if code == "content-safety-review":
        try:
            review = parse_content_safety_review(raw)
            if not review.passed:
                errors.append("内容安全审计未通过")
            return {"review": review.model_dump()}, errors
        except Exception as exc:
            return {}, [str(exc)]
    if code == "ecommerce-video-meta-15s":
        payload = _video_payload({**inputs, "asset_ids": inputs.get("asset_ids") or ["prompt-test-placeholder"]}, dry_run=False)
        item = SimpleNamespace(video_type=payload.video_types[0])
        return {"script_markdown": raw.strip(), "seedance_prompt": seedance_prompt_from_script(raw.strip(), payload.model_dump(), item)}, []
    if code == "aplus-meta":
        try:
            payload = _aplus_payload({**inputs, "asset_ids": inputs.get("asset_ids") or ["prompt-test-placeholder"]}, dry_run=False)
            global_plan, modules = _parse_aplus_plan(raw, _normalize_module_selections(payload.model_dump()))
            return {"global_plan": global_plan, "modules": modules}, []
        except Exception as exc:
            return {}, [str(exc)]
    try:
        parsed = json.loads(raw)
        return {"json": parsed}, []
    except json.JSONDecodeError:
        return {"text": raw.strip()}, []


def create_prompt_test_run_record(prompt: Prompt, payload: PromptTestRunCreate) -> PromptTestRun:
    return PromptTestRun(
        prompt_id=prompt.id,
        prompt_code=prompt.code,
        test_type=payload.test_type,
        status="queued",
        progress=0,
        prompt_content_snapshot=payload.prompt_content,
        prompt_content_sha256=_content_hash(payload.prompt_content),
        input_params_json=_json_dumps(payload.inputs),
        raw_output="",
        parsed_output_json="{}",
        validation_errors_json="[]",
        artifact_urls_json="[]",
    )


async def create_llm_prompt_test_run(
    session: Session,
    prompt: Prompt,
    payload: PromptTestRunCreate,
    cipher: ApiKeyCipher,
) -> PromptTestRun:
    _enabled_provider(session, "llm", "default")
    _enabled_provider(session, "llm", "fallback")
    run = create_prompt_test_run_record(prompt, payload)
    session.add(run)
    session.flush()
    await _run_llm_test(session, run, prompt, payload.inputs, cipher)
    return run


def create_full_chain_prompt_test_run(
    session: Session,
    prompt: Prompt,
    payload: PromptTestRunCreate,
    settings: Settings,
) -> tuple[PromptTestRun, tuple[str, str]]:
    if prompt.code not in FULL_CHAIN_PROMPT_CODES:
        raise ValueError("该提示词只支持 LLM 输出测试，不支持完整链路生成")
    if not payload.inputs.get("asset_ids"):
        raise ValueError("完整链路测试至少需要一张样例商品图")
    assets = _assets_for_inputs(session, payload.inputs)
    run = create_prompt_test_run_record(prompt, payload)
    session.add(run)
    session.flush()
    if prompt.code == "ecommerce-meta":
        job = _create_suite_admin_test_job(session, payload, prompt, run)
        return run, ("generation", job.id)
    if prompt.code == "ecommerce-video-meta-15s":
        job = _create_video_admin_test_job(session, payload, prompt, run, assets, settings)
        return run, ("video", job.id)
    job = _create_aplus_plan_admin_test_job(session, payload, prompt, run)
    return run, ("aplus_full_chain", job.id)


def _create_suite_admin_test_job(
    session: Session,
    payload: PromptTestRunCreate,
    prompt: Prompt,
    run: PromptTestRun,
) -> GenerationJob:
    data = _suite_payload(payload.inputs, dry_run=False)
    _enabled_provider(session, "llm", "default")
    _enabled_provider(session, "llm", "fallback")
    image_provider_route(data.model_preference, session)
    prompt_version_id = prompt.active_version_id
    workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
    if not prompt_version_id or not workflow or not workflow.active_version_id:
        raise RuntimeError("核心 Prompt 或 Workflow 未启用")
    auxiliary_codes = ("product-vision", "copywriting-assist", "edit-rewrite", "image-text-edit", "content-safety-review")
    auxiliary_prompts = session.scalars(select(Prompt).where(Prompt.code.in_(auxiliary_codes))).all()
    prompt_versions = {item.code: item.active_version_id for item in auxiliary_prompts if item.active_version_id}
    if len(prompt_versions) != len(auxiliary_codes):
        raise RuntimeError("Prompt 工程辅助资产未完整启用")
    params = data.model_dump()
    params["_prompt_versions"] = prompt_versions
    params["_admin_prompt_content"] = payload.prompt_content
    params["_admin_test_run_id"] = run.id
    job = GenerationJob(
        status="queued",
        dry_run=False,
        is_admin_test=True,
        params_json=_json_dumps(params),
        asset_ids_json=_json_dumps(data.asset_ids),
        count=data.count,
        progress=0,
        prompt_version_id=prompt_version_id,
        workflow_version_id=workflow.active_version_id,
    )
    session.add(job)
    session.flush()
    run.status = "running"
    run.progress = 3
    run.related_job_type = "generation"
    run.related_job_id = job.id
    return job


def _create_video_admin_test_job(
    session: Session,
    payload: PromptTestRunCreate,
    prompt: Prompt,
    run: PromptTestRun,
    assets: list[Asset],
    settings: Settings,
) -> VideoJob:
    data = _video_payload(payload.inputs, dry_run=False)
    _enabled_provider(session, "llm", "default")
    _enabled_provider(session, "llm", "fallback")
    _enabled_provider(session, "video", "default")
    public_asset_url(settings, assets[0])
    prompt_version_id = prompt.active_version_id
    if not prompt_version_id:
        raise RuntimeError("视频 Meta Prompt 未启用")
    params = data.model_dump()
    params["_prompt_versions"] = {"ecommerce-video-meta-15s": prompt_version_id}
    params["_admin_prompt_content"] = payload.prompt_content
    params["_admin_test_run_id"] = run.id
    job = VideoJob(
        status="queued",
        dry_run=False,
        is_admin_test=True,
        params_json=_json_dumps(params),
        asset_ids_json=_json_dumps(data.asset_ids),
        count=len(data.video_types),
        progress=0,
        prompt_version_id=prompt_version_id,
    )
    session.add(job)
    session.flush()
    for index, video_type in enumerate(data.video_types):
        session.add(VideoItem(job_id=job.id, index=index, video_type=video_type, status="queued"))
    run.status = "running"
    run.progress = 3
    run.related_job_type = "video"
    run.related_job_id = job.id
    return job


def _create_aplus_plan_admin_test_job(
    session: Session,
    payload: PromptTestRunCreate,
    prompt: Prompt,
    run: PromptTestRun,
) -> AplusJob:
    data = _aplus_payload(payload.inputs, dry_run=False)
    _enabled_provider(session, "llm", "default")
    _enabled_provider(session, "llm", "fallback")
    for target in data.output_targets:
        route_provider_codes(session, "aplus_mobile" if target.mode == "amazon_aplus_advanced_mobile" else "aplus_detail")
    prompt_version_id = prompt.active_version_id
    product_vision = _active_prompt_version(session, "product-vision")
    if not prompt_version_id:
        raise RuntimeError("A+ Meta Prompt 未启用")
    params = data.model_dump()
    params["input_language"] = str(payload.inputs.get("input_language") or "中文")
    params["brand_style"] = str(payload.inputs.get("brand_style") or "")
    params["module_total"] = data.module_total
    params["_prompt_versions"] = {"product-vision": product_vision.id}
    params["_admin_prompt_content"] = payload.prompt_content
    params["_admin_test_run_id"] = run.id
    job = AplusJob(
        job_type="plan",
        status="queued",
        dry_run=False,
        is_admin_test=True,
        params_json=_json_dumps(params),
        asset_ids_json=_json_dumps(data.asset_ids),
        count=data.module_total,
        progress=0,
        prompt_version_id=prompt_version_id,
    )
    session.add(job)
    session.flush()
    run.status = "running"
    run.progress = 3
    run.related_job_type = "aplus_plan"
    run.related_job_id = job.id
    return job


async def run_aplus_full_chain_prompt_test(
    run_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    with session_factory() as session:
        run = session.get(PromptTestRun, run_id)
        if not run or not run.related_job_id:
            return
        plan_job_id = run.related_job_id
    await run_aplus_plan_job(plan_job_id, session_factory, cipher)
    with session_factory() as session:
        run = session.get(PromptTestRun, run_id)
        plan_job = session.scalar(
            select(AplusJob)
            .where(AplusJob.id == plan_job_id)
            .options(selectinload(AplusJob.items).selectinload(AplusItem.versions))
        )
        if not run or not plan_job:
            return
        if plan_job.status != "succeeded":
            run.status = "failed"
            run.progress = 100
            run.error = plan_job.error or "A+ 方案生成失败"
            session.commit()
            return
        inputs = _json_loads(run.input_params_json, {})
        output_targets = inputs.get("generation_output_targets") or inputs.get("output_targets") or [{"mode": "detail", "aspect_ratio": "1:1"}]
        generation_payload = AplusGenerationJobCreate(
            plan_job_id=plan_job.id,
            module_item_ids=[],
            output_targets=[AplusOutputTarget.model_validate(item) for item in output_targets],
            dry_run=False,
        )
        prompt_version_id = plan_job.prompt_version_id
        generation_job = create_aplus_generation_job_from_plan(session, plan_job, generation_payload, prompt_version_id)
        generation_job.is_admin_test = True
        run.related_job_type = "aplus_generation"
        run.related_job_id = generation_job.id
        run.progress = 45
        session.commit()
        generation_job_id = generation_job.id
    await run_aplus_generation_job(generation_job_id, session_factory, settings, cipher)
    with session_factory() as session:
        run = session.get(PromptTestRun, run_id)
        if run:
            refresh_prompt_test_run_from_related_job(session, run)
            session.commit()


def refresh_prompt_test_run_from_related_job(session: Session, run: PromptTestRun) -> PromptTestRun:
    if not run.related_job_type or not run.related_job_id:
        return run
    if run.related_job_type == "generation":
        job = session.scalar(
            select(GenerationJob)
            .where(GenerationJob.id == run.related_job_id)
            .options(selectinload(GenerationJob.items).selectinload(GenerationItem.versions))
        )
        if job:
            _sync_generation_run(run, job)
    elif run.related_job_type == "video":
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == run.related_job_id).options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
        )
        if job:
            _sync_video_run(run, job)
    elif run.related_job_type in {"aplus_plan", "aplus_generation"}:
        job = session.scalar(
            select(AplusJob).where(AplusJob.id == run.related_job_id).options(selectinload(AplusJob.items).selectinload(AplusItem.versions))
        )
        if job:
            _sync_aplus_run(run, job)
    return run


def _sync_generation_run(run: PromptTestRun, job: GenerationJob) -> None:
    artifacts: list[str] = []
    items = []
    for item in job.items:
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current:
            artifacts.append(current.url)
        try:
            prompt = json.loads(item.prompt_text)
        except json.JSONDecodeError:
            prompt = {"text": item.prompt_text}
        items.append({"index": item.index, "image_type": item.image_type, "status": item.status, "prompt": prompt, "url": current.url if current else None, "error": item.error})
    run.status = job.status if job.status in TERMINAL_STATUSES else "running"
    run.progress = job.progress
    run.error = job.error
    run.parsed_output_json = _json_dumps({"job_status": job.status, "items": items})
    run.artifact_urls_json = _json_dumps(artifacts)


def _sync_video_run(run: PromptTestRun, job: VideoJob) -> None:
    artifacts: list[str] = []
    items = []
    for item in job.items:
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current:
            artifacts.append(current.url)
        items.append(
            {
                "index": item.index,
                "video_type": item.video_type,
                "status": item.status,
                "script_markdown": item.script_markdown,
                "prompt_text": item.prompt_text,
                "url": current.url if current else None,
                "remote_url": current.remote_url if current else "",
                "error": item.error,
            }
        )
    run.status = job.status if job.status in TERMINAL_STATUSES else "running"
    run.progress = job.progress
    run.error = job.error
    run.parsed_output_json = _json_dumps({"job_status": job.status, "items": items})
    run.artifact_urls_json = _json_dumps(artifacts)


def _sync_aplus_run(run: PromptTestRun, job: AplusJob) -> None:
    artifacts: list[str] = []
    items = []
    for item in job.items:
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current:
            artifacts.append(current.url)
        try:
            prompt = json.loads(item.prompt_text) if item.prompt_text else {}
        except json.JSONDecodeError:
            prompt = {"text": item.prompt_text}
        items.append(
            {
                "index": item.index,
                "module_name": item.module_name,
                "output_mode": item.output_mode,
                "aspect_ratio": item.aspect_ratio,
                "status": item.status,
                "image_prompt": item.image_prompt,
                "copy_requirements": item.copy_requirements,
                "prompt": prompt,
                "url": current.url if current else None,
                "error": item.error,
            }
        )
    run.status = job.status if job.status in TERMINAL_STATUSES else "running"
    run.progress = job.progress
    run.error = job.error
    run.parsed_output_json = _json_dumps({"job_type": job.job_type, "job_status": job.status, "items": items})
    run.artifact_urls_json = _json_dumps(artifacts)


def prompt_test_run_dict(run: PromptTestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "prompt_id": run.prompt_id,
        "prompt_code": run.prompt_code,
        "test_type": run.test_type,
        "status": run.status,
        "progress": run.progress,
        "prompt_content_sha256": run.prompt_content_sha256,
        "input_params": _json_loads(run.input_params_json, {}),
        "raw_output": run.raw_output,
        "parsed_output": _json_loads(run.parsed_output_json, {}),
        "validation_errors": _json_loads(run.validation_errors_json, []),
        "related_job_type": run.related_job_type,
        "related_job_id": run.related_job_id,
        "artifact_urls": _json_loads(run.artifact_urls_json, []),
        "provider_code": run.provider_code,
        "error": run.error,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
