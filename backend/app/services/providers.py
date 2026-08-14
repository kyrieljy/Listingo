from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from backend.app.models import Provider


IMAGE_DIMENSIONS_BY_RATIO: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "2:3": (1024, 1536),
    "3:2": (1536, 1024),
    "4:5": (1024, 1280),
    "3:4": (1024, 1365),
    "4:3": (1365, 1024),
    "5:4": (1280, 1024),
    "16:9": (1536, 864),
    "9:16": (864, 1536),
    "21:9": (1792, 768),
    "970:600": (970, 600),
    "1464:600": (1464, 600),
    "600:450": (600, 450),
}
IMAGE2_SIZE_MAP = {ratio: f"{width}x{height}" for ratio, (width, height) in IMAGE_DIMENSIONS_BY_RATIO.items()}
GPT_IMAGE2_EXACT_SIZE_MODES = {"width_height", "image_size_object", "size_string"}
GPT_IMAGE2_MIN_TOTAL_PIXELS = 655_360
FRONTEND_PARAMETER_VALUES = {"", "auto", "follow_ratio", "follow_frontend", None}
HELLOBABYGO_IMAGE2_SIZE_MAP = {
    "1:1": "1024x1024",
    "2:3": "1024x1792",
    "3:2": "1792x1024",
    "4:5": "1024x1792",
    "3:4": "1024x1792",
    "4:3": "1792x1024",
    "5:4": "1792x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "21:9": "1792x1024",
    "970:600": "1792x1024",
    "1464:600": "1792x1024",
    "600:450": "1792x1024",
}
HELLOBABYGO_IMAGE_ADAPTER = "hellobabygo_image_generation"
HELLOBABYGO_VIDEO_ADAPTER = "hellobabygo_video_generation"
MEDIA_IMAGE_ADAPTER = "media_image"
MEDIA_VIDEO_ADAPTER = "media_video"
HELLOBABYGO_IMAGE_PIXEL_SIZES = {"1024x1024", "1024x1792", "1792x1024"}
HELLOBABYGO_NANO_RESOLUTIONS = {"1K", "2K", "4K"}
HELLOBABYGO_NANO_SIZES = {"auto", "landscape", "portrait", "square"}
HELLOBABYGO_NANO_4K_SIZES = {"landscape", "portrait", "square"}
HELLOBABYGO_VIDEO_RESOLUTIONS = {"720p", "1080p"}
HELLOBABYGO_VIDEO_SIZES = {"1:1", "3:4", "4:3", "9:16", "16:9", "21:9", "landscape", "portrait"}
RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
REMOTE_RUNNING_STATUSES = {
    "created",
    "queued",
    "queuing",
    "waiting",
    "in_progress",
    "processing",
    "pending",
    "submitted",
    "submitting",
    "generating",
    "running",
}
REMOTE_SUCCESS_STATUSES = {"completed", "succeeded", "success"}
REMOTE_FAILED_STATUSES = {"failed", "fail", "cancelled", "canceled", "timeout", "error"}
ImageTaskSubmittedCallback = Callable[[str], Awaitable[None] | None]


def _retry_count(config: dict[str, Any]) -> int:
    try:
        configured = int(config.get("max_retries", 2))
    except (TypeError, ValueError):
        configured = 2
    return max(0, min(configured, 5))


def _retry_after_header_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


def _retry_delay_seconds(response: httpx.Response, attempt: int, config: dict[str, Any]) -> float:
    retry_after = _retry_after_header_seconds(response.headers.get("retry-after"))
    if retry_after is not None:
        try:
            cap = float(config.get("retry_after_cap_seconds", 20))
        except (TypeError, ValueError):
            cap = 20.0
        return min(retry_after, max(0.0, cap))
    try:
        base = float(config.get("retry_backoff_seconds", 1))
    except (TypeError, ValueError):
        base = 1.0
    return min(max(base, 0.0) * (2**attempt), 8.0)


def _ratio_value(ratio: str) -> float | None:
    try:
        width, height = (int(part) for part in ratio.split(":", 1))
    except (ValueError, AttributeError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def _size_matches_ratio(size: str, aspect_ratio: str, tolerance: float = 0.02) -> bool:
    try:
        width_text, height_text = size.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (ValueError, AttributeError):
        return True
    expected = _ratio_value(aspect_ratio)
    if expected is None or width <= 0 or height <= 0:
        return True
    return abs((width / height) - expected) <= tolerance


def _image_direction(aspect_ratio: str) -> str:
    value = _ratio_value(aspect_ratio)
    if value is None or abs(value - 1.0) <= 0.02:
        return "square"
    return "landscape" if value > 1 else "portrait"


def requested_image_size(aspect_ratio: str) -> dict[str, Any]:
    width, height = IMAGE_DIMENSIONS_BY_RATIO.get(aspect_ratio, (1024, 1024))
    return {"aspect_ratio": aspect_ratio, "width": width, "height": height, "size": f"{width}x{height}"}


def _uses_frontend_value(value: Any) -> bool:
    try:
        return value in FRONTEND_PARAMETER_VALUES
    except TypeError:
        return False


def _configured_aspect_ratio(config: dict[str, Any], aspect_ratio: str) -> str:
    configured = config.get("aspect_ratio")
    return aspect_ratio if _uses_frontend_value(configured) else str(configured)


def _requested_image_size_for_config(config: dict[str, Any], aspect_ratio: str) -> dict[str, Any]:
    effective_ratio = _configured_aspect_ratio(config, aspect_ratio)
    configured_size = str(config.get("size") or "").strip()
    if configured_size and not _uses_frontend_value(configured_size):
        if configured_size in IMAGE_DIMENSIONS_BY_RATIO:
            width, height = IMAGE_DIMENSIONS_BY_RATIO[configured_size]
            return {"aspect_ratio": configured_size, "width": width, "height": height, "size": f"{width}x{height}"}
        match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", configured_size.lower())
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            return {"aspect_ratio": effective_ratio, "width": width, "height": height, "size": f"{width}x{height}"}
    requested = requested_image_size(effective_ratio)
    return requested


def _configured_size_alignment(config: dict[str, Any]) -> int:
    default_alignment = (
        16
        if config.get("model_family") == "gpt-image-2"
        and config.get("size_param_mode") in GPT_IMAGE2_EXACT_SIZE_MODES
        else 1
    )
    try:
        alignment = int(config.get("size_alignment", default_alignment) or default_alignment)
    except (TypeError, ValueError):
        return default_alignment
    return max(1, min(alignment, 256))


def _align_dimension(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return max(alignment, int(math.ceil(value / alignment) * alignment))


def _configured_min_total_pixels(config: dict[str, Any]) -> int:
    default_min = (
        GPT_IMAGE2_MIN_TOTAL_PIXELS
        if config.get("model_family") == "gpt-image-2"
        and config.get("size_param_mode") in GPT_IMAGE2_EXACT_SIZE_MODES
        else 0
    )
    try:
        configured = int(config.get("min_total_pixels", default_min) or default_min)
    except (TypeError, ValueError):
        return default_min
    return max(0, configured)


def _scale_dimensions_to_min_pixels(
    requested_width: int,
    requested_height: int,
    aligned_width: int,
    aligned_height: int,
    alignment: int,
    min_total_pixels: int,
) -> tuple[int, int]:
    if requested_width <= 0 or requested_height <= 0:
        return aligned_width, aligned_height
    scale = math.sqrt(min_total_pixels / (requested_width * requested_height))
    width = max(aligned_width, _align_dimension(math.ceil(requested_width * scale), alignment))
    height = max(aligned_height, _align_dimension(math.ceil(requested_height * scale), alignment))
    while width * height < min_total_pixels:
        width = _align_dimension(width + 1, alignment)
        height = _align_dimension(height + 1, alignment)
    return width, height


def _provider_request_image_size_for_config(config: dict[str, Any], aspect_ratio: str) -> dict[str, Any]:
    requested = _requested_image_size_for_config(config, aspect_ratio)
    alignment = _configured_size_alignment(config)
    width = int(requested["width"])
    height = int(requested["height"])
    if alignment > 1:
        width = _align_dimension(width, alignment)
        height = _align_dimension(height, alignment)
    min_total_pixels = _configured_min_total_pixels(config)
    if min_total_pixels and width * height < min_total_pixels:
        width, height = _scale_dimensions_to_min_pixels(
            int(requested["width"]),
            int(requested["height"]),
            width,
            height,
            alignment,
            min_total_pixels,
        )
    if width == requested["width"] and height == requested["height"]:
        return requested
    return {**requested, "width": width, "height": height, "size": f"{width}x{height}", "target_size": requested}


def _configured_string(config: dict[str, Any], key: str, fallback: str) -> str:
    value = config.get(key)
    return fallback if _uses_frontend_value(value) else str(value)


def _configured_int(config: dict[str, Any], key: str, fallback: int) -> int:
    value = config.get(key)
    if _uses_frontend_value(value):
        return int(fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _configured_bool(config: dict[str, Any], key: str, fallback: bool | None) -> bool:
    value = config.get(key)
    if value is None:
        return bool(fallback)
    return bool(value)


def _configured_optional_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if _uses_frontend_value(value):
        return None
    normalized = str(value).strip()
    return normalized or None


def _configured_optional_int(
    config: dict[str, Any],
    key: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    value = config.get(key)
    if _uses_frontend_value(value):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def _configured_output_format(config: dict[str, Any], fallback: str = "png") -> str:
    value = config.get("output_format", config.get("format", fallback))
    if _uses_frontend_value(value):
        return fallback
    normalized = str(value or fallback).strip().lower()
    return normalized or fallback


def _apply_optional_scalar(payload: dict[str, Any], config: dict[str, Any], key: str) -> None:
    value = config.get(key)
    if _uses_frontend_value(value):
        return
    if value is not None and value != "":
        payload[key] = value


def append_requested_size_to_prompt(prompt: str, aspect_ratio: str, config: dict[str, Any] | None = None) -> str:
    requested = _provider_request_image_size_for_config(config, aspect_ratio) if config else requested_image_size(aspect_ratio)
    target_size = requested.get("target_size") if isinstance(requested.get("target_size"), dict) else None
    business_ratio = str(target_size.get("aspect_ratio") if target_size else requested["aspect_ratio"])
    request_ratio = f"{requested['width']}:{requested['height']}"
    if "target canvas size" in prompt.lower() or "目标画布尺寸" in prompt:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"Target canvas size: {requested['width']}x{requested['height']} px; "
        f"business target ratio: {business_ratio}; actual request ratio: {request_ratio}. "
        f"Compose strictly for this canvas.\n"
        f"目标画布尺寸: {requested['width']}x{requested['height']} px；"
        f"业务目标比例: {business_ratio}；实际请求比例: {request_ratio}。"
        f"必须按该实际画布构图，同时保持业务目标比例的版式语义。"
    )


def provider_config_dict(provider: Provider) -> dict[str, Any]:
    try:
        parsed = json.loads(provider.config_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def provider_requires_public_urls(provider: Provider) -> bool:
    config = provider_config_dict(provider)
    return bool(config.get("requires_public_urls") or provider.adapter in {HELLOBABYGO_IMAGE_ADAPTER, HELLOBABYGO_VIDEO_ADAPTER, MEDIA_IMAGE_ADAPTER, MEDIA_VIDEO_ADAPTER})


def _poll_interval_seconds(config: dict[str, Any]) -> float:
    try:
        return max(0.0, float(config.get("poll_interval_seconds", 5)))
    except (TypeError, ValueError):
        return 5.0


def _poll_attempts(config: dict[str, Any]) -> int:
    try:
        configured = int(config.get("max_poll_attempts", 0))
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured
    try:
        timeout = int(config.get("timeout_seconds", 600))
    except (TypeError, ValueError):
        timeout = 600
    interval = max(_poll_interval_seconds(config), 1)
    return max(1, int(timeout / interval))


def _task_id(data: dict[str, Any]) -> str:
    candidates = [
        data.get("task_id"),
        data.get("id"),
        data.get("request_id"),
        data.get("data", {}).get("task_id") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("request_id") if isinstance(data.get("data"), dict) else None,
        data.get("taskId"),
        data.get("taskUUID"),
        data.get("data", {}).get("taskId") if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("taskUUID") if isinstance(data.get("data"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError("HelloBabyGo response is missing task_id")


def _task_status(data: dict[str, Any]) -> str:
    for source in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        if not isinstance(source, dict):
            continue
        status = source.get("status") or source.get("state")
        if isinstance(status, str) and status.strip():
            return status.strip().lower()
    return "unknown"


def _task_error_message(data: dict[str, Any]) -> str:
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
        message = source.get("message") or source.get("error_message") or source.get("failMsg")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return "upstream task failed"


def _recoverable_existing_media_task_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {401, 403, 404, 410}
    message = str(exc).lower()
    recoverable_markers = (
        "http 401",
        "401 unauthorized",
        "unauthorized",
        "http 403",
        "403 forbidden",
        "forbidden",
        "http 404",
        "404 not found",
        "not found",
        "http 410",
        "410 gone",
        "expired",
        "invalid task",
        "invalid request_id",
        "invalid request id",
    )
    return any(marker in message for marker in recoverable_markers)


def _image_result_url(data: dict[str, Any]) -> str:
    sources: list[Any] = [data, data.get("data") if isinstance(data.get("data"), dict) else None]
    if isinstance(data.get("data"), list):
        sources.extend(data["data"])
    for source in sources:
        if isinstance(source, dict):
            url = source.get("url") or source.get("image_url") or source.get("output_url")
            if isinstance(url, str) and url.strip():
                return url.strip()
    raise RuntimeError("HelloBabyGo image task completed without data[0].url")


def _hellobabygo_image_task_base_url(provider: Provider) -> str:
    base_url = provider.base_url.rstrip("/")
    if base_url.endswith("/generations"):
        return base_url.rsplit("/", 1)[0]
    return base_url


def _validate_choice(value: str, allowed: set[str], field: str, model_name: str) -> str:
    if value not in allowed:
        raise RuntimeError(f"{model_name} 的 {field}={value} 不合法，支持值：{', '.join(sorted(allowed))}")
    return value


def _normalize_video_resolution(value: str) -> str:
    normalized = value.strip().lower()
    return normalized


def _response_text_snippet(text: str, limit: int = 240) -> str:
    collapsed = " ".join(text.strip().split())
    collapsed = re.sub(r"[A-Za-z0-9+/=]{120,}", "[LONG_TOKEN]", collapsed)
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


def _parse_response_json(provider: Provider, response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        status = f"HTTP {response.status_code} {response.reason_phrase}".strip()
        snippet = _response_text_snippet(response.text)
        message = f"{provider.code} 上游返回无效 JSON（{status}）"
        if snippet:
            message += f": {snippet}"
        raise RuntimeError(message) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{provider.code} 上游返回 JSON {type(data).__name__}，预期为对象")
    return data


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None:
        await value


def _apply_idempotency_key(payload: dict[str, Any], config: dict[str, Any], idempotency_key: str | None) -> None:
    if not idempotency_key:
        return
    field = config.get("idempotency_key_field")
    if isinstance(field, str) and field.strip():
        payload[field.strip()] = idempotency_key
        return
    if config.get("supports_idempotency_key"):
        payload["idempotency_key"] = idempotency_key


def _media_auth_headers(api_key: str, config: dict[str, Any]) -> dict[str, str]:
    mode = str(config.get("auth_header_mode") or "").strip()
    secret = str(api_key or "").strip()
    if mode != "raw_authorization" and secret.lower().startswith("bearer "):
        secret = secret[7:].strip()
    if mode == "fal_key" and secret.lower().startswith("key "):
        secret = secret[4:].strip()
    if mode == "fal_key":
        authorization = f"Key {secret}"
    elif mode == "raw_authorization":
        authorization = secret
    else:
        authorization = f"Bearer {secret}"
    headers = {"Authorization": authorization, "Content-Type": "application/json"}
    if config.get("provider_group") == "runware":
        headers["Runware-API-Key"] = secret
    return headers


def build_async_http_client(timeout: int) -> httpx.AsyncClient:
    """Use IPv4 explicitly to avoid Windows async DNS/IPv6 connection failures."""
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    return httpx.AsyncClient(timeout=timeout, transport=transport)


def file_to_inline_part(path: str) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(Path(path).read_bytes()).decode("ascii"),
        }
    }


def file_to_data_url(path: str) -> str:
    part = file_to_inline_part(path)["inlineData"]
    return f"data:{part['mimeType']};base64,{part['data']}"


class ProviderClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._external_client = http_client

    async def call_llm(
        self,
        provider: Provider,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[str] | None = None,
        response_format: str | None = "json_object",
    ) -> str:
        config = json.loads(provider.config_json)
        user_content: str | list[dict[str, Any]] = user_prompt
        if image_paths:
            user_content = [{"type": "text", "text": user_prompt}]
            user_content.extend(
                {"type": "image_url", "image_url": {"url": file_to_data_url(path)}}
                for path in image_paths
            )
        payload: dict[str, Any] = {
            "model": provider.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": config.get("temperature", 0.2),
        }
        if response_format:
            payload["response_format"] = {"type": response_format}
        data = await self._post_json(provider, api_key, payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM 响应缺少 choices[0].message.content") from exc
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM 返回空内容")
        return content

    async def generate_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        *,
        input_urls: list[str] | None = None,
        existing_task_id: str | None = None,
        on_task_submitted: ImageTaskSubmittedCallback | None = None,
        idempotency_key: str | None = None,
    ) -> bytes:
        config_for_prompt = provider_config_dict(provider)
        prompt = append_requested_size_to_prompt(prompt, aspect_ratio, config_for_prompt)
        if provider.adapter == HELLOBABYGO_IMAGE_ADAPTER:
            return await self._generate_hellobabygo_image(
                provider,
                api_key,
                prompt,
                input_paths,
                aspect_ratio,
                input_urls=input_urls,
                existing_task_id=existing_task_id,
                on_task_submitted=on_task_submitted,
                idempotency_key=idempotency_key,
            )
        if provider.adapter == "gemini_generate_content":
            return await self._generate_gemini(provider, api_key, prompt, input_paths, aspect_ratio)
        if provider.adapter == "openai_images_generation":
            return await self._generate_openai_image(provider, api_key, prompt, input_paths, aspect_ratio)
        if provider.adapter == MEDIA_IMAGE_ADAPTER:
            return await self._generate_media_image(
                provider,
                api_key,
                prompt,
                input_paths,
                aspect_ratio,
                input_urls=input_urls,
                existing_task_id=existing_task_id,
                on_task_submitted=on_task_submitted,
                idempotency_key=idempotency_key,
            )
        raise RuntimeError(f"Provider {provider.code} 不支持生图：{provider.adapter}")

    async def edit_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        *,
        input_urls: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> bytes:
        if not input_paths:
            raise RuntimeError("Image edit requires at least one source image")
        config_for_prompt = provider_config_dict(provider)
        prompt = append_requested_size_to_prompt(prompt, aspect_ratio, config_for_prompt)
        if provider.adapter == HELLOBABYGO_IMAGE_ADAPTER:
            return await self._edit_hellobabygo_image(
                provider,
                api_key,
                prompt,
                input_paths,
                aspect_ratio,
                input_urls=input_urls,
                idempotency_key=idempotency_key,
            )
        if provider.adapter == "openai_images_generation":
            config = json.loads(provider.config_json)
            configured_size = config.get("size", "follow_ratio")
            size = IMAGE2_SIZE_MAP[aspect_ratio] if configured_size == "follow_ratio" else configured_size
            return await self._post_openai_edit(provider, api_key, prompt, input_paths, size, config)
        config = json.loads(provider.config_json)
        if config.get("supports_image_edit") and provider.adapter == "gemini_generate_content":
            return await self._generate_gemini(provider, api_key, prompt, input_paths, aspect_ratio)
        if provider.adapter == MEDIA_IMAGE_ADAPTER:
            return await self._generate_media_image(
                provider,
                api_key,
                prompt,
                input_paths,
                aspect_ratio,
                input_urls=input_urls,
                idempotency_key=idempotency_key,
                force_edit=True,
            )
        raise RuntimeError(f"Provider {provider.code} does not expose an explicit image edit capability: {provider.adapter}")

    async def submit_video_task(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        image_urls: list[str] | None,
        *,
        aspect_ratio: str,
        duration: int,
        resolution: str,
        generate_audio: bool | None = None,
        camera_fixed: bool | None = None,
        watermark: bool | None = None,
    ) -> dict[str, Any]:
        if provider.adapter == HELLOBABYGO_VIDEO_ADAPTER:
            seconds = int(duration)
            if seconds < 5 or seconds > 15:
                raise RuntimeError(f"{provider.model_name} 的 seconds={seconds} 不合法，支持 5 到 15 秒")
            size = _validate_choice(str(aspect_ratio), HELLOBABYGO_VIDEO_SIZES, "size", provider.model_name)
            normalized_resolution = _validate_choice(
                _normalize_video_resolution(str(resolution or "1080p")),
                HELLOBABYGO_VIDEO_RESOLUTIONS,
                "resolution",
                provider.model_name,
            )
            payload: dict[str, Any] = {
                "model": provider.model_name,
                "prompt": prompt,
                "seconds": seconds,
                "size": size,
                "resolution": normalized_resolution,
            }
            if image_urls:
                payload["images"] = image_urls[:9]
            config = json.loads(provider.config_json)
            extra = config.get("extra")
            if isinstance(extra, dict) and extra:
                payload["extra"] = extra
            return await self._post_json(provider, api_key, payload)
        if provider.adapter == MEDIA_VIDEO_ADAPTER:
            return await self._submit_media_video_task(
                provider,
                api_key,
                prompt,
                image_urls,
                aspect_ratio=aspect_ratio,
                duration=duration,
                resolution=resolution,
                generate_audio=generate_audio,
                camera_fixed=camera_fixed,
                watermark=watermark,
            )
        if provider.adapter != "shengsuanyun_tasks_generation":
            raise RuntimeError(f"Provider {provider.code} does not support video generation: {provider.adapter}")
        config = json.loads(provider.config_json)
        image_role = str(config.get("image_role") or "reference_image")
        if image_role not in {"reference_image", "first_frame"}:
            raise RuntimeError(f"Seedance 图片角色不支持：{image_role}")
        payload: dict[str, Any] = {
            "model": provider.model_name,
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "role": image_role, "image_url": {"url": (image_urls or [""])[0]}},
            ],
            "ratio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": bool(generate_audio),
            "camera_fixed": bool(camera_fixed),
            "watermark": bool(watermark),
            "return_last_frame": bool(config.get("return_last_frame", False)),
            "draft": bool(config.get("draft", False)),
            "tools": config.get("tools", []),
        }
        if config.get("service_tier"):
            payload["service_tier"] = config["service_tier"]
        return await self._post_json(provider, api_key, payload)

    async def get_video_task(self, provider: Provider, api_key: str, request_id: str) -> dict[str, Any]:
        if provider.adapter == MEDIA_VIDEO_ADAPTER:
            return await self._get_media_task(provider, api_key, request_id)
        if provider.adapter not in {"shengsuanyun_tasks_generation", HELLOBABYGO_VIDEO_ADAPTER}:
            raise RuntimeError(f"Provider {provider.code} does not support video task polling: {provider.adapter}")
        config = json.loads(provider.config_json)
        url = provider.base_url.rstrip("/") + f"/{request_id}"
        headers = _media_auth_headers(api_key, config)
        if self._external_client:
            response = await self._external_client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 600))) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_response_json(provider, response)

    async def health_check(self, provider: Provider, api_key: str) -> dict[str, Any]:
        config = provider_config_dict(provider)
        started = datetime.now(timezone.utc)
        health = config.get("health_check") if isinstance(config.get("health_check"), dict) else {}
        url = str(health.get("url") or "").strip()
        group = str(config.get("provider_group") or "").strip()
        if not url:
            if group == "apimodels":
                url = provider.base_url.partition("/api/v1")[0].rstrip("/") + "/api/v1/balance"
            elif group == "openrouter" and provider.adapter == MEDIA_IMAGE_ADAPTER:
                url = provider.base_url.partition("/api/v1")[0].rstrip("/") + "/api/v1/images/models"
            elif group in {"openrouter", "cometapi"}:
                url = provider.base_url.partition("/v1")[0].rstrip("/") + "/v1/models"
            elif "/v1/" in provider.base_url:
                url = provider.base_url.partition("/v1")[0].rstrip("/") + "/v1/models"
            elif group == "replicate":
                url = "https://api.replicate.com/v1/models"
            else:
                return {
                    "ok": False,
                    "status": "unknown",
                    "latency_ms": 0,
                    "message": "该中转站未公开稳定的非计费模型目录；未发起扣费生成任务",
                }
        headers = _media_auth_headers(api_key, config)
        try:
            if self._external_client:
                response = await self._external_client.get(url, headers=headers)
            else:
                async with build_async_http_client(int(config.get("timeout_seconds", 60))) as client:
                    response = await client.get(url, headers=headers)
            response.raise_for_status()
            latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return {
                "ok": True,
                "status": "ok",
                "latency_ms": latency,
                "message": "连接可用，未发起计费生成任务",
            }
        except httpx.HTTPStatusError as exc:
            latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            detail = exc.response.text.replace("\n", " ")[:240]
            return {"ok": False, "status": "failed", "latency_ms": latency, "message": f"HTTP {exc.response.status_code}: {detail}"}
        except httpx.RequestError as exc:
            latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return {"ok": False, "status": "failed", "latency_ms": latency, "message": f"网络连接失败：{str(exc)[:240]}"}

    async def _preflight_if_needed(self, provider: Provider, api_key: str, config: dict[str, Any]) -> None:
        if not config.get("preflight_before_call"):
            return
        result = await self.health_check(provider, api_key)
        if result.get("status") == "failed":
            raise RuntimeError(f"{provider.code} 预检失败：{result.get('message')}")

    def _apply_size_payload(self, payload: dict[str, Any], config: dict[str, Any], aspect_ratio: str) -> None:
        requested = _provider_request_image_size_for_config(config, aspect_ratio)
        effective_aspect_ratio = requested["aspect_ratio"]
        mode = str(config.get("size_param_mode") or "size_string")
        if mode == "width_height":
            payload["width"] = requested["width"]
            payload["height"] = requested["height"]
        elif mode == "image_size_object":
            payload["image_size"] = {"width": requested["width"], "height": requested["height"]}
        elif mode == "aspect_ratio_resolution":
            payload["aspect_ratio"] = effective_aspect_ratio
            payload["resolution"] = config.get("resolution", "1K")
        elif mode == "aspect_ratio":
            payload["aspect_ratio"] = effective_aspect_ratio
        else:
            payload["size"] = requested["size"]
            payload["aspect_ratio"] = effective_aspect_ratio

    def _media_image_payload(
        self,
        provider: Provider,
        prompt: str,
        aspect_ratio: str,
        input_urls: list[str],
        *,
        force_edit: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        config = provider_config_dict(provider)
        group = str(config.get("provider_group") or "")
        operation = "edit" if force_edit else str(config.get("operation") or "generate")
        requested = _provider_request_image_size_for_config(config, aspect_ratio)
        effective_aspect_ratio = requested["aspect_ratio"]
        if operation == "edit" and not config.get("supports_edit"):
            raise RuntimeError(f"{provider.code} 未声明 edit 能力，不能进入图片编辑链路")
        if group == "runware":
            task: dict[str, Any] = {
                "taskType": "imageInference",
                "taskUUID": str(uuid4()),
                "model": provider.model_name,
                "positivePrompt": prompt,
                "numberResults": _configured_optional_int(config, "numberResults", minimum=1, maximum=4) or 1,
                "outputFormat": _configured_output_format(config).upper(),
                "width": requested["width"],
                "height": requested["height"],
            }
            for source_key, payload_key in (("outputQuality", "outputQuality"), ("seed", "seed")):
                configured = _configured_optional_int(config, source_key)
                if configured is not None:
                    task[payload_key] = configured
            for key in ("includeCost", "checkNSFW"):
                if key in config:
                    task[key] = bool(config[key])
            if input_urls:
                task["referenceImages"] = input_urls[: int(config.get("max_reference_images", len(input_urls)))]
            quality = config.get("quality")
            if quality:
                task["providerSettings"] = {"openai": {"quality": quality}}
            return [task]
        if group == "replicate":
            input_payload: dict[str, Any] = {
                "prompt": prompt,
                "aspect_ratio": effective_aspect_ratio,
                "output_format": _configured_output_format(config),
            }
            count = _configured_optional_int(config, "number_of_images", minimum=1, maximum=10)
            if count is not None:
                input_payload["number_of_images"] = count
            if config.get("quality"):
                input_payload["quality"] = config["quality"]
            if config.get("resolution"):
                input_payload["resolution"] = config["resolution"]
            for key in ("background", "moderation", "user_id"):
                _apply_optional_scalar(input_payload, config, key)
            compression = _configured_optional_int(config, "output_compression", minimum=0, maximum=100)
            if compression is not None:
                input_payload["output_compression"] = compression
            if input_urls:
                field = "input_images" if config.get("model_family") == "gpt-image-2" else "image_input"
                input_payload[field] = input_urls
            return {"input": input_payload}
        if group == "kie":
            model_name = provider.model_name
            if input_urls and config.get("edit_model_name"):
                model_name = str(config["edit_model_name"])
            input_payload = {"prompt": prompt, "aspect_ratio": effective_aspect_ratio}
            if config.get("resolution"):
                input_payload["resolution"] = config["resolution"]
            input_payload["output_format"] = _configured_output_format(config)
            if input_urls:
                references = input_urls[: int(config.get("max_reference_images", len(input_urls)))]
                if config.get("model_family") == "gpt-image-2":
                    input_payload["input_urls"] = references
                else:
                    input_payload["image_input"] = references
            payload = {"model": model_name, "input": input_payload}
            _apply_optional_scalar(payload, config, "callBackUrl")
            return payload
        payload: dict[str, Any] = {"prompt": prompt}
        if group not in {"fal", "wavespeed"}:
            payload["model"] = provider.model_name
        if group == "fal":
            payload["num_images"] = _configured_optional_int(config, "num_images", minimum=1, maximum=4) or 1
            if "sync_mode" in config:
                payload["sync_mode"] = bool(config["sync_mode"])
            if operation == "edit":
                _apply_optional_scalar(payload, config, "mask_image_url")
        elif group == "cometapi" and config.get("api_shape") == "gemini_generate_content":
            parts: list[dict[str, Any]] = [{"text": prompt}]
            parts.extend({"file_data": {"file_uri": url, "mime_type": "image/png"}} for url in input_urls[: int(config.get("max_reference_images", len(input_urls)))])
            image_config: dict[str, Any] = {"aspectRatio": effective_aspect_ratio}
            if config.get("resolution"):
                image_config["imageSize"] = str(config["resolution"]).upper()
            return {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "imageConfig": image_config,
                },
            }
        elif group in {"openrouter", "atlas", "cometapi"} or (
            group == "apimodels" and config.get("model_family") != "gpt-image-2"
        ):
            payload["n"] = _configured_optional_int(config, "n", minimum=1, maximum=10) or 1
        self._apply_size_payload(payload, config, aspect_ratio)
        if group == "wavespeed" and isinstance(payload.get("resolution"), str):
            payload["resolution"] = payload["resolution"].lower()
        if config.get("quality"):
            payload["quality"] = config["quality"]
        output_format = _configured_output_format(config)
        if output_format and not (group == "apimodels" and config.get("model_family") == "gpt-image-2"):
            if group != "fal":
                payload["format"] = output_format
            payload["output_format"] = output_format
        if not (group == "apimodels" and config.get("model_family") == "gpt-image-2"):
            for key in ("response_format", "background"):
                _apply_optional_scalar(payload, config, key)
        if group == "apimodels" and config.get("model_family") == "gpt-image-2":
            _apply_optional_scalar(payload, config, "callback_url")
        for key in ("output_compression", "seed"):
            configured = _configured_optional_int(config, key, minimum=0 if key == "output_compression" else None, maximum=100 if key == "output_compression" else None)
            if configured is not None:
                payload[key] = configured
        for key in ("stream", "enable_base64_output", "enable_sync_mode"):
            if key in config:
                payload[key] = bool(config[key])
        if input_urls:
            if group == "fal":
                payload["image_urls"] = input_urls
            elif group == "openrouter":
                payload["input_references"] = [
                    {"type": "image_url", "image_url": {"url": url}}
                    for url in input_urls[: int(config.get("max_reference_images", len(input_urls)))]
                ]
            elif group == "atlas":
                references = input_urls[: int(config.get("max_reference_images", len(input_urls)))]
                model_name = str(config.get("edit_model_name") or provider.model_name)
                if model_name.endswith("/text-to-image"):
                    model_name = model_name[: -len("/text-to-image")] + "/edit"
                payload["model"] = model_name
                payload["images"] = references
                if config.get("model_family") == "gpt-image-2":
                    payload.pop("aspect_ratio", None)
                elif config.get("model_family", "").startswith("nano-banana") and isinstance(payload.get("resolution"), str):
                    payload["resolution"] = payload["resolution"].lower()
            elif group == "apimodels":
                references = input_urls[: int(config.get("max_reference_images", len(input_urls)))]
                if len(references) == 1:
                    payload["image_url"] = references[0]
                elif references:
                    payload["image_urls"] = references
            elif group == "wavespeed":
                payload["images"] = input_urls
                payload["image"] = input_urls[0]
            else:
                payload["images"] = input_urls
        _apply_idempotency_key(payload, config, idempotency_key)
        return payload

    async def _generate_media_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        *,
        input_urls: list[str] | None = None,
        existing_task_id: str | None = None,
        on_task_submitted: ImageTaskSubmittedCallback | None = None,
        idempotency_key: str | None = None,
        force_edit: bool = False,
    ) -> bytes:
        config = provider_config_dict(provider)
        max_reference_images = int(config.get("max_reference_images", len(input_paths) or 0) or 0)
        if max_reference_images and len(input_paths) > max_reference_images:
            raise RuntimeError(f"{provider.label or provider.code} supports at most {max_reference_images} reference images; got {len(input_paths)}")
        if input_paths and not input_urls and not self._uses_multipart_image_edit(config, input_paths):
            raise RuntimeError("Live 图片模型需要配置 LISTINGO_PUBLIC_ASSET_BASE_URL，使中转站可读取参考图 URL")
        await self._preflight_if_needed(provider, api_key, config)
        if existing_task_id:
            try:
                completed = await self._poll_media_task(provider, api_key, existing_task_id, config)
                return await self._download_media_image_result(provider, completed, config, api_key=api_key)
            except Exception as exc:
                if not _recoverable_existing_media_task_error(exc):
                    raise
        if self._uses_multipart_image_edit(config, input_paths):
            submitted = await self._post_media_multipart_image_edit(
                provider,
                api_key,
                prompt,
                input_paths,
                aspect_ratio,
                config,
                idempotency_key=idempotency_key,
            )
            direct_url = self._extract_media_url(submitted, prefer_video=False)
            direct_b64 = self._extract_b64(submitted)
            if direct_b64:
                return base64.b64decode(direct_b64)
            if direct_url:
                return await self._download_media_result_url(provider, direct_url, config, api_key=api_key)
            task_id = _task_id(submitted)
            await _maybe_await(on_task_submitted(task_id) if on_task_submitted else None)
            completed = await self._poll_media_task(provider, api_key, task_id, config, submitted=submitted)
            return await self._download_media_image_result(provider, completed, config, api_key=api_key)
        payload = self._media_image_payload(
            provider,
            prompt,
            aspect_ratio,
            input_urls or [],
            force_edit=force_edit,
            idempotency_key=idempotency_key,
        )
        submitted = await self._post_media_payload(provider, api_key, payload, config)
        direct_url = self._extract_media_url(submitted, prefer_video=False)
        direct_b64 = self._extract_b64(submitted)
        if direct_b64:
            return base64.b64decode(direct_b64)
        if direct_url:
            return await self._download_media_result_url(provider, direct_url, config, api_key=api_key)
        task_id = _task_id(submitted)
        await _maybe_await(on_task_submitted(task_id) if on_task_submitted else None)
        completed = await self._poll_media_task(provider, api_key, task_id, config, submitted=submitted)
        return await self._download_media_image_result(provider, completed, config, api_key=api_key)

    def _uses_multipart_image_edit(self, config: dict[str, Any], input_paths: list[str]) -> bool:
        return (
            bool(input_paths)
            and config.get("provider_group") == "cometapi"
            and config.get("model_family") == "gpt-image-2"
        )

    async def _post_media_multipart_image_edit(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        config: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        requested = _provider_request_image_size_for_config(config, aspect_ratio)
        edit_url = str(config.get("edit_base_url") or provider.base_url.replace("/images/generations", "/images/edits"))
        headers = _media_auth_headers(api_key, config)
        headers.pop("Content-Type", None)
        form: dict[str, str] = {
            "model": provider.model_name,
            "prompt": prompt,
            "n": str(_configured_optional_int(config, "n", minimum=1, maximum=10) or 1),
            "size": requested["size"],
        }
        if config.get("quality"):
            form["quality"] = str(config["quality"])
        _apply_idempotency_key(form, config, idempotency_key)
        files = []
        for path in input_paths:
            inline = file_to_inline_part(path)["inlineData"]
            files.append(("image", (Path(path).name, Path(path).read_bytes(), inline["mimeType"])))
        if self._external_client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: self._external_client.post(edit_url, headers=headers, data=form, files=files),
            )
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: client.post(edit_url, headers=headers, data=form, files=files),
            )
            return _parse_response_json(provider, response)

    async def _post_media_payload(
        self,
        provider: Provider,
        api_key: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        headers = _media_auth_headers(api_key, config)
        url = self._media_submit_url(provider, payload, config)
        if self._external_client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: self._external_client.post(url, headers=headers, json=payload),
            )
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: client.post(url, headers=headers, json=payload),
            )
            return _parse_response_json(provider, response)

    def _media_submit_url(
        self,
        provider: Provider,
        payload: dict[str, Any] | list[dict[str, Any]],
        config: dict[str, Any],
    ) -> str:
        group = str(config.get("provider_group") or "")
        if group in {"fal", "wavespeed"} and isinstance(payload, dict):
            has_image_input = any(payload.get(key) for key in ("image_urls", "images", "image", "image_url"))
            edit_base_url = str(config.get("edit_base_url") or "").strip()
            if has_image_input and edit_base_url:
                return edit_base_url
        return provider.base_url

    async def _download_media_image_result(
        self,
        provider: Provider,
        data: dict[str, Any],
        config: dict[str, Any],
        *,
        api_key: str | None = None,
    ) -> bytes:
        b64 = self._extract_b64(data)
        if b64:
            return base64.b64decode(b64)
        result_url = self._extract_media_url(data, prefer_video=False)
        if not result_url:
            raise RuntimeError(f"{provider.code} 图片任务完成但响应缺少图片 URL")
        return await self._download_media_result_url(provider, result_url, config, api_key=api_key)

    async def _download_media_result_url(
        self,
        provider: Provider,
        result_url: str,
        config: dict[str, Any],
        *,
        api_key: str | None = None,
    ) -> bytes:
        timeout = int(config.get("timeout_seconds", 600))
        try:
            return await self._download(result_url, timeout)
        except Exception as first_error:
            group = str(config.get("provider_group") or "")
            if group == "atlas" and api_key:
                try:
                    headers = _media_auth_headers(api_key, config)
                    headers.pop("Content-Type", None)
                    return await self._download(result_url, timeout, headers=headers)
                except Exception as auth_error:
                    raise RuntimeError(
                        f"{provider.code} result image download failed after public and authenticated attempts: "
                        f"{first_error}; authenticated retry: {auth_error}"
                    ) from auth_error
            raise RuntimeError(f"{provider.code} result image download failed: {first_error}") from first_error

    def _task_poll_url(self, provider: Provider, request_id: str, config: dict[str, Any], submitted: dict[str, Any] | None = None) -> str:
        urls = submitted.get("urls") if isinstance(submitted, dict) else None
        if isinstance(urls, dict) and isinstance(urls.get("get"), str):
            return urls["get"]
        template = str(config.get("poll_url_template") or "").strip()
        if template:
            return template.format(task_id=request_id, request_id=request_id)
        group = str(config.get("provider_group") or "")
        if group == "kie":
            return "https://api.kie.ai/api/v1/jobs/recordInfo?taskId=" + quote(request_id, safe="")
        if group == "apimodels":
            return provider.base_url.rstrip("/") + "?task_id=" + quote(request_id, safe="")
        if group == "atlas":
            return "https://api.atlascloud.ai/api/v1/model/prediction/" + quote(request_id, safe="")
        if group == "wavespeed":
            return "https://api.wavespeed.ai/api/v3/predictions/" + quote(request_id, safe="") + "/result"
        return provider.base_url.rstrip("/") + "/" + quote(request_id, safe="")

    async def _poll_media_task(
        self,
        provider: Provider,
        api_key: str,
        request_id: str,
        config: dict[str, Any],
        *,
        submitted: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._task_poll_url(provider, request_id, config, submitted)
        last_data: dict[str, Any] = {}
        for attempt in range(_poll_attempts(config)):
            data = await self._get_json(provider, api_key, url, config)
            last_data = data
            status = _task_status(data)
            if status in REMOTE_SUCCESS_STATUSES or self._extract_media_url(data, prefer_video=False):
                return data
            if status in REMOTE_FAILED_STATUSES:
                raise RuntimeError(_task_error_message(data))
            if status not in REMOTE_RUNNING_STATUSES and status != "unknown":
                raise RuntimeError(f"{provider.code} task returned unknown status: {status}")
            if attempt < _poll_attempts(config) - 1:
                await asyncio.sleep(_poll_interval_seconds(config))
        raise RuntimeError(f"{provider.code} task timed out: {request_id}; last_status={_task_status(last_data)}")

    def _extract_b64(self, data: Any) -> str | None:
        if isinstance(data, str):
            value = data.strip()
            if value.lower().startswith("data:image/") and ";base64," in value.lower():
                return value.split(",", 1)[1].strip()
            if len(value) > 120 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", value):
                return re.sub(r"\s+", "", value)
            return None
        if isinstance(data, dict):
            for inline_key in ("inlineData", "inline_data"):
                inline = data.get(inline_key)
                if isinstance(inline, dict):
                    value = inline.get("data")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            for key in ("b64_json", "base64", "image_base64", "imageBase64", "output_base64", "outputBase64"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for value in data.values():
                found = self._extract_b64(value)
                if found:
                    return found
        if isinstance(data, list):
            for item in data:
                found = self._extract_b64(item)
                if found:
                    return found
        return None

    def _extract_media_url(self, data: Any, *, prefer_video: bool) -> str | None:
        if isinstance(data, str):
            lowered = data.lower()
            if data.startswith("http") and (not prefer_video or any(token in lowered for token in (".mp4", ".mov", ".webm", "video"))):
                return data
            return None
        if isinstance(data, list):
            for item in data:
                found = self._extract_media_url(item, prefer_video=prefer_video)
                if found:
                    return found
            return None
        if isinstance(data, dict):
            keys = (
                ("video_url", "file_url", "output_url", "download_url", "url")
                if prefer_video
                else ("imageURL", "image_url", "url", "output_url", "download_url")
            )
            for key in keys:
                found = self._extract_media_url(data.get(key), prefer_video=prefer_video)
                if found:
                    return found
            for value in data.values():
                found = self._extract_media_url(value, prefer_video=prefer_video)
                if found:
                    return found
        return None

    async def _submit_media_video_task(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        image_urls: list[str] | None,
        *,
        aspect_ratio: str,
        duration: int,
        resolution: str,
        generate_audio: bool | None = None,
        camera_fixed: bool | None = None,
        watermark: bool | None = None,
    ) -> dict[str, Any]:
        config = provider_config_dict(provider)
        await self._preflight_if_needed(provider, api_key, config)
        group = str(config.get("provider_group") or "")
        effective_aspect_ratio = _configured_string(config, "aspect_ratio", aspect_ratio)
        effective_duration = _configured_int(config, "duration", duration)
        effective_resolution = _configured_string(config, "resolution", resolution)
        effective_size = _configured_optional_string(config, "size")
        effective_generate_audio = _configured_bool(config, "generate_audio", generate_audio)
        effective_camera_fixed = _configured_bool(config, "camera_fixed", camera_fixed)
        effective_watermark = _configured_bool(config, "watermark", watermark)
        if group == "runware":
            task = {
                "taskType": "videoInference",
                "taskUUID": str(uuid4()),
                "model": provider.model_name,
                "positivePrompt": prompt,
                "duration": effective_duration,
                "resolution": effective_resolution,
                "aspectRatio": effective_aspect_ratio,
            }
            if image_urls:
                task["inputs"] = {"frameImages": image_urls[:2]}
            if generate_audio is not None or "generate_audio" in config:
                task["settings"] = {"audio": effective_generate_audio}
            seed = _configured_optional_int(config, "seed")
            if seed is not None:
                task["seed"] = seed
            if "includeCost" in config:
                task["includeCost"] = bool(config["includeCost"])
            payload: dict[str, Any] | list[dict[str, Any]] = [task]
        elif group == "kie":
            input_payload: dict[str, Any] = {
                "prompt": prompt,
                "aspect_ratio": effective_aspect_ratio,
                "duration": effective_duration,
                "resolution": effective_resolution,
                "fixed_lens": effective_camera_fixed,
                "generate_audio": effective_generate_audio,
                "nsfw_checker": False,
                "watermark": effective_watermark,
            }
            if image_urls:
                input_payload["first_frame_url"] = image_urls[0]
                if len(image_urls) > 1:
                    input_payload["last_frame_url"] = image_urls[1]
                if len(image_urls) > 2:
                    input_payload["reference_image_urls"] = image_urls[2:11]
            payload = {"model": provider.model_name, "input": input_payload}
            _apply_optional_scalar(payload, config, "callBackUrl")
        elif group == "replicate":
            payload = {
                "input": {
                    "prompt": prompt,
                    "aspect_ratio": effective_aspect_ratio,
                    "duration": effective_duration,
                    "resolution": effective_resolution,
                    "image": (image_urls or [None])[0],
                    "reference_images": image_urls or [],
                }
            }
        elif group == "openrouter":
            payload = {
                "model": provider.model_name,
                "prompt": prompt,
                "duration": effective_duration,
                "resolution": effective_resolution,
                "aspect_ratio": effective_aspect_ratio,
                "generate_audio": effective_generate_audio,
            }
            if effective_size:
                payload["size"] = effective_size
            seed = _configured_optional_int(config, "seed")
            if seed is not None:
                payload["seed"] = seed
            if image_urls:
                payload["frame_images"] = [{"frame_type": "first_frame", "url": image_urls[0]}]
                payload["input_references"] = [{"type": "image", "url": url} for url in image_urls[:9]]
        elif group == "cometapi":
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            content.extend({"type": "image", "url": url} for url in (image_urls or [])[:9])
            payload = {
                "model": provider.model_name,
                "content": content,
                "output": {
                    "ratio": effective_aspect_ratio,
                    "duration_s": effective_duration,
                    "resolution": effective_resolution,
                },
            }
        elif group == "atlas":
            payload = {
                "model": provider.model_name,
                "prompt": prompt,
                "duration": effective_duration,
                "resolution": effective_resolution,
                "ratio": effective_aspect_ratio if effective_aspect_ratio else "adaptive",
                "generate_audio": effective_generate_audio,
                "watermark": effective_watermark,
            }
            if image_urls:
                payload["image"] = image_urls[0]
                if len(image_urls) > 1:
                    payload["last_image"] = image_urls[1]
            seed = _configured_optional_int(config, "seed")
            if seed is not None:
                payload["seed"] = seed
            bitrate_mode = _configured_optional_string(config, "bitrate_mode")
            if bitrate_mode:
                payload["bitrate_mode"] = bitrate_mode
            return_last_frame = config.get("return_last_frame")
            if return_last_frame is not None:
                payload["return_last_frame"] = bool(return_last_frame)
        elif group == "fal":
            payload = {
                "prompt": prompt,
                "aspect_ratio": effective_aspect_ratio,
                "duration": str(effective_duration),
                "resolution": effective_resolution,
                "generate_audio": effective_generate_audio,
            }
            if image_urls:
                payload["image_url"] = image_urls[0]
                if len(image_urls) > 1:
                    payload["end_image_url"] = image_urls[1]
        else:
            payload = {"prompt": prompt}
            if group not in {"wavespeed"}:
                payload["model"] = provider.model_name
            payload.update(
                {
                    "aspect_ratio": effective_aspect_ratio,
                    "ratio": effective_aspect_ratio,
                    "duration": effective_duration,
                    "resolution": effective_resolution,
                    "images": image_urls or [],
                    "image": (image_urls or [""])[0] if image_urls else "",
                    "generate_audio": effective_generate_audio,
                    "camera_fixed": effective_camera_fixed,
                    "watermark": effective_watermark,
                }
            )
            if effective_size:
                payload["size"] = effective_size
            for key in ("callBackUrl",):
                _apply_optional_scalar(payload, config, key)
            for key in ("enable_base64_output", "enable_sync_mode"):
                if key in config:
                    payload[key] = bool(config[key])
        return await self._post_media_payload(provider, api_key, payload, config)

    async def _get_media_task(self, provider: Provider, api_key: str, request_id: str) -> dict[str, Any]:
        config = provider_config_dict(provider)
        url = self._task_poll_url(provider, request_id, config)
        return await self._get_json(provider, api_key, url, config)

    async def _generate_hellobabygo_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        *,
        input_urls: list[str] | None = None,
        existing_task_id: str | None = None,
        on_task_submitted: ImageTaskSubmittedCallback | None = None,
        idempotency_key: str | None = None,
    ) -> bytes:
        config = json.loads(provider.config_json)
        max_reference_images = int(config.get("max_reference_images", len(input_paths) or 0) or 0)
        if max_reference_images and len(input_paths) > max_reference_images:
            raise RuntimeError(
                f"{provider.label or provider.code} supports at most {max_reference_images} reference images; got {len(input_paths)}"
            )
        if existing_task_id:
            completed = await self._poll_hellobabygo_task(provider, api_key, existing_task_id, config)
            result_url = _image_result_url(completed)
            download_headers = (
                {"Authorization": f"Bearer {api_key}"}
                if result_url.startswith(_hellobabygo_image_task_base_url(provider) + "/")
                else None
            )
            return await self._download(result_url, int(config.get("timeout_seconds", 600)), headers=download_headers)
        payload = self._hellobabygo_image_payload(provider, prompt, aspect_ratio, config)
        _apply_idempotency_key(payload, config, idempotency_key)
        if input_paths and not input_urls:
            raise RuntimeError("Live 参考图需要配置 LISTINGO_PUBLIC_ASSET_BASE_URL（公网资源地址）")
        if input_urls:
            payload["images"] = input_urls
        submitted = await self._post_json(provider, api_key, payload)
        task_id = _task_id(submitted)
        await _maybe_await(on_task_submitted(task_id) if on_task_submitted else None)
        completed = await self._poll_hellobabygo_task(provider, api_key, task_id, config)
        result_url = _image_result_url(completed)
        download_headers = (
            {"Authorization": f"Bearer {api_key}"}
            if result_url.startswith(_hellobabygo_image_task_base_url(provider) + "/")
            else None
        )
        return await self._download(result_url, int(config.get("timeout_seconds", 600)), headers=download_headers)

    async def _edit_hellobabygo_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        *,
        input_urls: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> bytes:
        config = json.loads(provider.config_json)
        max_reference_images = int(config.get("max_reference_images", len(input_paths) or 0) or 0)
        if max_reference_images and len(input_paths) > max_reference_images:
            raise RuntimeError(
                f"{provider.label or provider.code} supports at most {max_reference_images} reference images; got {len(input_paths)}"
            )
        if not input_urls:
            raise RuntimeError("Live edit requires LISTINGO_PUBLIC_ASSET_BASE_URL so the provider can fetch source images")
        payload = self._hellobabygo_image_payload(provider, prompt, aspect_ratio, config)
        payload["images"] = input_urls
        _apply_idempotency_key(payload, config, idempotency_key)
        edit_url = str(config.get("edit_base_url") or provider.base_url.replace("/images/generations", "/images/edits"))
        submitted = await self._post_json_to_url(provider, api_key, edit_url, payload, config)
        task_id = _task_id(submitted)
        completed = await self._poll_hellobabygo_task(provider, api_key, task_id, config)
        result_url = _image_result_url(completed)
        download_headers = (
            {"Authorization": f"Bearer {api_key}"}
            if result_url.startswith(_hellobabygo_image_task_base_url(provider) + "/")
            else None
        )
        return await self._download(result_url, int(config.get("timeout_seconds", 600)), headers=download_headers)

    def _hellobabygo_image_payload(
        self,
        provider: Provider,
        prompt: str,
        aspect_ratio: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        model = provider.model_name
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
        if model in {"nano_banana_2", "nano_banana_pro"}:
            resolution = _validate_choice(str(config.get("resolution") or "2K"), HELLOBABYGO_NANO_RESOLUTIONS, "resolution", model)
            size = str(config.get("size") or "auto")
            if size == "follow_ratio":
                size = _image_direction(aspect_ratio)
            if size == "auto" and resolution == "4K":
                size = _image_direction(aspect_ratio)
            allowed_sizes = HELLOBABYGO_NANO_4K_SIZES if resolution == "4K" else HELLOBABYGO_NANO_SIZES
            size = _validate_choice(size, allowed_sizes, "size", model)
            payload.update({"resolution": resolution, "size": size})
            return payload
        configured_size = config.get("size", "follow_ratio")
        size = HELLOBABYGO_IMAGE2_SIZE_MAP[aspect_ratio] if configured_size in {"follow_ratio", "auto"} else configured_size
        payload["size"] = _validate_choice(str(size), HELLOBABYGO_IMAGE_PIXEL_SIZES, "size", model)
        return payload

    async def _poll_hellobabygo_task(
        self,
        provider: Provider,
        api_key: str,
        task_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        url = _hellobabygo_image_task_base_url(provider) + f"/{task_id}"
        last_data: dict[str, Any] = {}
        for attempt in range(_poll_attempts(config)):
            data = await self._get_json(provider, api_key, url, config)
            last_data = data
            status = _task_status(data)
            if status in REMOTE_SUCCESS_STATUSES:
                return data
            if status in REMOTE_FAILED_STATUSES:
                raise RuntimeError(_task_error_message(data))
            if status not in REMOTE_RUNNING_STATUSES:
                raise RuntimeError(f"HelloBabyGo task returned unknown status: {status}")
            if attempt < _poll_attempts(config) - 1:
                await asyncio.sleep(_poll_interval_seconds(config))
        raise RuntimeError(f"HelloBabyGo task timed out: {task_id}; last_status={_task_status(last_data)}")

    async def _generate_gemini(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
    ) -> bytes:
        config = json.loads(provider.config_json)
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts.extend(file_to_inline_part(path) for path in input_paths)
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "responseFormat": {
                    "image": {
                        "imageSize": config.get("resolution", "1K"),
                        "aspectRatio": aspect_ratio,
                    },
                },
            },
        }
        data = await self._post_json(provider, api_key, payload)
        try:
            response_parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Nano 响应缺少 candidates[0].content.parts") from exc
        for part in response_parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
        raise RuntimeError("Nano 响应未包含图片数据")

    async def _generate_openai_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
    ) -> bytes:
        config = json.loads(provider.config_json)
        configured_size = config.get("size", "follow_ratio")
        size = IMAGE2_SIZE_MAP[aspect_ratio] if configured_size == "follow_ratio" else configured_size
        if configured_size not in ("follow_ratio", "auto") and not _size_matches_ratio(str(size), aspect_ratio):
            raise RuntimeError(f"Image 2 固定 size {size} 与前台画面比例 {aspect_ratio} 不匹配，请改为“跟随前台画面比例”或选择匹配尺寸")
        if input_paths:
            return await self._post_openai_edit(provider, api_key, prompt, input_paths, size, config)
        payload: dict[str, Any] = {
            "model": provider.model_name,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": config.get("quality", "auto"),
            "format": config.get("format", "png"),
        }
        data = await self._post_json(provider, api_key, payload)
        try:
            result = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Image 2 响应缺少 data[0]") from exc
        if result.get("b64_json"):
            return base64.b64decode(result["b64_json"])
        if result.get("url"):
            return await self._download(result["url"], int(config.get("timeout_seconds", 180)))
        raise RuntimeError("Image 2 响应未包含 b64_json 或 url")

    async def _post_openai_edit(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        size: str,
        config: dict[str, Any],
    ) -> bytes:
        edit_url = str(config.get("edit_base_url") or provider.base_url.replace("/images/generations", "/images/edits"))
        headers = {"Authorization": f"Bearer {api_key}"}
        form = {
            "model": provider.model_name,
            "prompt": prompt,
            "n": "1",
            "size": size,
            "quality": config.get("quality", "auto"),
        }
        files = []
        for path in input_paths:
            inline = file_to_inline_part(path)["inlineData"]
            files.append(("image", (Path(path).name, Path(path).read_bytes(), inline["mimeType"])))
        if self._external_client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: self._external_client.post(edit_url, headers=headers, data=form, files=files),
            )
        else:
            async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
                response = await self._request_with_retries(
                    provider,
                    config,
                    lambda: client.post(edit_url, headers=headers, data=form, files=files),
                )
        response_data = _parse_response_json(provider, response)
        result_data = response_data.get("data")
        result = result_data[0] if isinstance(result_data, list) and result_data else result_data
        if not isinstance(result, dict):
            raise RuntimeError("Image 2 edit response is missing data")
        if result.get("b64_json"):
            return base64.b64decode(result["b64_json"])
        if result.get("url"):
            return await self._download(result["url"], int(config.get("timeout_seconds", 180)))
        raise RuntimeError("Image 2 edit response has no b64_json or url")

    async def _post_json_to_url(
        self,
        provider: Provider,
        api_key: str,
        url: str,
        payload: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        headers = _media_auth_headers(api_key, config)
        if self._external_client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: self._external_client.post(url, headers=headers, json=payload),
            )
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: client.post(url, headers=headers, json=payload),
            )
            return _parse_response_json(provider, response)

    async def _post_json(self, provider: Provider, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = json.loads(provider.config_json)
        return await self._post_json_to_url(provider, api_key, provider.base_url, payload, config)

    async def _get_json(
        self,
        provider: Provider,
        api_key: str,
        url: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        headers = _media_auth_headers(api_key, config)
        if self._external_client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: self._external_client.get(url, headers=headers),
            )
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: client.get(url, headers=headers),
            )
            return _parse_response_json(provider, response)

    async def _request_with_retries(
        self,
        provider: Provider,
        config: dict[str, Any],
        send: Callable[[], Awaitable[httpx.Response]],
    ) -> httpx.Response:
        max_retries = _retry_count(config)
        for attempt in range(max_retries + 1):
            response = await send()
            if response.status_code not in RETRYABLE_HTTP_STATUS_CODES or attempt >= max_retries:
                self._raise_for_status(provider, response)
                return response
            await asyncio.sleep(_retry_delay_seconds(response, attempt, config))
        raise RuntimeError(f"{provider.code} request failed after retries")

    def _raise_for_status(self, provider: Provider, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = response.text.strip()
        if len(detail) > 300:
            detail = detail[:300] + "..."
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            retry_hint = f" Retry-After={retry_after}." if retry_after else ""
            raise RuntimeError(
                f"{provider.code} rate limited by upstream provider (HTTP 429 Too Many Requests)."
                f"{retry_hint} Wait and retry, or lower LISTINGO_MAX_JOB_CONCURRENCY."
            )
        message = f"{provider.code} upstream request failed (HTTP {response.status_code} {response.reason_phrase})"
        if detail:
            message += f": {detail}"
        raise RuntimeError(message)

    async def _download(self, url: str, timeout: int, headers: dict[str, str] | None = None) -> bytes:
        if self._external_client:
            response = await self._external_client.get(url, headers=headers)
            response.raise_for_status()
            return response.content
        async with build_async_http_client(timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.content
