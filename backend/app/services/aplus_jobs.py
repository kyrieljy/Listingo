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
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.config import Settings
from backend.app.models import AplusItem, AplusJob, AplusVersion, Asset, PromptVersion, Provider, utcnow
from backend.app.security import ApiKeyCipher
from backend.app.services.jobs import _call_llm_with_fallback, _enabled_provider, _enabled_provider_by_code
from backend.app.services.prompt_contract import parse_product_facts
from backend.app.services.providers import ProviderClient
from backend.app.services.redaction import safe_json


DEMO_ASSET_DIR = Path(__file__).resolve().parents[1] / "static" / "demo"
DEMO_ASSETS = [DEMO_ASSET_DIR / f"aplus-outdoor-module-{index:02d}.png" for index in range(1, 11)]

DEFAULT_MODULES = ["首屏主视觉", "核心卖点图", "使用场景图", "多角度图", "场景氛围图", "商品细节图"]
MOBILE_EDIT_PROVIDER_CODE = "aplus-mobile-edit-low-cost"
WEB_PROVIDER_CODE = "yunwu-image-2"
OUTPUT_MODE_LABELS = {
    "detail": "详情页",
    "amazon_aplus_standard": "普通 A+",
    "amazon_aplus_advanced_web": "高级 A+ Web",
    "amazon_aplus_advanced_mobile": "高级 A+ 移动端",
}


def serialize_aplus_version(version: AplusVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "parent_version_id": version.parent_version_id,
        "version_no": version.version_no,
        "instruction": version.instruction,
        "url": version.url,
        "created_at": version.created_at,
    }


def serialize_aplus_job(job: AplusJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "dry_run": job.dry_run,
        "progress": job.progress,
        "count": job.count,
        "params": json.loads(job.params_json),
        "source_plan_job_id": job.source_plan_job_id,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "items": [
            {
                "id": item.id,
                "index": item.index,
                "module_index": item.module_index,
                "module_name": item.module_name,
                "output_mode": item.output_mode,
                "aspect_ratio": item.aspect_ratio,
                "image_prompt": item.image_prompt,
                "copy_requirements": item.copy_requirements,
                "prompt_text": item.prompt_text,
                "status": item.status,
                "provider_id": item.provider_id,
                "source_web_item_id": item.source_web_item_id,
                "error": item.error,
                "current_version_id": item.current_version_id,
                "versions": [serialize_aplus_version(version) for version in item.versions],
            }
            for item in job.items
        ],
    }


def load_aplus_job(session: Session, job_id: str) -> AplusJob | None:
    return session.scalar(
        select(AplusJob)
        .where(AplusJob.id == job_id)
        .options(selectinload(AplusJob.items).selectinload(AplusItem.versions))
    )


def _replace_prompt_variables(content: str, variables: dict[str, Any]) -> str:
    rendered = content
    replacements = {
        "${image_product}": "随请求携带的商品参考图",
        "${product_info}": str(variables.get("product_info", "")),
        "${platform}": str(variables.get("platform", "")),
        "${market}": str(variables.get("market", "")),
        "${language}": str(variables.get("language", "")),
        "${selected_modules}": str(variables.get("selected_modules", "")),
        "${970:600}": str(variables.get("aspect_ratio", "")),
    }
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def _parse_aplus_plan(raw: str, selected_modules: list[str]) -> tuple[str, list[dict[str, Any]]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("A+ 方案返回不是 JSON")
        parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("A+ 方案 JSON 顶层必须是对象")
    modules = parsed.get("modules")
    if not isinstance(modules, list):
        raise ValueError("A+ 方案缺少 modules 数组")
    by_name: dict[str, dict[str, Any]] = {}
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        image_type = str(module.get("image_type") or selected_modules[index] if index < len(selected_modules) else "")
        module_name = next((name for name in selected_modules if image_type.startswith(name) or name in image_type), "")
        if not module_name and index < len(selected_modules):
            module_name = selected_modules[index]
        if not module_name:
            continue
        by_name[module_name] = {
            "module_name": module_name,
            "module_index": int(module.get("index") or (selected_modules.index(module_name) + 1)),
            "image_type": image_type or module_name,
            "image_prompt": str(module.get("image_prompt") or module.get("picture_requirement") or ""),
            "copy_requirements": str(module.get("copy_requirements") or module.get("copywriting_requirements") or ""),
        }
    missing = [name for name in selected_modules if name not in by_name]
    if missing:
        raise ValueError(f"A+ 方案缺少选中模块：{', '.join(missing)}")
    return str(parsed.get("global_plan") or ""), [by_name[name] for name in selected_modules]


def _dryrun_modules(params: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    selected = params.get("selected_modules") or DEFAULT_MODULES
    product_info = params.get("product_info") or "根据商品图识别产品，并围绕核心卖点规划详情页。"
    modules = [
        {
            "module_name": name,
            "module_index": index + 1,
            "image_type": f"{name}: Dryrun 详情页模块",
            "image_prompt": f"{name}，围绕“{product_info}”规划高转化电商详情页画面，产品保持为第一主体，构图清晰，卖点准确。",
            "copy_requirements": f"使用{params.get('language')}，只表达已提供或图片可见的事实，不虚构参数和承诺。",
        }
        for index, name in enumerate(selected)
    ]
    return "Dryrun A+ 详情页方案：按选中模块生成可确认的模块规划。", modules


def _version_for_item(session: Session, item: AplusItem) -> AplusVersion | None:
    if item.current_version_id:
        return next((version for version in item.versions if version.id == item.current_version_id), None)
    return item.versions[-1] if item.versions else None


def _create_dryrun_version(session: Session, item: AplusItem, settings: Settings) -> None:
    source = DEMO_ASSETS[item.index % len(DEMO_ASSETS)]
    result_name = f"aplus-{item.job_id}-{item.index + 1}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    shutil.copy2(source, destination)
    version = AplusVersion(
        item_id=item.id,
        version_no=1,
        instruction="Dryrun A+ 生成",
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": True, "demo_asset": source.name, "aspect_ratio": item.aspect_ratio}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    item.status = "succeeded"


def create_plan_items(session: Session, job: AplusJob, global_plan: str, modules: list[dict[str, Any]]) -> None:
    params = json.loads(job.params_json)
    params["global_plan"] = global_plan
    job.params_json = json.dumps(params, ensure_ascii=False)
    for index, module in enumerate(modules):
        prompt_text = json.dumps(module, ensure_ascii=False)
        session.add(
            AplusItem(
                job_id=job.id,
                index=index,
                module_index=int(module["module_index"]),
                module_name=str(module["module_name"]),
                output_mode="plan",
                aspect_ratio="",
                image_prompt=str(module["image_prompt"]),
                copy_requirements=str(module["copy_requirements"]),
                prompt_text=prompt_text,
                status="succeeded",
            )
        )
    job.count = len(modules)
    job.progress = 100
    job.status = "succeeded"
    job.completed_at = utcnow()


async def run_aplus_plan_job(
    job_id: str,
    session_factory: sessionmaker[Session],
    cipher: ApiKeyCipher,
) -> None:
    client = ProviderClient()
    try:
        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if not job:
                return
            job.status = "running"
            job.started_at = utcnow()
            params = json.loads(job.params_json)
            asset_ids = json.loads(job.asset_ids_json)
            prompt_version = session.get(PromptVersion, job.prompt_version_id)
            if not prompt_version:
                raise RuntimeError("A+ Meta Prompt 未启用")
            session.commit()

        if job.dry_run:
            global_plan, modules = _dryrun_modules(params)
        else:
            with session_factory() as session:
                assets = session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
                asset_paths = [asset.file_path for asset in assets]
                llm_default = _enabled_provider(session, "llm", "default")
                llm_fallback = _enabled_provider(session, "llm", "fallback")
                prompt_versions = params.get("_prompt_versions") or {}
                vision_prompt = session.get(PromptVersion, prompt_versions.get("product-vision"))
                if not vision_prompt:
                    raise RuntimeError("商品视觉事实 Prompt 未启用")
            facts_raw, _ = await _call_llm_with_fallback(
                client,
                llm_default,
                llm_fallback,
                cipher,
                vision_prompt.content,
                json.dumps({"product_info": params.get("product_info", "")}, ensure_ascii=False),
                image_paths=asset_paths,
            )
            product_facts = parse_product_facts(facts_raw)
            input_mode = "image_with_text" if str(params.get("product_info") or "").strip() else "image_only"
            product_info = params.get("product_info") or json.dumps(product_facts.model_dump(), ensure_ascii=False)
            variables = {
                "product_info": product_info,
                "platform": params["platform"],
                "market": params["market"],
                "language": params["language"],
                "selected_modules": ",".join(params["selected_modules"]),
                "aspect_ratio": ", ".join(target["aspect_ratio"] for target in params["output_targets"]),
            }
            system_prompt = _replace_prompt_variables(prompt_version.content, variables)
            user_prompt = json.dumps(
                {
                    "input_mode": input_mode,
                    "product_info": product_info,
                    "product_facts": product_facts.model_dump(),
                    "platform": params["platform"],
                    "market": params["market"],
                    "language": params["language"],
                    "selected_modules": params["selected_modules"],
                    "output_targets": params["output_targets"],
                    "instruction": "严格输出 JSON。若 product_info 有文字，卖点事实只能来自文字；若只有图片，则基于图片识别商品事实。",
                },
                ensure_ascii=False,
            )
            raw_plan, _ = await _call_llm_with_fallback(
                client,
                llm_default,
                llm_fallback,
                cipher,
                system_prompt,
                user_prompt,
                image_paths=asset_paths,
            )
            global_plan, modules = _parse_aplus_plan(raw_plan, params["selected_modules"])

        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if job:
                create_plan_items(session, job, global_plan, modules)
                session.commit()
    except Exception as exc:
        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                session.commit()


def _build_generation_items(session: Session, generation_job: AplusJob, plan_job: AplusJob, output_targets: list[dict[str, str]], module_item_ids: list[str]) -> None:
    plan_items = [item for item in plan_job.items if item.output_mode == "plan"]
    if module_item_ids:
        allowed = set(module_item_ids)
        plan_items = [item for item in plan_items if item.id in allowed]
    index = 0
    web_by_module: dict[int, AplusItem] = {}
    needs_advanced_web = any(target["mode"] == "amazon_aplus_advanced_web" for target in output_targets)
    for plan_item in plan_items:
        if needs_advanced_web:
            web_item = AplusItem(
                job_id=generation_job.id,
                index=index,
                module_index=plan_item.module_index,
                module_name=plan_item.module_name,
                output_mode="amazon_aplus_advanced_web",
                aspect_ratio="1464:600",
                image_prompt=plan_item.image_prompt,
                copy_requirements=plan_item.copy_requirements,
                prompt_text=plan_item.prompt_text,
                status="queued",
            )
            session.add(web_item)
            session.flush()
            web_by_module[plan_item.module_index] = web_item
            index += 1
        for target in output_targets:
            if target["mode"] == "amazon_aplus_advanced_web":
                continue
            source = web_by_module.get(plan_item.module_index) if target["mode"] == "amazon_aplus_advanced_mobile" else None
            item = AplusItem(
                job_id=generation_job.id,
                index=index,
                module_index=plan_item.module_index,
                module_name=plan_item.module_name,
                output_mode=target["mode"],
                aspect_ratio=target["aspect_ratio"],
                image_prompt=plan_item.image_prompt,
                copy_requirements=plan_item.copy_requirements,
                prompt_text=plan_item.prompt_text,
                source_web_item_id=source.id if source else None,
                status="queued",
            )
            session.add(item)
            session.flush()
            index += 1
    generation_job.count = index


def create_aplus_generation_job_from_plan(
    session: Session,
    plan_job: AplusJob,
    payload: Any,
    prompt_version_id: str,
) -> AplusJob:
    params = {
        "plan_job_id": plan_job.id,
        "module_item_ids": payload.module_item_ids,
        "output_targets": [target.model_dump() for target in payload.output_targets],
        "plan_params": json.loads(plan_job.params_json),
    }
    job = AplusJob(
        job_type="generation",
        status="queued",
        dry_run=payload.dry_run,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=plan_job.asset_ids_json,
        count=0,
        progress=0,
        prompt_version_id=prompt_version_id,
        source_plan_job_id=plan_job.id,
    )
    session.add(job)
    session.flush()
    _build_generation_items(session, job, plan_job, params["output_targets"], payload.module_item_ids)
    return job


async def run_aplus_generation_job(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    client = ProviderClient()
    try:
        with session_factory() as session:
            job = load_aplus_job(session, job_id)
            if not job:
                return
            job.status = "running"
            job.started_at = utcnow()
            params = json.loads(job.params_json)
            asset_ids = json.loads(job.asset_ids_json)
            asset_paths = [asset.file_path for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()]
            if not job.dry_run:
                _enabled_provider_by_code(session, WEB_PROVIDER_CODE)
                if any(item.output_mode == "amazon_aplus_advanced_mobile" and item.source_web_item_id for item in job.items):
                    _enabled_provider_by_code(session, MOBILE_EDIT_PROVIDER_CODE)
            session.commit()

        if job.dry_run:
            with session_factory() as session:
                job = load_aplus_job(session, job_id)
                for item in job.items:
                    item.status = "running"
                    _create_dryrun_version(session, item, settings)
                    job.progress = round(((item.index + 1) / max(job.count, 1)) * 100)
                    session.commit()
                job.status = "succeeded"
                job.progress = 100
                job.completed_at = utcnow()
                session.commit()
            return

        with session_factory() as session:
            item_ids = session.scalars(select(AplusItem.id).where(AplusItem.job_id == job_id).order_by(AplusItem.index)).all()

        semaphore = asyncio.Semaphore(settings.max_job_concurrency)
        for item_id in item_ids:
            async with semaphore:
                await _run_generation_item(item_id, session_factory, settings, cipher, client, asset_paths, params)

        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            statuses = session.scalars(select(AplusItem.status).where(AplusItem.job_id == job_id)).all()
            success_count = statuses.count("succeeded")
            failed_count = statuses.count("failed")
            job.status = "succeeded" if failed_count == 0 else "failed" if success_count == 0 else "partial_failed"
            job.progress = 100
            job.completed_at = utcnow()
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                session.commit()


async def _run_generation_item(
    item_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
    client: ProviderClient,
    asset_paths: list[str],
    params: dict[str, Any],
) -> None:
    with session_factory() as session:
        item = session.get(AplusItem, item_id)
        if not item:
            return
        item.status = "running"
        session.commit()
        input_paths = asset_paths
        provider_code = WEB_PROVIDER_CODE
        if item.output_mode == "amazon_aplus_advanced_mobile" and item.source_web_item_id:
            provider_code = MOBILE_EDIT_PROVIDER_CODE
            source = session.scalar(
                select(AplusItem)
                .where(AplusItem.id == item.source_web_item_id)
                .options(selectinload(AplusItem.versions))
            )
            source_version = _version_for_item(session, source) if source else None
            if not source_version or not source_version.file_path:
                item.status = "failed"
                item.error = "高级 A+ 移动端缺少已生成的 Web 端图片"
                session.commit()
                return
            input_paths = [source_version.file_path]
        provider = session.scalar(select(Provider).where(Provider.code == provider_code))
        if not provider or not provider.encrypted_api_key:
            item.status = "failed"
            item.error = f"Provider {provider_code} 未启用或缺少 API Key"
            session.commit()
            return
        prompt = (
            f"输出模式：{OUTPUT_MODE_LABELS.get(item.output_mode, item.output_mode)}；目标画面比例：{item.aspect_ratio}。\n"
            f"模块：{item.module_name}。\n"
            f"画面需求：{item.image_prompt}\n"
            f"文案需求：{item.copy_requirements}\n"
            "必须保持商品外观、颜色、结构、材质、标识和包装事实一致；不得虚构用户未提供的参数、认证、功效或承诺。"
        )
        if item.output_mode == "amazon_aplus_advanced_mobile" and item.source_web_item_id:
            prompt += "\n以输入的高级 A+ Web 图为视觉母版，重排为 600:450 移动端版式，保留同一模块卖点和视觉资产，不做简单拉伸。"
        elif item.output_mode == "amazon_aplus_advanced_mobile":
            prompt += "\n按高级 A+ Web 端同等画面规划标准直接生成 600:450 移动端版式，构图为独立移动端成图，不依赖 Web 母版或简单裁切。"

    try:
        image_bytes = await client.generate_image(
            provider,
            cipher.decrypt(provider.encrypted_api_key),
            prompt,
            input_paths,
            item.aspect_ratio,
        )
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
        result_name = f"aplus-{item_id}-{uuid4().hex[:8]}.png"
        destination = settings.results_dir / result_name
        destination.write_bytes(image_bytes)
        with session_factory() as session:
            item = session.get(AplusItem, item_id)
            provider = session.scalar(select(Provider).where(Provider.code == provider_code))
            version = AplusVersion(
                item_id=item.id,
                version_no=1,
                instruction="Live A+ 生成",
                file_path=str(destination),
                url=f"/files/results/{result_name}",
                metadata_json=safe_json({"dry_run": False, "provider": provider_code, "actual_size": [width, height]}),
            )
            session.add(version)
            session.flush()
            item.current_version_id = version.id
            item.provider_id = provider.id if provider else None
            item.status = "succeeded"
            item.error = None
            job = session.get(AplusJob, item.job_id)
            done = session.scalars(
                select(AplusItem.status).where(AplusItem.job_id == item.job_id, AplusItem.status.in_(["succeeded", "failed"]))
            ).all()
            if job:
                job.progress = round((len(done) / max(job.count, 1)) * 100)
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            item = session.get(AplusItem, item_id)
            if item:
                item.status = "failed"
                item.error = str(exc)
                session.commit()
