from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.config import Settings
from backend.app.database import get_session
from backend.app.models import (
    ExecutionLog,
    Notification,
    PaymentOrder,
    PlanQuotaRule,
    Prompt,
    PromptTestRun,
    PromptVersion,
    Provider,
    SmsConfig,
    SubscriptionPlan,
    User,
    Workflow,
    WorkflowVersion,
)
from backend.app.schemas import (
    AdminNotificationBroadcastCreate,
    AdminPlanUpdate,
    AdminQuotaRuleUpdate,
    AdminUserUpdate,
    PromptTestRunCreate,
    PromptTestRunOut,
    PromptVersionCreate,
    ProviderGroupOut,
    ProviderOut,
    ProviderRouteChainUpdate,
    ProviderTestOut,
    ProviderUpdate,
    SmsSendCreate,
    SmsSendOut,
    SmsSettingsUpdate,
    WorkflowVersionCreate,
)
from backend.app.security import mask_api_key
from backend.app.services.auth import public_user, require_admin
from backend.app.services.analytics import (
    build_business_metric_users,
    build_business_metrics,
    build_business_user_metrics,
    build_ops_monitoring,
    resolve_window,
)
from backend.app.services.notifications import create_notification
from backend.app.services.provider_routing import (
    PROVIDER_ROUTE_DEFINITIONS,
    VALID_PROVIDER_ROUTE_ROLES,
    invalidate_provider_cache,
    normalize_route_roles,
    provider_display_name,
    provider_config,
    provider_is_route_eligible,
    provider_route_roles,
    write_provider_config,
)
from backend.app.services.provider_catalog import PROVIDER_GROUPS, ROUTE_SLOT_ORDER, normalize_route_role
from backend.app.services.redaction import safe_json
from backend.app.services.providers import HELLOBABYGO_IMAGE_ADAPTER, ProviderClient, build_async_http_client
from backend.app.services.image_text_edit import (
    SUPPORTED_OCR_ENGINES,
    SUPPORTED_OCR_MODELS,
    clear_ocr_engine_cache,
    ocr_cache_size,
    prewarm_ocr_engine,
)
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
from backend.app.services.runtime_cache import (
    invalidate_prompt_cache,
    invalidate_subscription_cache,
    invalidate_workflow_cache,
)
from backend.app.services.sms import load_sms_config, send_sms_code
from backend.app.services.subscriptions import (
    list_subscription_plans,
    serialize_order,
    serialize_plan,
    serialize_quota_rule,
)
from backend.app.services.workflow_registry import validate_workflow_graph


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


HELLOBABYGO_UNUSED_IMAGE_CONFIG_KEYS = (
    "aspect_ratio",
    "compression",
    "format",
    "quality",
    "response_format",
    "style",
)


@router.get("/ops-monitoring")
def get_ops_monitoring(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    granularity: str = Query(default="day", pattern="^(hour|day|week)$"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        start, end = resolve_window(start_at, end_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_ops_monitoring(session, start_at=start, end_at=end, granularity=granularity)


@router.get("/business-metrics")
def get_business_metrics(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    granularity: str = Query(default="day", pattern="^(hour|day|week)$"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        start, end = resolve_window(start_at, end_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_business_metrics(session, start_at=start, end_at=end, granularity=granularity)


@router.get("/business-metrics/users")
def get_business_metric_users(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        start, end = resolve_window(start_at, end_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_business_metric_users(session, start_at=start, end_at=end, limit=limit)


@router.get("/business-metrics/users/{user_id}")
def get_business_user_metrics(
    user_id: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    granularity: str = Query(default="day", pattern="^(hour|day|week)$"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        start, end = resolve_window(start_at, end_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = build_business_user_metrics(session, user_id, start_at=start, end_at=end, granularity=granularity)
    if result is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return result


def provider_admin_config(provider: Provider, config: dict | None = None) -> dict:
    normalized = dict(config if config is not None else provider_config(provider))
    if provider.adapter == HELLOBABYGO_IMAGE_ADAPTER:
        for key in HELLOBABYGO_UNUSED_IMAGE_CONFIG_KEYS:
            normalized.pop(key, None)
    return normalized


def provider_dict(provider: Provider, request: Request) -> dict:
    plain = request.app.state.cipher.decrypt(provider.encrypted_api_key) if provider.encrypted_api_key else None
    config = provider_admin_config(provider)
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
        "provider_group": config.get("provider_group"),
        "provider_group_label": config.get("provider_group_label"),
        "operation": config.get("operation"),
        "supports_custom_size": bool(config.get("supports_custom_size")),
        "supports_exact_custom_size": bool(config.get("supports_exact_custom_size")),
        "supports_edit": bool(config.get("supports_edit")),
        "pricing": config.get("pricing") if isinstance(config.get("pricing"), dict) else None,
        "health": config.get("health") if isinstance(config.get("health"), dict) else None,
        "has_api_key": bool(plain),
        "api_key_masked": mask_api_key(plain),
        "config": config,
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


def _normalize_admin_ocr_model(value: Any) -> str:
    normalized = str(value or "").strip()
    lowered = normalized.lower().replace("_", "-")
    aliases = {
        "pp-ocrv6": "PP-OCRv6",
        "ppocrv6": "PP-OCRv6",
        "ocrv6": "PP-OCRv6",
        "v6": "PP-OCRv6",
        "pp-ocrv5": "PP-OCRv5",
        "ppocrv5": "PP-OCRv5",
        "ocrv5": "PP-OCRv5",
        "v5": "PP-OCRv5",
        "pp-ocrv4": "PP-OCRv4",
        "ppocrv4": "PP-OCRv4",
        "ocrv4": "PP-OCRv4",
        "v4": "PP-OCRv4",
        "pp-ocrv3": "PP-OCRv3",
        "ppocrv3": "PP-OCRv3",
        "ocrv3": "PP-OCRv3",
        "v3": "PP-OCRv3",
    }
    return aliases.get(lowered, normalized)


def _ocr_settings_dict(settings: Settings) -> dict[str, Any]:
    return {
        "ocr_engine": settings.ocr_engine,
        "ocr_primary_model": settings.ocr_primary_model,
        "ocr_fallback_model": settings.ocr_fallback_model,
        "ocr_device": settings.ocr_device,
        "ocr_text_score_threshold": settings.ocr_text_score_threshold,
        "ocr_box_score_threshold": settings.ocr_box_score_threshold,
        "ocr_short_text_score_threshold": settings.ocr_short_text_score_threshold,
        "ocr_min_box_width": settings.ocr_min_box_width,
        "ocr_min_box_height": settings.ocr_min_box_height,
        "ocr_min_box_area": settings.ocr_min_box_area,
        "ocr_filter_isolated_cjk": settings.ocr_filter_isolated_cjk,
        "ocr_filter_watermark_text": settings.ocr_filter_watermark_text,
        "ocr_use_enhanced_variants": settings.ocr_use_enhanced_variants,
        "supported_engines": list(SUPPORTED_OCR_ENGINES),
        "supported_models": list(SUPPORTED_OCR_MODELS),
        "cache_size": ocr_cache_size(),
    }


def _bounded_float(payload: dict[str, Any], key: str, current: float, minimum: float = 0, maximum: float = 1) -> float:
    if key not in payload:
        return current
    try:
        value = float(payload[key])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{key} must be a number")
    if value < minimum or value > maximum:
        raise HTTPException(status_code=422, detail=f"{key} must be between {minimum} and {maximum}")
    return value


def _bounded_int(payload: dict[str, Any], key: str, current: int, minimum: int = 0, maximum: int = 10000) -> int:
    if key not in payload:
        return current
    try:
        value = int(payload[key])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise HTTPException(status_code=422, detail=f"{key} must be between {minimum} and {maximum}")
    return value


def _provider_parameter_schema(config: dict[str, Any]) -> list[dict[str, Any]]:
    schema = config.get("parameter_schema")
    return [item for item in schema if isinstance(item, dict) and isinstance(item.get("key"), str)] if isinstance(schema, list) else []


def _coerce_provider_parameter(value: Any, schema_item: dict[str, Any]) -> Any:
    value_type = schema_item.get("type")
    if value_type == "boolean":
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"false", "0", "no", "off", ""}:
                return False
            if lowered in {"true", "1", "yes", "on"}:
                return True
        return bool(value)
    if value_type == "number":
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{schema_item['key']} must be a number")
        minimum = schema_item.get("min")
        maximum = schema_item.get("max")
        if minimum is not None and number < float(minimum):
            raise HTTPException(status_code=422, detail=f"{schema_item['key']} must be >= {minimum}")
        if maximum is not None and number > float(maximum):
            raise HTTPException(status_code=422, detail=f"{schema_item['key']} must be <= {maximum}")
        step = schema_item.get("step")
        return int(number) if step == 1 or float(number).is_integer() else number
    if value_type == "select":
        allowed = {
            str(option.get("value"))
            for option in schema_item.get("options", [])
            if isinstance(option, dict) and option.get("value") is not None
        }
        normalized = "" if value is None else str(value)
        if allowed and normalized not in allowed:
            raise HTTPException(status_code=422, detail=f"{schema_item['key']} must be one of {', '.join(sorted(allowed))}")
        return normalized
    return value


def apply_provider_parameter_values(config: dict[str, Any], values: dict[str, Any] | None) -> None:
    if not values:
        return
    schema_by_key = {item["key"]: item for item in _provider_parameter_schema(config)}
    unknown = sorted(set(values) - set(schema_by_key))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported provider parameters: {', '.join(unknown)}")
    for key, value in values.items():
        schema_item = schema_by_key[key]
        if value in (None, ""):
            if schema_item.get("optional"):
                config.pop(key, None)
                continue
            if "default" in schema_item:
                value = schema_item["default"]
        config[key] = _coerce_provider_parameter(value, schema_item)


def provider_matches_route_definition(provider: Provider, route_key: str, definition: dict[str, Any]) -> bool:
    config = provider_config(provider)
    if not provider_is_route_eligible(provider, route_key):
        return False
    if provider.capability != definition["capability"]:
        return False
    operation = str(config.get("operation") or "")
    family = str(config.get("model_family") or provider.model_name or provider.code)
    if route_key == "suite_fidelity":
        return operation == "generate" and "nano-banana" in family
    if route_key in {"suite_layout", "aplus_detail"}:
        return operation == "generate" and family == "gpt-image-2"
    if route_key in {"aplus_mobile", "image_edit"}:
        return operation == "edit" and family == "gpt-image-2" and bool(config.get("supports_edit"))
    if route_key == "video":
        return operation == "video" and family == "seedance-2.0"
    return True


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(request: Request, include_hidden: bool = False, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    providers = session.scalars(select(Provider).order_by(Provider.capability, Provider.is_default.desc())).all()
    return [
        provider_dict(provider, request)
        for provider in providers
        if include_hidden or not provider_config(provider).get("hidden_legacy")
    ]


@router.get("/provider-groups", response_model=list[ProviderGroupOut])
def list_provider_groups(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    providers = [
        provider
        for provider in session.scalars(select(Provider)).all()
        if not provider_config(provider).get("hidden_legacy")
    ]
    counts: dict[str, dict[str, int]] = {}
    for provider in providers:
        group = str(provider_config(provider).get("provider_group") or "")
        if not group:
            continue
        bucket = counts.setdefault(group, {"provider_count": 0, "enabled_count": 0, "keyed_count": 0})
        bucket["provider_count"] += 1
        if provider.enabled:
            bucket["enabled_count"] += 1
        if provider.encrypted_api_key:
            bucket["keyed_count"] += 1
    return [
        {
            **group,
            **counts.get(group["key"], {"provider_count": 0, "enabled_count": 0, "keyed_count": 0}),
        }
        for group in PROVIDER_GROUPS
    ]


@router.patch("/provider-routes/{route_key}/chain")
def update_provider_route_chain(
    route_key: str,
    payload: ProviderRouteChainUpdate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    definition = PROVIDER_ROUTE_DEFINITIONS.get(route_key)
    if not definition:
        raise HTTPException(status_code=404, detail=f"未知模型链路：{route_key}")
    provider_codes = [code for code in payload.provider_codes if code]
    if len(provider_codes) != len(set(provider_codes)):
        raise HTTPException(status_code=422, detail="同一链路中不能重复选择同一个模型")
    providers = session.scalars(select(Provider).where(Provider.code.in_(provider_codes))).all()
    by_code = {provider.code: provider for provider in providers}
    missing = [code for code in provider_codes if code not in by_code]
    if missing:
        raise HTTPException(status_code=422, detail=f"Provider 不存在：{', '.join(missing)}")
    for code in provider_codes:
        provider = by_code[code]
        if not provider_matches_route_definition(provider, route_key, definition):
            raise HTTPException(status_code=422, detail=f"{provider.label} 不能配置到 {route_key} 链路")
        config = provider_config(provider)
        expected_operation = definition.get("operation")
        if expected_operation == "edit" and not config.get("supports_edit"):
            raise HTTPException(status_code=422, detail=f"{provider.label} 不支持 edit，不能进入 {route_key}")
    all_providers = session.scalars(select(Provider)).all()
    selected = set(provider_codes)
    for provider in all_providers:
        config = provider_config(provider)
        roles = normalize_route_roles(config.get("route_roles"))
        if provider.code not in selected and route_key in roles:
            roles.pop(route_key, None)
            config["route_roles"] = roles
            write_provider_config(provider, config)
    for index, code in enumerate(provider_codes[: len(ROUTE_SLOT_ORDER)]):
        provider = by_code[code]
        config = provider_config(provider)
        roles = normalize_route_roles(config.get("route_roles"))
        roles[route_key] = ROUTE_SLOT_ORDER[index]  # type: ignore[assignment]
        config["route_roles"] = roles
        write_provider_config(provider, config)
    session.commit()
    invalidate_provider_cache()
    return {"route_key": route_key, "provider_codes": provider_codes[: len(ROUTE_SLOT_ORDER)]}


@router.get("/runtime-settings")
def get_runtime_settings(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "public_asset_base_url": settings.public_asset_base_url,
        "public_asset_base_url_configured": bool(settings.public_asset_base_url.strip()),
    }


@router.patch("/runtime-settings")
def update_runtime_settings(payload: dict[str, str], request: Request) -> dict[str, Any]:
    value = (payload.get("public_asset_base_url") or "").strip()
    request.app.state.settings.public_asset_base_url = value.rstrip("/")
    return {
        "public_asset_base_url": request.app.state.settings.public_asset_base_url,
        "public_asset_base_url_configured": bool(request.app.state.settings.public_asset_base_url),
    }


@router.get("/ocr-settings")
def get_ocr_settings(request: Request) -> dict[str, Any]:
    return _ocr_settings_dict(request.app.state.settings)


@router.patch("/ocr-settings")
def update_ocr_settings(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if "ocr_engine" in payload:
        engine = str(payload.get("ocr_engine") or "").strip().lower()
        if engine not in SUPPORTED_OCR_ENGINES:
            raise HTTPException(status_code=422, detail=f"ocr_engine must be one of {', '.join(SUPPORTED_OCR_ENGINES)}")
        settings.ocr_engine = engine
    for key in ("ocr_primary_model", "ocr_fallback_model"):
        if key in payload:
            model = _normalize_admin_ocr_model(payload.get(key))
            if model not in SUPPORTED_OCR_MODELS:
                raise HTTPException(status_code=422, detail=f"{key} must be one of {', '.join(SUPPORTED_OCR_MODELS)}")
            setattr(settings, key, model)
    if "ocr_device" in payload:
        device = str(payload.get("ocr_device") or "cpu").strip().lower()
        if not device:
            device = "cpu"
        settings.ocr_device = device
    settings.ocr_text_score_threshold = _bounded_float(
        payload, "ocr_text_score_threshold", settings.ocr_text_score_threshold
    )
    settings.ocr_box_score_threshold = _bounded_float(payload, "ocr_box_score_threshold", settings.ocr_box_score_threshold)
    settings.ocr_short_text_score_threshold = _bounded_float(
        payload, "ocr_short_text_score_threshold", settings.ocr_short_text_score_threshold
    )
    settings.ocr_min_box_width = _bounded_int(payload, "ocr_min_box_width", settings.ocr_min_box_width)
    settings.ocr_min_box_height = _bounded_int(payload, "ocr_min_box_height", settings.ocr_min_box_height)
    settings.ocr_min_box_area = _bounded_int(payload, "ocr_min_box_area", settings.ocr_min_box_area)
    for key in ("ocr_filter_isolated_cjk", "ocr_filter_watermark_text", "ocr_use_enhanced_variants"):
        if key in payload:
            setattr(settings, key, bool(payload[key]))
    clear_ocr_engine_cache()
    return _ocr_settings_dict(settings)


@router.post("/ocr-settings/prewarm")
def prewarm_ocr_settings(request: Request) -> dict[str, Any]:
    try:
        result = prewarm_ocr_engine(request.app.state.settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {**_ocr_settings_dict(request.app.state.settings), "prewarm": result}


@router.post("/ocr-settings/cache/clear")
def clear_ocr_settings_cache(request: Request) -> dict[str, Any]:
    clear_ocr_engine_cache()
    return _ocr_settings_dict(request.app.state.settings)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: str,
    payload: ProviderUpdate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    provider = session.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    updates = payload.model_dump(exclude_unset=True)
    api_key = updates.pop("api_key", None)
    route_role_updates = updates.pop("route_roles", None)
    parameter_values = updates.pop("parameter_values", None)
    config = provider_config(provider)
    for key in (
        "resolution",
        "size",
        "quality",
        "style",
        "format",
        "response_format",
        "compression",
        "timeout_seconds",
        "poll_interval_seconds",
        "max_reference_images",
    ):
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
            if not provider_matches_route_definition(provider, route_key, PROVIDER_ROUTE_DEFINITIONS[route_key]):
                raise HTTPException(status_code=422, detail=f"{provider.label} cannot be assigned to {route_key}")
            normalized_role = normalize_route_role(role)
            if role not in (None, "", "none") and normalized_role is None:
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
    apply_provider_parameter_values(config, parameter_values)
    provider.config_json = json.dumps(provider_admin_config(provider, config), ensure_ascii=False)
    session.commit()
    invalidate_provider_cache()
    session.refresh(provider)
    return provider_dict(provider, request)


@router.post("/providers/{provider_id}/test", response_model=ProviderTestOut)
async def test_provider(provider_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    provider = session.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if not provider.encrypted_api_key:
        raise HTTPException(status_code=422, detail="请先录入 API Key")
    api_key = request.app.state.cipher.decrypt(provider.encrypted_api_key)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    config = json.loads(provider.config_json)
    if provider.capability in {"image", "video"}:
        result = await ProviderClient().health_check(provider, api_key)
        config["health"] = {
            "status": result.get("status"),
            "ok": result.get("ok"),
            "message": result.get("message"),
            "latency_ms": result.get("latency_ms", 0),
        }
        write_provider_config(provider, provider_admin_config(provider, config))
        session.commit()
        invalidate_provider_cache()
        return ProviderTestOut(
            ok=bool(result.get("ok")),
            status=str(result.get("status") or "unknown"),  # type: ignore[arg-type]
            latency_ms=int(result.get("latency_ms") or 0),
            message=str(result.get("message") or "未发起计费生成任务"),
        )
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
            if provider.adapter in {HELLOBABYGO_IMAGE_ADAPTER, HELLOBABYGO_VIDEO_ADAPTER, "shengsuanyun_tasks_generation"}:
                return ProviderTestOut(
                    ok=True,
                    latency_ms=latency,
                    message="连接可用，未发起计费生成任务",
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


@router.post("/provider-groups/{group_key}/health-check")
async def health_check_provider_group(group_key: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    providers = [
        provider
        for provider in session.scalars(select(Provider)).all()
        if provider_config(provider).get("provider_group") == group_key and not provider_config(provider).get("hidden_legacy")
    ]
    if not providers:
        raise HTTPException(status_code=404, detail=f"中转站不存在或没有模型：{group_key}")
    client = ProviderClient()
    results: list[dict[str, Any]] = []
    for provider in providers:
        config = provider_config(provider)
        if not provider.encrypted_api_key:
            result = {"ok": False, "status": "failed", "latency_ms": 0, "message": "缺少 API Key"}
        else:
            api_key = request.app.state.cipher.decrypt(provider.encrypted_api_key)
            result = await client.health_check(provider, api_key)
        config["health"] = {
            "status": result.get("status"),
            "ok": result.get("ok"),
            "message": result.get("message"),
            "latency_ms": result.get("latency_ms", 0),
        }
        write_provider_config(provider, provider_admin_config(provider, config))
        results.append(
            {
                "provider_id": provider.id,
                "code": provider.code,
                "label": provider.label,
                "model_name": provider.model_name,
                "operation": config.get("operation"),
                "supports_custom_size": bool(config.get("supports_custom_size")),
                "supports_exact_custom_size": bool(config.get("supports_exact_custom_size")),
                "supports_edit": bool(config.get("supports_edit")),
                "pricing": config.get("pricing"),
                **config["health"],
            }
        )
    session.commit()
    invalidate_provider_cache()
    return {"group_key": group_key, "results": results}


@router.get("/users")
def list_users(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    users = session.scalars(select(User).order_by(User.created_at.desc())).all()
    return [public_user(user) for user in users]


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: AdminUserUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("role") is not None:
        user.role = updates["role"]
    if updates.get("status") is not None:
        user.status = updates["status"]
    if updates.get("plan_code"):
        plan = session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == updates["plan_code"]).limit(1))
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在")
        user.current_plan_code = plan.code
        create_notification(
            session,
            user.id,
            title="订阅套餐已调整",
            body=f"管理员已将你的订阅套餐调整为 {plan.name}。",
            category="payment",
            metadata={"plan_code": plan.code},
        )
    session.commit()
    return public_user(user)


@router.get("/subscription-plans")
def admin_subscription_plans(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return list_subscription_plans(session, include_internal=True)


@router.patch("/subscription-plans/{plan_id}")
def update_subscription_plan(plan_id: str, payload: AdminPlanUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
    plan = session.get(SubscriptionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")
    updates = payload.model_dump(exclude_unset=True)
    for key in ("name", "description", "badge", "cta", "visible", "enabled", "contact_text", "contact_phone"):
        if key in updates and updates[key] is not None:
            setattr(plan, key, updates[key])
    if updates.get("features") is not None:
        plan.features_json = json.dumps(updates["features"], ensure_ascii=False)
    session.commit()
    invalidate_subscription_cache()
    return serialize_plan(session, plan, include_internal=True)


@router.patch("/quota-rules/{rule_id}")
def update_quota_rule(rule_id: str, payload: AdminQuotaRuleUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
    rule = session.get(PlanQuotaRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="额度规则不存在")
    updates = payload.model_dump(exclude_unset=True)
    for key in ("monthly_limit", "cost_multiplier", "warning_threshold", "enabled"):
        if key in updates:
            setattr(rule, key, updates[key])
    session.commit()
    invalidate_subscription_cache()
    return serialize_quota_rule(rule)


@router.get("/payment-orders")
def list_payment_orders(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    orders = session.scalars(select(PaymentOrder).order_by(PaymentOrder.created_at.desc()).limit(100)).all()
    return [serialize_order(session, order) for order in orders]


def _sms_settings_dict(config: SmsConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "provider": config.provider,
        "enabled": config.enabled,
        "debug_mode": config.debug_mode,
        "region_id": config.region_id,
        "sign_name": config.sign_name,
        "login_template_code": config.login_template_code,
        "register_template_code": config.register_template_code,
        "change_phone_template_code": config.change_phone_template_code,
        "admin_template_code": config.admin_template_code,
        "access_key_id": config.access_key_id,
        "has_access_key_secret": bool(config.encrypted_access_key_secret),
        "code_ttl_seconds": config.code_ttl_seconds,
        "cooldown_seconds": config.cooldown_seconds,
        "daily_limit_per_phone": config.daily_limit_per_phone,
        "updated_at": config.updated_at,
    }


@router.get("/sms-settings")
def get_sms_settings(session: Session = Depends(get_session)) -> dict[str, Any]:
    return _sms_settings_dict(load_sms_config(session))


@router.patch("/sms-settings")
def update_sms_settings(payload: SmsSettingsUpdate, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    config = load_sms_config(session)
    updates = payload.model_dump(exclude_unset=True)
    secret = updates.pop("access_key_secret", None)
    for key, value in updates.items():
        if value is not None:
            setattr(config, key, value)
    if secret:
        config.encrypted_access_key_secret = request.app.state.cipher.encrypt(secret)
    session.commit()
    return _sms_settings_dict(config)


@router.post("/sms-settings/test-send", response_model=SmsSendOut)
async def test_sms_settings(payload: SmsSendCreate, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    result = await send_sms_code(
        session,
        request,
        phone=payload.phone,
        purpose=payload.purpose,
        cipher=request.app.state.cipher,
    )
    session.commit()
    return result


@router.post("/notifications/broadcast")
def broadcast_notification(payload: AdminNotificationBroadcastCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    query = select(User).where(User.status == "active")
    if payload.user_ids:
        query = query.where(User.id.in_(payload.user_ids))
    users = session.scalars(query).all()
    for user in users:
        create_notification(session, user.id, title=payload.title, body=payload.body, category="admin")
    session.commit()
    return {"ok": True, "count": len(users)}


@router.get("/prompts")
def list_prompts(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
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
def get_prompt(prompt_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
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
def create_prompt_version(prompt_id: str, payload: PromptVersionCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
def activate_prompt_version(prompt_id: str, version_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    prompt = session.get(Prompt, prompt_id)
    version = session.get(PromptVersion, version_id)
    if not prompt or not version or version.prompt_id != prompt.id:
        raise HTTPException(status_code=404, detail="提示词或版本不存在")
    prompt.active_version_id = version.id
    session.commit()
    invalidate_prompt_cache()
    return {"id": prompt.id, "active_version_id": prompt.active_version_id}


@router.post("/prompts/{prompt_id}/test-runs", response_model=PromptTestRunOut, status_code=201)
async def create_prompt_test_run(
    prompt_id: str,
    payload: PromptTestRunCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
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
def get_prompt_test_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
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
) -> list[dict[str, Any]]:
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
def list_workflows(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
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
def get_workflow(workflow_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
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
def create_workflow_version(workflow_id: str, payload: WorkflowVersionCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
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
def activate_workflow_version(workflow_id: str, version_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    workflow = session.get(Workflow, workflow_id)
    version = session.get(WorkflowVersion, version_id)
    if not workflow or not version or version.workflow_id != workflow.id:
        raise HTTPException(status_code=404, detail="Workflow 或版本不存在")
    errors = validate_workflow_graph(json.loads(version.graph_json))
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Workflow 校验失败", "errors": errors})
    workflow.active_version_id = version.id
    session.commit()
    invalidate_workflow_cache()
    return {"id": workflow.id, "active_version_id": workflow.active_version_id}


@router.post("/workflows/{workflow_id}/versions/{version_id}/dryrun")
def dryrun_workflow(workflow_id: str, version_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
