from __future__ import annotations

from copy import deepcopy
from typing import Any


ROUTE_SLOT_ORDER = ("primary", "backup1", "backup2", "backup3", "backup4")
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
)

DEFAULT_ROUTE_CHAINS: dict[str, list[str]] = {
    "suite_fidelity": [
        "apimodels-nano-pro-generate",
        "kie-nano-2-generate",
        "atlas-nano-2-generate",
        "apimodels-nano-2-generate",
        "runware-nano-2-generate",
    ],
    "suite_layout": [
        "atlas-gpt-image-2-generate",
        "cometapi-gpt-image-2-generate",
        "runware-gpt-image-2-generate",
        "fal-gpt-image-2-generate",
        "openrouter-gpt-image-2-generate",
    ],
    "aplus_detail": [
        "atlas-gpt-image-2-generate",
        "cometapi-gpt-image-2-generate",
        "runware-gpt-image-2-generate",
        "fal-gpt-image-2-generate",
        "openrouter-gpt-image-2-generate",
    ],
    "aplus_mobile": [
        "atlas-gpt-image-2-edit",
        "cometapi-gpt-image-2-edit",
        "runware-gpt-image-2-edit",
        "fal-gpt-image-2-edit",
        "openrouter-gpt-image-2-edit",
    ],
    "image_edit": [
        "atlas-gpt-image-2-edit",
        "cometapi-gpt-image-2-edit",
        "runware-gpt-image-2-edit",
        "fal-gpt-image-2-edit",
        "openrouter-gpt-image-2-edit",
    ],
    "video": [
        "hellobabygo-seedance-2-0-video",
        "cometapi-seedance-2-0-video",
        "kie-seedance-2-0-video",
        "atlas-seedance-2-0-video",
        "wavespeed-seedance-2-0-video",
    ],
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


def _image_parameter_schema(
    *,
    size_param_mode: str,
    model_family: str,
    quality_enabled: bool,
) -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = []
    if size_param_mode in {"width_height", "image_size_object", "size_string"}:
        schema.append(
            {
                "key": "size",
                "label": "尺寸参数",
                "type": "select",
                "options": IMAGE_SIZE_OPTIONS,
                "help": "根据中转站映射为 size、width/height 或 image_size；默认跟随前端选择。",
            }
        )
    if size_param_mode in {"aspect_ratio", "aspect_ratio_resolution"}:
        schema.append(
            {
                "key": "aspect_ratio",
                "label": "比例参数",
                "type": "select",
                "options": ASPECT_RATIO_OPTIONS,
                "help": "默认跟随前端比例；固定值会覆盖真实请求里的比例字段。",
            }
        )
    if size_param_mode == "aspect_ratio_resolution" or model_family.startswith("nano-banana"):
        schema.append(
            {
                "key": "resolution",
                "label": "清晰度 / resolution",
                "type": "select",
                "options": IMAGE_RESOLUTION_OPTIONS,
            }
        )
    if quality_enabled:
        schema.append(
            {
                "key": "quality",
                "label": "质量 / quality",
                "type": "select",
                "options": GPT_IMAGE_QUALITY_OPTIONS,
            }
        )
    schema.append(
        {
            "key": "format",
            "label": "输出格式",
            "type": "select",
            "options": IMAGE_FORMAT_OPTIONS,
        }
    )
    schema.extend(_runtime_parameter_schema())
    return schema


def _video_parameter_schema() -> list[dict[str, Any]]:
    schema: list[dict[str, Any]] = [
        {
            "key": "aspect_ratio",
            "label": "视频比例",
            "type": "select",
            "options": ASPECT_RATIO_OPTIONS,
            "help": "默认跟随前端视频任务输入。",
        },
        {
            "key": "duration",
            "label": "时长",
            "type": "select",
            "options": VIDEO_DURATION_OPTIONS,
            "help": "默认跟随前端视频任务输入。",
        },
        {
            "key": "resolution",
            "label": "视频清晰度",
            "type": "select",
            "options": VIDEO_RESOLUTION_OPTIONS,
            "help": "默认跟随前端视频任务输入。",
        },
        {"key": "generate_audio", "label": "生成音频", "type": "boolean"},
        {"key": "camera_fixed", "label": "固定镜头", "type": "boolean"},
        {"key": "watermark", "label": "水印", "type": "boolean"},
    ]
    schema.extend(_runtime_parameter_schema())
    return schema


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
    if size_param_mode == "aspect_ratio_resolution" or model_family.startswith("nano-banana"):
        schema.append(_select_parameter("resolution", "resolution", IMAGE_RESOLUTION_OPTIONS, default="1K", optional=False, section="core"))
    if quality_enabled:
        schema.append(_select_parameter("quality", "quality", GPT_IMAGE_QUALITY_OPTIONS, default="medium", optional=False, section="core"))
    if not (group == "apimodels" and model_family == "gpt-image-2"):
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
    if not (group == "apimodels" and model_family == "gpt-image-2"):
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
    gpt_gen_source = "https://www.atlascloud.ai/models/gpt-image"
    gpt_edit_source = "https://fal.ai/models/openai/gpt-image-2/edit"
    presets: list[dict[str, Any]] = [
        _image_preset(
            "fal-gpt-image-2-generate",
            "fal.ai GPT Image 2",
            "fal",
            "https://fal.run/openai/gpt-image-2",
            "openai/gpt-image-2",
            "generate",
            "gpt-image-2",
            size_param_mode="image_size_object",
            supports_edit=False,
            cost_usd=0.053,
            source_url="https://fal.ai/models/openai/gpt-image-2",
            route_roles=default_route_roles_for_code("fal-gpt-image-2-generate"),
            quality="medium",
            extra={"edit_base_url": "https://fal.run/openai/gpt-image-2/edit"},
        ),
        _image_preset(
            "fal-gpt-image-2-edit",
            "fal.ai GPT Image 2 Edit",
            "fal",
            "https://fal.run/openai/gpt-image-2/edit",
            "openai/gpt-image-2/edit",
            "edit",
            "gpt-image-2",
            size_param_mode="image_size_object",
            supports_edit=True,
            cost_usd=0.061,
            source_url=gpt_edit_source,
            route_roles=default_route_roles_for_code("fal-gpt-image-2-edit"),
            quality="medium",
        ),
        _image_preset(
            "fal-nano-pro-generate",
            "fal.ai Nano Banana Pro",
            "fal",
            "https://fal.run/fal-ai/nano-banana-pro",
            "fal-ai/nano-banana-pro",
            "generate",
            "nano-banana-pro",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.15,
            source_url="https://fal.ai/docs/model-api-reference/image-generation-api/nano-banana-pro",
            extra={
                "resolution": "2K",
                "allowed_resolutions": ["1K", "2K", "4K"],
                "max_reference_images": 14,
                "edit_base_url": "https://fal.run/fal-ai/nano-banana-pro/edit",
            },
        ),
        _image_preset(
            "fal-nano-2-generate",
            "fal.ai Nano Banana 2",
            "fal",
            "https://fal.run/fal-ai/nano-banana-2",
            "fal-ai/nano-banana-2",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.07,
            source_url="https://fal.ai/docs/model-api-reference/image-generation-api/nano-banana-2",
            extra={
                "resolution": "1K",
                "allowed_resolutions": ["0.5K", "1K", "2K", "4K"],
                "max_reference_images": 14,
                "edit_base_url": "https://fal.run/fal-ai/nano-banana-2/edit",
            },
        ),
        _image_preset(
            "runware-gpt-image-2-generate",
            "Runware GPT Image 2",
            "runware",
            "https://api.runware.ai/v1",
            "openai:gpt-image@2",
            "generate",
            "gpt-image-2",
            size_param_mode="width_height",
            supports_edit=False,
            cost_usd=0.053,
            source_url="https://runware.ai/docs/models/openai-gpt-image-2",
            route_roles=default_route_roles_for_code("runware-gpt-image-2-generate"),
            quality="medium",
        ),
        _image_preset(
            "runware-gpt-image-2-edit",
            "Runware GPT Image 2 Edit",
            "runware",
            "https://api.runware.ai/v1",
            "openai:gpt-image@2",
            "edit",
            "gpt-image-2",
            size_param_mode="width_height",
            supports_edit=True,
            cost_usd=0.061,
            source_url="https://runware.ai/docs/models/openai-gpt-image-2/examples",
            route_roles=default_route_roles_for_code("runware-gpt-image-2-edit"),
            quality="medium",
        ),
        _image_preset(
            "runware-nano-pro-generate",
            "Runware Nano Banana Pro",
            "runware",
            "https://api.runware.ai/v1",
            "google:4@2",
            "generate",
            "nano-banana-pro",
            size_param_mode="width_height",
            supports_edit=True,
            cost_usd=None,
            source_url="https://runware.ai/docs/models/google-nano-banana-pro",
            extra={"resolution": "2K", "max_reference_images": 14},
        ),
        _image_preset(
            "runware-nano-2-generate",
            "Runware Nano Banana 2",
            "runware",
            "https://api.runware.ai/v1",
            "google:4@3",
            "generate",
            "nano-banana-2",
            size_param_mode="width_height",
            supports_edit=True,
            cost_usd=0.039,
            source_url="https://runware.ai/docs/models/google-nano-banana",
            route_roles=default_route_roles_for_code("runware-nano-2-generate"),
            extra={"resolution": "1K", "max_reference_images": 14},
        ),
        _image_preset(
            "openrouter-gpt-image-2-generate",
            "OpenRouter GPT Image 2",
            "openrouter",
            "https://openrouter.ai/api/v1/images",
            "openai/gpt-image-2",
            "generate",
            "gpt-image-2",
            size_param_mode="size_string",
            supports_edit=False,
            cost_usd=None,
            source_url="https://openrouter.ai/openai/gpt-image-2",
            quality="medium",
        ),
        _image_preset(
            "openrouter-gpt-image-2-edit",
            "OpenRouter GPT Image 2 Edit",
            "openrouter",
            "https://openrouter.ai/api/v1/images",
            "openai/gpt-image-2",
            "edit",
            "gpt-image-2",
            size_param_mode="size_string",
            supports_edit=True,
            cost_usd=None,
            source_url="https://openrouter.ai/docs/guides/overview/multimodal/image-generation",
            quality="medium",
        ),
        _image_preset(
            "openrouter-nano-2-generate",
            "OpenRouter Nano Banana 2",
            "openrouter",
            "https://openrouter.ai/api/v1/images",
            "google/gemini-3.1-flash-image",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio",
            supports_edit=True,
            cost_usd=None,
            source_url="https://openrouter.ai/google/gemini-3.1-flash-image/api",
        ),
        _image_preset(
            "atlas-gpt-image-2-generate",
            "Atlas Cloud GPT Image 2",
            "atlas",
            "https://api.atlascloud.ai/api/v1/model/generateImage",
            "openai/gpt-image-2/text-to-image",
            "generate",
            "gpt-image-2",
            size_param_mode="size_string",
            supports_edit=False,
            cost_usd=0.009,
            source_url=gpt_gen_source,
            route_roles=default_route_roles_for_code("atlas-gpt-image-2-generate"),
            quality="medium",
            extra={
                "format": "jpeg",
                "enable_sync_mode": True,
                "enable_base64_output": True,
                "edit_model_name": "openai/gpt-image-2/edit",
            },
        ),
        _image_preset(
            "atlas-gpt-image-2-edit",
            "Atlas Cloud GPT Image 2 Edit",
            "atlas",
            "https://api.atlascloud.ai/api/v1/model/generateImage",
            "openai/gpt-image-2/edit",
            "edit",
            "gpt-image-2",
            size_param_mode="size_string",
            supports_edit=True,
            cost_usd=0.01,
            source_url=gpt_gen_source,
            route_roles=default_route_roles_for_code("atlas-gpt-image-2-edit"),
            quality="medium",
            extra={"format": "jpeg", "enable_sync_mode": True, "enable_base64_output": True},
        ),
        _image_preset(
            "atlas-nano-pro-generate",
            "Atlas Cloud Nano Banana Pro",
            "atlas",
            "https://api.atlascloud.ai/api/v1/model/generateImage",
            "google/nano-banana-pro/text-to-image",
            "generate",
            "nano-banana-pro",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.14,
            source_url="https://www.atlascloud.ai/models/google/nano-banana-pro/text-to-image",
            extra={"resolution": "2K", "max_reference_images": 14, "edit_model_name": "google/nano-banana-pro/edit"},
        ),
        _image_preset(
            "atlas-nano-2-generate",
            "Atlas Cloud Nano Banana 2",
            "atlas",
            "https://api.atlascloud.ai/api/v1/model/generateImage",
            "google/nano-banana-2/text-to-image",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.04,
            source_url="https://www.atlascloud.ai/models/google/nano-banana-2/text-to-image",
            route_roles=default_route_roles_for_code("atlas-nano-2-generate"),
            extra={"resolution": "1K", "max_reference_images": 14, "edit_model_name": "google/nano-banana-2/edit"},
        ),
        _image_preset(
            "replicate-gpt-image-2-generate",
            "Replicate GPT Image 2",
            "replicate",
            "https://api.replicate.com/v1/models/openai/gpt-image-2/predictions",
            "openai/gpt-image-2",
            "generate",
            "gpt-image-2",
            size_param_mode="aspect_ratio",
            supports_edit=False,
            cost_usd=None,
            source_url="https://replicate.com/openai/gpt-image-2",
            quality="medium",
        ),
        _image_preset(
            "replicate-gpt-image-2-edit",
            "Replicate GPT Image 2 Edit",
            "replicate",
            "https://api.replicate.com/v1/models/openai/gpt-image-2/predictions",
            "openai/gpt-image-2",
            "edit",
            "gpt-image-2",
            size_param_mode="aspect_ratio",
            supports_edit=True,
            cost_usd=None,
            source_url="https://replicate.com/openai/gpt-image-2/api/schema",
            quality="medium",
        ),
        _image_preset(
            "replicate-nano-pro-generate",
            "Replicate Nano Banana Pro",
            "replicate",
            "https://api.replicate.com/v1/models/google/nano-banana-pro/predictions",
            "google/nano-banana-pro",
            "generate",
            "nano-banana-pro",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=None,
            source_url="https://replicate.com/google/nano-banana-pro",
            extra={"resolution": "2K", "max_reference_images": 14},
        ),
        _image_preset(
            "replicate-nano-2-generate",
            "Replicate Nano Banana 2",
            "replicate",
            "https://api.replicate.com/v1/models/google/nano-banana-2/predictions",
            "google/nano-banana-2",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=None,
            source_url="https://replicate.com/google/nano-banana-2/api/schema",
            extra={"resolution": "1K", "max_reference_images": 14},
        ),
        _image_preset(
            "wavespeed-gpt-image-2-generate",
            "WaveSpeedAI GPT Image 2",
            "wavespeed",
            "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/text-to-image",
            "openai/gpt-image-2/text-to-image",
            "generate",
            "gpt-image-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=False,
            cost_usd=None,
            source_url="https://wavespeed.ai/models/openai/gpt-image-2/text-to-image",
            quality="medium",
            extra={"resolution": "1K", "edit_base_url": "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/edit"},
        ),
        _image_preset(
            "wavespeed-gpt-image-2-edit",
            "WaveSpeedAI GPT Image 2 Edit",
            "wavespeed",
            "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/edit",
            "openai/gpt-image-2/edit",
            "edit",
            "gpt-image-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=None,
            source_url="https://wavespeed.ai/models/openai/gpt-image-2/edit",
            quality="medium",
            extra={"resolution": "1K"},
        ),
        _image_preset(
            "wavespeed-nano-pro-generate",
            "WaveSpeedAI Nano Banana Pro",
            "wavespeed",
            "https://api.wavespeed.ai/api/v3/google/nano-banana-pro/text-to-image",
            "google/nano-banana-pro/text-to-image",
            "generate",
            "nano-banana-pro",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.14,
            source_url="https://wavespeed.ai/models/google/nano-banana-pro/text-to-image",
            extra={
                "resolution": "2K",
                "max_reference_images": 14,
                "edit_base_url": "https://api.wavespeed.ai/api/v3/google/nano-banana-pro/edit",
            },
        ),
        _image_preset(
            "wavespeed-nano-2-generate",
            "WaveSpeedAI Nano Banana 2",
            "wavespeed",
            "https://api.wavespeed.ai/api/v3/google/nano-banana-2/text-to-image",
            "google/nano-banana-2/text-to-image",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.045,
            source_url="https://wavespeed.ai/models/google/nano-banana-2/text-to-image",
            extra={
                "resolution": "1K",
                "max_reference_images": 14,
                "edit_base_url": "https://api.wavespeed.ai/api/v3/google/nano-banana-2/edit",
            },
        ),
        _image_preset(
            "kie-gpt-image-2-generate",
            "Kie.ai GPT Image 2",
            "kie",
            "https://api.kie.ai/api/v1/jobs/createTask",
            "gpt-image-2-text-to-image",
            "generate",
            "gpt-image-2",
            size_param_mode="aspect_ratio",
            supports_edit=False,
            cost_usd=0.03,
            source_url="https://kie.ai/",
            route_roles=default_route_roles_for_code("kie-gpt-image-2-generate"),
            extra={"edit_model_name": "gpt-image-2-image-to-image"},
        ),
        _image_preset(
            "kie-gpt-image-2-edit",
            "Kie.ai GPT Image 2 Edit",
            "kie",
            "https://api.kie.ai/api/v1/jobs/createTask",
            "gpt-image-2-image-to-image",
            "edit",
            "gpt-image-2",
            size_param_mode="aspect_ratio",
            supports_edit=True,
            cost_usd=0.03,
            source_url="https://docs.kie.ai/market/gpt/gpt-image-2-image-to-image",
            route_roles=default_route_roles_for_code("kie-gpt-image-2-edit"),
        ),
        _image_preset(
            "kie-nano-pro-generate",
            "Kie.ai Nano Banana Pro",
            "kie",
            "https://api.kie.ai/api/v1/jobs/createTask",
            "nano-banana-pro",
            "generate",
            "nano-banana-pro",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.09,
            source_url="https://kie.ai/",
            extra={"resolution": "1K", "max_reference_images": 14},
        ),
        _image_preset(
            "kie-nano-2-generate",
            "Kie.ai Nano Banana 2",
            "kie",
            "https://api.kie.ai/api/v1/jobs/createTask",
            "nano-banana-2",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.04,
            source_url="https://kie.ai/",
            route_roles=default_route_roles_for_code("kie-nano-2-generate"),
            extra={"resolution": "1K", "max_reference_images": 14},
        ),
        _image_preset(
            "cometapi-gpt-image-2-generate",
            "CometAPI GPT Image 2",
            "cometapi",
            "https://api.cometapi.com/v1/images/generations",
            "gpt-image-2",
            "generate",
            "gpt-image-2",
            size_param_mode="size_string",
            supports_edit=False,
            cost_usd=None,
            source_url="https://www.cometapi.com/models/openai/gpt-image-2/",
            quality="medium",
        ),
        _image_preset(
            "cometapi-gpt-image-2-edit",
            "CometAPI GPT Image 2 Edit",
            "cometapi",
            "https://api.cometapi.com/v1/images/edits",
            "gpt-image-2",
            "edit",
            "gpt-image-2",
            size_param_mode="size_string",
            supports_edit=True,
            cost_usd=None,
            source_url="https://www.cometapi.com/models/openai/gpt-image-2/",
            quality="medium",
        ),
        _image_preset(
            "cometapi-nano-2-generate",
            "CometAPI Nano Banana 2",
            "cometapi",
            "https://api.cometapi.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent",
            "gemini-3.1-flash-image-preview",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=None,
            source_url="https://www.cometapi.com/models/google/gemini-3-1-flash-image-preview/",
            extra={
                "resolution": "1K",
                "max_reference_images": 14,
                "api_shape": "gemini_generate_content",
                "auth_header_mode": "raw_authorization",
            },
        ),
        _image_preset(
            "apimodels-gpt-image-2-generate",
            "API Models GPT Image 2",
            "apimodels",
            "https://apimodels.app/api/v1/images/generations",
            "gpt-image-2",
            "generate",
            "gpt-image-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=False,
            cost_usd=0.025,
            source_url="https://apimodels.app/docs/image",
            route_roles=default_route_roles_for_code("apimodels-gpt-image-2-generate"),
            max_reference_images=16,
            extra={"resolution": "1K"},
        ),
        _image_preset(
            "apimodels-gpt-image-2-edit",
            "API Models GPT Image 2 Edit",
            "apimodels",
            "https://apimodels.app/api/v1/images/generations",
            "gpt-image-2",
            "edit",
            "gpt-image-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.025,
            source_url="https://apimodels.app/docs/image",
            route_roles=default_route_roles_for_code("apimodels-gpt-image-2-edit"),
            max_reference_images=16,
            extra={"resolution": "1K"},
        ),
        _image_preset(
            "apimodels-nano-pro-generate",
            "API Models Nano Banana Pro",
            "apimodels",
            "https://apimodels.app/api/v1/images/generations",
            "gemini-3-pro-image-gemini",
            "generate",
            "nano-banana-pro",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.03,
            source_url="https://apimodels.app/docs/image",
            route_roles=default_route_roles_for_code("apimodels-nano-pro-generate"),
            extra={"resolution": "1K", "max_reference_images": 14},
        ),
        _image_preset(
            "apimodels-nano-2-generate",
            "API Models Nano Banana 2",
            "apimodels",
            "https://apimodels.app/api/v1/images/generations",
            "nanobanana2/gemini-3.1-flash-image-preview",
            "generate",
            "nano-banana-2",
            size_param_mode="aspect_ratio_resolution",
            supports_edit=True,
            cost_usd=0.05,
            source_url="https://apimodels.app/models/nanobanana2",
            route_roles=default_route_roles_for_code("apimodels-nano-2-generate"),
            extra={"resolution": "1K", "max_reference_images": 14},
        ),
    ]
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
        _video_preset(
            "fal-seedance-2-0-video",
            "fal.ai Seedance 2.0",
            "fal",
            "https://fal.run/bytedance/seedance-2.0/image-to-video",
            "bytedance/seedance-2.0/image-to-video",
            cost_usd_per_second=0.3024,
            source_url="https://fal.ai/models/bytedance/seedance-2.0/image-to-video",
        ),
        _video_preset(
            "runware-seedance-2-0-video",
            "Runware Seedance 2.0",
            "runware",
            "https://api.runware.ai/v1",
            "bytedance:seedance@2.0",
            cost_usd_per_second=0.40,
            source_url="https://runware.ai/docs/models/bytedance-seedance-2-0",
        ),
        _video_preset(
            "openrouter-seedance-2-0-video",
            "OpenRouter Seedance 2.0",
            "openrouter",
            "https://openrouter.ai/api/v1/videos",
            "bytedance/seedance-2.0",
            cost_usd_per_second=0.3402,
            source_url="https://openrouter.ai/bytedance/seedance-2.0/performance",
            route_roles=default_route_roles_for_code("openrouter-seedance-2-0-video"),
        ),
        _video_preset(
            "atlas-seedance-2-0-video",
            "Atlas Cloud Seedance 2.0",
            "atlas",
            "https://api.atlascloud.ai/api/v1/model/generateVideo",
            "bytedance/seedance-2.0/image-to-video",
            cost_usd_per_second=0.09,
            source_url="https://www.atlascloud.ai/models/bytedance/seedance-2.0/image-to-video",
            route_roles=default_route_roles_for_code("atlas-seedance-2-0-video"),
            extra={"bitrate_mode": "standard", "return_last_frame": False},
        ),
        _video_preset(
            "replicate-seedance-2-0-video",
            "Replicate Seedance 2.0",
            "replicate",
            "https://api.replicate.com/v1/models/bytedance/seedance-2.0/predictions",
            "bytedance/seedance-2.0",
            cost_usd_per_second=0.45,
            source_url="https://replicate.com/bytedance/seedance-2.0/api/schema",
        ),
        _video_preset(
            "wavespeed-seedance-2-0-video",
            "WaveSpeedAI Seedance 2.0",
            "wavespeed",
            "https://api.wavespeed.ai/api/v3/bytedance/seedance-2.0/image-to-video-turbo",
            "bytedance/seedance-2.0/image-to-video-turbo",
            cost_usd_per_second=0.15,
            source_url="https://wavespeed.ai/models/bytedance/seedance-2.0/image-to-video-turbo",
            route_roles=default_route_roles_for_code("wavespeed-seedance-2-0-video"),
        ),
        _video_preset(
            "kie-seedance-2-0-video",
            "Kie.ai Seedance 2.0",
            "kie",
            "https://api.kie.ai/api/v1/jobs/createTask",
            "bytedance/seedance-2",
            cost_usd_per_second=0.057,
            source_url="https://docs.kie.ai/market/bytedance/seedance-2",
            route_roles=default_route_roles_for_code("kie-seedance-2-0-video"),
        ),
        _video_preset(
            "cometapi-seedance-2-0-video",
            "CometAPI Seedance 2.0",
            "cometapi",
            "https://api.cometapi.com/volc/v3/contents/generations/tasks",
            "doubao-seedance-2-pro",
            cost_usd_per_second=0.056,
            source_url="https://www.cometapi.com/how-to-use-seedance-2-0-api/",
            route_roles=default_route_roles_for_code("cometapi-seedance-2-0-video"),
        ),
        _video_preset(
            "apimodels-seedance-2-0-video",
            "API Models Seedance 2.0",
            "apimodels",
            "https://apimodels.app/api/v1/video/generations",
            "seedance-2.0",
            cost_usd_per_second=0.33,
            source_url="https://apimodels.app/models/seedance-2.0",
        ),
    ]
    return deepcopy(presets + video_presets)
