from __future__ import annotations

import asyncio
import json
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings
from backend.app.models import (
    Asset,
    ExecutionLog,
    GenerationItem,
    GenerationJob,
    GenerationVersion,
    PromptVersion,
    Provider,
    utcnow,
)
from backend.app.security import ApiKeyCipher
from backend.app.services.execution import (
    parse_plan_with_one_repair,
    run_image_route,
    validate_plan_with_one_replan,
)
from backend.app.services.prompt_contract import (
    ImagePromptItem,
    MetaPromptPlan,
    append_runtime_contract,
    parse_product_facts,
    plan_to_json,
    render_prompt_variables,
    validate_meta_prompt_semantics,
)
from backend.app.services.content_safety import ContentSafetyBlocked, ensure_content_safe, run_content_safety_review
from backend.app.services.provider_routing import enabled_provider_for_route, route_provider_codes
from backend.app.services.providers import ProviderClient
from backend.app.services.redaction import safe_json


DEMO_ASSET_DIR = Path(__file__).resolve().parents[1] / "static" / "demo"
DEMO_ASSETS = [
    DEMO_ASSET_DIR / "tumbler-feature.png",
    DEMO_ASSET_DIR / "tumbler-lifestyle.png",
    DEMO_ASSET_DIR / "tumbler-commute.png",
    DEMO_ASSET_DIR / "tumbler-source.png",
]
SMART_TYPES = [
    "首屏主视觉",
    "核心卖点图",
    "真实使用场景",
    "结构细节特写",
    "通勤生活方式",
    "材质与触感",
    "规格信息图",
    "多角度展示",
    "场景氛围图",
    "包装与配件",
    "目标人群图",
    "收尾品牌图",
]

CUSTOM_COUNT_LABELS = (
    ("white_background", "白底图"),
    ("scene", "场景图"),
    ("selling_point", "卖点图"),
    ("other", "其他图"),
)
PLATFORM_PROMPT_NAMES = {
    "亚马逊": "Amazon",
    "虾皮": "Shopee",
    "来赞达": "Lazada",
    "拼多多跨境": "Temu",
    "抖音海外商城": "TikTok Shop",
    "速卖通": "AliExpress",
    "易贝": "eBay",
    "沃尔玛": "Walmart",
    "美客多": "Mercado Libre",
    "酷澎": "Coupang",
    "维费尔": "Wayfair",
}


def image_provider_route(preference: str, session: Session | None = None) -> list[str]:
    route_key = "suite_layout" if preference == "layout" else "suite_fidelity"
    if session is not None:
        return route_provider_codes(session, route_key)
    return ["yunwu-image-2"] if route_key == "suite_layout" else ["yunwu-nano-pro", "yunwu-nano"]


def expand_custom_types(custom_counts: dict[str, Any] | None) -> list[str]:
    counts = custom_counts or {}
    return [
        f"{label} {index + 1}"
        for key, label in CUSTOM_COUNT_LABELS
        for index in range(int(counts.get(key, 0)))
    ]


def custom_count_instruction(custom_counts: dict[str, Any] | None) -> str:
    counts = custom_counts or {}
    return "、".join(f"{label}{int(counts.get(key, 0))}张" for key, label in CUSTOM_COUNT_LABELS)


def prompt_platform_name(platform: str) -> str:
    return PLATFORM_PROMPT_NAMES.get(platform, platform)


def build_dryrun_plan(params: dict[str, Any], count: int) -> MetaPromptPlan:
    custom_types = expand_custom_types(params.get("custom_counts"))
    image_types = custom_types if params.get("mode") == "custom" and len(custom_types) == count else SMART_TYPES[:count]
    selling_points = params.get("selling_points", "产品核心卖点")
    images = [
        ImagePromptItem(
            route_symbol="#@",
            image_type=image_type,
            picture_requirement=(
                f"{image_type}：{'纯白背景，' if index == 0 and prompt_platform_name(str(params.get('platform'))) == 'Amazon' else ''}"
                f"围绕“{selling_points}”设计适合 {prompt_platform_name(str(params.get('platform')))} / {params.get('market')} "
                f"的 {params.get('aspect_ratio')} 电商画面。产品为第一视觉主体，保持外观、颜色、结构、标签与配件关系不变。"
            ),
            copywriting_requirements=(
                "No Text Overlay" if params.get("language") in {"No Text Overlay", "无文字", "无文案"} else f"使用 {params.get('language')}，短标题优先，不添加未提供的数据与承诺。"
            ),
        )
        for index, image_type in enumerate(image_types)
    ]
    return MetaPromptPlan(schema_version="1.0", images=images)


def _run_dryrun_job(job_id: str, session_factory: sessionmaker[Session], settings: Settings) -> None:
    with session_factory() as session:
        job = session.get(GenerationJob, job_id)
        if not job:
            return
        params = json.loads(job.params_json)
        job.status = "running"
        job.started_at = utcnow()
        session.add(
            ExecutionLog(
                job_id=job.id,
                node="input",
                status="succeeded",
                request_summary=safe_json({"asset_count": len(json.loads(job.asset_ids_json)), "count": job.count}),
                response_summary=safe_json({"validated": True}),
                dry_run=job.dry_run,
            )
        )
        session.commit()

        try:
            prompt_version = session.get(PromptVersion, job.prompt_version_id)
            prompt_content = str(params.get("_admin_prompt_content") or (prompt_version.content if prompt_version else ""))
            plan = build_dryrun_plan(params, job.count)
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="product_vision",
                    status="succeeded",
                    request_summary=safe_json({"asset_count": len(json.loads(job.asset_ids_json))}),
                    response_summary=safe_json({"simulated": True, "source": "用户输入与本地演示商品"}),
                    dry_run=True,
                )
            )
            combined_length = len(append_runtime_contract(prompt_content, job.count)) if prompt_content else 0
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="meta_prompt",
                    status="succeeded",
                    request_summary=safe_json({"source_chars": len(prompt_content)}),
                    response_summary=safe_json({"combined_chars": combined_length, "image_count": len(plan.images)}),
                    dry_run=job.dry_run,
                )
            )
            semantic_errors = validate_meta_prompt_semantics(plan, params)
            if semantic_errors:
                raise ValueError("Dryrun 计划语义校验失败：" + "；".join(semantic_errors))
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="semantic_validator",
                    status="succeeded",
                    request_summary=safe_json({"image_count": len(plan.images)}),
                    response_summary=safe_json({"passed": True, "simulated": True}),
                    dry_run=True,
                )
            )

            for index, prompt_item in enumerate(plan.images):
                item = GenerationItem(
                    job_id=job.id,
                    index=index,
                    route_symbol=prompt_item.route_symbol,
                    image_type=prompt_item.image_type,
                    prompt_text=json.dumps(prompt_item.model_dump(), ensure_ascii=False),
                    status="running",
                )
                session.add(item)
                session.flush()

                source = DEMO_ASSETS[index % len(DEMO_ASSETS)]
                if not source.exists():
                    raise FileNotFoundError(f"Dryrun 演示资产不存在：{source.name}")
                result_name = f"{job.id}-{index + 1}-{uuid4().hex[:8]}.png"
                destination = settings.results_dir / result_name
                shutil.copy2(source, destination)
                version = GenerationVersion(
                    item_id=item.id,
                    version_no=1,
                    instruction="Dryrun 初始生成",
                    file_path=str(destination),
                    url=f"/files/results/{result_name}",
                    metadata_json=safe_json({"dry_run": True, "demo_asset": source.name}),
                )
                session.add(version)
                session.flush()
                item.current_version_id = version.id
                item.status = "succeeded"
                session.add(
                    ExecutionLog(
                        job_id=job.id,
                        item_id=item.id,
                        node="image_generate",
                        status="succeeded",
                        duration_ms=0,
                        request_summary=safe_json({"index": index, "route_symbol": "#@", "prompt": prompt_item.model_dump()}),
                        response_summary=safe_json({"url": version.url}),
                        dry_run=True,
                    )
                )
                job.progress = round(((index + 1) / job.count) * 100)
                session.commit()

            job.status = "succeeded"
            job.progress = 100
            job.completed_at = utcnow()
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="aggregate",
                    status="succeeded",
                    request_summary=safe_json({"items": job.count}),
                    response_summary=safe_json({"succeeded": job.count, "failed": 0}),
                    dry_run=job.dry_run,
                )
            )
            session.commit()
        except Exception as exc:
            job = session.get(GenerationJob, job_id)
            if job:
                succeeded = session.scalar(
                    select(GenerationItem).where(
                        GenerationItem.job_id == job.id, GenerationItem.status == "succeeded"
                    ).limit(1)
                )
                job.status = "partial_failed" if succeeded else "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                session.add(
                    ExecutionLog(
                        job_id=job.id,
                        node="aggregate",
                        status="failed",
                        error=str(exc),
                        request_summary="{}",
                        response_summary="{}",
                        dry_run=job.dry_run,
                    )
                )
                session.commit()


async def run_generation_job(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    with session_factory() as session:
        job = session.get(GenerationJob, job_id)
        if not job:
            return
        is_dry_run = job.dry_run
    if is_dry_run:
        _run_dryrun_job(job_id, session_factory, settings)
        return
    await _run_live_job(job_id, session_factory, settings, cipher)


def _enabled_provider(session: Session, capability: str, relation: str) -> Provider:
    route_key = "llm" if capability == "llm" else "video" if capability == "video" else ""
    if route_key:
        try:
            return enabled_provider_for_route(session, route_key, "primary" if relation == "default" else "fallback")
        except RuntimeError:
            # Compatibility for tests and older databases that still only mark global default/fallback flags.
            pass
    column = Provider.is_default if relation == "default" else Provider.is_fallback
    provider = session.scalar(
        select(Provider).where(
            Provider.capability == capability,
            column.is_(True),
            Provider.enabled.is_(True),
        )
    )
    if not provider or not provider.encrypted_api_key:
        raise RuntimeError(f"{capability} {relation} Provider 未启用或缺少 API Key")
    return provider


def _enabled_provider_by_code(session: Session, code: str) -> Provider:
    provider = session.scalar(
        select(Provider).where(Provider.code == code, Provider.enabled.is_(True))
    )
    if not provider or not provider.encrypted_api_key:
        raise RuntimeError(f"图片 Provider {code} 未启用或缺少 API Key")
    return provider


async def _call_llm_with_fallback(
    client: ProviderClient,
    default_provider: Provider,
    fallback_provider: Provider,
    cipher: ApiKeyCipher,
    system_prompt: str,
    user_prompt: str,
    image_paths: list[str] | None = None,
    response_format: str | None = "json_object",
) -> tuple[str, Provider]:
    try:
        return (
            await client.call_llm(
                default_provider,
                cipher.decrypt(default_provider.encrypted_api_key or ""),
                system_prompt,
                user_prompt,
                image_paths=image_paths,
                response_format=response_format,
            ),
            default_provider,
        )
    except Exception:
        return (
            await client.call_llm(
                fallback_provider,
                cipher.decrypt(fallback_provider.encrypted_api_key or ""),
                system_prompt,
                user_prompt,
                image_paths=image_paths,
                response_format=response_format,
            ),
            fallback_provider,
        )


async def _run_live_job(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    client = ProviderClient()
    try:
        with session_factory() as session:
            job = session.get(GenerationJob, job_id)
            if not job:
                return
            job.status = "running"
            job.started_at = utcnow()
            params = json.loads(job.params_json)
            asset_ids = json.loads(job.asset_ids_json)
            asset_paths = [
                asset.file_path
                for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
            ]
            llm_default = _enabled_provider(session, "llm", "default")
            llm_fallback = _enabled_provider(session, "llm", "fallback")
            image_codes = image_provider_route(params.get("model_preference", "fidelity"), session)
            for image_code in image_codes:
                _enabled_provider_by_code(session, image_code)
            prompt_version = session.get(PromptVersion, job.prompt_version_id)
            if not prompt_version:
                raise RuntimeError("任务引用的 Prompt 版本不存在")
            prompt_content = str(params.get("_admin_prompt_content") or prompt_version.content)
            prompt_versions = params.get("_prompt_versions") or {}
            vision_prompt = session.get(PromptVersion, prompt_versions.get("product-vision"))
            safety_prompt = session.get(PromptVersion, prompt_versions.get("content-safety-review"))
            if not vision_prompt:
                raise RuntimeError("任务引用的商品视觉事实 Prompt 版本不存在")
            if not safety_prompt:
                raise RuntimeError("任务引用的内容安全审计 Prompt 版本不存在")
            job_count = job.count
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="input",
                    status="succeeded",
                    request_summary=safe_json({"asset_count": len(asset_ids), "count": job.count}),
                    response_summary=safe_json({"validated": True}),
                    dry_run=False,
                )
            )
            session.commit()

        facts_raw, facts_provider = await _call_llm_with_fallback(
            client,
            llm_default,
            llm_fallback,
            cipher,
            vision_prompt.content,
            json.dumps(
                {
                    "product_name": params.get("product_name"),
                    "category": params.get("category"),
                    "specifications": params.get("specifications"),
                    "sku_info": params.get("sku_info"),
                    "accessories": params.get("accessories"),
                    "certifications": params.get("certifications"),
                    "selling_points": params.get("selling_points"),
                },
                ensure_ascii=False,
            ),
            image_paths=asset_paths,
        )
        product_facts = parse_product_facts(facts_raw)
        image_plan = custom_count_instruction(params.get("custom_counts")) if params.get("mode") == "custom" else f"由核心提示词智能匹配，共 {job_count} 张"
        product_info_parts = [
            f"商品名称：{params.get('product_name') or product_facts.product_name}",
            f"商品品类：{params.get('category') or product_facts.category}",
            f"核心卖点：{params.get('selling_points', '')}",
            f"规格：{params.get('specifications') or '未提供'}",
            f"SKU：{params.get('sku_info') or f'图片可见 {product_facts.sku_count} 个 SKU'}",
            f"配件：{params.get('accessories') or '以图片可见事实为准'}",
            f"认证：{params.get('certifications') or '未提供，不得虚构'}",
            f"目标人群：{params.get('target_audience') or '由商品与市场合理判断'}",
            f"画面比例：{params['aspect_ratio']}",
        ]
        if params.get("mode") == "custom":
            product_info_parts.append(f"套图数量指令：{image_plan}。总数必须严格等于 {job_count} 张。")
        prompt_variables = {
            "platform": prompt_platform_name(params["platform"]),
            "market": params["market"],
            "language": params["language"],
            "input_language": "中文",
            "product_info": "\n".join(product_info_parts),
            "product_facts": product_facts.model_dump(),
            "brand_style": params.get("brand_style") or "由商品品类、目标市场和可见包装风格推导，不使用通用固定模板",
            "aspect_ratio": params["aspect_ratio"],
            "image_plan": image_plan,
            "model_preference": "视觉排版优先：加强文字层级与版式组织" if params.get("model_preference") == "layout" else "商品保持优先：强化产品锁定与参考图一致性",
        }
        combined_prompt = append_runtime_contract(render_prompt_variables(prompt_content, prompt_variables), job_count)
        user_prompt = json.dumps({**prompt_variables, "count": job_count}, ensure_ascii=False)
        with session_factory() as session:
            session.add(ExecutionLog(
                job_id=job_id,
                node="product_vision",
                provider_id=facts_provider.id,
                status="succeeded",
                request_summary=safe_json({"asset_count": len(asset_paths)}),
                response_summary=safe_json({"category": product_facts.category, "sku_count": product_facts.sku_count, "uncertain": product_facts.uncertain}),
                dry_run=False,
            ))
            session.commit()

        raw_plan, llm_used = await _call_llm_with_fallback(
            client, llm_default, llm_fallback, cipher, combined_prompt, user_prompt, image_paths=asset_paths
        )

        async def repair(raw: str, error: str) -> str:
            repair_system = append_runtime_contract(
                "你是 JSON 修复器。只修复结构与字段，不改变图片策划含义。", job_count
            )
            repaired, _ = await _call_llm_with_fallback(
                client,
                llm_default,
                llm_fallback,
                cipher,
                repair_system,
                json.dumps({"invalid_output": raw, "validation_error": error}, ensure_ascii=False),
            )
            return repaired

        plan = await parse_plan_with_one_repair(raw_plan, job_count, repair)

        semantic_context = {**params, "platform": prompt_platform_name(params["platform"])}
        replanned = False

        async def replan(invalid_plan: MetaPromptPlan, errors: list[str]) -> MetaPromptPlan:
            nonlocal replanned
            replanned = True
            raw, _ = await _call_llm_with_fallback(
                client,
                llm_default,
                llm_fallback,
                cipher,
                combined_prompt,
                json.dumps({"task": "根据语义错误重规划整套图片，只输出完整 JSON", "errors": errors, "invalid_plan": invalid_plan.model_dump(), "runtime": prompt_variables}, ensure_ascii=False),
                image_paths=asset_paths,
            )
            return await parse_plan_with_one_repair(raw, job_count, repair)

        plan = await validate_plan_with_one_replan(plan, semantic_context, replan)
        try:
            plan_safety, safety_provider = await run_content_safety_review(
                client,
                llm_default,
                llm_fallback,
                cipher,
                safety_prompt,
                subject="image_plan",
                text=plan_to_json(plan),
                image_paths=asset_paths,
            )
            ensure_content_safe(plan_safety, "内容安全拦截")
            with session_factory() as session:
                session.add(ExecutionLog(
                    job_id=job_id,
                    node="content_safety",
                    provider_id=safety_provider.id,
                    status="succeeded",
                    request_summary=safe_json({"subject": "image_plan", "asset_count": len(asset_paths)}),
                    response_summary=safe_json(plan_safety.model_dump()),
                    dry_run=False,
                ))
                session.commit()
        except ContentSafetyBlocked as exc:
            with session_factory() as session:
                session.add(ExecutionLog(
                    job_id=job_id,
                    node="content_safety",
                    status="failed",
                    request_summary=safe_json({"subject": "image_plan"}),
                    response_summary=safe_json(exc.review.model_dump() if exc.review else {}),
                    error=str(exc),
                    dry_run=False,
                ))
                session.commit()
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            with session_factory() as session:
                session.add(ExecutionLog(
                    job_id=job_id,
                    node="content_safety",
                    status="failed",
                    request_summary=safe_json({"subject": "image_plan"}),
                    response_summary="{}",
                    error=str(exc),
                    dry_run=False,
                ))
                session.commit()
            raise RuntimeError(f"内容安全拦截：安全审计失败：{exc}") from exc
        with session_factory() as session:
            job = session.get(GenerationJob, job_id)
            if not job:
                return
            for index, prompt_item in enumerate(plan.images):
                session.add(
                    GenerationItem(
                        job_id=job.id,
                        index=index,
                        route_symbol=prompt_item.route_symbol,
                        image_type=prompt_item.image_type,
                        prompt_text=json.dumps(prompt_item.model_dump(), ensure_ascii=False),
                        status="queued",
                    )
                )
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="llm_contract",
                    provider_id=llm_used.id,
                    status="succeeded",
                    request_summary=safe_json({"count": job.count}),
                    response_summary=safe_json({"image_count": len(plan.images)}),
                    dry_run=False,
                )
            )
            session.add(ExecutionLog(
                job_id=job.id,
                node="semantic_validator",
                provider_id=llm_used.id,
                status="succeeded",
                request_summary=safe_json({"image_count": len(plan.images)}),
                response_summary=safe_json({"passed": True, "replanned": replanned}),
                dry_run=False,
            ))
            session.commit()
            item_ids = session.scalars(
                select(GenerationItem.id).where(GenerationItem.job_id == job.id).order_by(GenerationItem.index)
            ).all()

        semaphore = asyncio.Semaphore(settings.max_job_concurrency)

        async def guarded(item_id: str) -> None:
            async with semaphore:
                await _run_live_item(
                    item_id,
                    session_factory,
                    settings,
                    cipher,
                    client,
                    image_codes,
                    asset_paths,
                    params["aspect_ratio"],
                    params,
                )

        await asyncio.gather(*(guarded(item_id) for item_id in item_ids))
        with session_factory() as session:
            job = session.get(GenerationJob, job_id)
            statuses = session.scalars(
                select(GenerationItem.status).where(GenerationItem.job_id == job_id)
            ).all()
            success_count = statuses.count("succeeded")
            failed_count = statuses.count("failed")
            job.status = "succeeded" if failed_count == 0 else "failed" if success_count == 0 else "partial_failed"
            job.progress = 100
            job.completed_at = utcnow()
            session.add(
                ExecutionLog(
                    job_id=job.id,
                    node="aggregate",
                    status=job.status,
                    request_summary=safe_json({"items": len(statuses)}),
                    response_summary=safe_json({"succeeded": success_count, "failed": failed_count}),
                    dry_run=False,
                )
            )
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            job = session.get(GenerationJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                session.add(
                    ExecutionLog(
                        job_id=job.id,
                        node="live_execution",
                        status="failed",
                        request_summary="{}",
                        response_summary="{}",
                        error=str(exc),
                        dry_run=False,
                    )
                )
                session.commit()


async def _run_live_item(
    item_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
    client: ProviderClient,
    provider_codes: list[str],
    asset_paths: list[str],
    aspect_ratio: str,
    params: dict[str, Any],
) -> None:
    with session_factory() as session:
        item = session.get(GenerationItem, item_id)
        if not item:
            return
        item.status = "running"
        prompt_item = json.loads(item.prompt_text)
        prompt = f"{prompt_item['picture_requirement']}\n\n文案要求：{prompt_item['copywriting_requirements']}"
        session.commit()

    async def generate(provider_code: str) -> bytes:
        with session_factory() as session:
            provider = session.scalar(select(Provider).where(Provider.code == provider_code))
            if not provider or not provider.encrypted_api_key:
                raise RuntimeError(f"Provider {provider_code} 不可用")
            return await client.generate_image(
                provider,
                cipher.decrypt(provider.encrypted_api_key),
                prompt,
                asset_paths,
                aspect_ratio,
            )

    try:
        image_bytes, used_code = await run_image_route(provider_codes, generate)
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
        result_name = f"{item_id}-{uuid4().hex[:8]}.png"
        destination = settings.results_dir / result_name
        destination.write_bytes(image_bytes)
        with session_factory() as session:
            prompt_versions = params.get("_prompt_versions") or {}
            safety_prompt = session.get(PromptVersion, prompt_versions.get("content-safety-review"))
            llm_default = _enabled_provider(session, "llm", "default")
            llm_fallback = _enabled_provider(session, "llm", "fallback")
            if not safety_prompt:
                raise RuntimeError("内容安全审计 Prompt 版本不存在")
        try:
            safety_review, safety_provider = await run_content_safety_review(
                client,
                llm_default,
                llm_fallback,
                cipher,
                safety_prompt,
                subject="generated_image",
                text=prompt,
                image_paths=[str(destination), *asset_paths],
            )
            ensure_content_safe(safety_review, "内容安全拦截")
        except ContentSafetyBlocked as exc:
            destination.unlink(missing_ok=True)
            with session_factory() as session:
                item = session.get(GenerationItem, item_id)
                if item:
                    item.status = "failed"
                    item.error = str(exc)
                    session.add(
                        ExecutionLog(
                            job_id=item.job_id,
                            item_id=item.id,
                            node="content_safety",
                            provider_id=safety_provider.id if "safety_provider" in locals() else None,
                            status="failed",
                            request_summary=safe_json({"subject": "generated_image", "asset_count": len(asset_paths) + 1}),
                            response_summary=safe_json(exc.review.model_dump() if exc.review else {}),
                            error=str(exc),
                            dry_run=False,
                        )
                    )
                    session.commit()
            return
        except Exception as exc:
            destination.unlink(missing_ok=True)
            error = f"内容安全拦截：安全审计失败：{exc}"
            with session_factory() as session:
                item = session.get(GenerationItem, item_id)
                if item:
                    item.status = "failed"
                    item.error = error
                    session.add(
                        ExecutionLog(
                            job_id=item.job_id,
                            item_id=item.id,
                            node="content_safety",
                            status="failed",
                            request_summary=safe_json({"subject": "generated_image", "asset_count": len(asset_paths) + 1}),
                            response_summary="{}",
                            error=error,
                            dry_run=False,
                        )
                    )
                    session.commit()
            return
        with session_factory() as session:
            item = session.get(GenerationItem, item_id)
            provider = session.scalar(select(Provider).where(Provider.code == used_code))
            version = GenerationVersion(
                item_id=item.id,
                version_no=1,
                instruction="Live 初始生成",
                file_path=str(destination),
                url=f"/files/results/{result_name}",
                metadata_json=safe_json({"dry_run": False, "provider": used_code, "actual_size": [width, height]}),
            )
            session.add(version)
            session.flush()
            item.current_version_id = version.id
            item.provider_id = provider.id if provider else None
            item.status = "succeeded"
            item.error = None
            session.add(
                ExecutionLog(
                    job_id=item.job_id,
                    item_id=item.id,
                    node="content_safety",
                    provider_id=safety_provider.id,
                    status="succeeded",
                    request_summary=safe_json({"subject": "generated_image", "asset_count": len(asset_paths) + 1}),
                    response_summary=safe_json(safety_review.model_dump()),
                    dry_run=False,
                )
            )
            session.add(
                ExecutionLog(
                    job_id=item.job_id,
                    item_id=item.id,
                    node="image_generate",
                    provider_id=item.provider_id,
                    status="succeeded",
                    request_summary=safe_json({"route_symbol": "#@", "aspect_ratio": aspect_ratio, "prompt_chars": len(prompt)}),
                    response_summary=safe_json({"url": version.url, "bytes": len(image_bytes)}),
                    dry_run=False,
                )
            )
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            item = session.get(GenerationItem, item_id)
            if item:
                item.status = "failed"
                item.error = str(exc)
                session.add(
                    ExecutionLog(
                        job_id=item.job_id,
                        item_id=item.id,
                        node="image_generate",
                        status="failed",
                        request_summary=safe_json({"route_symbol": "#@", "aspect_ratio": aspect_ratio}),
                        response_summary="{}",
                        error=str(exc),
                        dry_run=False,
                    )
                )
                session.commit()


def create_dryrun_child_version(session: Session, item: GenerationItem, instruction: str, settings: Settings) -> GenerationVersion:
    current = session.get(GenerationVersion, item.current_version_id)
    if not current:
        raise ValueError("当前版本不存在")
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    source = DEMO_ASSETS[version_no % len(DEMO_ASSETS)]
    result_name = f"{item.job_id}-{item.index + 1}-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    shutil.copy2(source, destination)
    version = GenerationVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=instruction,
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": True, "demo_asset": source.name}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    session.add(
        ExecutionLog(
            job_id=item.job_id,
            item_id=item.id,
            node="image_generate_edit",
            status="succeeded",
            request_summary=safe_json({"instruction": instruction, "parent_version_id": current.id}),
            response_summary=safe_json({"url": version.url}),
            dry_run=True,
        )
    )
    session.commit()
    session.refresh(version)
    return version


async def create_live_child_version(
    session: Session,
    item: GenerationItem,
    instruction: str,
    settings: Settings,
    cipher: ApiKeyCipher,
) -> GenerationVersion:
    current = session.get(GenerationVersion, item.current_version_id)
    job = session.get(GenerationJob, item.job_id)
    if not current or not job:
        raise ValueError("当前版本或任务不存在")
    llm_default = _enabled_provider(session, "llm", "default")
    llm_fallback = _enabled_provider(session, "llm", "fallback")
    params = json.loads(job.params_json)
    image_codes = image_provider_route(params.get("model_preference", "fidelity"))
    for image_code in image_codes:
        _enabled_provider_by_code(session, image_code)
    asset_ids = json.loads(job.asset_ids_json)
    original_paths = [asset.file_path for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()]
    client = ProviderClient()
    prompt_versions = params.get("_prompt_versions") or {}
    edit_prompt = session.get(PromptVersion, prompt_versions.get("edit-rewrite"))
    if not edit_prompt:
        raise RuntimeError("二次编辑 Prompt 版本不存在")
    safety_prompt = session.get(PromptVersion, prompt_versions.get("content-safety-review"))
    if not safety_prompt:
        raise RuntimeError("内容安全审计 Prompt 版本不存在")
    input_paths = [current.file_path, *original_paths]
    rewritten, _ = await _call_llm_with_fallback(
        client,
        llm_default,
        llm_fallback,
        cipher,
        edit_prompt.content,
        json.dumps({"instruction": instruction, "original_prompt": json.loads(item.prompt_text)}, ensure_ascii=False),
        image_paths=input_paths,
    )
    try:
        prompt = json.loads(rewritten)["prompt"]
    except Exception:
        prompt = rewritten
    async def generate(provider_code: str) -> bytes:
        provider = session.scalar(select(Provider).where(Provider.code == provider_code))
        if not provider or not provider.encrypted_api_key:
            raise RuntimeError(f"Provider {provider_code} 不可用")
        return await client.generate_image(
            provider,
            cipher.decrypt(provider.encrypted_api_key),
            prompt,
            input_paths,
            params["aspect_ratio"],
        )

    image_bytes, used_code = await run_image_route(image_codes, generate)
    with Image.open(BytesIO(image_bytes)) as image:
        image.verify()
    with Image.open(BytesIO(image_bytes)) as image:
        width, height = image.size
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    result_name = f"{item.job_id}-{item.index + 1}-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    destination.write_bytes(image_bytes)
    try:
        safety_review, safety_provider = await run_content_safety_review(
            client,
            llm_default,
            llm_fallback,
            cipher,
            safety_prompt,
            subject="generated_image_edit",
            text=prompt,
            image_paths=[str(destination), *input_paths],
        )
        ensure_content_safe(safety_review, "内容安全拦截")
    except ContentSafetyBlocked as exc:
        destination.unlink(missing_ok=True)
        session.add(
            ExecutionLog(
                job_id=item.job_id,
                item_id=item.id,
                node="content_safety",
                provider_id=safety_provider.id if "safety_provider" in locals() else None,
                status="failed",
                request_summary=safe_json({"subject": "generated_image_edit", "asset_count": len(input_paths) + 1}),
                response_summary=safe_json(exc.review.model_dump() if exc.review else {}),
                error=str(exc),
                dry_run=False,
            )
        )
        session.commit()
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        error = f"内容安全拦截：安全审计失败：{exc}"
        session.add(
            ExecutionLog(
                job_id=item.job_id,
                item_id=item.id,
                node="content_safety",
                status="failed",
                request_summary=safe_json({"subject": "generated_image_edit", "asset_count": len(input_paths) + 1}),
                response_summary="{}",
                error=error,
                dry_run=False,
            )
        )
        session.commit()
        raise RuntimeError(error) from exc
    version = GenerationVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=instruction,
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": False, "provider": used_code, "capability_routed": True, "actual_size": [width, height]}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    provider = session.scalar(select(Provider).where(Provider.code == used_code))
    item.provider_id = provider.id if provider else item.provider_id
    session.add(
        ExecutionLog(
            job_id=item.job_id,
            item_id=item.id,
            node="content_safety",
            provider_id=safety_provider.id,
            status="succeeded",
            request_summary=safe_json({"subject": "generated_image_edit", "asset_count": len(input_paths) + 1}),
            response_summary=safe_json(safety_review.model_dump()),
            dry_run=False,
        )
    )
    session.add(
        ExecutionLog(
            job_id=item.job_id,
            item_id=item.id,
            node="image_generate_edit",
            provider_id=item.provider_id,
            status="succeeded",
            request_summary=safe_json({"instruction": instruction, "input_image_count": len(input_paths)}),
            response_summary=safe_json({"url": version.url, "version_no": version_no}),
            dry_run=False,
        )
    )
    session.commit()
    session.refresh(version)
    return version


async def retry_failed_live_items(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    with session_factory() as session:
        job = session.get(GenerationJob, job_id)
        if not job or job.dry_run:
            return
        failed_ids = session.scalars(
            select(GenerationItem.id).where(GenerationItem.job_id == job_id, GenerationItem.status == "failed")
        ).all()
        if not failed_ids:
            return
        params = json.loads(job.params_json)
        asset_ids = json.loads(job.asset_ids_json)
        asset_paths = [asset.file_path for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()]
        image_codes = image_provider_route(params.get("model_preference", "fidelity"))
        for image_code in image_codes:
            _enabled_provider_by_code(session, image_code)
        job.status = "running"
        session.commit()
    semaphore = asyncio.Semaphore(settings.max_job_concurrency)
    client = ProviderClient()

    async def guarded(item_id: str) -> None:
        async with semaphore:
            await _run_live_item(
                item_id, session_factory, settings, cipher, client, image_codes, asset_paths, params["aspect_ratio"], params
            )

    await asyncio.gather(*(guarded(item_id) for item_id in failed_ids))
    with session_factory() as session:
        job = session.get(GenerationJob, job_id)
        statuses = session.scalars(select(GenerationItem.status).where(GenerationItem.job_id == job_id)).all()
        successes, failures = statuses.count("succeeded"), statuses.count("failed")
        job.status = "succeeded" if failures == 0 else "failed" if successes == 0 else "partial_failed"
        job.completed_at = utcnow()
        session.commit()
