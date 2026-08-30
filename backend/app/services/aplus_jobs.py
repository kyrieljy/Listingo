from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import re
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.config import Settings
from backend.app.models import AplusItem, AplusJob, AplusVersion, Asset, ExecutionLog, PromptVersion, utcnow
from backend.app.schemas import A_PLUS_MODULE_TOTAL_LIMIT
from backend.app.security import ApiKeyCipher
from backend.app.core.runtime import default_runtime
from backend.app.services.execution import run_image_route
from backend.app.services.jobs import _call_llm_with_fallback, _enabled_provider, validate_generated_image_bytes
from backend.app.services.provider_routing import (
    ProviderSnapshot,
    cached_provider_by_code,
    provider_display_names_by_code,
    route_provider_codes,
)
from backend.app.services.provider_limiter import provider_slot
from backend.app.services.prompt_contract import parse_product_facts, sensitive_image_categories
from backend.app.services.providers import ProviderClient, provider_requires_public_urls, requested_image_size
from backend.app.services.redaction import safe_json
from backend.app.services.sensitive_words import load_sensitive_word_snapshot
from backend.app.services.storage import public_file_url
from backend.app.services.subscriptions import confirm_quota, release_quota


AplusPlanRepairCallback = Callable[[str, str], Awaitable[str]]

DEMO_ASSET_DIR = Path(__file__).resolve().parents[1] / "static" / "demo"
DEMO_ASSETS = [DEMO_ASSET_DIR / f"aplus-outdoor-module-{index:02d}.png" for index in range(1, 11)]
JOB_FINAL_STATUSES = {"succeeded", "partial_failed", "failed", "cancelled", "partial_cancelled"}
ITEM_FINAL_STATUSES = {"succeeded", "failed", "cancelled"}
CANCEL_REQUESTED_STATUSES = {"cancelling", "cancelled", "partial_cancelled"}
USER_CANCELLED_ERROR = "用户已取消任务"

DEFAULT_MODULE_SELECTIONS = [
    {"name": "商品主视觉", "count": 1},
    {"name": "卖点拆解", "count": 1},
    {"name": "生活场景", "count": 1},
    {"name": "全方位展示", "count": 1},
    {"name": "情绪氛围", "count": 1},
    {"name": "品质细看", "count": 1},
]
OUTPUT_MODE_LABELS = {
    "detail": "详情页",
    "amazon_aplus_standard": "普通 A+",
    "amazon_aplus_advanced_web": "高级 A+ Web",
    "amazon_aplus_advanced_mobile": "高级 A+ 移动端",
}
A_PLUS_ATLAS_DETAIL_PROVIDER_CODE = "atlas-gpt-image-2-generate"
A_PLUS_ATLAS_MOBILE_PROVIDER_CODE = "atlas-gpt-image-2-edit"


def _normalize_module_selections(params: dict[str, Any]) -> list[dict[str, Any]]:
    selections = params.get("module_selections")
    if not selections:
        selections = [{"name": name, "count": 1} for name in (params.get("selected_modules") or [])]
    if not selections:
        selections = DEFAULT_MODULE_SELECTIONS
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        name = str(selection.get("name") or "").strip()
        count = int(selection.get("count") or 0)
        if not name or count <= 0 or name in seen:
            continue
        seen.add(name)
        total += count
        normalized.append({"name": name, "count": count})
    if total < 1:
        raise ValueError("请至少生成 1 张详情页模块")
    if total > A_PLUS_MODULE_TOTAL_LIMIT:
        raise ValueError(f"详情页模块最多生成 {A_PLUS_MODULE_TOTAL_LIMIT} 张")
    return normalized


def _expand_module_selections(selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    module_index = 1
    for selection in selections:
        name = str(selection["name"])
        count = int(selection["count"])
        for instance_index in range(1, count + 1):
            expanded.append(
                {
                    "module_name": name,
                    "instance_index": instance_index,
                    "module_count": count,
                    "module_index": module_index,
                }
            )
            module_index += 1
    return expanded


def _module_text(selections: list[dict[str, Any]]) -> str:
    return "/".join(f"{selection['name']}{int(selection['count'])}张" for selection in selections)


def _planning_canvas(output_targets: list[dict[str, str]]) -> dict[str, Any]:
    preferred = (
        next((target for target in output_targets if target.get("mode") == "amazon_aplus_advanced_web"), None)
        or next((target for target in output_targets if target.get("mode") == "amazon_aplus_standard"), None)
        or output_targets[0]
    )
    ratio = preferred.get("aspect_ratio", "1:1")
    sizes = {
        "970:600": (970, 600),
        "1464:600": (1464, 600),
        "600:450": (600, 450),
        "1:1": (1024, 1024),
        "3:4": (900, 1200),
        "9:16": (1080, 1920),
        "16:9": (1600, 900),
    }
    width, height = sizes.get(ratio, (1024, 1024))
    return {"width": width, "height": height, "proportion": ratio, "target": preferred}


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
                "provider_task_id": item.provider_task_id,
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


def aplus_status_from_item_statuses(statuses: list[str]) -> str:
    success_count = statuses.count("succeeded")
    failed_count = statuses.count("failed")
    cancelled_count = statuses.count("cancelled")
    if cancelled_count:
        return "partial_cancelled" if success_count or failed_count else "cancelled"
    return "succeeded" if failed_count == 0 else "failed" if success_count == 0 else "partial_failed"


def finalize_aplus_cancellation(session: Session, job: AplusJob) -> None:
    for item in job.items:
        if item.status == "queued":
            item.status = "cancelled"
            item.error = USER_CANCELLED_ERROR
    statuses = [item.status for item in job.items]
    if not statuses:
        job.status = "cancelled"
        job.progress = 100
        job.completed_at = utcnow()
        return
    if any(status in {"queued", "running"} for status in statuses):
        job.status = "cancelling"
        return
    job.status = aplus_status_from_item_statuses(statuses)
    job.progress = 100
    job.completed_at = utcnow()
    sync_aplus_quota(session, job)


def sync_aplus_quota(session: Session, job: AplusJob) -> None:
    if job.status in {"succeeded", "partial_failed"}:
        confirm_quota(session, ref_type="aplus_job", ref_id=job.id)
    elif job.status in {"failed", "cancelled", "partial_cancelled"}:
        release_quota(session, ref_type="aplus_job", ref_id=job.id)


def cancel_aplus_job(session: Session, job: AplusJob) -> AplusJob:
    if job.status in JOB_FINAL_STATUSES:
        return job
    job.status = "cancelling"
    finalize_aplus_cancellation(session, job)
    sync_aplus_quota(session, job)
    session.commit()
    session.refresh(job)
    return job


def aplus_cancel_requested(session_factory: sessionmaker[Session], job_id: str) -> bool:
    with session_factory() as session:
        job = load_aplus_job(session, job_id)
        if not job:
            return True
        if job.status not in CANCEL_REQUESTED_STATUSES:
            return False
        finalize_aplus_cancellation(session, job)
        sync_aplus_quota(session, job)
        session.commit()
        return True


def _replace_prompt_variables(content: str, variables: dict[str, Any]) -> str:
    rendered = content
    replacements = {
        "${image_product}": "随请求携带的商品参考图",
        "${product_info}": str(variables.get("product_info", "")),
        "${platform}": str(variables.get("platform", "")),
        "${market}": str(variables.get("market", "")),
        "${language}": str(variables.get("language", "")),
        "${input_language}": str(variables.get("input_language", "")),
        "${modules}": str(variables.get("modules", "")),
        "${selected_modules}": str(variables.get("selected_modules", variables.get("modules", ""))),
        "${brand_style}": str(variables.get("brand_style", "")),
        "${reference_assets}": str(variables.get("reference_assets", "")),
        "${module_selections}": str(variables.get("module_selections", "")),
        "${canvas}": str(variables.get("canvas", "")),
        "${output_targets}": str(variables.get("output_targets", "")),
        "${width}": str(variables.get("width", "")),
        "${height}": str(variables.get("height", "")),
        "${proportion}": str(variables.get("proportion", "")),
        "${970:600}": str(variables.get("aspect_ratio", "")),
    }
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def _expected_module_items(module_selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _expand_module_selections(module_selections)


def _match_expected_module_name(text: str, expected_names: set[str]) -> str:
    normalized = text.strip()
    if normalized in expected_names:
        return normalized
    return next((name for name in expected_names if normalized.startswith(name) or name in normalized), "")


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_image_prompt(module_name: str, image_type: str, image_prompt: str) -> str:
    prompt = image_prompt.strip()
    header = image_type.strip() or module_name
    if prompt.startswith("#@"):
        return prompt
    if prompt:
        return f"#@ {header}\n{prompt}"
    return f"#@ {header}"


def _copy_requirements_from_block(block: str) -> str:
    for marker in ("【画面文字内容】", "【画面文案要求】", "【文案要求】"):
        if marker not in block:
            continue
        section = block.split(marker, 1)[1]
        section = re.split(r"\n\s*【", section, maxsplit=1)[0]
        return section.strip()
    if "此图无需添加任何文字" in block:
        return "此图无需添加任何文字"
    return ""


def _ordered_modules_from_map(
    by_key: dict[tuple[str, int], dict[str, Any]],
    expected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing = [
        f"{item['module_name']}#{item['instance_index']}"
        for item in expected
        if (str(item["module_name"]), int(item["instance_index"])) not in by_key
    ]
    if missing:
        raise ValueError(f"A+ 方案缺少选中模块：{', '.join(missing)}")
    return [by_key[(str(item["module_name"]), int(item["instance_index"]))] for item in expected]


def _next_non_whitespace_index(source: str, start: int) -> int:
    index = start
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _insert_missing_json_value_commas(source: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(source):
        output.append(char)
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                next_index = _next_non_whitespace_index(source, index + 1)
                if next_index < len(source) and source[next_index] in '"{[':
                    output.append(",")
            continue
        if char == '"':
            in_string = True
        elif char in "}]":
            next_index = _next_non_whitespace_index(source, index + 1)
            if next_index < len(source) and source[next_index] in '"{[':
                output.append(",")
    return "".join(output)


def _load_aplus_json_object(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        extracted = stripped[start : end + 1]
        if extracted != stripped:
            candidates.append(extracted)
    elif not stripped.startswith("{"):
        raise ValueError("A+ 方案返回不是 JSON")

    last_json_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        for source in (candidate, _insert_missing_json_value_commas(candidate)):
            try:
                parsed = json.loads(source)
            except json.JSONDecodeError as exc:
                last_json_error = exc
                continue
            if not isinstance(parsed, dict):
                raise ValueError("A+ 方案 JSON 顶层必须是对象")
            return parsed
    if last_json_error:
        raise last_json_error
    raise ValueError("A+ 方案返回不是 JSON")


def _parse_aplus_json_plan(raw: str, expected: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    parsed = _load_aplus_json_object(raw)
    modules = parsed.get("modules")
    if not isinstance(modules, list):
        raise ValueError("A+ 方案缺少 modules 数组")
    if len(modules) != len(expected):
        raise ValueError(f"A+ 方案 modules 数量应为 {len(expected)}，实际为 {len(modules)}")
    expected_names = {str(item["module_name"]) for item in expected}
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    occurrences: dict[str, int] = {}
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        expected_item = expected[index]
        raw_module_name = str(module.get("module_name") or "")
        image_type = str(module.get("image_type") or "")
        image_prompt = str(module.get("image_prompt") or module.get("picture_requirement") or "")
        module_name = _match_expected_module_name(raw_module_name, expected_names)
        if not module_name:
            module_name = _match_expected_module_name(image_type, expected_names)
        if not module_name:
            module_name = _match_expected_module_name(image_prompt, expected_names)
        if not module_name:
            module_name = str(expected_item["module_name"])
        if not module_name:
            continue
        explicit_instance = _positive_int(module.get("instance_index"))
        if explicit_instance is None:
            occurrences[module_name] = occurrences.get(module_name, 0) + 1
            instance_index = occurrences[module_name]
        else:
            instance_index = explicit_instance
            occurrences[module_name] = max(occurrences.get(module_name, 0), instance_index)
        module_index = int(expected_item["module_index"])
        key = (module_name, instance_index)
        if key in by_key:
            raise ValueError(f"A+ 方案重复模块：{module_name}#{instance_index}")
        image_type = image_type or f"{module_name}: {module.get('topic') or module.get('core_theme') or ''}".strip()
        by_key[key] = {
            "module_name": module_name,
            "instance_index": instance_index,
            "module_index": module_index,
            "image_type": image_type or module_name,
            "image_prompt": _normalize_image_prompt(module_name, image_type or module_name, image_prompt),
            "copy_requirements": str(module.get("copy_requirements") or module.get("copywriting_requirements") or ""),
        }
    return str(parsed.get("global_plan") or ""), _ordered_modules_from_map(by_key, expected)


def _parse_aplus_text_blocks(raw: str, expected: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    pattern = re.compile(r"(?m)^#@\s*(?:\[)?([^:\]：\n]+)(?:\])?\s*[:：]?\s*([^\n]*)")
    matches = list(pattern.finditer(raw))
    if not matches:
        raise ValueError("A+ 方案返回不是 JSON，也未找到 #@ 模块块")
    if len(matches) != len(expected):
        raise ValueError(f"A+ 方案 #@ 模块数量应为 {len(expected)}，实际为 {len(matches)}")
    expected_names = {str(item["module_name"]) for item in expected}
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    occurrences: dict[str, int] = {}
    for index, match in enumerate(matches):
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        block = raw[match.start() : block_end].strip()
        expected_item = expected[index]
        module_name = _match_expected_module_name(match.group(1), expected_names) or str(expected_item["module_name"])
        occurrences[module_name] = occurrences.get(module_name, 0) + 1
        instance_index = occurrences[module_name]
        topic = match.group(2).strip()
        image_type = f"{module_name}: {topic}" if topic else module_name
        key = (module_name, instance_index)
        if key in by_key:
            raise ValueError(f"A+ 方案重复模块：{module_name}#{instance_index}")
        by_key[key] = {
            "module_name": module_name,
            "instance_index": instance_index,
            "module_index": int(expected_item["module_index"]),
            "image_type": image_type,
            "image_prompt": block,
            "copy_requirements": _copy_requirements_from_block(block),
        }
    global_plan = raw[: matches[0].start()].strip()
    return global_plan, _ordered_modules_from_map(by_key, expected)


def _parse_aplus_plan(raw: str, module_selections: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    expected = _expected_module_items(module_selections)
    try:
        return _parse_aplus_json_plan(raw, expected)
    except (json.JSONDecodeError, ValueError) as json_error:
        try:
            return _parse_aplus_text_blocks(raw, expected)
        except ValueError:
            raise json_error


def _format_aplus_parse_error(error: Exception) -> str:
    if isinstance(error, json.JSONDecodeError):
        return f"JSON 结构不完整或缺少分隔符（第 {error.lineno} 行，第 {error.colno} 列）"
    return str(error)


async def _parse_aplus_plan_with_one_repair(
    raw: str,
    module_selections: list[dict[str, Any]],
    repair_callback: AplusPlanRepairCallback,
) -> tuple[str, list[dict[str, Any]]]:
    try:
        return _parse_aplus_plan(raw, module_selections)
    except Exception as first_error:
        repaired = await repair_callback(raw, str(first_error))
        try:
            return _parse_aplus_plan(repaired, module_selections)
        except Exception as repaired_error:
            raise ValueError(f"A+ 方案 JSON 修复后仍不合法：{_format_aplus_parse_error(repaired_error)}") from repaired_error


def _dryrun_modules(params: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    selections = _normalize_module_selections(params)
    expected = _expand_module_selections(selections)
    product_info = params.get("product_info") or "根据商品图识别产品，并围绕核心卖点规划详情页。"
    modules = []
    for item in expected:
        name = str(item["module_name"])
        instance = int(item["instance_index"])
        count = int(item["module_count"])
        image_type = f"{name}: Dryrun 详情页模块 {instance}/{count}" if count > 1 else f"{name}: Dryrun 详情页模块"
        modules.append(
            {
                "module_name": name,
                "instance_index": instance,
                "module_index": int(item["module_index"]),
                "image_type": image_type,
                "image_prompt": f"#@ {image_type}\n围绕“{product_info}”规划高转化电商详情页画面，产品保持为第一主体，构图清晰，卖点准确。",
                "copy_requirements": f"使用{params.get('language')}，只表达已提供或图片可见的事实，不虚构参数和承诺。",
            }
        )
    return "Dryrun A+ 详情页方案：按选中模块生成可确认的模块规划。", modules


def _version_for_item(session: Session, item: AplusItem) -> AplusVersion | None:
    if item.current_version_id:
        return next((version for version in item.versions if version.id == item.current_version_id), None)
    return item.versions[-1] if item.versions else None


def build_aplus_generation_prompt(item: AplusItem) -> str:
    output_label = OUTPUT_MODE_LABELS.get(item.output_mode, item.output_mode)
    if item.output_mode == "amazon_aplus_advanced_mobile" and item.source_web_item_id:
        return (
            f"输出模式：{output_label}；目标画面比例：{item.aspect_ratio}。\n"
            f"模块：{item.module_name}。\n"
            "【移动端派生模式】输入图是唯一视觉母版，也是唯一视觉内容来源。\n"
            "只把这张 Web 成图适配为 600:450 移动端画布；不要参考原始商品图重新生成，不要把 Web 图当成弱参考。\n"
            "逐字保留母版中所有可见文字、字母大小写、数字、标点、品牌名、单位和语言；"
            "禁止翻译、改写、本地化、概括、新增或删除任何可见文字。"
            "Do not translate, rewrite, localize, paraphrase, add, or remove visible text.\n"
            "保持商品、背景氛围、卖点层级、图标、标签、标题、副标题、条目文字、颜色关系和视觉资产一致；"
            "不新增、不替换、不删减、不改写内容。\n"
            "只允许为 600:450 进行等比缩放、裁切取景、留白、换行和局部位置调整，必要时扩大画布补背景；"
            "不要重新设计画面，不要改变布局逻辑，不要简单拉伸。"
        )

    prompt = (
        f"输出模式：{output_label}；目标画面比例：{item.aspect_ratio}。\n"
        f"模块：{item.module_name}。\n"
        f"画面需求：{item.image_prompt}\n"
        f"文案需求：{item.copy_requirements}\n"
        "必须保持商品外观、颜色、结构、材质、标识和包装事实一致；不得虚构用户未提供的参数、认证、功效或承诺。"
    )
    if item.output_mode == "amazon_aplus_advanced_mobile":
        prompt += (
            "\n【移动端独立生成模式】当前未提供高级 A+ Web 母版，直接根据商品参考图和模块规划生成移动端成图。"
            "按移动端画布重新组织信息层级，确保文字可读、构图完整，不依赖 Web 母版，不做简单裁切。"
        )
    return prompt


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


def create_dryrun_aplus_child_version(session: Session, item: AplusItem, instruction: str, settings: Settings) -> AplusVersion:
    current = _version_for_item(session, item)
    if not current:
        raise ValueError("当前版本不存在")
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    source = DEMO_ASSETS[version_no % len(DEMO_ASSETS)]
    result_name = f"aplus-{item.job_id}-{item.index + 1}-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    shutil.copy2(source, destination)
    version = AplusVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=instruction,
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": True, "demo_asset": source.name, "aspect_ratio": item.aspect_ratio}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    session.commit()
    session.refresh(version)
    return version


async def create_live_aplus_child_version(
    session: Session,
    item: AplusItem,
    instruction: str,
    settings: Settings,
    cipher: ApiKeyCipher,
) -> AplusVersion:
    current = _version_for_item(session, item)
    job = session.get(AplusJob, item.job_id)
    if not current or not current.file_path or not job:
        raise ValueError("当前版本或任务不存在")
    asset_ids = json.loads(job.asset_ids_json)
    asset_paths = [asset.file_path for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()]
    input_paths = [current.file_path, *asset_paths]
    route_key = "image_edit"
    provider_codes = route_provider_codes(session, route_key)
    provider_display_names = provider_display_names_by_code(session, provider_codes)
    prompt = (
        f"Edit this A+ detail image while preserving the product identity.\n"
        f"Output mode: {OUTPUT_MODE_LABELS.get(item.output_mode, item.output_mode)}; aspect ratio: {item.aspect_ratio}.\n"
        f"Module: {item.module_name}.\n"
        f"Original image prompt:\n{item.image_prompt}\n\n"
        f"Copy requirements:\n{item.copy_requirements}\n\n"
        f"Original module payload:\n{item.prompt_text}\n\n"
        f"User edit instruction:\n{instruction}"
    )
    client = ProviderClient()

    async def generate(provider_code: str) -> bytes:
        provider = cached_provider_by_code(session, provider_code)
        if not provider or not provider.encrypted_api_key:
            raise RuntimeError(f"Provider {provider_code} 不可用")
        input_urls = (
            [public_file_url(settings, path) for path in input_paths]
            if provider_requires_public_urls(provider) and input_paths
            else None
        )
        async with provider_slot(settings.max_provider_concurrency):
            image_bytes = await client.edit_image(
                provider,
                cipher.decrypt(provider.encrypted_api_key),
                prompt,
                input_paths,
                item.aspect_ratio,
                input_urls=input_urls,
                idempotency_key=f"{item.id}:edit:{instruction}",
            )
        validate_generated_image_bytes(image_bytes)
        return image_bytes

    image_bytes, used_code = await run_image_route(provider_codes, generate, provider_display_names)
    width, height = validate_generated_image_bytes(image_bytes)
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    result_name = f"aplus-{item.job_id}-{item.index + 1}-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    destination.write_bytes(image_bytes)
    version = AplusVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=instruction,
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": False, "provider": used_code, "route_key": route_key, "requested_size": requested_image_size(item.aspect_ratio), "actual_size": [width, height]}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    provider = cached_provider_by_code(session, used_code)
    item.provider_id = provider.id if provider else item.provider_id
    session.commit()
    session.refresh(version)
    return version


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
    sync_aplus_quota(session, job)


def _aplus_json_execution_contract(module_selections: list[dict[str, Any]]) -> str:
    expected = _expand_module_selections(module_selections)
    expected_lines = "\n".join(
        f"- {item['module_index']}. {item['module_name']}#{item['instance_index']}"
        for item in expected
    )
    return f"""

## 程序执行契约
无论上文描述了何种写作格式，最终只输出一个可解析 JSON 对象，不要输出 Markdown 代码围栏或额外解释。
JSON 顶层结构必须为：
{{
  "global_plan": "整体规划说明",
  "modules": [
    {{
      "module_name": "商品主视觉",
      "instance_index": 1,
      "image_type": "商品主视觉: 核心主题",
      "image_prompt": "#@ 商品主视觉: 核心主题\\n完整生图子 prompt",
      "copy_requirements": "画面文字与文案要求"
    }}
  ]
}}
modules 数组长度必须等于 {len(expected)}，模块数量必须严格匹配：{_module_text(module_selections)}
modules 顺序必须按以下清单输出：
{expected_lines}
module_name 必须使用清单中的模块名称；同一模块多张时 instance_index 从 1 开始递增，主题不得重复。
image_prompt 必须保留新 prompt 的 "#@ 模块名称:核心主题" 内容公式，作为实际生图子 prompt。
copy_requirements 只写画面文字与文案要求；无文字时明确写“此图无需添加任何文字”。
"""


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
            if job.status in CANCEL_REQUESTED_STATUSES:
                finalize_aplus_cancellation(session, job)
                session.commit()
                return
            job.status = "running"
            job.started_at = utcnow()
            params = json.loads(job.params_json)
            asset_ids = json.loads(job.asset_ids_json)
            prompt_version = session.get(PromptVersion, job.prompt_version_id)
            if not prompt_version:
                raise RuntimeError("A+ Meta Prompt 未启用")
            prompt_content = str(params.get("_admin_prompt_content") or prompt_version.content)
            image_safety_enabled = bool(load_sensitive_word_snapshot(session, default_runtime()))
            session.commit()

        module_selections = _normalize_module_selections(params)
        modules_text = _module_text(module_selections)
        canvas = _planning_canvas(params["output_targets"])
        if aplus_cancel_requested(session_factory, job_id):
            return

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
            if aplus_cancel_requested(session_factory, job_id):
                return
            product_facts = parse_product_facts(facts_raw)
            image_safety = sensitive_image_categories(product_facts)
            if image_safety_enabled and image_safety:
                with session_factory() as session:
                    session.add(
                        ExecutionLog(
                            job_id=job_id,
                            node="sensitive_image",
                            status="failed",
                            request_summary="{}",
                            response_summary=safe_json({"categories": image_safety}),
                            error="包含敏感信息",
                            dry_run=False,
                        )
                    )
                    session.commit()
                raise RuntimeError("包含敏感信息")
            input_mode = "image_with_text" if str(params.get("product_info") or "").strip() else "image_only"
            product_info = params.get("product_info") or json.dumps(product_facts.model_dump(), ensure_ascii=False)
            product_facts_dict = product_facts.model_dump()
            reference_assets = json.dumps(product_facts_dict, ensure_ascii=False)
            variables = {
                "product_info": product_info,
                "platform": params["platform"],
                "market": params["market"],
                "language": params["language"],
                "input_language": params.get("input_language") or "中文",
                "modules": modules_text,
                "selected_modules": modules_text,
                "brand_style": params.get("brand_style") or "",
                "reference_assets": reference_assets,
                "module_selections": json.dumps(module_selections, ensure_ascii=False),
                "canvas": json.dumps({"width": canvas["width"], "height": canvas["height"], "proportion": canvas["proportion"]}, ensure_ascii=False),
                "output_targets": json.dumps(params["output_targets"], ensure_ascii=False),
                "width": canvas["width"],
                "height": canvas["height"],
                "proportion": canvas["proportion"],
                "aspect_ratio": ", ".join(target["aspect_ratio"] for target in params["output_targets"]),
            }
            system_prompt = _replace_prompt_variables(prompt_content, variables) + _aplus_json_execution_contract(module_selections)
            user_prompt = json.dumps(
                {
                    "input_mode": input_mode,
                    "product_info": product_info,
                    "product_facts": product_facts_dict,
                    "platform": params["platform"],
                    "market": params["market"],
                    "language": params["language"],
                    "input_language": variables["input_language"],
                    "brand_style": variables["brand_style"],
                    "reference_assets": product_facts_dict,
                    "modules": modules_text,
                    "module_selections": module_selections,
                    "canvas": {
                        "width": canvas["width"],
                        "height": canvas["height"],
                        "proportion": canvas["proportion"],
                    },
                    "output_targets": params["output_targets"],
                    "instruction": "严格输出 JSON，modules 数量、名称和 instance_index 必须与 module_selections 完全一致。若 product_info 有文字，卖点事实只能来自文字；若只有图片，则基于图片识别商品事实。",
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
            if aplus_cancel_requested(session_factory, job_id):
                return

            async def repair(raw: str, error: str) -> str:
                repair_system = (
                    "你是 JSON 修复器。只修复结构与字段，不改变 A+ 详情页策划含义。"
                    "最终只输出一个合法 JSON 对象。"
                    + _aplus_json_execution_contract(module_selections)
                )
                repaired, _ = await _call_llm_with_fallback(
                    client,
                    llm_default,
                    llm_fallback,
                    cipher,
                    repair_system,
                    json.dumps(
                        {
                            "invalid_output": raw,
                            "validation_error": error,
                            "module_selections": module_selections,
                            "expected_modules": _expected_module_items(module_selections),
                        },
                        ensure_ascii=False,
                    ),
                )
                return repaired

            global_plan, modules = await _parse_aplus_plan_with_one_repair(raw_plan, module_selections, repair)

        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if job:
                if job.status in CANCEL_REQUESTED_STATUSES:
                    finalize_aplus_cancellation(session, job)
                    session.commit()
                    return
                create_plan_items(session, job, global_plan, modules)
                session.commit()
    except Exception as exc:
        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if job:
                if job.status in CANCEL_REQUESTED_STATUSES:
                    finalize_aplus_cancellation(session, job)
                    session.commit()
                    return
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


def _aplus_generation_route_key(output_mode: str) -> str:
    return "aplus_mobile" if output_mode == "amazon_aplus_advanced_mobile" else "aplus_detail"


def _aplus_atlas_provider_code(output_mode: str) -> str:
    return A_PLUS_ATLAS_MOBILE_PROVIDER_CODE if output_mode == "amazon_aplus_advanced_mobile" else A_PLUS_ATLAS_DETAIL_PROVIDER_CODE


def _enabled_aplus_atlas_provider(session: Session, provider_code: str) -> ProviderSnapshot:
    provider = cached_provider_by_code(session, provider_code)
    if not provider or not provider.enabled or not provider.encrypted_api_key:
        raise RuntimeError(f"A+ Atlas Provider {provider_code} 未启用或缺少 API Key")
    return provider


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
            if job.status in CANCEL_REQUESTED_STATUSES:
                finalize_aplus_cancellation(session, job)
                session.commit()
                return
            job.status = "running"
            job.started_at = utcnow()
            params = json.loads(job.params_json)
            asset_ids = json.loads(job.asset_ids_json)
            asset_paths = [asset.file_path for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()]
            if not job.dry_run:
                provider_codes = {_aplus_atlas_provider_code(item.output_mode) for item in job.items}
                for provider_code in provider_codes:
                    _enabled_aplus_atlas_provider(session, provider_code)
            session.commit()

        if job.dry_run:
            with session_factory() as session:
                job = load_aplus_job(session, job_id)
                for item in job.items:
                    if item.status in ITEM_FINAL_STATUSES:
                        continue
                    if job.status in CANCEL_REQUESTED_STATUSES or item.status == "cancelled":
                        if item.status == "queued":
                            item.status = "cancelled"
                            item.error = USER_CANCELLED_ERROR
                            session.commit()
                        continue
                    item.status = "running"
                    _create_dryrun_version(session, item, settings)
                    job.progress = round(((item.index + 1) / max(job.count, 1)) * 100)
                    session.commit()
                job.status = aplus_status_from_item_statuses([item.status for item in job.items])
                job.progress = 100
                job.completed_at = utcnow()
                sync_aplus_quota(session, job)
                session.commit()
            return

        with session_factory() as session:
            pending_items = session.scalars(
                select(AplusItem)
                .where(AplusItem.job_id == job_id, AplusItem.status.not_in(ITEM_FINAL_STATUSES))
                .order_by(AplusItem.index)
            ).all()
            independent_item_ids = [item.id for item in pending_items if not item.source_web_item_id]
            derived_mobile_item_ids = [item.id for item in pending_items if item.source_web_item_id]

        if aplus_cancel_requested(session_factory, job_id):
            return

        async def run_item_group(item_ids: list[str]) -> None:
            semaphore = asyncio.Semaphore(settings.max_job_concurrency)

            async def guarded(item_id: str) -> None:
                async with semaphore:
                    await _run_generation_item(item_id, session_factory, settings, cipher, client, asset_paths, params)

            await asyncio.gather(*(guarded(item_id) for item_id in item_ids))

        await run_item_group(independent_item_ids)
        if not aplus_cancel_requested(session_factory, job_id):
            await run_item_group(derived_mobile_item_ids)

        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            statuses = session.scalars(select(AplusItem.status).where(AplusItem.job_id == job_id)).all()
            job.status = aplus_status_from_item_statuses(statuses)
            job.progress = 100
            job.completed_at = utcnow()
            sync_aplus_quota(session, job)
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            job = session.get(AplusJob, job_id)
            if job:
                if job.status in CANCEL_REQUESTED_STATUSES:
                    finalize_aplus_cancellation(session, job)
                    session.commit()
                    return
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                sync_aplus_quota(session, job)
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
        job = session.get(AplusJob, item.job_id)
        if not job or job.status in CANCEL_REQUESTED_STATUSES or item.status == "cancelled":
            if item and item.status == "queued":
                item.status = "cancelled"
                item.error = USER_CANCELLED_ERROR
                session.commit()
            return
        item.status = "running"
        session.commit()
        input_paths = asset_paths
        route_key = _aplus_generation_route_key(item.output_mode)
        if item.output_mode == "amazon_aplus_advanced_mobile" and item.source_web_item_id:
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
        provider_code = _aplus_atlas_provider_code(item.output_mode)
        provider_display_names = provider_display_names_by_code(session, [provider_code])
        prompt = build_aplus_generation_prompt(item)

    try:
        async def generate() -> bytes:
            with session_factory() as session:
                item = session.get(AplusItem, item_id)
                job = session.get(AplusJob, item.job_id) if item else None
                if not item or not job or job.status in CANCEL_REQUESTED_STATUSES:
                    raise RuntimeError(USER_CANCELLED_ERROR)
                provider = _enabled_aplus_atlas_provider(session, provider_code)
                input_urls = (
                    [public_file_url(settings, path) for path in input_paths]
                    if provider_requires_public_urls(provider) and input_paths
                    else None
                )
                provider_id = provider.id
                existing_task_id = item.provider_task_id if item.provider_id == provider_id else None

                async def persist_task_id(task_id: str) -> None:
                    with session_factory() as write_session:
                        write_item = write_session.get(AplusItem, item_id)
                        if write_item:
                            write_item.provider_id = provider_id
                            write_item.provider_task_id = task_id
                            write_session.commit()

                async with provider_slot(settings.max_provider_concurrency):
                    if item.output_mode == "amazon_aplus_advanced_mobile" and item.source_web_item_id:
                        image_bytes = await client.edit_image(
                            provider,
                            cipher.decrypt(provider.encrypted_api_key),
                            prompt,
                            input_paths,
                            item.aspect_ratio,
                            input_urls=input_urls,
                            idempotency_key=item.id,
                        )
                    else:
                        image_bytes = await client.generate_image(
                            provider,
                            cipher.decrypt(provider.encrypted_api_key),
                            prompt,
                            input_paths,
                            item.aspect_ratio,
                            input_urls=input_urls,
                            existing_task_id=existing_task_id,
                            on_task_submitted=persist_task_id,
                            idempotency_key=item.id,
                        )
                validate_generated_image_bytes(image_bytes)
                return image_bytes

        try:
            image_bytes = await generate()
            used_code = provider_code
        except Exception as exc:
            display_name = provider_display_names.get(provider_code) or provider_code
            message = str(exc)
            if display_name != provider_code:
                message = message.replace(provider_code, display_name)
            raise RuntimeError(f"{display_name}: {message}") from exc
        width, height = validate_generated_image_bytes(image_bytes)
        result_name = f"aplus-{item_id}-{uuid4().hex[:8]}.png"
        destination = settings.results_dir / result_name
        destination.write_bytes(image_bytes)
        with session_factory() as session:
            item = session.get(AplusItem, item_id)
            provider = cached_provider_by_code(session, used_code)
            version = AplusVersion(
                item_id=item.id,
                version_no=1,
                instruction="Live A+ 生成",
                file_path=str(destination),
                url=f"/files/results/{result_name}",
                metadata_json=safe_json({"dry_run": False, "provider": used_code, "route_key": route_key, "requested_size": requested_image_size(item.aspect_ratio), "actual_size": [width, height]}),
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
                if item.status == "cancelled":
                    return
                job = session.get(AplusJob, item.job_id)
                if job and job.status in CANCEL_REQUESTED_STATUSES and str(exc) == USER_CANCELLED_ERROR:
                    item.status = "cancelled"
                    item.error = USER_CANCELLED_ERROR
                    session.commit()
                    return
                item.status = "failed"
                item.error = str(exc)
                session.commit()


async def retry_failed_aplus_items(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    with session_factory() as session:
        job = load_aplus_job(session, job_id)
        if not job or job.job_type != "generation":
            return
        failed_items = [item for item in job.items if item.status == "failed"]
        if not failed_items:
            return
        for item in failed_items:
            item.status = "queued"
            item.error = None
            item.provider_id = None
            item.provider_task_id = None
        job.status = "running"
        job.error = None
        job.completed_at = None
        session.commit()
    await run_aplus_generation_job(job_id, session_factory, settings, cipher)


async def retry_aplus_item(
    item_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> str | None:
    with session_factory() as session:
        item = session.get(AplusItem, item_id)
        if not item:
            return None
        job = load_aplus_job(session, item.job_id)
        if not job or job.job_type != "generation":
            return None
        if item.status != "failed":
            return job.id
        item.status = "queued"
        item.error = None
        item.provider_id = None
        item.provider_task_id = None
        job.status = "running"
        job.error = None
        job.completed_at = None
        session.commit()
        job_id = job.id
    await run_aplus_generation_job(job_id, session_factory, settings, cipher)
    return job_id
