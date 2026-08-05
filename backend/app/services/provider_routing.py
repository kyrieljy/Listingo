from __future__ import annotations

import json
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Provider


ProviderRouteRole = Literal["primary", "fallback"]

PRIMARY_ROLE: ProviderRouteRole = "primary"
FALLBACK_ROLE: ProviderRouteRole = "fallback"
VALID_PROVIDER_ROUTE_ROLES: set[str] = {PRIMARY_ROLE, FALLBACK_ROLE}

PROVIDER_ROUTE_DEFINITIONS: dict[str, dict[str, str | None]] = {
    "suite_fidelity": {
        "category": "套图",
        "title": "保真",
        "description": "套图商品保持优先链路，强调商品外观、颜色、结构与标签一致。",
        "capability": "image",
        "default_primary": "yunwu-nano-pro",
        "default_fallback": "yunwu-nano",
    },
    "suite_layout": {
        "category": "套图",
        "title": "排版",
        "description": "套图视觉排版优先链路，强化文字层级与海报版式。",
        "capability": "image",
        "default_primary": "yunwu-image-2",
        "default_fallback": None,
    },
    "aplus_detail": {
        "category": "A+",
        "title": "详情页",
        "description": "A+ 详情页、普通 A+ 与高级 A+ Web 生图链路。",
        "capability": "image",
        "default_primary": "yunwu-image-2",
        "default_fallback": None,
    },
    "aplus_mobile": {
        "category": "A+",
        "title": "移动端",
        "description": "高级 A+ 移动端 600:450 生成或 Web 成图派生链路。",
        "capability": "image",
        "default_primary": "aplus-mobile-edit-low-cost",
        "default_fallback": None,
    },
    "video": {
        "category": "视频",
        "title": "视频",
        "description": "爆款视频异步生成链路。",
        "capability": "video",
        "default_primary": "shengsuanyun-doubao-seedance-2-0",
        "default_fallback": None,
    },
    "llm": {
        "category": "LLM",
        "title": "LLM",
        "description": "提示词理解、商品识别、文案帮写与安全审计链路。",
        "capability": "llm",
        "default_primary": "doubao-seed-2-0-mini",
        "default_fallback": "qwen-3-6",
    },
}

DEFAULT_ROUTE_ROLES_BY_PROVIDER: dict[str, dict[str, ProviderRouteRole]] = {}
for route_key, definition in PROVIDER_ROUTE_DEFINITIONS.items():
    primary_code = definition.get("default_primary")
    fallback_code = definition.get("default_fallback")
    if primary_code:
        DEFAULT_ROUTE_ROLES_BY_PROVIDER.setdefault(str(primary_code), {})[route_key] = PRIMARY_ROLE
    if fallback_code:
        DEFAULT_ROUTE_ROLES_BY_PROVIDER.setdefault(str(fallback_code), {})[route_key] = FALLBACK_ROLE


def provider_config(provider: Provider) -> dict[str, Any]:
    try:
        parsed = json.loads(provider.config_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def provider_route_roles(provider: Provider) -> dict[str, ProviderRouteRole]:
    roles = provider_config(provider).get("route_roles", {})
    if not isinstance(roles, dict):
        return {}
    valid: dict[str, ProviderRouteRole] = {}
    for route_key, role in roles.items():
        if route_key in PROVIDER_ROUTE_DEFINITIONS and role in VALID_PROVIDER_ROUTE_ROLES:
            valid[str(route_key)] = role  # type: ignore[assignment]
    return valid


def normalize_route_roles(value: Any) -> dict[str, ProviderRouteRole]:
    if not isinstance(value, dict):
        return {}
    roles: dict[str, ProviderRouteRole] = {}
    for route_key, role in value.items():
        if route_key in PROVIDER_ROUTE_DEFINITIONS and role in VALID_PROVIDER_ROUTE_ROLES:
            roles[str(route_key)] = role  # type: ignore[assignment]
    return roles


def write_provider_config(provider: Provider, config: dict[str, Any]) -> None:
    provider.config_json = json.dumps(config, ensure_ascii=False)


def provider_display_name(provider: Provider) -> str:
    label = (provider.label or "").strip()
    model_name = (provider.model_name or "").strip()
    base_url = (provider.base_url or "").strip()
    host = urlparse(base_url).netloc or base_url
    name = label or model_name or provider.code
    if model_name and model_name not in name:
        name = f"{name} / {model_name}"
    if host:
        name = f"{name} @ {host}"
    return name


def provider_display_names_by_code(session: Session, provider_codes: list[str]) -> dict[str, str]:
    if not provider_codes:
        return {}
    providers = session.scalars(select(Provider).where(Provider.code.in_(provider_codes))).all()
    return {provider.code: provider_display_name(provider) for provider in providers}


def set_provider_route_role(provider: Provider, route_key: str, role: ProviderRouteRole | None) -> None:
    config = provider_config(provider)
    roles = normalize_route_roles(config.get("route_roles"))
    if role is None:
        roles.pop(route_key, None)
    else:
        roles[route_key] = role
    config["route_roles"] = roles
    write_provider_config(provider, config)


def provider_matches_route(provider: Provider, route_key: str, role: ProviderRouteRole) -> bool:
    return provider_route_roles(provider).get(route_key) == role


def route_provider_codes(
    session: Session,
    route_key: str,
    *,
    include_fallback: bool = True,
    require_enabled: bool = True,
    require_api_key: bool = True,
) -> list[str]:
    definition = PROVIDER_ROUTE_DEFINITIONS.get(route_key)
    if not definition:
        raise RuntimeError(f"未知模型链路：{route_key}")
    providers = session.scalars(
        select(Provider).where(Provider.capability == definition["capability"])
    ).all()

    def available(provider: Provider) -> bool:
        if require_enabled and not provider.enabled:
            return False
        if require_api_key and not provider.encrypted_api_key:
            return False
        return True

    primary = next(
        (provider for provider in providers if provider_matches_route(provider, route_key, PRIMARY_ROLE) and available(provider)),
        None,
    )
    if not primary:
        raise RuntimeError(f"{definition['category']}-{definition['title']} 主模型未启用或缺少 API Key")
    codes = [primary.code]
    if include_fallback:
        fallback = next(
            (provider for provider in providers if provider_matches_route(provider, route_key, FALLBACK_ROLE) and available(provider)),
            None,
        )
        if fallback:
            codes.append(fallback.code)
    return codes


def enabled_provider_for_route(session: Session, route_key: str, role: ProviderRouteRole = PRIMARY_ROLE) -> Provider:
    definition = PROVIDER_ROUTE_DEFINITIONS.get(route_key)
    if not definition:
        raise RuntimeError(f"未知模型链路：{route_key}")
    providers = session.scalars(
        select(Provider).where(
            Provider.capability == definition["capability"],
            Provider.enabled.is_(True),
        )
    ).all()
    provider = next(
        (item for item in providers if item.encrypted_api_key and provider_matches_route(item, route_key, role)),
        None,
    )
    if not provider:
        role_label = "主模型" if role == PRIMARY_ROLE else "备用模型"
        raise RuntimeError(f"{definition['category']}-{definition['title']} {role_label}未启用或缺少 API Key")
    return provider


def default_route_roles_for_provider(code: str) -> dict[str, ProviderRouteRole]:
    return dict(DEFAULT_ROUTE_ROLES_BY_PROVIDER.get(code, {}))
