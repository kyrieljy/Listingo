from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
from time import perf_counter

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.database import get_session
from backend.app.models import ExecutionLog, Prompt, PromptTestRun, PromptVersion, Provider, Workflow, WorkflowVersion
from backend.app.schemas import (
    PromptTestRunCreate,
    PromptTestRunOut,
    PromptVersionCreate,
    ProviderOut,
    ProviderTestOut,
    ProviderUpdate,
    WorkflowVersionCreate,
)
from backend.app.security import mask_api_key
from backend.app.services.provider_routing import (
    PROVIDER_ROUTE_DEFINITIONS,
    VALID_PROVIDER_ROUTE_ROLES,
    normalize_route_roles,
    provider_config,
    provider_route_roles,
    write_provider_config,
)
from backend.app.services.redaction import safe_json
from backend.app.services.providers import build_async_http_client
from backend.app.services.jobs import run_generation_job
from backend.app.services.prompt_testing import (
    FULL_CHAIN_TEST_TYPE,
    LLM_TEST_TYPE,
    create_full_chain_prompt_test_run,
    create_llm_prompt_test_run,
    prompt_test_run_dict,
    refresh_prompt_test_run_from_related_job,
    run_aplus_full_chain_prompt_test,
)
from backend.app.services.video_jobs import run_video_job
from backend.app.services.workflow_registry import validate_workflow_graph


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def provider_dict(provider: Provider, request: Request) -> dict:
    plain = request.app.state.cipher.decrypt(provider.encrypted_api_key) if provider.encrypted_api_key else None
    return {
        "id": provider.id,
        "code": provider.code,
        "label": provider.label,
        "capability": provider.capability,
        "adapter": provider.adapter,
        "base_url": provider.base_url,
        "model_name": provider.model_name,
        "enabled": provider.enabled,
        "is_default": provider.is_default,
        "is_fallback": provider.is_fallback,
        "route_roles": provider_route_roles(provider),
        "has_api_key": bool(plain),
        "api_key_masked": mask_api_key(plain),
        "config": json.loads(provider.config_json),
        "updated_at": provider.updated_at,
    }


def prompt_version_dict(version: PromptVersion) -> dict:
    return {
        "id": version.id,
        "version_no": version.version_no,
        "content": version.content,
        "content_sha256": version.content_sha256,
        "change_note": version.change_note,
        "created_at": version.created_at,
    }


def workflow_version_dict(version: WorkflowVersion) -> dict:
    graph = json.loads(version.graph_json)
    return {
        "id": version.id,
        "version_no": version.version_no,
        "graph": graph,
        "change_note": version.change_note,
        "validation_errors": validate_workflow_graph(graph),
        "created_at": version.created_at,
    }


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(request: Request, session: Session = Depends(get_session)):
    providers = session.scalars(select(Provider).order_by(Provider.capability, Provider.is_default.desc())).all()
    return [provider_dict(provider, request) for provider in providers]


@router.get("/runtime-settings")
def get_runtime_settings(request: Request):
    settings = request.app.state.settings
    return {
        "public_asset_base_url": settings.public_asset_base_url,
        "public_asset_base_url_configured": bool(settings.public_asset_base_url.strip()),
    }


@router.patch("/runtime-settings")
def update_runtime_settings(payload: dict[str, str], request: Request):
    value = (payload.get("public_asset_base_url") or "").strip()
    request.app.state.settings.public_asset_base_url = value.rstrip("/")
    return {
        "public_asset_base_url": request.app.state.settings.public_asset_base_url,
        "public_asset_base_url_configured": bool(request.app.state.settings.public_asset_base_url),
    }


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    request: Request,
    session: Session = Depends(get_session),
):
    provider = session.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    updates = payload.model_dump(exclude_unset=True)
    api_key = updates.pop("api_key", None)
    route_role_updates = updates.pop("route_roles", None)
    config = provider_config(provider)
    for key in ("resolution", "size", "quality", "format", "compression", "timeout_seconds"):
        if key in updates:
            config[key] = updates.pop(key)
    for key in ("label", "base_url", "model_name", "enabled"):
        if key in updates:
            setattr(provider, key, updates.pop(key))
    for relation_key in ("is_default", "is_fallback"):
        if relation_key in updates:
            enabled_relation = updates.pop(relation_key)
            if enabled_relation:
                peers = session.scalars(
                    select(Provider).where(Provider.capability == provider.capability, Provider.id != provider.id)
                ).all()
                for peer in peers:
                    setattr(peer, relation_key, False)
            setattr(provider, relation_key, enabled_relation)
    if api_key:
        provider.encrypted_api_key = request.app.state.cipher.encrypt(api_key)
    if route_role_updates is not None:
        roles = normalize_route_roles(config.get("route_roles"))
        for route_key, role in route_role_updates.items():
            if route_key not in PROVIDER_ROUTE_DEFINITIONS:
                raise HTTPException(status_code=422, detail=f"未知模型链路：{route_key}")
            route_capability = PROVIDER_ROUTE_DEFINITIONS[route_key]["capability"]
            if route_capability != provider.capability:
                raise HTTPException(status_code=422, detail=f"{provider.label} 不能配置到 {route_key} 链路")
            normalized_role = None if role in (None, "", "none") else role
            if normalized_role is not None and normalized_role not in VALID_PROVIDER_ROUTE_ROLES:
                raise HTTPException(status_code=422, detail=f"不支持的链路角色：{role}")
            if normalized_role is None:
                roles.pop(route_key, None)
                continue
            peers = session.scalars(select(Provider).where(Provider.id != provider.id)).all()
            for peer in peers:
                peer_config = provider_config(peer)
                peer_roles = normalize_route_roles(peer_config.get("route_roles"))
                if peer_roles.get(route_key) == normalized_role:
                    peer_roles.pop(route_key, None)
                    peer_config["route_roles"] = peer_roles
                    write_provider_config(peer, peer_config)
            roles[route_key] = normalized_role
        config["route_roles"] = roles
    provider.config_json = json.dumps(config, ensure_ascii=False)
    session.commit()
    session.refresh(provider)
    return provider_dict(provider, request)


@router.post("/providers/{provider_id}/test", response_model=ProviderTestOut)
async def test_provider(provider_id: str, request: Request, session: Session = Depends(get_session)):
    provider = session.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if not provider.encrypted_api_key:
        raise HTTPException(status_code=422, detail="请先录入 API Key")
    api_key = request.app.state.cipher.decrypt(provider.encrypted_api_key)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    config = json.loads(provider.config_json)
    if provider.capability in {"image", "video"}:
        started = perf_counter()
        try:
            models_url = provider.base_url.partition("/v1")[0] + "/v1/models"
            async with build_async_http_client(int(config.get("timeout_seconds", 60))) as client:
                response = await client.get(models_url, headers=headers)
                response.raise_for_status()
            model_ids = {
                item.get("id")
                for item in response.json().get("data", [])
                if isinstance(item, dict)
            }
            latency = int((perf_counter() - started) * 1000)
            if provider.adapter == "shengsuanyun_tasks_generation":
                return ProviderTestOut(
                    ok=True,
                    latency_ms=latency,
                    message="连接可用，未发起计费视频任务",
                )
            if provider.model_name not in model_ids:
                return ProviderTestOut(
                    ok=False,
                    latency_ms=latency,
                    message=f"认证成功，但模型目录中不存在 {provider.model_name}",
                )
            return ProviderTestOut(
                ok=True,
                latency_ms=latency,
                message=f"连接成功：密钥有效，模型 {provider.model_name} 可用（未发起计费生图）",
            )
        except httpx.HTTPStatusError as exc:
            latency = int((perf_counter() - started) * 1000)
            detail = exc.response.text.replace("\n", " ")[:240]
            return ProviderTestOut(
                ok=False,
                latency_ms=latency,
                message=f"HTTP {exc.response.status_code}：{detail}",
            )
        except httpx.RequestError as exc:
            latency = int((perf_counter() - started) * 1000)
            return ProviderTestOut(ok=False, latency_ms=latency, message=f"网络连接失败：{str(exc)[:240]}")
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            latency = int((perf_counter() - started) * 1000)
            return ProviderTestOut(ok=False, latency_ms=latency, message=f"响应校验失败：{str(exc)[:240]}")
    if provider.adapter == "openai_chat":
        payload = {"model": provider.model_name, "messages": [{"role": "user", "content": "仅回复 OK"}], "max_tokens": 8}
    elif provider.adapter == "gemini_generate_content":
        payload = {"contents": [{"parts": [{"text": "Return a 32x32 neutral test image."}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    else:
        payload = {"model": provider.model_name, "prompt": "A plain white square", "n": 1, "size": "1024x1024"}
    started = perf_counter()
    try:
        async with build_async_http_client(int(config.get("timeout_seconds", 60))) as client:
            response = await client.post(provider.base_url, headers=headers, json=payload)
            response.raise_for_status()
        latency = int((perf_counter() - started) * 1000)
        return ProviderTestOut(ok=True, latency_ms=latency, message="连通测试成功")
    except httpx.HTTPError as exc:
        latency = int((perf_counter() - started) * 1000)
        return ProviderTestOut(ok=False, latency_ms=latency, message=f"连通测试失败：{type(exc).__name__}")


@router.get("/prompts")
def list_prompts(session: Session = Depends(get_session)):
    prompts = session.scalars(select(Prompt).options(selectinload(Prompt.versions)).order_by(Prompt.name)).all()
    return [
        {
            "id": prompt.id,
            "code": prompt.code,
            "name": prompt.name,
            "description": prompt.description,
            "active_version_id": prompt.active_version_id,
            "version_count": len(prompt.versions),
            "updated_at": prompt.updated_at,
        }
        for prompt in prompts
    ]


@router.get("/prompts/{prompt_id}")
def get_prompt(prompt_id: str, session: Session = Depends(get_session)):
    prompt = session.scalar(select(Prompt).where(Prompt.id == prompt_id).options(selectinload(Prompt.versions)))
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    active = next((version for version in prompt.versions if version.id == prompt.active_version_id), None)
    return {
        "id": prompt.id,
        "code": prompt.code,
        "name": prompt.name,
        "description": prompt.description,
        "active_version_id": prompt.active_version_id,
        "active_version": prompt_version_dict(active) if active else None,
        "versions": [prompt_version_dict(version) for version in sorted(prompt.versions, key=lambda item: item.version_no, reverse=True)],
    }


@router.post("/prompts/{prompt_id}/versions", status_code=201)
def create_prompt_version(prompt_id: str, payload: PromptVersionCreate, session: Session = Depends(get_session)):
    prompt = session.scalar(select(Prompt).where(Prompt.id == prompt_id).options(selectinload(Prompt.versions)))
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    version = PromptVersion(
        prompt_id=prompt.id,
        version_no=max((item.version_no for item in prompt.versions), default=0) + 1,
        content=payload.content,
        content_sha256=hashlib.sha256(payload.content.encode("utf-8")).hexdigest().upper(),
        change_note=payload.change_note,
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return prompt_version_dict(version)


@router.post("/prompts/{prompt_id}/versions/upload", status_code=201)
async def upload_prompt_version(
    prompt_id: str,
    file: UploadFile,
    change_note: str = Form(default=""),
    session: Session = Depends(get_session),
):
    prompt = session.scalar(
        select(Prompt).where(Prompt.id == prompt_id).options(selectinload(Prompt.versions))
    )
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词资产不存在")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".md", ".txt"}:
        raise HTTPException(status_code=422, detail="仅支持上传 MD 或 TXT 提示词文件")
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="提示词文件不能超过 2MB")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="提示词文件必须为 UTF-8 编码") from exc
    if "\x00" in content or len(content.strip()) < 20:
        raise HTTPException(status_code=422, detail="提示词文件内容过短或不是文本文件")
    version = PromptVersion(
        prompt_id=prompt.id,
        version_no=max((item.version_no for item in prompt.versions), default=0) + 1,
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest().upper(),
        change_note=change_note.strip()[:500] or f"上传文件：{file.filename}",
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return prompt_version_dict(version)


@router.get("/prompts/{prompt_id}/compare")
def compare_prompt_versions(
    prompt_id: str,
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
    session: Session = Depends(get_session),
):
    versions = session.scalars(select(PromptVersion).where(PromptVersion.prompt_id == prompt_id)).all()
    source = next((version for version in versions if version.version_no == from_version), None)
    target = next((version for version in versions if version.version_no == to_version), None)
    if not source or not target:
        raise HTTPException(status_code=404, detail="提示词版本不存在")
    diff = "\n".join(
        difflib.unified_diff(
            source.content.splitlines(),
            target.content.splitlines(),
            fromfile=f"v{from_version}",
            tofile=f"v{to_version}",
            lineterm="",
        )
    )
    return {"from_version": from_version, "to_version": to_version, "diff": diff}


@router.post("/prompts/{prompt_id}/versions/{version_id}/activate")
def activate_prompt_version(prompt_id: str, version_id: str, session: Session = Depends(get_session)):
    prompt = session.get(Prompt, prompt_id)
    version = session.get(PromptVersion, version_id)
    if not prompt or not version or version.prompt_id != prompt.id:
        raise HTTPException(status_code=404, detail="提示词或版本不存在")
    prompt.active_version_id = version.id
    session.commit()
    return {"id": prompt.id, "active_version_id": prompt.active_version_id}


@router.post("/prompts/{prompt_id}/test-runs", response_model=PromptTestRunOut, status_code=201)
async def create_prompt_test_run(
    prompt_id: str,
    payload: PromptTestRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
):
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    if payload.test_type == LLM_TEST_TYPE:
        try:
            run = await create_llm_prompt_test_run(session, prompt, payload, request.app.state.cipher)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.commit()
        session.refresh(run)
        return prompt_test_run_dict(run)
    if payload.test_type == FULL_CHAIN_TEST_TYPE:
        try:
            run, schedule = create_full_chain_prompt_test_run(session, prompt, payload, request.app.state.settings)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.commit()
        session.refresh(run)
        kind, job_id = schedule
        if kind == "generation":
            background_tasks.add_task(
                run_generation_job,
                job_id,
                request.app.state.session_factory,
                request.app.state.settings,
                request.app.state.cipher,
            )
        elif kind == "video":
            background_tasks.add_task(
                run_video_job,
                job_id,
                request.app.state.session_factory,
                request.app.state.settings,
                request.app.state.cipher,
            )
        else:
            background_tasks.add_task(
                run_aplus_full_chain_prompt_test,
                run.id,
                request.app.state.session_factory,
                request.app.state.settings,
                request.app.state.cipher,
            )
        return prompt_test_run_dict(run)
    raise HTTPException(status_code=422, detail="不支持的提示词测试类型")


@router.get("/prompt-test-runs/{run_id}", response_model=PromptTestRunOut)
def get_prompt_test_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(PromptTestRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="提示词测试记录不存在")
    refresh_prompt_test_run_from_related_job(session, run)
    session.commit()
    session.refresh(run)
    return prompt_test_run_dict(run)


@router.get("/prompts/{prompt_id}/test-runs", response_model=list[PromptTestRunOut])
def list_prompt_test_runs(
    prompt_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
):
    prompt = session.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    runs = session.scalars(
        select(PromptTestRun)
        .where(PromptTestRun.prompt_id == prompt_id)
        .order_by(PromptTestRun.created_at.desc())
        .limit(limit)
    ).all()
    for run in runs:
        refresh_prompt_test_run_from_related_job(session, run)
    session.commit()
    return [prompt_test_run_dict(run) for run in runs]


@router.get("/workflows")
def list_workflows(session: Session = Depends(get_session)):
    workflows = session.scalars(select(Workflow).options(selectinload(Workflow.versions))).all()
    return [
        {
            "id": workflow.id,
            "code": workflow.code,
            "name": workflow.name,
            "description": workflow.description,
            "active_version_id": workflow.active_version_id,
            "version_count": len(workflow.versions),
        }
        for workflow in workflows
    ]


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, session: Session = Depends(get_session)):
    workflow = session.scalar(
        select(Workflow).where(Workflow.id == workflow_id).options(selectinload(Workflow.versions))
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow 不存在")
    return {
        "id": workflow.id,
        "code": workflow.code,
        "name": workflow.name,
        "description": workflow.description,
        "active_version_id": workflow.active_version_id,
        "versions": [workflow_version_dict(version) for version in sorted(workflow.versions, key=lambda item: item.version_no, reverse=True)],
    }


@router.post("/workflows/{workflow_id}/versions", status_code=201)
def create_workflow_version(workflow_id: str, payload: WorkflowVersionCreate, session: Session = Depends(get_session)):
    workflow = session.scalar(
        select(Workflow).where(Workflow.id == workflow_id).options(selectinload(Workflow.versions))
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow 不存在")
    version = WorkflowVersion(
        workflow_id=workflow.id,
        version_no=max((item.version_no for item in workflow.versions), default=0) + 1,
        graph_json=json.dumps(payload.graph, ensure_ascii=False),
        change_note=payload.change_note,
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return workflow_version_dict(version)


@router.post("/workflows/{workflow_id}/versions/{version_id}/activate")
def activate_workflow_version(workflow_id: str, version_id: str, session: Session = Depends(get_session)):
    workflow = session.get(Workflow, workflow_id)
    version = session.get(WorkflowVersion, version_id)
    if not workflow or not version or version.workflow_id != workflow.id:
        raise HTTPException(status_code=404, detail="Workflow 或版本不存在")
    errors = validate_workflow_graph(json.loads(version.graph_json))
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Workflow 校验失败", "errors": errors})
    workflow.active_version_id = version.id
    session.commit()
    return {"id": workflow.id, "active_version_id": workflow.active_version_id}


@router.post("/workflows/{workflow_id}/versions/{version_id}/dryrun")
def dryrun_workflow(workflow_id: str, version_id: str, session: Session = Depends(get_session)):
    version = session.get(WorkflowVersion, version_id)
    if not version or version.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Workflow 版本不存在")
    graph = json.loads(version.graph_json)
    errors = validate_workflow_graph(graph)
    trace = [node.get("type") for node in graph.get("nodes", []) if node.get("type")]
    return {"ok": not errors, "errors": errors, "external_calls": 0, "trace": trace}


@router.get("/logs")
def list_logs(
    job_id: str | None = None,
    node: str | None = None,
    provider_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_session),
):
    conditions = []
    if job_id:
        conditions.append(ExecutionLog.job_id == job_id)
    if node:
        conditions.append(ExecutionLog.node == node)
    if provider_id:
        conditions.append(ExecutionLog.provider_id == provider_id)
    if status:
        conditions.append(ExecutionLog.status == status)
    query = select(ExecutionLog).where(*conditions).order_by(ExecutionLog.created_at.desc())
    count_query = select(func.count(ExecutionLog.id)).where(*conditions)
    total = session.scalar(count_query) or 0
    logs = session.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [
            {
                "id": log.id,
                "job_id": log.job_id,
                "item_id": log.item_id,
                "node": log.node,
                "provider_id": log.provider_id,
                "status": log.status,
                "duration_ms": log.duration_ms,
                "request_summary": json.loads(log.request_summary or "{}"),
                "response_summary": json.loads(log.response_summary or "{}"),
                "error": log.error,
                "dry_run": log.dry_run,
                "created_at": log.created_at,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
