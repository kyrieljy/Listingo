from __future__ import annotations

from copy import deepcopy
from typing import Any


ROUTE_SLOT_ORDER = ("primary", "backup1", "backup2", "backup3", "backup4", "backup5", "backup6")
LEGACY_ROUTE_ROLE_ALIASES = {"fallback": "backup1"}
VALID_ROUTE_ROLES = set(ROUTE_SLOT_ORDER) | set(LEGACY_ROUTE_ROLE_ALIASES)
EXACT_CUSTOM_SIZE_MODES = {"width_height", "image_size_object", "size_string"}
GPT_IMAGE2_EXACT_SIZE_ROUTE_KEYS = {"suite_layout", "aplus_detail", "aplus_mobile", "image_edit"}

PROVIDER_GROUPS: tuple[dict[str, str], ...] = (
    {"key": "hellobabygo", "label": "HelloBabyGo", "website": "https://xxp0w23uvv.apifox.cn/"},
    {"key": "fal", "label": "fal.ai", "website": "https://fal.ai/"},
    {"key": "runware", "label": "Runware", "website": "https://runware.ai/"},
    {"key": "openrouter", "label": "OpenRouter", "website": "https://openrouter.ai/"},
    {"key": "atlas", "label": "Atlas Cloud", "website": "https://www.atlascloud.ai/"},
    {"key": "replicate", "label": "Replicate", "website": "https://replicate.com/"},
    {"key": "wavespeed", "label": "WaveSpeedAI", "website": "https://wavespeed.ai/"},
    {"key": "kie", "label": "Kie.ai", "website": "https://kie.ai/"},
    {"key": "cometapi", "label": "CometAPI", "website": "https://www.cometapi.com/"},
    {"key": "apimodels", "label": "API Models", "website": "https://apimodels.app/"},
    {"key": "molink", "label": "MoLink", "website": "https://getmolinkapi.com/"},
)

MOLINK_IMAGE_CODES = {
    (preference, operation): f"molink-image-26-{model}-{operation}"
    for preference, model in (("speed", "flare"), ("quality", "sunburst"))
    for operation in ("generate", "edit")
}

def image_preference(value: str | None) -> str:
    return "quality" if value in {"quality", "layout"} else "speed"


def aplus_image_route(output_mode: str, preference: str | None = None) -> str:
    base = "aplus_mobile" if output_mode == "amazon_aplus_advanced_mobile" else "aplus_detail"
    return f"{base}_quality" if image_preference(preference) == "quality" else base


def image_edit_route(preference: str | None = None) -> str:
    return "image_edit_quality" if image_preference(preference) == "quality" else "image_edit"


DEFAULT_ROUTE_CHAINS: dict[str, list[str]] = {
    "suite_fidelity": [MOLINK_IMAGE_CODES["speed", "generate"]],
    "suite_layout": [MOLINK_IMAGE_CODES["quality", "generate"]],
    "aplus_detail": [MOLINK_IMAGE_CODES["speed", "generate"]],
    "aplus_detail_quality": [MOLINK_IMAGE_CODES["quality", "generate"]],
    "aplus_mobile": [MOLINK_IMAGE_CODES["speed", "edit"]],
    "aplus_mobile_quality": [MOLINK_IMAGE_CODES["quality", "edit"]],
    "image_edit": [MOLINK_IMAGE_CODES["speed", "edit"]],
    "image_edit_quality": [MOLINK_IMAGE_CODES["quality", "edit"]],
    "video": ["hellobabygo-seedance-2-0-video"],
    "llm": ["doubao-seed-2-0-mini", "qwen-3-6"],
}


GROUP_LABELS = {item["key"]: item["label"] for item in PROVIDER_GROUPS}
FRONTEND_PARAMETER_VALUE = "follow_frontend"


def _option(value: str, label: str | None = None) -> dict[str, str]:
    return {"value": value, "label": label or value}


IMAGE_SIZE_OPTIONS = [
    _option(FRONTEND_PARAMETER_VALUE, "根据前端输入传参"),
    _option("1024x1024"),
    _option("1024x1536"),
    _option("1536x1024"),
    _option("1024x1280"),
    _option("1280x1024"),
    _option("1536x864"),
    _option("864x1536"),
    _option("1792x768"),
    _option("970x600"),
    _option("1464x600"),
    _option("600x450"),
]
ASPECT_RATIO_OPTIONS = [
    _option(FRONTEND_PARAMETER_VALUE, "根据前端输入传参"),
    _option("1:1"),
    _option("2:3"),
    _option("3:2"),
    _option("3:4"),
    _option("4:3"),
    _option("4:5"),
    _option("5:4"),
    _option("9:16"),
    _option("16:9"),
    _option("21:9"),
    _option("970:600"),
    _option("1464:600"),
    _option("600:450"),
]
IMAGE_RESOLUTION_OPTIONS = [_option("0.5K"), _option("1K"), _option("2K"), _option("4K")]
GPT_IMAGE_QUALITY_OPTIONS = [_option("auto"), _option("low"), _option("medium"), _option("high"), _option("standard")]
MOLINK_IMAGE_QUALITY_OPTIONS = [_option("auto"), _option("low"), _option("medium"), _option("high")]
MOLINK_NANO_RESOLUTION_OPTIONS = [_option("1K"), _option("2K"), _option("4K")]
IMAGE_FORMAT_OPTIONS = [_option("png"), _option("jpeg"), _option("webp")]
IMAGE_BACKGROUND_OPTIONS = [_option("auto"), _option("opaque"), _option("transparent")]
IMAGE_MODERATION_OPTIONS = [_option("auto"), _option("low")]
IMAGE_RESPONSE_FORMAT_OPTIONS = [_option("url"), _option("b64_json")]
VIDEO_DURATION_OPTIONS = [
    _option(FRONTEND_PARAMETER_VALUE, "根据前端输入传参"),
    _option("5", "5 秒"),
    _option("10", "10 秒"),
    _option("15", "15 秒"),
]
VIDEO_RESOLUTION_OPTIONS = [_option(FRONTEND_PARAMETER_VALUE, "根据前端输入传参"), _option("720p"), _option("1080p")]


def _number_parameter(
    key: str,
    label: str,
    *,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    step: int | float = 1,
    default: int | float | None = None,
    optional: bool = True,
    section: str = "advanced",
    help_text: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "number",
        "step": step,
        "optional": optional,
        "section": section,
    }
    if minimum is not None:
        item["min"] = minimum
    if maximum is not None:
        item["max"] = maximum
    if default is not None:
        item["default"] = default
    if help_text:
        item["help"] = help_text
    return item


def _boolean_parameter(
    key: str,
    label: str,
    *,
    default: bool | None = None,
    optional: bool = True,
    section: str = "advanced",
    help_text: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"key": key, "label": label, "type": "boolean", "optional": optional, "section": section}
    if default is not None:
        item["default"] = default
    if help_text:
        item["help"] = help_text
    return item


def _text_parameter(
    key: str,
    label: str,
    *,
    default: str | None = None,
    optional: bool = True,
    section: str = "advanced",
    help_text: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"key": key, "label": label, "type": "text", "optional": optional, "section": section}
    if default is not None:
        item["default"] = default
    if help_text:
        item["help"] = help_text
    return item


def _select_parameter(
    key: str,
    label: str,
    options: list[dict[str, str]],
    *,
    default: str | None = None,
    optional: bool = True,
    section: str = "advanced",
    help_text: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "select",
        "options": options,
        "optional": optional,
        "section": section,
    }
    if default is not None:
        item["default"] = default
    if help_text:
        item["help"] = help_text
    return item


def _runtime_parameter_schema() -> list[dict[str, Any]]:
    return [
        {
            "key": "max_reference_images",
            "label": "参考图上限",
            "type": "number",
            "min": 0,
            "max": 14,
            "step": 1,
            "default": 6,
            "optional": False,
            "section": "runtime",
            "help": "实际请求会按该值截断参考图 URL。",
        },
        {
            "key": "timeout_seconds",
            "label": "超时时间（秒）",
            "type": "number",
            "min": 5,
            "max": 1800,
            "step": 5,
            "default": 900,
            "optional": False,
            "section": "runtime",
        },
        {
            "key": "poll_interval_seconds",
            "label": "轮询间隔（秒）",
            "type": "number",
            "min": 0,
            "max": 120,
            "step": 1,
            "default": 5,
            "optional": False,
            "section": "runtime",
        },
        {
            "key": "preflight_before_call",
            "label": "执行前健康检查",
            "type": "boolean",
            "default": True,
            "optional": False,
            "section": "runtime",
            "help": "开启后真实任务提交前先跑非计费健康检查；失败会跳到下一备线。",
        },
    ]


def _provider_image_parameter_schema(
    *,
    group: str,
    operation: str,
    size_param_mode: str,
    model_family: str,
    quality_enabled: bool,
) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    if size_param_mode in {"width_height", "image_size_object", "size_string"}:
        schema.append(
            _select_parameter(
                "size",
                "size / image_size / width+height",
                IMAGE_SIZE_OPTIONS,
                default=FRONTEND_PARAMETER_VALUE,
                optional=False,
                section="core",
                help_text="Default follows frontend input; adapters map this to the provider's documented size fields.",
            )
        )
    if size_param_mode in {"aspect_ratio", "aspect_ratio_resolution"}:
        schema.append(
            _select_parameter(
                "aspect_ratio",
                "aspect_ratio",
                ASPECT_RATIO_OPTIONS,
                default=FRONTEND_PARAMETER_VALUE,
                optional=False,
                section="core",
                help_text="Default follows frontend input; fixed values override the runtime aspect ratio field.",
            )
        )
    resolution_options = MOLINK_NANO_RESOLUTION_OPTIONS if group == "molink" and model_family.startswith("nano-banana") else IMAGE_RESOLUTION_OPTIONS
    if size_param_mode == "aspect_ratio_resolution" or model_family.startswith("nano-banana"):
        schema.append(_select_parameter("resolution", "resolution", resolution_options, default="1K", optional=False, section="core"))
    if quality_enabled:
        quality_options = MOLINK_IMAGE_QUALITY_OPTIONS if group == "molink" else GPT_IMAGE_QUALITY_OPTIONS
        schema.append(_select_parameter("quality", "quality", quality_options, default="medium", optional=False, section="core"))
    if group == "molink" and model_family == "gpt-image-2":
        schema.append(_select_parameter("output_format", "output_format", IMAGE_FORMAT_OPTIONS, default="png", optional=False, section="core"))
    elif not (group == "apimodels" and model_family == "gpt-image-2"):
        schema.append(_select_parameter("format", "output_format / format", IMAGE_FORMAT_OPTIONS, default="png", optional=False, section="core"))
    if group == "fal":
        schema.extend(
            [
                _number_parameter("num_images", "num_images", minimum=1, maximum=4, default=1),
                _boolean_parameter("sync_mode", "sync_mode"),
            ]
        )
        if operation == "edit":
            schema.append(_text_parameter("mask_image_url", "mask_image_url"))
    elif group == "runware":
        schema.extend(
            [
                _number_parameter("numberResults", "numberResults", minimum=1, maximum=4, default=1),
                _number_parameter("outputQuality", "outputQuality", minimum=20, maximum=99),
                _boolean_parameter("includeCost", "includeCost"),
                _boolean_parameter("checkNSFW", "checkNSFW"),
                _number_parameter("seed", "seed", minimum=-1, maximum=2147483647),
            ]
        )
    elif group == "replicate":
        schema.extend(
            [
                _number_parameter("number_of_images", "number_of_images", minimum=1, maximum=10, default=1),
                _select_parameter("background", "background", IMAGE_BACKGROUND_OPTIONS),
                _select_parameter("moderation", "moderation", IMAGE_MODERATION_OPTIONS),
                _number_parameter("output_compression", "output_compression", minimum=0, maximum=100),
                _text_parameter("user_id", "user_id"),
            ]
        )
    elif group == "openrouter":
        schema.extend(
            [
                _number_parameter("n", "n", minimum=1, maximum=10, default=1),
                _select_parameter("background", "background", IMAGE_BACKGROUND_OPTIONS),
                _number_parameter("output_compression", "output_compression", minimum=0, maximum=100),
                _number_parameter("seed", "seed", minimum=-1, maximum=2147483647),
                _boolean_parameter("stream", "stream"),
            ]
        )
    elif group == "atlas":
        schema.extend(
            [
                _number_parameter("n", "n", minimum=1, maximum=10, default=1),
                _number_parameter("output_compression", "output_compression", minimum=0, maximum=100),
                _boolean_parameter("enable_base64_output", "enable_base64_output"),
                _boolean_parameter("enable_sync_mode", "enable_sync_mode"),
                _number_parameter("seed", "seed", minimum=-1, maximum=2147483647),
            ]
        )
    elif group == "wavespeed":
        schema.extend(
            [
                _number_parameter("seed", "seed", minimum=-1, maximum=2147483647),
                _boolean_parameter("enable_base64_output", "enable_base64_output"),
                _boolean_parameter("enable_sync_mode", "enable_sync_mode"),
            ]
        )
    elif group == "kie":
        schema.append(_text_parameter("callBackUrl", "callBackUrl"))
    elif group == "apimodels" and model_family == "gpt-image-2":
        schema.append(_text_parameter("callback_url", "callback_url"))
    elif group in {"cometapi", "apimodels"}:
        schema.extend(
            [
                _number_parameter("n", "n", minimum=1, maximum=10, default=1),
                _select_parameter("response_format", "response_format", IMAGE_RESPONSE_FORMAT_OPTIONS),
                _number_parameter("output_compression", "output_compression", minimum=0, maximum=100),
                _select_parameter("background", "background", IMAGE_BACKGROUND_OPTIONS),
            ]
        )
    elif group == "molink" and model_family == "gpt-image-2":
        schema.append(_number_parameter("n", "n", minimum=1, maximum=10, default=1))
    schema.extend(_runtime_parameter_schema())
    return schema


def _provider_video_parameter_schema(*, group: str) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = [
        _select_parameter(
            "aspect_ratio",
            "aspect_ratio",
            ASPECT_RATIO_OPTIONS,
            default=FRONTEND_PARAMETER_VALUE,
            optional=False,
            section="core",
            help_text="Default follows frontend video input.",
        ),
        _select_parameter(
            "duration",
            "duration",
            VIDEO_DURATION_OPTIONS,
            default=FRONTEND_PARAMETER_VALUE,
            optional=False,
            section="core",
            help_text="Default follows frontend video input.",
        ),
        _select_parameter(
            "resolution",
            "resolution",
            VIDEO_RESOLUTION_OPTIONS,
            default=FRONTEND_PARAMETER_VALUE,
            optional=False,
            section="core",
            help_text="Default follows frontend video input.",
        ),
        _boolean_parameter("generate_audio", "generate_audio", default=False, optional=False, section="core"),
        _boolean_parameter("camera_fixed", "camera_fixed", default=False, optional=False, section="core"),
        _boolean_parameter("watermark", "watermark", default=False, optional=False, section="core"),
    ]
    if group == "openrouter":
        schema.extend(
            [
                _select_parameter(
                    "size",
                    "size",
                    IMAGE_SIZE_OPTIONS,
                    default=FRONTEND_PARAMETER_VALUE,
                    optional=False,
                    section="core",
                    help_text="Exact video WIDTHxHEIGHT; default follows frontend aspect/resolution.",
                ),
                _number_parameter("seed", "seed", minimum=-1, maximum=2147483647),
            ]
        )
    elif group == "runware":
        schema.extend(
            [
                _boolean_parameter("includeCost", "includeCost"),
                _number_parameter("seed", "seed", minimum=-1, maximum=2147483647),
            ]
        )
    elif group in {"kie", "atlas", "apimodels"}:
        schema.append(_text_parameter("callBackUrl", "callBackUrl"))
    elif group == "wavespeed":
        schema.extend(
            [
                _boolean_parameter("enable_base64_output", "enable_base64_output"),
                _boolean_parameter("enable_sync_mode", "enable_sync_mode"),
            ]
        )
    schema.extend(_runtime_parameter_schema())
    return schema


def normalize_route_role(role: Any) -> str | None:
    if role in (None, "", "none"):
        return None
    normalized = str(role)
    return LEGACY_ROUTE_ROLE_ALIASES.get(normalized, normalized) if normalized in VALID_ROUTE_ROLES else None


def default_route_roles_for_code(code: str) -> dict[str, str]:
    roles: dict[str, str] = {}
    for route_key, chain in DEFAULT_ROUTE_CHAINS.items():
        for index, provider_code in enumerate(chain[: len(ROUTE_SLOT_ORDER)]):
            if provider_code == code:
                roles[route_key] = ROUTE_SLOT_ORDER[index]
    return roles


def _base_image_config(
    *,
    group: str,
    operation: str,
    model_family: str,
    size_param_mode: str,
    supports_edit: bool,
    cost_usd: float | None,
    source_url: str,
    max_reference_images: int = 6,
    quality: str | None = None,
    format_: str = "png",
    route_roles: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "provider_group": group,
        "provider_group_label": GROUP_LABELS[group],
        "operation": operation,
        "model_family": model_family,
        "supports_custom_size": True,
        "supports_exact_custom_size": size_param_mode in EXACT_CUSTOM_SIZE_MODES,
        "supports_edit": supports_edit,
        "requires_public_urls": True,
        "size_param_mode": size_param_mode,
        "size_alignment": 16 if model_family == "gpt-image-2" and size_param_mode in EXACT_CUSTOM_SIZE_MODES else 1,
        "size": FRONTEND_PARAMETER_VALUE,
        "aspect_ratio": FRONTEND_PARAMETER_VALUE,
        "timeout_seconds": 900,
        "poll_interval_seconds": 5,
        "max_poll_attempts": 180,
        "max_reference_images": max_reference_images,
        "preflight_before_call": True,
        "pricing": {
            "basis": "production_default_1k",
            "currency": "USD",
            "unit": "image",
            "cost": cost_usd,
            "source_url": source_url,
            "verified_on": "2026-08-11",
        },
        "health_check": {"mode": "models_or_metadata"},
        "parameter_schema": _provider_image_parameter_schema(
            group=group,
            operation=operation,
            size_param_mode=size_param_mode,
            model_family=model_family,
            quality_enabled=quality is not None,
        ),
        "route_roles": route_roles or {},
    }
    if quality is not None:
        config["quality"] = quality
    if not (group == "apimodels" and model_family == "gpt-image-2") and group != "molink":
        config["format"] = format_
    if group == "fal":
        config["auth_header_mode"] = "fal_key"
    if extra:
        config.update(extra)
    return config


def _base_video_config(
    *,
    group: str,
    cost_usd_per_second: float | None,
    source_url: str,
    route_roles: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "provider_group": group,
        "provider_group_label": GROUP_LABELS[group],
        "operation": "video",
        "model_family": "seedance-2.0",
        "supports_custom_size": True,
        "supports_exact_custom_size": False,
        "supports_edit": False,
        "requires_public_urls": True,
        "size_param_mode": "aspect_ratio_resolution",
        "size": FRONTEND_PARAMETER_VALUE,
        "aspect_ratio": FRONTEND_PARAMETER_VALUE,
        "duration": FRONTEND_PARAMETER_VALUE,
        "resolution": FRONTEND_PARAMETER_VALUE,
        "generate_audio": False,
        "camera_fixed": False,
        "watermark": False,
        "timeout_seconds": 1200,
        "poll_interval_seconds": 5,
        "max_poll_attempts": 240,
        "preflight_before_call": True,
        "pricing": {
            "basis": "production_default_video",
            "currency": "USD",
            "unit": "second",
            "cost": cost_usd_per_second,
            "source_url": source_url,
            "verified_on": "2026-08-11",
        },
        "health_check": {"mode": "models_or_metadata"},
        "parameter_schema": _provider_video_parameter_schema(group=group),
        "route_roles": route_roles or {},
    }
    if extra:
        config.update(extra)
    if group == "fal":
        config["auth_header_mode"] = "fal_key"
    return config


def _image_preset(
    code: str,
    label: str,
    group: str,
    base_url: str,
    model_name: str,
    operation: str,
    model_family: str,
    *,
    size_param_mode: str,
    supports_edit: bool,
    cost_usd: float | None,
    source_url: str,
    route_roles: dict[str, str] | None = None,
    quality: str | None = None,
    max_reference_images: int = 6,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "capability": "image",
        "adapter": "media_image",
        "base_url": base_url,
        "model_name": model_name,
        "is_default": route_roles is not None and any(role == "primary" for role in route_roles.values()),
        "is_fallback": route_roles is not None and any(role != "primary" for role in route_roles.values()),
        "config": _base_image_config(
            group=group,
            operation=operation,
            model_family=model_family,
            size_param_mode=size_param_mode,
            supports_edit=supports_edit,
            cost_usd=cost_usd,
            source_url=source_url,
            route_roles=route_roles,
            quality=quality,
            max_reference_images=max_reference_images,
            extra=extra,
        ),
    }


def _video_preset(
    code: str,
    label: str,
    group: str,
    base_url: str,
    model_name: str,
    *,
    cost_usd_per_second: float | None,
    source_url: str,
    route_roles: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "capability": "video",
        "adapter": "media_video",
        "base_url": base_url,
        "model_name": model_name,
        "is_default": route_roles is not None and any(role == "primary" for role in route_roles.values()),
        "is_fallback": route_roles is not None and any(role != "primary" for role in route_roles.values()),
        "config": _base_video_config(
            group=group,
            cost_usd_per_second=cost_usd_per_second,
            source_url=source_url,
            route_roles=route_roles,
            extra=extra,
        ),
    }


def media_provider_presets() -> list[dict[str, Any]]:
    video_presets = [
        {
            "code": "hellobabygo-seedance-2-0-video",
            "label": "HelloBabyGo Seedance 2.0",
            "capability": "video",
            "adapter": "hellobabygo_video_generation",
            "base_url": "https://api.hellobabygo.com/v1/videos",
            "model_name": "seedance-2.0",
            "is_default": True,
            "is_fallback": False,
            "config": _base_video_config(
                group="hellobabygo",
                cost_usd_per_second=None,
                source_url="https://xxp0w23uvv.apifox.cn/",
                route_roles=default_route_roles_for_code("hellobabygo-seedance-2-0-video"),
                extra={"poll_interval_seconds": 20, "health_check": {"mode": "models_or_metadata"}},
            ),
        },
    ]
    images = []
    base = "https://www.getmolinkapi.com/v1"
    for (preference, operation), code in MOLINK_IMAGE_CODES.items():
        model = "flare" if preference == "speed" else "sunburst"
        endpoint = "generations" if operation == "generate" else "edits"
        images.append(_image_preset(
            code, f"MoLink Image 2.6 {model.title()} {operation}", "molink",
            f"{base}/images/{endpoint}", f"gpt-image-2.6-{model}", operation, "gpt-image-2",
            size_param_mode="size_string", supports_edit=True, cost_usd=None,
            source_url=base, route_roles=default_route_roles_for_code(code),
            extra={"requires_public_urls": False, "edit_base_url": f"{base}/images/edits",
                   "output_format": "png", "timeout_seconds": 240, "max_retries": 0,
                   "health_check": {"mode": "models_or_metadata", "url": f"{base}/models"}},
        ))
    return deepcopy(images + video_presets)
