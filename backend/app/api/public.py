from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.database import get_session
from backend.app.models import (
    Asset,
    ExecutionLog,
    GenerationItem,
    GenerationJob,
    GenerationVersion,
    Prompt,
    PromptVersion,
    Provider,
    VideoItem,
    VideoJob,
    VideoVersion,
    Workflow,
)
from backend.app.schemas import (
    AssetOut,
    CopywritingAssistCreate,
    CopywritingAssistOut,
    GenerationJobCreate,
    GenerationJobOut,
    GenerationVersionCreate,
    GenerationVersionOut,
    VideoCopywritingAssistCreate,
    VideoCopywritingAssistOut,
    VideoJobCreate,
    VideoJobOut,
)
from backend.app.services.jobs import (
    _call_llm_with_fallback,
    _enabled_provider,
    create_dryrun_child_version,
    create_live_child_version,
    image_provider_route,
    retry_failed_live_items,
    run_generation_job,
)
from backend.app.services.content_safety import (
    ContentSafetyBlocked,
    ensure_content_safe,
    run_content_safety_review,
    run_local_text_safety_review,
)
from backend.app.services.providers import ProviderClient
from backend.app.services.redaction import safe_json
from backend.app.services.storage import store_upload
from backend.app.services.video_jobs import (
    build_video_copywriting_user_prompt,
    dryrun_video_script,
    public_asset_url,
    run_video_job,
)


router = APIRouter(prefix="/api/v1", tags=["generation"])

def serialize_version(version: GenerationVersion) -> dict:
    return {
        "id": version.id,
        "parent_version_id": version.parent_version_id,
        "version_no": version.version_no,
        "instruction": version.instruction,
        "url": version.url,
        "created_at": version.created_at,
    }


def serialize_job(job: GenerationJob) -> dict:
    serialized_items = []
    for item in job.items:
        serialized_items.append(
            {
                "id": item.id,
                "index": item.index,
                "route_symbol": item.route_symbol,
                "image_type": item.image_type,
                "status": item.status,
                "provider_id": item.provider_id,
                "error": item.error,
                "current_version_id": item.current_version_id,
                "versions": [serialize_version(version) for version in item.versions],
            }
        )
    return {
        "id": job.id,
        "status": job.status,
        "dry_run": job.dry_run,
        "progress": job.progress,
        "count": job.count,
        "params": json.loads(job.params_json),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "items": serialized_items,
    }


def serialize_video_version(version: VideoVersion) -> dict:
    return {
        "id": version.id,
        "parent_version_id": version.parent_version_id,
        "version_no": version.version_no,
        "instruction": version.instruction,
        "url": version.url,
        "remote_url": version.remote_url,
        "created_at": version.created_at,
    }


def serialize_video_job(job: VideoJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "dry_run": job.dry_run,
        "progress": job.progress,
        "count": job.count,
        "params": json.loads(job.params_json),
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "items": [
            {
                "id": item.id,
                "index": item.index,
                "video_type": item.video_type,
                "status": item.status,
                "provider_id": item.provider_id,
                "provider_task_id": item.provider_task_id,
                "error": item.error,
                "prompt_text": item.prompt_text,
                "script_markdown": item.script_markdown,
                "current_version_id": item.current_version_id,
                "versions": [serialize_video_version(version) for version in item.versions],
            }
            for item in job.items
        ],
    }


def load_job(session: Session, job_id: str) -> GenerationJob:
    job = session.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id)
        .options(selectinload(GenerationJob.items).selectinload(GenerationItem.versions))
    )
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def load_video_job(session: Session, job_id: str) -> VideoJob:
    job = session.scalar(
        select(VideoJob)
        .where(VideoJob.id == job_id)
        .options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
    )
    if not job:
        raise HTTPException(status_code=404, detail="视频任务不存在")
    return job


def dryrun_copywriting_text(source: str) -> str:
    product_name = source.replace("，", ",").split(",")[0].strip() or "商品"
    return f"""---
### 1. 商品定位
- 品名：{product_name}
### 2. 适用场景
- 日常通勤：上班族随身携带，路上与办公室都方便取用。
- 桌面使用：家庭用户放在桌面，喝水、饮茶时顺手稳定。
- 短途出行：外出人群放入背包或车内，满足临时饮用需求。
### 3. 5大核心卖点
1. 简洁外观：日常搭配自然不突兀。
2. 防滑握持：拿取更稳，降低滑落风险。
3. 场景百搭：通勤、居家与出行都适用。
4. 使用顺手：高频饮用场景取放更方便。
5. 视觉干净：适合电商主图与场景图表达。
---"""


def parse_copywriting_text(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("selling_points"), str):
        return parsed["selling_points"].strip()
    return raw.strip()


def build_long_image(image_paths: list[str], destination: Path) -> None:
    opened: list[Image.Image] = []
    try:
        for image_path in image_paths:
            opened.append(Image.open(image_path).convert("RGB"))
        target_width = max(image.width for image in opened)
        resized: list[Image.Image] = []
        for image in opened:
            if image.width == target_width:
                resized.append(image.copy())
                continue
            target_height = round(image.height * target_width / image.width)
            resized.append(image.resize((target_width, target_height), Image.Resampling.LANCZOS))
        total_height = sum(image.height for image in resized)
        canvas = Image.new("RGB", (target_width, total_height), "white")
        offset = 0
        for image in resized:
            canvas.paste(image, (0, offset))
            offset += image.height
        canvas.save(destination, format="PNG")
    finally:
        for image in opened:
            image.close()


def build_copywriting_user_prompt(payload: CopywritingAssistCreate) -> str:
    input_mode = "image_with_text" if payload.selling_points.strip() else "image_only"
    return json.dumps(
        {
            "input_mode": input_mode,
            "platform": payload.platform,
            "market": payload.market,
            "image_text_language": payload.language,
            "output_language": "简体中文",
            "selling_points": payload.selling_points,
            "instruction": (
                "必须使用简体中文输出 AI 帮写候选内容；"
                "image_text_language 只代表后续图片画面文案语言，不得影响本节点输出语言。"
            ),
        },
        ensure_ascii=False,
    )


@router.post("/assets", response_model=AssetOut, status_code=201)
async def create_asset(request: Request, file: UploadFile, session: Session = Depends(get_session)):
    asset = await store_upload(file, request.app.state.settings)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/generation-jobs", response_model=GenerationJobOut, status_code=201)
async def create_generation_job(
    payload: GenerationJobCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
):
    assets = session.scalars(select(Asset).where(Asset.id.in_(payload.asset_ids))).all()
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="存在无效商品图")
    if not payload.dry_run:
        providers = session.scalars(select(Provider)).all()
        required: dict[tuple[str, str], Provider | None] = {
            ("llm", "default"): next((item for item in providers if item.capability == "llm" and item.is_default), None),
            ("llm", "fallback"): next((item for item in providers if item.capability == "llm" and item.is_fallback), None),
        }
        for code in image_provider_route(payload.model_preference):
            required[("image", code)] = next((item for item in providers if item.code == code), None)
        unavailable = [
            f"{capability}-{relation}"
            for (capability, relation), provider in required.items()
            if not provider or not provider.enabled or not provider.encrypted_api_key
        ]
        if unavailable:
            raise HTTPException(
                status_code=409,
                detail=f"Live 模式不可用，请先配置并启用：{', '.join(unavailable)}",
            )

    prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-meta"))
    workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
    if not prompt or not prompt.active_version_id or not workflow or not workflow.active_version_id:
        raise HTTPException(status_code=500, detail="核心 Prompt 或 Workflow 未启用")
    auxiliary_prompts = session.scalars(
        select(Prompt).where(Prompt.code.in_(("product-vision", "copywriting-assist", "edit-rewrite", "content-safety-review")))
    ).all()
    prompt_versions = {
        item.code: item.active_version_id for item in auxiliary_prompts if item.active_version_id
    }
    if len(prompt_versions) != 4:
        raise HTTPException(status_code=500, detail="Prompt 工程辅助资产未完整启用")
    params = payload.model_dump()
    params["_prompt_versions"] = prompt_versions
    input_text = json.dumps(payload.model_dump(exclude={"asset_ids", "dry_run"}), ensure_ascii=False)
    try:
        ensure_content_safe(run_local_text_safety_review(input_text), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not payload.dry_run:
        safety_prompt = next((item for item in auxiliary_prompts if item.code == "content-safety-review"), None)
        safety_version = session.get(PromptVersion, safety_prompt.active_version_id) if safety_prompt and safety_prompt.active_version_id else None
        if not safety_version:
            raise HTTPException(status_code=500, detail="内容安全审计 Prompt 未启用")
        assets_by_id = {asset.id: asset for asset in assets}
        image_paths = [assets_by_id[asset_id].file_path for asset_id in payload.asset_ids]
        llm_default = _enabled_provider(session, "llm", "default")
        llm_fallback = _enabled_provider(session, "llm", "fallback")
        try:
            review, provider = await run_content_safety_review(
                ProviderClient(),
                llm_default,
                llm_fallback,
                request.app.state.cipher,
                safety_version,
                subject="generation_input",
                text=input_text,
                image_paths=image_paths,
            )
            ensure_content_safe(review, "输入内容安全拦截")
        except ContentSafetyBlocked as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"输入内容安全拦截：安全审计失败：{exc}") from exc
        session.add(
            ExecutionLog(
                node="content_safety",
                provider_id=provider.id,
                status="succeeded",
                request_summary=safe_json({"subject": "generation_input", "asset_count": len(image_paths)}),
                response_summary=safe_json(review.model_dump()),
                dry_run=False,
            )
        )
        session.commit()
    job = GenerationJob(
        status="queued",
        dry_run=payload.dry_run,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=payload.count,
        progress=0,
        prompt_version_id=prompt.active_version_id,
        workflow_version_id=workflow.active_version_id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    background_tasks.add_task(
        run_generation_job,
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.cipher,
    )
    return serialize_job(job)


@router.post("/copywriting-assist", response_model=CopywritingAssistOut)
async def assist_copywriting(
    payload: CopywritingAssistCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    user_prompt = build_copywriting_user_prompt(payload)
    try:
        ensure_content_safe(run_local_text_safety_review(user_prompt), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.dry_run:
        source = payload.selling_points.strip() or "突出产品用途、材质体验与使用场景"
        result = dryrun_copywriting_text(source)
        session.add(
            ExecutionLog(
                node="copywriting_assist",
                status="succeeded",
                request_summary=safe_json(payload.model_dump()),
                response_summary=safe_json({"selling_points": result}),
                dry_run=True,
            )
        )
        session.commit()
        return CopywritingAssistOut(selling_points=result, dry_run=True)

    prompt = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    if not prompt_version:
        raise HTTPException(status_code=500, detail="AI 帮写 Prompt 未启用")
    safety_prompt = session.scalar(select(Prompt).where(Prompt.code == "content-safety-review"))
    safety_version = session.get(PromptVersion, safety_prompt.active_version_id) if safety_prompt and safety_prompt.active_version_id else None
    if not safety_version:
        raise HTTPException(status_code=500, detail="内容安全审计 Prompt 未启用")
    assets = session.scalars(select(Asset).where(Asset.id.in_(payload.asset_ids))).all() if payload.asset_ids else []
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="AI 帮写包含无效商品图")
    image_paths = [asset.file_path for asset in assets]
    llm_default = _enabled_provider(session, "llm", "default")
    llm_fallback = _enabled_provider(session, "llm", "fallback")
    try:
        input_review, input_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="copywriting_input",
            text=user_prompt,
            image_paths=image_paths,
        )
        ensure_content_safe(input_review, "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"输入内容安全拦截：安全审计失败：{exc}") from exc
    session.add(
        ExecutionLog(
            node="content_safety",
            provider_id=input_provider.id,
            status="succeeded",
            request_summary=safe_json({"subject": "copywriting_input", "asset_count": len(image_paths)}),
            response_summary=safe_json(input_review.model_dump()),
            dry_run=False,
        )
    )
    session.commit()
    raw, provider = await _call_llm_with_fallback(
        ProviderClient(),
        llm_default,
        llm_fallback,
        request.app.state.cipher,
        prompt_version.content,
        user_prompt,
        image_paths=image_paths,
        response_format=None,
    )
    selling_points = parse_copywriting_text(raw)
    if not selling_points:
        raise HTTPException(status_code=502, detail="AI 帮写返回空内容")
    try:
        output_review, output_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="copywriting_output",
            text=selling_points,
        )
        ensure_content_safe(output_review, "内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"内容安全拦截：安全审计失败：{exc}") from exc
    session.add(
        ExecutionLog(
            node="content_safety",
            provider_id=output_provider.id,
            status="succeeded",
            request_summary=safe_json({"subject": "copywriting_output"}),
            response_summary=safe_json(output_review.model_dump()),
            dry_run=False,
        )
    )
    session.add(
        ExecutionLog(
            node="copywriting_assist",
            provider_id=provider.id,
            status="succeeded",
            request_summary=safe_json({**payload.model_dump(exclude={"dry_run", "asset_ids"}), "asset_count": len(image_paths), "prompt_version_id": prompt_version.id}),
            response_summary=safe_json({"selling_points": selling_points}),
            dry_run=False,
        )
    )
    session.commit()
    return CopywritingAssistOut(
        selling_points=selling_points.strip(),
        dry_run=False,
        provider_code=provider.code,
    )


@router.post("/video-copywriting-assist", response_model=VideoCopywritingAssistOut)
async def assist_video_copywriting(
    payload: VideoCopywritingAssistCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    user_prompt = build_video_copywriting_user_prompt(payload)
    try:
        ensure_content_safe(run_local_text_safety_review(user_prompt), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.dry_run:
        text = payload.selling_points.strip() or "请突出商品核心痛点、适用人群、使用场景和 15 秒视频转化目标。"
        result = (
            f"1. 核心卖点：{text}\n"
            f"2. 视频方向：{', '.join(payload.video_types or ['UGC 种草'])}\n"
            "3. 建议结构：前三秒抓痛点，中段展示商品解决过程，最后定格产品和简单行动号召。"
        )
        session.add(
            ExecutionLog(
                node="video_copywriting_assist",
                status="succeeded",
                request_summary=safe_json(payload.model_dump()),
                response_summary=safe_json({"selling_points": result}),
                dry_run=True,
            )
        )
        session.commit()
        return VideoCopywritingAssistOut(selling_points=result, dry_run=True)

    prompt = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    safety_prompt = session.scalar(select(Prompt).where(Prompt.code == "content-safety-review"))
    safety_version = session.get(PromptVersion, safety_prompt.active_version_id) if safety_prompt and safety_prompt.active_version_id else None
    if not prompt_version or not safety_version:
        raise HTTPException(status_code=500, detail="视频帮写依赖 Prompt 未启用")
    assets = session.scalars(select(Asset).where(Asset.id.in_(payload.asset_ids))).all() if payload.asset_ids else []
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="视频帮写包含无效商品图")
    image_paths = [asset.file_path for asset in assets]
    llm_default = _enabled_provider(session, "llm", "default")
    llm_fallback = _enabled_provider(session, "llm", "fallback")
    try:
        input_review, input_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="video_copywriting_input",
            text=user_prompt,
            image_paths=image_paths,
        )
        ensure_content_safe(input_review, "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"输入内容安全拦截：安全审计失败：{exc}") from exc
    raw, provider = await _call_llm_with_fallback(
        ProviderClient(),
        llm_default,
        llm_fallback,
        request.app.state.cipher,
        prompt_version.content,
        user_prompt,
        image_paths=image_paths,
        response_format=None,
    )
    selling_points = parse_copywriting_text(raw)
    try:
        output_review, output_provider = await run_content_safety_review(
            ProviderClient(),
            llm_default,
            llm_fallback,
            request.app.state.cipher,
            safety_version,
            subject="video_copywriting_output",
            text=selling_points,
        )
        ensure_content_safe(output_review, "内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"内容安全拦截：安全审计失败：{exc}") from exc
    session.add_all(
        [
            ExecutionLog(
                node="content_safety",
                provider_id=input_provider.id,
                status="succeeded",
                request_summary=safe_json({"subject": "video_copywriting_input", "asset_count": len(image_paths)}),
                response_summary=safe_json(input_review.model_dump()),
                dry_run=False,
            ),
            ExecutionLog(
                node="content_safety",
                provider_id=output_provider.id,
                status="succeeded",
                request_summary=safe_json({"subject": "video_copywriting_output"}),
                response_summary=safe_json(output_review.model_dump()),
                dry_run=False,
            ),
            ExecutionLog(
                node="video_copywriting_assist",
                provider_id=provider.id,
                status="succeeded",
                request_summary=safe_json(payload.model_dump(exclude={"asset_ids"})),
                response_summary=safe_json({"selling_points": selling_points}),
                dry_run=False,
            ),
        ]
    )
    session.commit()
    return VideoCopywritingAssistOut(selling_points=selling_points, dry_run=False, provider_code=provider.code)


@router.post("/video-jobs", response_model=VideoJobOut, status_code=201)
async def create_video_job(
    payload: VideoJobCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
):
    assets = session.scalars(select(Asset).where(Asset.id.in_(payload.asset_ids))).all()
    if len(assets) != len(payload.asset_ids):
        raise HTTPException(status_code=422, detail="存在无效商品图")
    prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-video-meta-15s"))
    prompt_version = session.get(PromptVersion, prompt.active_version_id) if prompt and prompt.active_version_id else None
    if not prompt_version:
        raise HTTPException(status_code=500, detail="视频 Meta Prompt 未启用")
    params = payload.model_dump()
    input_text = json.dumps(payload.model_dump(exclude={"asset_ids", "dry_run"}), ensure_ascii=False)
    try:
        ensure_content_safe(run_local_text_safety_review(input_text), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not payload.dry_run:
        try:
            _enabled_provider(session, "llm", "default")
            _enabled_provider(session, "llm", "fallback")
            _enabled_provider(session, "video", "default")
            public_asset_url(request.app.state.settings, assets[0])
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        safety_prompt = session.scalar(select(Prompt).where(Prompt.code == "content-safety-review"))
        safety_version = session.get(PromptVersion, safety_prompt.active_version_id) if safety_prompt and safety_prompt.active_version_id else None
        if not safety_version:
            raise HTTPException(status_code=500, detail="内容安全审计 Prompt 未启用")
        llm_default = _enabled_provider(session, "llm", "default")
        llm_fallback = _enabled_provider(session, "llm", "fallback")
        try:
            review, provider = await run_content_safety_review(
                ProviderClient(),
                llm_default,
                llm_fallback,
                request.app.state.cipher,
                safety_version,
                subject="video_generation_input",
                text=input_text,
                image_paths=[asset.file_path for asset in assets],
            )
            ensure_content_safe(review, "输入内容安全拦截")
        except ContentSafetyBlocked as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"输入内容安全拦截：安全审计失败：{exc}") from exc
        session.add(
            ExecutionLog(
                node="content_safety",
                provider_id=provider.id,
                status="succeeded",
                request_summary=safe_json({"subject": "video_generation_input", "asset_count": len(assets)}),
                response_summary=safe_json(review.model_dump()),
                dry_run=False,
            )
        )
        session.commit()

    params["_prompt_versions"] = {"ecommerce-video-meta-15s": prompt_version.id}
    job = VideoJob(
        status="queued",
        dry_run=payload.dry_run,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=len(payload.video_types),
        progress=0,
        prompt_version_id=prompt_version.id,
    )
    session.add(job)
    session.flush()
    for index, video_type in enumerate(payload.video_types):
        session.add(
            VideoItem(
                job_id=job.id,
                index=index,
                video_type=video_type,
                status="queued",
            )
        )
    session.commit()
    session.refresh(job)
    background_tasks.add_task(
        run_video_job,
        job.id,
        request.app.state.session_factory,
        request.app.state.settings,
        request.app.state.cipher,
    )
    return serialize_video_job(load_video_job(session, job.id))


@router.get("/video-jobs", response_model=list[VideoJobOut])
def list_video_jobs(session: Session = Depends(get_session)):
    jobs = session.scalars(
        select(VideoJob)
        .options(selectinload(VideoJob.items).selectinload(VideoItem.versions))
        .order_by(VideoJob.created_at.desc())
    ).all()
    return [serialize_video_job(job) for job in jobs]


@router.get("/video-jobs/{job_id}", response_model=VideoJobOut)
def get_video_job(job_id: str, session: Session = Depends(get_session)):
    return serialize_video_job(load_video_job(session, job_id))


@router.post("/video-jobs/{job_id}/retry-failed", response_model=VideoJobOut)
async def retry_failed_video_job(job_id: str, request: Request, session: Session = Depends(get_session)):
    job = load_video_job(session, job_id)
    if not any(item.status == "failed" for item in job.items):
        return serialize_video_job(job)
    for item in job.items:
        if item.status == "failed":
            item.status = "queued"
            item.error = None
    job.status = "queued"
    job.progress = 0
    session.commit()
    await run_video_job(job.id, request.app.state.session_factory, request.app.state.settings, request.app.state.cipher)
    session.expire_all()
    return serialize_video_job(load_video_job(session, job.id))


@router.get("/video-jobs/{job_id}/download")
def download_video_results(
    job_id: str,
    request: Request,
    item_ids: str = Query(min_length=1),
    session: Session = Depends(get_session),
):
    job = load_video_job(session, job_id)
    selected = {item_id for item_id in item_ids.split(",") if item_id}
    versions: list[tuple[VideoItem, VideoVersion]] = []
    for item in job.items:
        if item.id not in selected or not item.current_version_id:
            continue
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current and current.file_path and Path(current.file_path).exists():
            versions.append((item, current))
    if not versions:
        raise HTTPException(status_code=422, detail="没有可下载的视频结果")
    if len(versions) == 1:
        item, version = versions[0]
        return FileResponse(version.file_path, media_type="video/mp4", filename=f"listingo-video-{item.index + 1:02d}.mp4")
    archive = request.app.state.settings.exports_dir / f"listingo-video-{job.id}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for item, version in versions:
            zip_file.write(version.file_path, arcname=f"{item.index + 1:02d}-{item.video_type}.mp4")
    return FileResponse(archive, media_type="application/zip", filename=f"listingo-video-{job.id}.zip")


@router.get("/generation-jobs", response_model=list[GenerationJobOut])
def list_generation_jobs(session: Session = Depends(get_session)):
    jobs = session.scalars(
        select(GenerationJob)
        .options(selectinload(GenerationJob.items).selectinload(GenerationItem.versions))
        .order_by(GenerationJob.created_at.desc())
    ).all()
    return [serialize_job(job) for job in jobs]


@router.get("/generation-jobs/{job_id}", response_model=GenerationJobOut)
def get_generation_job(job_id: str, session: Session = Depends(get_session)):
    return serialize_job(load_job(session, job_id))


@router.post("/generation-jobs/{job_id}/retry-failed", response_model=GenerationJobOut)
async def retry_failed(job_id: str, request: Request, session: Session = Depends(get_session)):
    job = load_job(session, job_id)
    failed = [item for item in job.items if item.status == "failed"]
    if not failed:
        return serialize_job(job)
    if job.dry_run:
        raise HTTPException(status_code=409, detail="Dryrun 不会产生可重试的模型失败项")
    await retry_failed_live_items(
        job.id, request.app.state.session_factory, request.app.state.settings, request.app.state.cipher
    )
    session.expire_all()
    return serialize_job(load_job(session, job.id))


@router.get("/generation-jobs/{job_id}/download")
def download_results(
    job_id: str,
    request: Request,
    item_ids: str = Query(min_length=1),
    format: str = Query(default="zip", pattern="^(zip|long_image)$"),
    session: Session = Depends(get_session),
):
    job = load_job(session, job_id)
    selected = {item_id for item_id in item_ids.split(",") if item_id}
    versions: list[tuple[GenerationItem, GenerationVersion]] = []
    for item in job.items:
        if item.id not in selected or not item.current_version_id:
            continue
        current = next((version for version in item.versions if version.id == item.current_version_id), None)
        if current and Path(current.file_path).exists():
            versions.append((item, current))
    if not versions:
        raise HTTPException(status_code=422, detail="没有可下载的已选结果")

    if format == "long_image":
        export_path = request.app.state.settings.exports_dir / f"listingo-{job.id}-long.png"
        build_long_image([version.file_path for _, version in versions], export_path)
        return FileResponse(export_path, media_type="image/png", filename=f"listingo-{job.id}-long.png")

    archive = request.app.state.settings.exports_dir / f"listingo-{job.id}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for item, version in versions:
            zip_file.write(version.file_path, arcname=f"{item.index + 1:02d}-{item.image_type}.png")
    return FileResponse(archive, media_type="application/zip", filename=f"listingo-{job.id}.zip")


@router.post("/generation-items/{item_id}/versions", response_model=GenerationVersionOut, status_code=201)
async def create_generation_version(
    item_id: str,
    payload: GenerationVersionCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    item = session.scalar(
        select(GenerationItem).where(GenerationItem.id == item_id).options(selectinload(GenerationItem.versions))
    )
    if not item:
        raise HTTPException(status_code=404, detail="生成项不存在")
    job = session.get(GenerationJob, item.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.dry_run:
        return create_dryrun_child_version(session, item, payload.instruction, request.app.state.settings)
    try:
        return await create_live_child_version(
            session, item, payload.instruction, request.app.state.settings, request.app.state.cipher
        )
    except ContentSafetyBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        if str(exc).startswith("内容安全拦截"):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise
