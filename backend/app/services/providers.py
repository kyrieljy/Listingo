from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
from typing import Any

import httpx

from backend.app.models import Provider


IMAGE2_SIZE_MAP = {
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
HELLOBABYGO_IMAGE_PIXEL_SIZES = {"1024x1024", "1024x1792", "1792x1024"}
HELLOBABYGO_NANO_RESOLUTIONS = {"1K", "2K", "4K"}
HELLOBABYGO_NANO_SIZES = {"auto", "landscape", "portrait", "square"}
HELLOBABYGO_NANO_4K_SIZES = {"landscape", "portrait", "square"}
HELLOBABYGO_VIDEO_RESOLUTIONS = {"720p", "1080p"}
HELLOBABYGO_VIDEO_SIZES = {"1:1", "3:4", "4:3", "9:16", "16:9", "21:9", "landscape", "portrait"}
RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
REMOTE_RUNNING_STATUSES = {"queued", "in_progress", "processing", "pending", "submitted", "submitting", "running"}
REMOTE_SUCCESS_STATUSES = {"completed", "succeeded", "success"}
REMOTE_FAILED_STATUSES = {"failed", "cancelled", "canceled", "timeout", "error"}


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
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError("HelloBabyGo response is missing task_id")


def _task_status(data: dict[str, Any]) -> str:
    for source in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        if not isinstance(source, dict):
            continue
        status = source.get("status")
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
        message = source.get("message") or source.get("error_message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return "upstream task failed"


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
    ) -> bytes:
        if provider.adapter == HELLOBABYGO_IMAGE_ADAPTER:
            return await self._generate_hellobabygo_image(
                provider,
                api_key,
                prompt,
                input_paths,
                aspect_ratio,
                input_urls=input_urls,
            )
        if provider.adapter == "gemini_generate_content":
            return await self._generate_gemini(provider, api_key, prompt, input_paths, aspect_ratio)
        if provider.adapter == "openai_images_generation":
            return await self._generate_openai_image(provider, api_key, prompt, input_paths, aspect_ratio)
        raise RuntimeError(f"Provider {provider.code} 不支持生图：{provider.adapter}")

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
        if provider.adapter not in {"shengsuanyun_tasks_generation", HELLOBABYGO_VIDEO_ADAPTER}:
            raise RuntimeError(f"Provider {provider.code} does not support video task polling: {provider.adapter}")
        config = json.loads(provider.config_json)
        url = provider.base_url.rstrip("/") + f"/{request_id}"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self._external_client:
            response = await self._external_client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 600))) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return _parse_response_json(provider, response)

    async def _generate_hellobabygo_image(
        self,
        provider: Provider,
        api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        *,
        input_urls: list[str] | None = None,
    ) -> bytes:
        config = json.loads(provider.config_json)
        payload = self._hellobabygo_image_payload(provider, prompt, aspect_ratio, config)
        if input_paths and not input_urls:
            raise RuntimeError("Live 参考图需要配置 LISTINGO_PUBLIC_ASSET_BASE_URL（公网资源地址）")
        if input_urls:
            payload["images"] = input_urls
        submitted = await self._post_json(provider, api_key, payload)
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
        size = IMAGE2_SIZE_MAP[aspect_ratio] if configured_size in {"follow_ratio", "auto"} else configured_size
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
        edit_url = provider.base_url.replace("/images/generations", "/images/edits")
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

    async def _post_json(self, provider: Provider, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = json.loads(provider.config_json)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self._external_client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: self._external_client.post(provider.base_url, headers=headers, json=payload),
            )
            return _parse_response_json(provider, response)
        async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
            response = await self._request_with_retries(
                provider,
                config,
                lambda: client.post(provider.base_url, headers=headers, json=payload),
            )
            return _parse_response_json(provider, response)

    async def _get_json(
        self,
        provider: Provider,
        api_key: str,
        url: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
