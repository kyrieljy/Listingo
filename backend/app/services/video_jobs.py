from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.config import Settings
from backend.app.models import Asset, ExecutionLog, PromptVersion, Provider, VideoItem, VideoJob, VideoVersion, utcnow
from backend.app.security import ApiKeyCipher
from backend.app.services.content_safety import (
    ensure_content_safe,
    run_content_safety_review,
    run_local_text_safety_review,
)
from backend.app.services.jobs import _call_llm_with_fallback
from backend.app.services.provider_routing import (
    ProviderRecord,
    ProviderSnapshot,
    cached_provider_by_code,
    enabled_provider_for_route,
    provider_display_names_by_code,
    route_provider_codes,
)
from backend.app.services.runtime_cache import active_prompt_version_id
from backend.app.services.providers import HELLOBABYGO_VIDEO_ADAPTER, ProviderClient
from backend.app.services.redaction import safe_json
from backend.app.services.storage import public_file_url


FINAL_STATUSES = {"succeeded", "partial_failed", "failed", "cancelled", "partial_cancelled"}
ITEM_FINAL_STATUSES = {"succeeded", "failed", "cancelled"}
CANCEL_REQUESTED_STATUSES = {"cancelling", "cancelled", "partial_cancelled"}
USER_CANCELLED_ERROR = "用户已取消任务"
REMOTE_RUNNING_STATUSES = {"SUBMITTING", "PENDING", "SUBMITTED", "QUEUED", "IN_PROGRESS", "PROCESSING", "RUNNING"}
REMOTE_FAILED_STATUSES = {"FAILED", "CANCELLED", "TIMEOUT", "UNKNOWN"}
REMOTE_SUCCESS_STATUSES = {"COMPLETED", "SUCCEEDED", "SUCCESS"}


def public_asset_url(settings: Settings, asset: Asset) -> str:
    return public_file_url(settings, asset.file_path)


def build_video_copywriting_user_prompt(payload: Any) -> str:
    input_mode = "image_with_text" if payload.selling_points.strip() else "image_only"
    return json.dumps(
        {
            "input_mode": input_mode,
            "platform": payload.platform,
            "market": payload.market,
            "country": payload.country,
            "language": payload.language,
            "video_types": payload.video_types,
            "selling_points": payload.selling_points,
            "instruction": (
                "输出面向 15 秒电商短视频的商品卖点和脚本素材。"
                "input_mode=image_only 时，可根据商品图视觉事实合理提炼；"
                "input_mode=image_with_text 时，必须严格遵循用户文字事实，不得补造参数、功效、价格、认证或对比结论。"
            ),
        },
        ensure_ascii=False,
    )


def build_video_script_user_prompt(params: dict[str, Any], item: VideoItem, image_urls: list[str]) -> str:
    input_mode = "image_with_text" if str(params.get("selling_points", "")).strip() else "image_only"
    return json.dumps(
        {
            "input_mode": input_mode,
            "video_type": item.video_type,
            "platform": params.get("platform"),
            "market": params.get("market"),
            "country": params.get("country"),
            "language": params.get("language"),
            "aspect_ratio": params.get("aspect_ratio"),
            "duration": params.get("duration", 15),
            "product_name": params.get("product_name", ""),
            "target_audience": params.get("target_audience", ""),
            "selling_points": params.get("selling_points", ""),
            "product_image_url": image_urls[0] if image_urls else "",
            "product_image_urls": image_urls,
            "instruction": (
                "请根据当前视频类型从 10 个母模板中选择最匹配模板，输出固定 15 秒导演分镜 Markdown。"
                "输出必须可直接交给 Seedance 生成视频，包含镜头、人物/动作、运镜、口播/字幕、节奏和最后定格画面。"
            ),
        },
        ensure_ascii=False,
    )


def seedance_prompt_from_script(script: str, params: dict[str, Any], item: VideoItem) -> str:
    return (
        f"生成一个 {params.get('duration', 15)} 秒电商短视频，视频类型：{item.video_type}。"
        f"平台：{params.get('platform')}；国家/市场：{params.get('country')} / {params.get('market')}；"
        f"语言：{params.get('language')}；画幅：{params.get('aspect_ratio')}。\n\n"
        "严格按照以下导演分镜执行，保持商品图中的产品外观、颜色、结构和主要视觉特征一致，"
        "不要添加政治、成人、赌博、毒品或违法内容。\n\n"
        f"{script}"
    )


def dryrun_video_script(params: dict[str, Any], video_type: str) -> str:
    product = params.get("product_name") or "上传商品"
    return f"""# 15 秒电商短视频脚本

**视频类型**：{video_type}
**推广商品**：{product}
**平台 / 语言**：{params.get("platform")} / {params.get("language")}

## 0-3s Hook
展示用户在真实场景中遇到的小痛点，商品进入画面，字幕点出核心利益。

## 3-10s 核心卖点
围绕用户提供的卖点进行 2 个镜头展示，突出外观、使用方式和目标人群，不补造参数。

## 10-13.5s 结果证明
让用户看到商品解决问题后的状态，画面保持干净，产品持续可见。

## 13.5-15s 定格
商品正面稳定展示，保留简洁 CTA：立即了解。
"""


def _current_video_version(item: VideoItem) -> VideoVersion | None:
    if not item.current_version_id:
        return None
    return next((version for version in item.versions if version.id == item.current_version_id), None)


def _edited_video_script(item: VideoItem, instruction: str) -> str:
    base_script = item.script_markdown.strip() or item.prompt_text.strip()
    if not base_script:
        raise ValueError("Current video script is unavailable")
    return (
        f"{base_script}\n\n"
        "## Secondary edit instruction\n"
        f"{instruction.strip()}"
    )


def create_dryrun_video_child_version(session: Session, item: VideoItem, instruction: str) -> VideoVersion:
    current = _current_video_version(item)
    if not current:
        raise ValueError("Current video version is unavailable")
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    params = json.loads(item.job.params_json)
    script = _edited_video_script(item, instruction)
    version = VideoVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=instruction,
        file_path="",
        url=f"/demo/video-skincare-result.png?v={version_no}",
        remote_url="",
        metadata_json=safe_json({"dry_run": True, "video_type": item.video_type, "secondary_edit": True}),
    )
    session.add(version)
    session.flush()
    item.script_markdown = script
    item.prompt_text = seedance_prompt_from_script(script, params, item)
    item.current_version_id = version.id
    item.status = "succeeded"
    item.error = None
    session.commit()
    session.refresh(version)
    return version


def extract_request_id(data: dict[str, Any]) -> str:
    candidates = [
        data.get("request_id"),
        data.get("id"),
        data.get("task_id"),
        data.get("data", {}).get("request_id") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("task_id") if isinstance(data.get("data"), dict) else None,
        data.get("taskId"),
        data.get("taskUUID"),
        data.get("data", {}).get("taskId") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("taskUUID") if isinstance(data.get("data"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError("Seedance 提交响应缺少 request_id")


def extract_status(data: dict[str, Any]) -> str:
    for source in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        status = source.get("status") if isinstance(source, dict) else None
        if isinstance(status, str) and status:
            return status.upper()
    return "UNKNOWN"


def extract_progress(data: dict[str, Any]) -> int | None:
    source = data.get("data") if isinstance(data.get("data"), dict) else data
    progress = source.get("progress") if isinstance(source, dict) else None
    if isinstance(progress, (int, float)):
        return max(0, min(100, int(progress)))
    if isinstance(progress, str):
        normalized = progress.strip().removesuffix("%")
        try:
            return max(0, min(100, int(float(normalized))))
        except ValueError:
            return None
    return None


def extract_video_url(data: Any) -> str | None:
    if isinstance(data, str):
        lowered = data.lower()
        if data.startswith("http") and any(token in lowered for token in (".mp4", ".mov", ".webm", "video")):
            return data
        return None
    if isinstance(data, list):
        for item in data:
            found = extract_video_url(item)
            if found:
                return found
        return None
    if isinstance(data, dict):
        for key in ("video_url", "url", "file_url", "output_url", "download_url"):
            found = extract_video_url(data.get(key))
            if found:
                return found
        for value in data.values():
            found = extract_video_url(value)
            if found:
                return found
    return None


def extract_error_message(data: dict[str, Any]) -> str:
    for source in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        if not isinstance(source, dict):
            continue
        error = source.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("error") or error.get("detail")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        message = source.get("message") or source.get("error_message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return "上游任务失败"


def _enabled_provider(session: Session, capability: str, relation: str = "default") -> ProviderRecord:
    route_key = "llm" if capability == "llm" else "video" if capability == "video" else ""
    if route_key:
        try:
            provider_codes = route_provider_codes(session, route_key)
            provider_code = provider_codes[0] if relation == "default" or len(provider_codes) == 1 else provider_codes[1]
            provider = cached_provider_by_code(session, provider_code)
            if provider and provider.encrypted_api_key:
                return provider
        except RuntimeError:
            # Compatibility for older tests and databases that still only use capability-level flags.
            pass
    column = Provider.is_default if relation == "default" else Provider.is_fallback
    provider = session.scalar(
        select(Provider).where(Provider.capability == capability, column.is_(True), Provider.enabled.is_(True))
    )
    if not provider or not provider.encrypted_api_key:
        raise RuntimeError(f"{capability} {relation} Provider 未启用或缺少 API Key")
    return provider


def _job_status(items: list[VideoItem]) -> str:
    if any(item.status == "cancelled" for item in items):
        return "partial_cancelled" if any(item.status in {"succeeded", "failed"} for item in items) else "cancelled"
    if all(item.status == "succeeded" for item in items):
        return "succeeded"
    if any(item.status == "succeeded" for item in items):
        return "partial_failed"
    return "failed"


def finalize_video_cancellation(session: Session, job: VideoJob) -> None:
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
    job.status = _job_status(job.items)
    job.progress = 100
    job.completed_at = utcnow()
    sync_video_quota(session, job)


def sync_video_quota(session: Session, job: VideoJob) -> None:
    # Video generation is disabled for V1; preserved jobs remain audit-only.
    return


def cancel_video_job(session: Session, job: VideoJob) -> VideoJob:
    """仅 queued 任务可取消；running/终态由调用方（端点）拦截。

    队列化后任务进入 running 即不可中断，取消接口对 running 返回 409，
    不再将状态置为 cancelling，执行链路也不再响应取消请求。
    """
    if job.status != "queued":
        return job
    job.status = "cancelled"
    job.progress = 100
    job.completed_at = utcnow()
    for item in job.items:
        if item.status == "queued":
            item.status = "cancelled"
            item.error = USER_CANCELLED_ERROR
    sync_video_quota(session, job)
    session.commit()
    session.refresh(job)
    return job


def video_cancel_requested(session_factory: sessionmaker[Session], job_id: str) -> bool:
    with session_factory() as session:
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
        )
        if not job:
            return True
        if job.status not in CANCEL_REQUESTED_STATUSES:
            return False
        finalize_video_cancellation(session, job)
        sync_video_quota(session, job)
        session.commit()
        return True


def cancel_video_item_if_requested(
    session_factory: sessionmaker[Session], job_id: str, item_id: str
) -> bool:
    with session_factory() as session:
        job = session.get(VideoJob, job_id)
        item = session.get(VideoItem, item_id)
        if not job or not item:
            return True
        if job.status not in CANCEL_REQUESTED_STATUSES and item.status != "cancelled":
            return False
        item.status = "cancelled"
        item.error = USER_CANCELLED_ERROR
        session.commit()
        return True


async def run_video_job(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> None:
    client = ProviderClient()
    with session_factory() as session:
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
        )
        if not job:
            return
        if job.status in CANCEL_REQUESTED_STATUSES:
            finalize_video_cancellation(session, job)
            session.commit()
            return
        job.status = "running"
        job.started_at = utcnow()
        session.commit()

    try:
        await _run_video_job(job_id, session_factory, settings, cipher, client)
    except Exception as exc:
        with session_factory() as session:
            job = session.scalar(
                select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
            )
            if job:
                if job.status in CANCEL_REQUESTED_STATUSES:
                    finalize_video_cancellation(session, job)
                    session.commit()
                    return
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                for item in job.items:
                    if item.status in {"queued", "running"}:
                        item.status = "failed"
                        item.error = str(exc)
                sync_video_quota(session, job)
                session.commit()


async def _run_video_job(
    job_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
    client: ProviderClient,
) -> None:
    with session_factory() as session:
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
        )
        if not job:
            return
        params = json.loads(job.params_json)
        asset_ids = json.loads(job.asset_ids_json)
        assets = session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
        assets_by_id = {asset.id: asset for asset in assets}
        ordered_assets = [assets_by_id.get(asset_id) for asset_id in asset_ids]
        if any(asset is None for asset in ordered_assets):
            raise RuntimeError("视频任务引用的商品图不存在")
        image_urls = (
            [public_asset_url(settings, asset) for asset in ordered_assets if asset]
            if not job.dry_run
            else [asset.url for asset in ordered_assets if asset]
        )
        prompt_version = session.get(PromptVersion, job.prompt_version_id)
        if not prompt_version:
            raise RuntimeError("视频 Meta Prompt 版本不存在")
        prompt_content = str(params.get("_admin_prompt_content") or prompt_version.content)
        llm_default = _enabled_provider(session, "llm", "default") if not job.dry_run else None
        llm_fallback = _enabled_provider(session, "llm", "fallback") if not job.dry_run else None
        video_provider_codes = route_provider_codes(session, "video") if not job.dry_run else []
        safety_version_id = active_prompt_version_id(session, "content-safety-review") if not job.dry_run else None
        safety_prompt = (
            session.get(PromptVersion, safety_version_id) if safety_version_id else None
        )
        if not job.dry_run and not safety_prompt:
            raise RuntimeError("内容安全审计 Prompt 未启用")

    if video_cancel_requested(session_factory, job_id):
        return
    if not job.dry_run:
        input_text = json.dumps({key: value for key, value in params.items() if not key.startswith("_") and key not in {"asset_ids", "dry_run"}}, ensure_ascii=False)
        try:
            input_review, input_provider = await run_content_safety_review(
                client,
                llm_default,
                llm_fallback,
                cipher,
                safety_prompt,
                subject="video_generation_input",
                text=input_text,
                image_paths=[asset.file_path for asset in ordered_assets if asset],
            )
            ensure_content_safe(input_review, "输入内容安全拦截")
            with session_factory() as session:
                session.add(
                    ExecutionLog(
                        node="content_safety",
                        provider_id=input_provider.id,
                        status="succeeded",
                        request_summary=safe_json({"subject": "video_generation_input", "asset_count": len(ordered_assets)}),
                        response_summary=safe_json(input_review.model_dump()),
                        dry_run=False,
                    )
                )
                session.commit()
        except Exception as exc:
            with session_factory() as session:
                session.add(
                    ExecutionLog(
                        node="content_safety",
                        status="failed",
                        request_summary=safe_json({"subject": "video_generation_input", "asset_count": len(ordered_assets)}),
                        response_summary=safe_json(getattr(exc, "review", {}).model_dump() if getattr(exc, "review", None) else {}),
                        error=str(exc),
                        dry_run=False,
                    )
                )
                session.commit()
            raise RuntimeError(str(exc)) from exc
    if video_cancel_requested(session_factory, job_id):
        return

    for index, _ in enumerate(range(len(job.items))):
        with session_factory() as session:
            job = session.scalar(
                select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
            )
            if job.status in CANCEL_REQUESTED_STATUSES:
                finalize_video_cancellation(session, job)
                session.commit()
                return
            item = job.items[index]
            if item.status in {"succeeded", "cancelled"}:
                continue
            item.status = "running"
            session.commit()

        await _run_video_item(
            job_id,
            item.id,
            params,
            image_urls,
            prompt_content,
            llm_default,
            llm_fallback,
            video_provider_codes,
            session_factory,
            settings,
            cipher,
            client,
        )

        with session_factory() as session:
            job = session.scalar(
                select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
            )
            finished = sum(1 for item in job.items if item.status in ITEM_FINAL_STATUSES)
            job.progress = round(finished * 100 / max(1, job.count))
            session.commit()

    with session_factory() as session:
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
        )
        job.status = _job_status(job.items)
        job.progress = 100
        job.completed_at = utcnow()
        sync_video_quota(session, job)
        session.commit()


async def _run_video_item(
    job_id: str,
    item_id: str,
    params: dict[str, Any],
    image_urls: list[str],
    prompt_content: str,
        llm_default: ProviderRecord | None,
        llm_fallback: ProviderRecord | None,
    video_provider_codes: list[str],
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ApiKeyCipher,
    client: ProviderClient,
) -> None:
    with session_factory() as session:
        item = session.get(VideoItem, item_id)
        job = session.get(VideoJob, job_id)
        if not item or not job:
            return
        if job.status in CANCEL_REQUESTED_STATUSES or item.status == "cancelled":
            item.status = "cancelled"
            item.error = USER_CANCELLED_ERROR
            session.commit()
            return
        if job.dry_run:
            script = dryrun_video_script(params, item.video_type)
            item.script_markdown = script
            item.prompt_text = seedance_prompt_from_script(script, params, item)
            version = VideoVersion(
                item_id=item.id,
                version_no=1,
                instruction="dryrun placeholder",
                file_path="",
                url="/demo/video-skincare-result.png",
                remote_url="",
                metadata_json=safe_json({"dry_run": True, "video_type": item.video_type}),
            )
            session.add(version)
            session.flush()
            item.current_version_id = version.id
            item.status = "succeeded"
            session.commit()
            return

    started = perf_counter()
    try:
        if cancel_video_item_if_requested(session_factory, job_id, item_id):
            return
        script_user_prompt = build_video_script_user_prompt(params, item, image_urls)
        ensure_content_safe(run_local_text_safety_review(script_user_prompt), "内容安全拦截")
        script, llm_provider = await _call_llm_with_fallback(
            client,
            llm_default,
            llm_fallback,
            cipher,
            prompt_content,
            script_user_prompt,
            response_format=None,
        )
        ensure_content_safe(run_local_text_safety_review(script), "内容安全拦截")
        with session_factory() as session:
            item = session.get(VideoItem, item_id)
            item.script_markdown = script.strip()
            item.prompt_text = seedance_prompt_from_script(script.strip(), params, item)
            session.add(
                ExecutionLog(
                    node="video_meta_prompt",
                    provider_id=llm_provider.id,
                    status="succeeded",
                    duration_ms=int((perf_counter() - started) * 1000),
                    request_summary=safe_json({"video_job_id": job_id, "video_type": item.video_type}),
                    response_summary=safe_json({"script_chars": len(script)}),
                    dry_run=False,
                )
            )
            session.commit()

        if cancel_video_item_if_requested(session_factory, job_id, item_id):
            return
        generation_settings = {
            "size": params.get("aspect_ratio", "9:16"),
            "seconds": int(params.get("duration", 15)),
            "resolution": params.get("resolution", "1080p"),
            "image_count": len(image_urls),
        }
        errors: list[str] = []
        with session_factory() as session:
            provider_display_names = provider_display_names_by_code(session, video_provider_codes)
        used_provider: ProviderSnapshot | None = None
        used_api_key = ""
        request_id = ""
        response: dict[str, Any] = {}
        remote_url = ""
        for provider_code in video_provider_codes:
            submit_started = perf_counter()
            with session_factory() as session:
                candidate = cached_provider_by_code(session, provider_code)
                if candidate is not None and not candidate.enabled:
                    candidate = None
                if not candidate or not candidate.encrypted_api_key:
                    errors.append(f"{provider_display_names.get(provider_code, provider_code)}: 未启用或缺少 API Key")
                    continue
                api_key = cipher.decrypt(candidate.encrypted_api_key)
            try:
                response = await client.submit_video_task(
                    candidate,
                    api_key,
                    seedance_prompt_from_script(script.strip(), params, item),
                    image_urls,
                    aspect_ratio=params.get("aspect_ratio", "9:16"),
                    duration=int(params.get("duration", 15)),
                    resolution=params.get("resolution", "1080p"),
                )
                request_id = extract_request_id(response)
                with session_factory() as session:
                    write_item = session.get(VideoItem, item_id)
                    if write_item:
                        write_item.provider_id = candidate.id
                        write_item.provider_task_id = request_id
                        session.add(
                            ExecutionLog(
                                node="video_submit",
                                provider_id=candidate.id,
                                status="succeeded",
                                duration_ms=int((perf_counter() - submit_started) * 1000),
                                request_summary=safe_json({"video_job_id": job_id, "item_id": item_id, "request_id": request_id, "generation_settings": generation_settings, "route_candidates": video_provider_codes}),
                                response_summary=safe_json(response),
                                dry_run=False,
                            )
                        )
                        session.commit()
                remote_url = await poll_video_completion(client, candidate, api_key, request_id, job_id, item_id, session_factory)
                used_provider = candidate
                used_api_key = api_key
                break
            except Exception as provider_error:
                errors.append(f"{provider_display_names.get(provider_code, provider_code)}: {provider_error}")
        if not used_provider or not remote_url:
            raise RuntimeError("视频模型调用失败：" + "；".join(errors))
        content_api_key = (
            used_api_key
            if used_provider.adapter == HELLOBABYGO_VIDEO_ADAPTER
            and remote_url.startswith(used_provider.base_url.rstrip("/") + "/")
            else None
        )
        local_url, file_path = await save_remote_video(client, settings, remote_url, job_id, item_id, api_key=content_api_key)
        with session_factory() as session:
            item = session.get(VideoItem, item_id)
            version = VideoVersion(
                item_id=item.id,
                version_no=len(item.versions) + 1 if item.versions else 1,
                instruction="seedance result",
                file_path=str(file_path),
                url=local_url,
                remote_url=remote_url,
                metadata_json=safe_json({"provider": used_provider.code, "request_id": request_id, "params": params}),
            )
            session.add(version)
            session.flush()
            item.current_version_id = version.id
            item.status = "succeeded"
            item.error = None
            session.commit()
    except Exception as exc:
        with session_factory() as session:
            item = session.get(VideoItem, item_id)
            if item:
                if item.status == "cancelled":
                    return
                item.status = "failed"
                item.error = str(exc)
                session.add(
                    ExecutionLog(
                        node="video_generate",
                        provider_id=item.provider_id,
                        status="failed",
                        request_summary=safe_json({"video_job_id": job_id, "item_id": item_id}),
                        response_summary="{}",
                        error=str(exc),
                        dry_run=False,
                    )
                )
                session.commit()


async def create_live_video_child_version(
    session: Session,
    item: VideoItem,
    instruction: str,
    settings: Settings,
    cipher: ApiKeyCipher,
    session_factory: sessionmaker[Session],
) -> VideoVersion:
    current = _current_video_version(item)
    job = session.get(VideoJob, item.job_id)
    if not current or not job:
        raise ValueError("Current video version is unavailable")

    params = json.loads(job.params_json)
    asset_ids = json.loads(job.asset_ids_json)
    assets = session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
    assets_by_id = {asset.id: asset for asset in assets}
    ordered_assets = [assets_by_id.get(asset_id) for asset_id in asset_ids]
    if any(asset is None for asset in ordered_assets):
        raise ValueError("Referenced product images are unavailable")

    script = _edited_video_script(item, instruction)
    prompt = seedance_prompt_from_script(script, params, item)
    ensure_content_safe(run_local_text_safety_review(script), "Input content safety blocked")
    ensure_content_safe(run_local_text_safety_review(prompt), "Input content safety blocked")

    video_provider_codes = route_provider_codes(session, "video")
    provider_display_names = provider_display_names_by_code(session, video_provider_codes)
    image_urls = [public_asset_url(settings, asset) for asset in ordered_assets if asset]
    client = ProviderClient()
    errors: list[str] = []
    used_provider: ProviderSnapshot | None = None
    used_api_key = ""
    request_id = ""
    remote_url = ""
    response: dict[str, Any] = {}
    for provider_code in video_provider_codes:
        video_provider = cached_provider_by_code(session, provider_code)
        if video_provider is not None and not video_provider.enabled:
            video_provider = None
        if not video_provider or not video_provider.encrypted_api_key:
            errors.append(f"{provider_display_names.get(provider_code, provider_code)}: 未启用或缺少 API Key")
            continue
        api_key = cipher.decrypt(video_provider.encrypted_api_key or "")
        try:
            response = await client.submit_video_task(
                video_provider,
                api_key,
                prompt,
                image_urls,
                aspect_ratio=params.get("aspect_ratio", "9:16"),
                duration=int(params.get("duration", 15)),
                resolution=params.get("resolution", "1080p"),
            )
            request_id = extract_request_id(response)
            item.provider_id = video_provider.id
            item.provider_task_id = request_id
            session.add(
                ExecutionLog(
                    node="video_edit_submit",
                    provider_id=video_provider.id,
                    status="succeeded",
                    request_summary=safe_json({"video_job_id": job.id, "item_id": item.id, "request_id": request_id, "route_candidates": video_provider_codes}),
                    response_summary=safe_json(response),
                    dry_run=False,
                )
            )
            session.commit()
            remote_url = await poll_video_completion(client, video_provider, api_key, request_id, job.id, item.id, session_factory)
            used_provider = video_provider
            used_api_key = api_key
            break
        except Exception as provider_error:
            errors.append(f"{provider_display_names.get(provider_code, provider_code)}: {provider_error}")
    if not used_provider or not remote_url:
        raise RuntimeError("视频编辑模型调用失败：" + "；".join(errors))
    content_api_key = (
        used_api_key
        if used_provider.adapter == HELLOBABYGO_VIDEO_ADAPTER
        and remote_url.startswith(used_provider.base_url.rstrip("/") + "/")
        else None
    )
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    local_url, file_path = await save_remote_video(
        client,
        settings,
        remote_url,
        job.id,
        item.id,
        api_key=content_api_key,
        version_no=version_no,
    )
    version = VideoVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=instruction,
        file_path=str(file_path),
        url=local_url,
        remote_url=remote_url,
        metadata_json=safe_json({"dry_run": False, "provider": used_provider.code, "request_id": request_id, "secondary_edit": True}),
    )
    session.add(version)
    session.flush()
    item.script_markdown = script
    item.prompt_text = prompt
    item.current_version_id = version.id
    item.status = "succeeded"
    item.error = None
    session.commit()
    session.refresh(version)
    return version


async def poll_video_completion(
    client: ProviderClient,
    provider: ProviderRecord,
    api_key: str,
    request_id: str,
    job_id: str,
    item_id: str,
    session_factory: sessionmaker[Session],
) -> str:
    for _ in range(180):
        data = await client.get_video_task(provider, api_key, request_id)
        status = extract_status(data)
        progress = extract_progress(data)
        if progress is not None:
            with session_factory() as session:
                job = session.get(VideoJob, job_id)
                if job:
                    base = job.progress
                    job.progress = max(base, min(99, progress))
                    session.commit()
        if status in REMOTE_SUCCESS_STATUSES:
            if provider.adapter == HELLOBABYGO_VIDEO_ADAPTER:
                return provider.base_url.rstrip("/") + f"/{request_id}/content"
            video_url = extract_video_url(data)
            if not video_url:
                raise RuntimeError("Seedance 任务完成但响应缺少视频 URL")
            return video_url
        if status in REMOTE_FAILED_STATUSES:
            raise RuntimeError(f"Seedance 视频任务失败：{extract_error_message(data)}")
        if status not in REMOTE_RUNNING_STATUSES:
            raise RuntimeError(f"Seedance 视频任务状态未知：{status}")
        await asyncio.sleep(5)
    raise RuntimeError("Seedance 视频任务等待超时")


async def save_remote_video(
    client: ProviderClient,
    settings: Settings,
    remote_url: str,
    job_id: str,
    item_id: str,
    *,
    api_key: str | None = None,
    version_no: int | None = None,
) -> tuple[str, Path]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    content = await client._download(remote_url, 600, headers=headers)
    video_dir = settings.results_dir / "videos" / job_id
    video_dir.mkdir(parents=True, exist_ok=True)
    destination = video_dir / (f"{item_id}-v{version_no}.mp4" if version_no else f"{item_id}.mp4")
    destination.write_bytes(content)
    relative = destination.relative_to(settings.data_dir).as_posix()
    return f"/files/{relative}", destination
