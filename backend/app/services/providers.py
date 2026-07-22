from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from backend.app.models import Provider


IMAGE2_SIZE_MAP = {
    "1:1": "1024x1024",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
    "4:5": "1024x1536",
    "3:4": "1024x1536",
    "4:3": "1536x1024",
    "5:4": "1536x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "21:9": "3840x2160",
    "970:600": "auto",
    "1464:600": "auto",
    "600:450": "auto",
}


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
    ) -> bytes:
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
        image_url: str,
        *,
        aspect_ratio: str,
        duration: int,
        resolution: str,
        generate_audio: bool,
        camera_fixed: bool,
        watermark: bool,
    ) -> dict[str, Any]:
        if provider.adapter != "shengsuanyun_tasks_generation":
            raise RuntimeError(f"Provider {provider.code} does not support video generation: {provider.adapter}")
        config = json.loads(provider.config_json)
        payload: dict[str, Any] = {
            "model": provider.model_name,
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
            "ratio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "camera_fixed": camera_fixed,
            "watermark": watermark,
        }
        if config.get("service_tier"):
            payload["service_tier"] = config["service_tier"]
        return await self._post_json(provider, api_key, payload)

    async def get_video_task(self, provider: Provider, api_key: str, request_id: str) -> dict[str, Any]:
        if provider.adapter != "shengsuanyun_tasks_generation":
            raise RuntimeError(f"Provider {provider.code} does not support video task polling: {provider.adapter}")
        config = json.loads(provider.config_json)
        url = provider.base_url.rstrip("/") + f"/{request_id}"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self._external_client:
            response = await self._external_client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        async with build_async_http_client(int(config.get("timeout_seconds", 600))) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

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
            response = await self._external_client.post(edit_url, headers=headers, data=form, files=files)
        else:
            async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
                response = await client.post(edit_url, headers=headers, data=form, files=files)
        response.raise_for_status()
        response_data = response.json()
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
            response = await self._external_client.post(provider.base_url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        async with build_async_http_client(int(config.get("timeout_seconds", 180))) as client:
            response = await client.post(provider.base_url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def _download(self, url: str, timeout: int) -> bytes:
        if self._external_client:
            response = await self._external_client.get(url)
            response.raise_for_status()
            return response.content
        async with build_async_http_client(timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
