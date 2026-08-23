from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models import AplusJob, Asset, GenerationJob, PromptVersion
from backend.app.schemas import AplusGenerationJobCreate, AplusPlanJobCreate, GenerationJobCreate
from backend.app.services.aplus_jobs import create_aplus_generation_job_from_plan, load_aplus_job
from backend.app.services.content_safety import ContentSafetyBlocked, ensure_content_safe, run_local_text_safety_review
from backend.app.services.jobs import _enabled_provider, image_provider_route
from backend.app.services.provider_routing import (
    ProviderSnapshot,
    cached_provider_by_code,
    provider_config,
    route_provider_codes,
)
from backend.app.services.runtime_cache import active_prompt_version_id, active_workflow_version_id


class TaskCreationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _ensure_assets(
    session: Session,
    asset_ids: list[str],
    max_asset_count: int,
    *,
    user_id: str | None = None,
) -> list[Asset]:
    if len(asset_ids) > max_asset_count:
        raise TaskCreationError(422, f"At most {max_asset_count} product images are allowed")
    query = select(Asset).where(Asset.id.in_(asset_ids))
    if user_id:
        query = query.where(or_(Asset.user_id == user_id, Asset.user_id.is_(None)))
    assets = session.scalars(query).all()
    if len(assets) != len(asset_ids):
        raise TaskCreationError(422, "One or more product images are invalid")
    return assets


def _ensure_provider_reference_capacity(session: Session, provider_codes: list[str], asset_count: int) -> None:
    if asset_count <= 0:
        return
    for provider_code in provider_codes:
        provider: ProviderSnapshot | None = cached_provider_by_code(session, provider_code)
        if not provider:
            continue
        config = provider_config(provider)
        max_reference_images = int(config.get("max_reference_images", asset_count) or 0)
        if max_reference_images and asset_count > max_reference_images:
            raise TaskCreationError(
                422,
                f"{provider.label or provider.code} supports at most {max_reference_images} reference images; got {asset_count}",
            )


def _ensure_text_safe(payload: dict[str, Any]) -> None:
    input_text = json.dumps(payload, ensure_ascii=False)
    try:
        ensure_content_safe(run_local_text_safety_review(input_text), "输入内容安全拦截")
    except ContentSafetyBlocked as exc:
        raise TaskCreationError(422, str(exc)) from exc


def create_generation_job_record(
    session: Session,
    payload: GenerationJobCreate,
    *,
    max_asset_count: int = 6,
    is_admin_test: bool = False,
    user_id: str | None = None,
) -> GenerationJob:
    _ensure_assets(session, payload.asset_ids, max_asset_count, user_id=user_id)
    if not payload.dry_run:
        try:
            _enabled_provider(session, "llm", "default")
            _enabled_provider(session, "llm", "fallback")
            provider_codes = image_provider_route(payload.model_preference, session)
            _ensure_provider_reference_capacity(session, provider_codes, len(payload.asset_ids))
        except RuntimeError as exc:
            raise TaskCreationError(409, str(exc)) from exc

    prompt_version_id = active_prompt_version_id(session, "ecommerce-meta")
    workflow_version_id = active_workflow_version_id(session, "product-suite-v1")
    if not prompt_version_id or not workflow_version_id:
        raise TaskCreationError(500, "Core Prompt or Workflow is not enabled")
    auxiliary_codes = ("product-vision", "copywriting-assist", "edit-rewrite", "image-text-edit", "content-safety-review")
    prompt_versions = {code: active_prompt_version_id(session, code) for code in auxiliary_codes}
    prompt_versions = {code: version_id for code, version_id in prompt_versions.items() if version_id}
    if len(prompt_versions) != len(auxiliary_codes):
        raise TaskCreationError(500, "Auxiliary Prompt assets are incomplete")

    params = payload.model_dump()
    params["_prompt_versions"] = prompt_versions
    _ensure_text_safe(payload.model_dump(exclude={"asset_ids", "dry_run"}))
    job = GenerationJob(
        user_id=user_id,
        status="queued",
        dry_run=payload.dry_run,
        is_admin_test=is_admin_test,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=payload.count,
        progress=0,
        prompt_version_id=prompt_version_id,
        workflow_version_id=workflow_version_id,
    )
    session.add(job)
    session.flush()
    return job


def create_aplus_plan_job_record(
    session: Session,
    payload: AplusPlanJobCreate,
    *,
    max_asset_count: int = 6,
    is_admin_test: bool = False,
    user_id: str | None = None,
) -> AplusJob:
    _ensure_assets(session, payload.asset_ids, max_asset_count, user_id=user_id)
    _ensure_text_safe(payload.model_dump(exclude={"asset_ids", "dry_run"}))
    if not payload.dry_run:
        try:
            _enabled_provider(session, "llm", "default")
            _enabled_provider(session, "llm", "fallback")
        except RuntimeError as exc:
            raise TaskCreationError(409, str(exc)) from exc

    prompt_version = session.get(PromptVersion, active_prompt_version_id(session, "aplus-meta"))
    product_vision_version = session.get(PromptVersion, active_prompt_version_id(session, "product-vision"))
    if not prompt_version or not product_vision_version:
        raise TaskCreationError(500, "A+ Prompt assets are incomplete")

    params = payload.model_dump()
    params["module_total"] = payload.module_total
    params["_prompt_versions"] = {"product-vision": product_vision_version.id}
    if not payload.dry_run:
        provider_codes: list[str] = []
        for target in payload.output_targets:
            route_key = "aplus_mobile" if target.mode == "amazon_aplus_advanced_mobile" else "aplus_detail"
            provider_codes.extend(route_provider_codes(session, route_key))
        _ensure_provider_reference_capacity(session, provider_codes, len(payload.asset_ids))

    job = AplusJob(
        user_id=user_id,
        job_type="plan",
        status="queued",
        dry_run=payload.dry_run,
        is_admin_test=is_admin_test,
        params_json=json.dumps(params, ensure_ascii=False),
        asset_ids_json=json.dumps(payload.asset_ids),
        count=payload.module_total,
        progress=0,
        prompt_version_id=prompt_version.id,
    )
    session.add(job)
    session.flush()
    return job


def create_aplus_generation_job_record(
    session: Session,
    payload: AplusGenerationJobCreate,
    *,
    is_admin_test: bool = False,
    prompt_version_id: str | None = None,
    user_id: str | None = None,
) -> AplusJob:
    plan_job = load_aplus_job(session, payload.plan_job_id)
    if not plan_job or plan_job.job_type != "plan" or plan_job.status != "succeeded":
        raise TaskCreationError(409, "A+ plan job has not succeeded")
    if user_id and plan_job.user_id not in {None, user_id}:
        raise TaskCreationError(404, "A+ plan job does not exist")
    plan_params = json.loads(plan_job.params_json)
    if any(target.mode != "detail" for target in payload.output_targets) and plan_params.get("platform") != "亚马逊":
        raise TaskCreationError(422, "Amazon A+ targets only support Amazon platform")
    if not payload.dry_run:
        try:
            provider_codes: list[str] = []
            for target in payload.output_targets:
                route_key = "aplus_mobile" if target.mode == "amazon_aplus_advanced_mobile" else "aplus_detail"
                provider_codes.extend(route_provider_codes(session, route_key))
            _ensure_provider_reference_capacity(session, provider_codes, len(json.loads(plan_job.asset_ids_json)))
        except RuntimeError as exc:
            raise TaskCreationError(409, str(exc)) from exc

    locked_prompt_version_id = (
        prompt_version_id
        or plan_job.prompt_version_id
        or active_prompt_version_id(session, "aplus-meta")
    )
    if not locked_prompt_version_id:
        raise TaskCreationError(500, "A+ Meta Prompt is not enabled")
    job = create_aplus_generation_job_from_plan(session, plan_job, payload, locked_prompt_version_id)
    job.user_id = user_id or plan_job.user_id
    job.is_admin_test = is_admin_test
    return job
