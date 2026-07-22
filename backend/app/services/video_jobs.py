from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

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
from backend.app.services.providers import ProviderClient
from backend.app.services.redaction import safe_json


FINAL_STATUSES = {"succeeded", "partial_failed", "failed"}
REMOTE_RUNNING_STATUSES = {"SUBMITTING", "PENDING", "SUBMITTED", "QUEUED", "IN_PROGRESS"}
REMOTE_FAILED_STATUSES = {"FAILED", "CANCELLED", "TIMEOUT", "UNKNOWN"}


def public_asset_url(settings: Settings, asset: Asset) -> str:
    base = settings.public_asset_base_url.strip().rstrip("/")
    if not base:
        raise RuntimeError("视频生成需要配置公网资源地址 PUBLIC_ASSET_BASE_URL")
    parsed = urlparse(base)
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        raise RuntimeError("视频生成需要公网可访问的资源地址，不能使用 localhost/127.0.0.1")
    return f"{base}{asset.url if asset.url.startswith('/') else '/' + asset.url}"


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


def build_video_script_user_prompt(params: dict[str, Any], item: VideoItem, image_url: str) -> str:
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
            "product_image_url": image_url,
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


def extract_request_id(data: dict[str, Any]) -> str:
    candidates = [
        data.get("request_id"),
        data.get("id"),
        data.get("task_id"),
        data.get("data", {}).get("request_id") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("task_id") if isinstance(data.get("data"), dict) else None,
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


def _enabled_provider(session: Session, capability: str, relation: str = "default") -> Provider:
    column = Provider.is_default if relation == "default" else Provider.is_fallback
    provider = session.scalar(
        select(Provider).where(Provider.capability == capability, column.is_(True), Provider.enabled.is_(True))
    )
    if not provider or not provider.encrypted_api_key:
        raise RuntimeError(f"{capability} {relation} Provider 未启用或缺少 API Key")
    return provider


def _job_status(items: list[VideoItem]) -> str:
    if all(item.status == "succeeded" for item in items):
        return "succeeded"
    if any(item.status == "succeeded" for item in items):
        return "partial_failed"
    return "failed"


async def run_video_job(job_id: str, session_factory, settings: Settings, cipher: ApiKeyCipher) -> None:
    client = ProviderClient()
    with session_factory() as session:
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
        )
        if not job:
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
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = utcnow()
                for item in job.items:
                    if item.status in {"queued", "running"}:
                        item.status = "failed"
                        item.error = str(exc)
                session.commit()


async def _run_video_job(
    job_id: str,
    session_factory,
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
        asset = session.scalar(select(Asset).where(Asset.id == asset_ids[0]))
        if not asset:
            raise RuntimeError("视频任务引用的商品图不存在")
        image_url = public_asset_url(settings, asset) if not job.dry_run else asset.url
        prompt_version = session.get(PromptVersion, job.prompt_version_id)
        if not prompt_version:
            raise RuntimeError("视频 Meta Prompt 版本不存在")
        llm_default = _enabled_provider(session, "llm", "default") if not job.dry_run else None
        llm_fallback = _enabled_provider(session, "llm", "fallback") if not job.dry_run else None
        video_provider = _enabled_provider(session, "video", "default") if not job.dry_run else None

    for index, _ in enumerate(range(len(job.items))):
        with session_factory() as session:
            job = session.scalar(
                select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
            )
            item = job.items[index]
            if item.status == "succeeded":
                continue
            item.status = "running"
            session.commit()

        await _run_video_item(
            job_id,
            item.id,
            params,
            image_url,
            prompt_version,
            llm_default,
            llm_fallback,
            video_provider,
            session_factory,
            settings,
            cipher,
            client,
        )

        with session_factory() as session:
            job = session.scalar(
                select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
            )
            finished = sum(1 for item in job.items if item.status in {"succeeded", "failed"})
            job.progress = round(finished * 100 / max(1, job.count))
            session.commit()

    with session_factory() as session:
        job = session.scalar(
            select(VideoJob).where(VideoJob.id == job_id).options(selectinload(VideoJob.items))
        )
        job.status = _job_status(job.items)
        job.progress = 100
        job.completed_at = utcnow()
        session.commit()


async def _run_video_item(
    job_id: str,
    item_id: str,
    params: dict[str, Any],
    image_url: str,
    prompt_version: PromptVersion,
    llm_default: Provider | None,
    llm_fallback: Provider | None,
    video_provider: Provider | None,
    session_factory,
    settings: Settings,
    cipher: ApiKeyCipher,
    client: ProviderClient,
) -> None:
    with session_factory() as session:
        item = session.get(VideoItem, item_id)
        job = session.get(VideoJob, job_id)
        if not item or not job:
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
        script_user_prompt = build_video_script_user_prompt(params, item, image_url)
        ensure_content_safe(run_local_text_safety_review(script_user_prompt), "内容安全拦截")
        script, llm_provider = await _call_llm_with_fallback(
            client,
            llm_default,
            llm_fallback,
            cipher,
            prompt_version.content,
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

        submit_started = perf_counter()
        api_key = cipher.decrypt(video_provider.encrypted_api_key or "")
        response = await client.submit_video_task(
            video_provider,
            api_key,
            seedance_prompt_from_script(script.strip(), params, item),
            image_url,
            aspect_ratio=params.get("aspect_ratio", "9:16"),
            duration=int(params.get("duration", 15)),
            resolution=params.get("resolution", "1080p"),
            generate_audio=bool(params.get("generate_audio", True)),
            camera_fixed=bool(params.get("camera_fixed", False)),
            watermark=bool(params.get("watermark", False)),
        )
        request_id = extract_request_id(response)
        with session_factory() as session:
            item = session.get(VideoItem, item_id)
            item.provider_id = video_provider.id
            item.provider_task_id = request_id
            session.add(
                ExecutionLog(
                    node="video_submit",
                    provider_id=video_provider.id,
                    status="succeeded",
                    duration_ms=int((perf_counter() - submit_started) * 1000),
                    request_summary=safe_json({"video_job_id": job_id, "item_id": item_id, "request_id": request_id}),
                    response_summary=safe_json(response),
                    dry_run=False,
                )
            )
            session.commit()

        remote_url = await poll_video_completion(client, video_provider, api_key, request_id, job_id, item_id, session_factory)
        local_url, file_path = await save_remote_video(client, settings, remote_url, job_id, item_id)
        with session_factory() as session:
            item = session.get(VideoItem, item_id)
            version = VideoVersion(
                item_id=item.id,
                version_no=len(item.versions) + 1 if item.versions else 1,
                instruction="seedance result",
                file_path=str(file_path),
                url=local_url,
                remote_url=remote_url,
                metadata_json=safe_json({"provider": video_provider.code, "request_id": request_id, "params": params}),
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
                item.status = "failed"
                item.error = str(exc)
                session.add(
                    ExecutionLog(
                        node="video_generate",
                        provider_id=video_provider.id if video_provider else None,
                        status="failed",
                        request_summary=safe_json({"video_job_id": job_id, "item_id": item_id}),
                        response_summary="{}",
                        error=str(exc),
                        dry_run=False,
                    )
                )
                session.commit()


async def poll_video_completion(
    client: ProviderClient,
    provider: Provider,
    api_key: str,
    request_id: str,
    job_id: str,
    item_id: str,
    session_factory,
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
        if status == "COMPLETED":
            video_url = extract_video_url(data)
            if not video_url:
                raise RuntimeError("Seedance 任务完成但响应缺少视频 URL")
            return video_url
        if status in REMOTE_FAILED_STATUSES:
            raise RuntimeError(f"Seedance 视频任务失败：{status}")
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
) -> tuple[str, Path]:
    content = await client._download(remote_url, 600)
    video_dir = settings.results_dir / "videos" / job_id
    video_dir.mkdir(parents=True, exist_ok=True)
    destination = video_dir / f"{item_id}.mp4"
    destination.write_bytes(content)
    relative = destination.relative_to(settings.data_dir).as_posix()
    return f"/files/{relative}", destination


def copy_video_file(source: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
