from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.runtime import RuntimeStateService, default_runtime
from backend.app.core.storage.keys import cache_key
from backend.app.models import Provider
from backend.app.services.provider_catalog import (
    DEFAULT_ROUTE_CHAINS,
    GPT_IMAGE2_EXACT_SIZE_ROUTE_KEYS,
    ROUTE_SLOT_ORDER,
    VALID_ROUTE_ROLES,
    default_route_roles_for_code,
    normalize_route_role,
)

logger = logging.getLogger(__name__)


ProviderRouteRole = Literal["primary", "backup1", "backup2", "backup3", "backup4"]

PRIMARY_ROLE: ProviderRouteRole = "primary"
FALLBACK_ROLE: ProviderRouteRole = "backup1"
VALID_PROVIDER_ROUTE_ROLES: set[str] = set(ROUTE_SLOT_ORDER)

PROVIDER_ROUTE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "suite_fidelity": {
        "category": "套图",
        "title": "保真",
        "description": "套图商品保真优先链路，优先 Nano Pro，备线 Nano 2。",
        "capability": "image",
        "operation": "generate",
        "default_chain": DEFAULT_ROUTE_CHAINS["suite_fidelity"],
    },
    "suite_layout": {
        "category": "套图",
        "title": "排版",
        "description": "套图视觉排版链路，使用 GPT Image 2 generations。",
        "capability": "image",
        "operation": "generate",
        "default_chain": DEFAULT_ROUTE_CHAINS["suite_layout"],
    },
    "aplus_detail": {
        "category": "A+",
        "title": "详情页",
        "description": "A+ 详情页、普通 A+ 与高级 A+ Web 生图链路。",
        "capability": "image",
        "operation": "generate",
        "default_chain": DEFAULT_ROUTE_CHAINS["aplus_detail"],
    },
    "aplus_mobile": {
        "category": "A+",
        "title": "移动端",
        "description": "高级 A+ 移动端 600:450 由 GPT Image 2 edit 生成。",
        "capability": "image",
        "operation": "edit",
        "default_chain": DEFAULT_ROUTE_CHAINS["aplus_mobile"],
    },
    "image_edit": {
        "category": "改图",
        "title": "图片编辑",
        "description": "套图、A+ 结果图二次编辑和文字替换链路，只使用图片 edit 能力。",
        "capability": "image",
        "operation": "edit",
        "default_chain": DEFAULT_ROUTE_CHAINS["image_edit"],
    },
    "video": {
        "category": "视频",
        "title": "视频",
        "description": "Seedance 2.0 异步视频生成链路。",
        "capability": "video",
        "operation": "video",
        "default_chain": DEFAULT_ROUTE_CHAINS["video"],
    },
    "llm": {
        "category": "LLM",
        "title": "LLM",
        "description": "提示词理解、商品识别、文案帮写与安全审计链路。该链路暂不重构。",
        "capability": "llm",
        "operation": "chat",
        "default_chain": DEFAULT_ROUTE_CHAINS["llm"],
    },
}

DEFAULT_ROUTE_ROLES_BY_PROVIDER: dict[str, dict[str, ProviderRouteRole]] = {}
for route_key, chain in DEFAULT_ROUTE_CHAINS.items():
    for index, provider_code in enumerate(chain[: len(ROUTE_SLOT_ORDER)]):
        DEFAULT_ROUTE_ROLES_BY_PROVIDER.setdefault(provider_code, {})[route_key] = ROUTE_SLOT_ORDER[index]  # type: ignore[assignment]


@dataclass(frozen=True)
class ProviderSnapshot:
    """Detached read model for execution chains.

    ORM instances are session-bound and unsafe to cache; snapshots freeze the
    provider columns actually consumed by read paths (plaintext API keys are
    never stored, only the existing encrypted representation).
    """

    id: str
    code: str
    label: str
    capability: str
    adapter: str
    base_url: str
    model_name: str
    enabled: bool
    is_default: bool
    is_fallback: bool
    encrypted_api_key: str | None
    config_json: str

    @classmethod
    def from_provider(cls, provider: Provider) -> "ProviderSnapshot":
        return cls(
            id=provider.id,
            code=provider.code,
            label=provider.label,
            capability=provider.capability,
            adapter=provider.adapter,
            base_url=provider.base_url,
            model_name=provider.model_name,
            enabled=bool(provider.enabled),
            is_default=bool(provider.is_default),
            is_fallback=bool(provider.is_fallback),
            encrypted_api_key=provider.encrypted_api_key,
            config_json=provider.config_json or "{}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "label": self.label,
            "capability": self.capability,
            "adapter": self.adapter,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "enabled": self.enabled,
            "is_default": self.is_default,
            "is_fallback": self.is_fallback,
            "encrypted_api_key": self.encrypted_api_key,
            "config_json": self.config_json,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderSnapshot":
        return cls(
            id=str(data["id"]),
            code=str(data["code"]),
            label=str(data.get("label") or ""),
            capability=str(data.get("capability") or ""),
            adapter=str(data.get("adapter") or ""),
            base_url=str(data.get("base_url") or ""),
            model_name=str(data.get("model_name") or ""),
            enabled=bool(data.get("enabled")),
            is_default=bool(data.get("is_default")),
            is_fallback=bool(data.get("is_fallback")),
            encrypted_api_key=data.get("encrypted_api_key"),
            config_json=str(data.get("config_json") or "{}"),
        )


ProviderRecord = Provider | ProviderSnapshot


def cached_providers_for_capability(
    session: Session,
    capability: str,
    runtime: RuntimeStateService | None = None,
) -> list[ProviderSnapshot]:
    """Read provider rows through a versioned cache; fall back to PostgreSQL."""
    service = runtime or default_runtime()
    if service is None:
        rows = session.scalars(select(Provider).where(Provider.capability == capability)).all()
        return [ProviderSnapshot.from_provider(provider) for provider in rows]
    def produce() -> list[dict[str, Any]]:
        fresh = session.scalars(select(Provider).where(Provider.capability == capability)).all()
        return [ProviderSnapshot.from_provider(provider).to_dict() for provider in fresh]

    cached = service.cached_versioned("provider", capability, produce)
    return [ProviderSnapshot.from_dict(item) for item in cached]


def cached_provider_by_code(
    session: Session,
    code: str,
    runtime: RuntimeStateService | None = None,
) -> ProviderSnapshot | None:
    service = runtime or default_runtime()
    if service is None:
        provider = session.scalar(select(Provider).where(Provider.code == code).limit(1))
        return ProviderSnapshot.from_provider(provider) if provider else None
    def produce() -> dict[str, Any] | None:
        provider = session.scalar(select(Provider).where(Provider.code == code).limit(1))
        return ProviderSnapshot.from_provider(provider).to_dict() if provider else None

    cached = service.cached_versioned("provider", f"code:{code}", produce)
    return ProviderSnapshot.from_dict(cached) if cached is not None else None


def invalidate_provider_cache(runtime: RuntimeStateService | None = None) -> None:
    service = runtime or default_runtime()
    if service is not None:
        service.invalidate_best_effort("provider")


def provider_config(provider: ProviderRecord) -> dict[str, Any]:
    try:
        parsed = json.loads(provider.config_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def provider_route_roles(provider: ProviderRecord) -> dict[str, ProviderRouteRole]:
    roles = provider_config(provider).get("route_roles", {})
    if not isinstance(roles, dict):
        return {}
    valid: dict[str, ProviderRouteRole] = {}
    for route_key, role in roles.items():
        normalized_role = normalize_route_role(role)
        if route_key in PROVIDER_ROUTE_DEFINITIONS and normalized_role in VALID_PROVIDER_ROUTE_ROLES:
            valid[str(route_key)] = normalized_role  # type: ignore[assignment]
    return valid


def normalize_route_roles(value: Any) -> dict[str, ProviderRouteRole]:
    if not isinstance(value, dict):
        return {}
    roles: dict[str, ProviderRouteRole] = {}
    for route_key, role in value.items():
        normalized_role = normalize_route_role(role)
        if route_key in PROVIDER_ROUTE_DEFINITIONS and normalized_role in VALID_PROVIDER_ROUTE_ROLES:
            roles[str(route_key)] = normalized_role  # type: ignore[assignment]
    return roles


def write_provider_config(provider: Provider, config: dict[str, Any]) -> None:
    provider.config_json = json.dumps(config, ensure_ascii=False)


def provider_is_route_eligible(provider: ProviderRecord, route_key: str) -> bool:
    config = provider_config(provider)
    if route_key in GPT_IMAGE2_EXACT_SIZE_ROUTE_KEYS and not bool(config.get("supports_exact_custom_size")):
        return False
    return True


def provider_display_name(provider: ProviderRecord) -> str:
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


def provider_display_names_by_code(
    session: Session,
    provider_codes: list[str],
    runtime: RuntimeStateService | None = None,
) -> dict[str, str]:
    if not provider_codes:
        return {}
    return {
        provider.code: provider_display_name(provider)
        for code in provider_codes
        if (provider := cached_provider_by_code(session, code, runtime)) is not None
    }


def provider_matches_route(provider: ProviderRecord, route_key: str, role: ProviderRouteRole | str) -> bool:
    return provider_route_roles(provider).get(route_key) == normalize_route_role(role)


def route_provider_codes(
    session: Session,
    route_key: str,
    *,
    include_fallback: bool = True,
    require_enabled: bool = True,
    require_api_key: bool = True,
    runtime: RuntimeStateService | None = None,
) -> list[str]:
    definition = PROVIDER_ROUTE_DEFINITIONS.get(route_key)
    if not definition:
        raise RuntimeError(f"未知模型链路：{route_key}")
    providers = cached_providers_for_capability(session, definition["capability"], runtime)

    def available(provider: ProviderSnapshot) -> bool:
        if provider_config(provider).get("hidden_legacy"):
            return False
        if not provider_is_route_eligible(provider, route_key):
            return False
        if require_enabled and not provider.enabled:
            return False
        if require_api_key and not provider.encrypted_api_key:
            return False
        return True

    by_role: dict[str, ProviderSnapshot] = {}
    for provider in providers:
        if not available(provider):
            continue
        role = provider_route_roles(provider).get(route_key)
        if role and role not in by_role:
            by_role[role] = provider
    roles = ROUTE_SLOT_ORDER if include_fallback else (PRIMARY_ROLE,)
    selected_codes = [by_role[role].code for role in roles if role in by_role]
    if selected_codes:
        return selected_codes
    raise RuntimeError(f"{definition['category']}-{definition['title']} 没有可用模型（未启用或缺少 API Key）")


def enabled_provider_for_route(
    session: Session,
    route_key: str,
    role: ProviderRouteRole | str = PRIMARY_ROLE,
    runtime: RuntimeStateService | None = None,
) -> ProviderSnapshot:
    definition = PROVIDER_ROUTE_DEFINITIONS.get(route_key)
    if not definition:
        raise RuntimeError(f"未知模型链路：{route_key}")
    normalized_role = normalize_route_role(role) or PRIMARY_ROLE
    providers = [
        provider
        for provider in cached_providers_for_capability(session, definition["capability"], runtime)
        if provider.enabled
    ]
    provider = next(
        (
            item
            for item in providers
            if item.encrypted_api_key
            and not provider_config(item).get("hidden_legacy")
            and provider_is_route_eligible(item, route_key)
            and provider_matches_route(item, route_key, normalized_role)
        ),
        None,
    )
    if not provider:
        role_label = "主模型" if normalized_role == PRIMARY_ROLE else "备用模型"
        raise RuntimeError(f"{definition['category']}-{definition['title']} {role_label}未启用或缺少 API Key")
    return provider


def default_route_roles_for_provider(code: str) -> dict[str, ProviderRouteRole]:
    return dict(DEFAULT_ROUTE_ROLES_BY_PROVIDER.get(code, default_route_roles_for_code(code)))  # type: ignore[return-value]
