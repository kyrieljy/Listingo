import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from backend.app.api.public import serialize_job
from sqlalchemy import select

from backend.app.models import GenerationItem, GenerationJob, Prompt, PromptVersion, Provider, Workflow
from backend.app.services.execution import parse_plan_with_one_repair, run_image_route, run_image_with_fallback
from backend.app.services.jobs import _run_live_item, image_provider_route
from backend.app.services.providers import IMAGE2_SIZE_MAP, ProviderClient, build_async_http_client
from backend.app.services.redaction import safe_json


VALID_PLAN = {
    "schema_version": "1.0",
    "images": [
        {
            "route_symbol": "#@",
            "image_type": f"图 {index + 1}",
            "picture_requirement": "保持产品不变",
            "copywriting_requirements": "无文字",
        }
        for index in range(7)
    ],
}


def test_parse_plan_repairs_once() -> None:
    calls = 0

    async def repair(_: str, __: str) -> dict:
        nonlocal calls
        calls += 1
        return VALID_PLAN

    plan = asyncio.run(parse_plan_with_one_repair("not-json", 7, repair))

    assert len(plan.images) == 7
    assert calls == 1


def test_parse_plan_stops_after_failed_repair() -> None:
    calls = 0

    async def repair(_: str, __: str) -> str:
        nonlocal calls
        calls += 1
        return "still-invalid"

    with pytest.raises(ValueError, match="修复后仍不合法"):
        asyncio.run(parse_plan_with_one_repair("not-json", 7, repair))
    assert calls == 1


def test_image_generation_falls_back_from_nano_to_image2_once() -> None:
    calls: list[str] = []

    async def generate(provider_code: str) -> bytes:
        calls.append(provider_code)
        if provider_code == "yunwu-nano":
            raise RuntimeError("nano temporary failure")
        return b"image-bytes"

    result, provider_code = asyncio.run(
        run_image_with_fallback("yunwu-nano", "yunwu-image-2", generate)
    )

    assert result == b"image-bytes"
    assert provider_code == "yunwu-image-2"
    assert calls == ["yunwu-nano", "yunwu-image-2"]


def test_image_route_errors_use_current_provider_display_name() -> None:
    async def generate(provider_code: str) -> bytes:
        raise RuntimeError(f"Provider {provider_code} 不可用")

    display_names = {
        "yunwu-image-2": "HelloBabyGo GPT Image 2 / gpt-image-2 @ api.hellobabygo.com"
    }

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(run_image_route(["yunwu-image-2"], generate, display_names))

    message = str(exc_info.value)
    assert "HelloBabyGo GPT Image 2 / gpt-image-2 @ api.hellobabygo.com" in message
    assert "yunwu-image-2" not in message


def test_frontend_model_preference_routes_to_expected_hidden_providers() -> None:
    assert image_provider_route("fidelity") == ["yunwu-nano-pro", "yunwu-nano"]
    assert image_provider_route("layout") == ["yunwu-image-2"]


def test_safe_log_redacts_secrets_and_large_base64() -> None:
    encoded = base64.b64encode(b"x" * 500).decode()
    logged = safe_json(
        {
            "Authorization": "Bearer secret",
            "api_key": "secret",
            "image": encoded,
            "prompt": "safe",
        }
    )

    assert "Bearer secret" not in logged
    assert '"api_key": "[REDACTED]"' in logged
    assert encoded not in logged
    assert "[BASE64 668 chars]" in logged
    assert '"prompt": "safe"' in logged


def test_llm_response_format_can_be_disabled_for_markdown_prompts() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "### 1. 商品定位"}}]})

    client = ProviderClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    content = asyncio.run(
        client.call_llm(
            llm_provider(),
            "key",
            "system",
            "user",
            response_format=None,
        )
    )

    assert content == "### 1. 商品定位"
    assert "response_format" not in seen


def llm_provider() -> Provider:
    return Provider(
        code="gpt-5-4-mini",
        label="GPT‑5.4‑Mini",
        capability="llm",
        adapter="openai_chat",
        base_url="https://router.shengsuanyun.com/api/v1/chat/completions",
        model_name="openai/gpt-5.4-mini",
        enabled=True,
        is_default=True,
        is_fallback=False,
        config_json=json.dumps({"temperature": 0.2, "timeout_seconds": 90, "response_format": "json_object"}),
    )


def image2_provider() -> Provider:
    return Provider(
        code="yunwu-image-2",
        label="HelloBabyGo GPT Image 2",
        capability="image",
        adapter="hellobabygo_image_generation",
        base_url="https://api.hellobabygo.com/v1/images/generations",
        model_name="gpt-image-2",
        enabled=True,
        is_default=False,
        is_fallback=True,
        config_json=json.dumps({"size": "follow_ratio", "poll_interval_seconds": 0, "max_poll_attempts": 3}),
    )


def nano_provider() -> Provider:
    return Provider(
        code="yunwu-nano",
        label="HelloBabyGo Nano Banana 2",
        capability="image",
        adapter="hellobabygo_image_generation",
        base_url="https://api.hellobabygo.com/v1/images/generations",
        model_name="nano_banana_2",
        enabled=True,
        is_default=True,
        is_fallback=False,
        config_json=json.dumps({"resolution": "2K", "size": "auto", "poll_interval_seconds": 0, "max_poll_attempts": 3}),
    )


def test_nano_submits_hellobabygo_resolution_and_direction() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"task_id": "task-nano", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-nano"):
            seen["poll_url"] = str(request.url)
            return httpx.Response(200, json={"id": "task-nano", "status": "completed", "data": [{"url": "https://cdn.example.test/nano.png"}]})
        return httpx.Response(200, content=b"nano-image")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                nano_provider(), "key", "prompt", [], "16:9"
            )

    assert asyncio.run(run()) == b"nano-image"
    assert seen["url"] == "https://api.hellobabygo.com/v1/images/generations"
    assert seen["body"] == {"model": "nano_banana_2", "prompt": "prompt", "n": 1, "resolution": "2K", "size": "auto"}
    assert seen["poll_url"].endswith("/v1/images/task-nano")


def test_nano_4k_auto_size_maps_to_runtime_direction() -> None:
    provider = nano_provider()
    provider.config_json = json.dumps({"resolution": "4K", "size": "auto", "poll_interval_seconds": 0, "max_poll_attempts": 3})
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"task_id": "task-4k", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-4k"):
            return httpx.Response(200, json={"status": "completed", "data": [{"url": "https://cdn.example.test/4k.png"}]})
        return httpx.Response(200, content=b"4k")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider, "key", "prompt", [], "16:9"
            )

    assert asyncio.run(run()) == b"4k"
    assert seen["body"]["resolution"] == "4K"
    assert seen["body"]["size"] == "landscape"


def test_image2_generate_uses_json_without_reference_image() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["content_type"] = request.headers["content-type"]
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"id": "task-image2", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-image2"):
            return httpx.Response(200, json={"id": "task-image2", "status": "completed", "data": [{"url": "https://cdn.example.test/image2.png"}]})
        return httpx.Response(200, content=b"image")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                image2_provider(), "key", "prompt", [], "16:9"
            )

    assert asyncio.run(run()) == b"image"
    assert seen["url"].endswith("/v1/images/generations")
    assert seen["content_type"].startswith("application/json")
    assert seen["body"]["size"] == "1792x1024"
    assert "quality" not in seen["body"]
    assert "style" not in seen["body"]
    assert "response_format" not in seen["body"]
    assert "images" not in seen["body"]


def test_provider_invalid_json_response_reports_upstream_context() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"task_id":"task-bad" "status":"queued"}')

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                image2_provider(), "key", "prompt", [], "1:1"
            )

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(run())

    message = str(exc_info.value)
    assert "yunwu-image-2 上游返回无效 JSON（HTTP 200 OK）" in message
    assert "Expecting ',' delimiter" not in message


def test_image2_rejects_invalid_configured_size_before_submit() -> None:
    provider = image2_provider()
    provider.config_json = json.dumps({"size": "512x512"})

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider, "key", "prompt", [], "1:1"
            )

    with pytest.raises(RuntimeError, match="size=512x512 不合法"):
        asyncio.run(run())


def test_image2_follow_ratio_maps_to_documented_sizes() -> None:
    provider = image2_provider()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"task_id": "task-portrait", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-portrait"):
            return httpx.Response(200, json={"status": "completed", "data": [{"url": "https://cdn.example.test/portrait.png"}]})
        return httpx.Response(200, content=b"portrait")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider, "key", "prompt", [], "16:9"
            )

    assert asyncio.run(run()) == b"portrait"
    assert seen["body"]["size"] == "1792x1024"


def test_image2_with_reference_image_uses_public_urls(tmp_path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"fake-png")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["content_type"] = request.headers["content-type"]
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"task_id": "task-edit", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-edit"):
            return httpx.Response(200, json={"status": "completed", "data": [{"url": "https://cdn.example.test/edited.png"}]})
        return httpx.Response(200, content=b"edited")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                image2_provider(),
                "key",
                "prompt",
                [str(source)],
                "4:5",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"edited"
    assert seen["url"].endswith("/v1/images/generations")
    assert seen["content_type"].startswith("application/json")
    assert seen["body"]["images"] == ["https://assets.example.test/source.png"]


def test_image2_content_download_uses_api_key_for_hellobabygo_content_url() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-content", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-content"):
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "data": [{"url": "https://api.hellobabygo.com/v1/images/task-content/content"}],
                },
            )
        if str(request.url).endswith("/v1/images/task-content/content"):
            seen["download_authorization"] = request.headers.get("authorization")
            return httpx.Response(200, content=b"image-content")
        return httpx.Response(404)

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                image2_provider(), "sk-test", "prompt", [], "1:1"
            )

    assert asyncio.run(run()) == b"image-content"
    assert seen["download_authorization"] == "Bearer sk-test"


def test_image2_with_reference_image_requires_public_url(tmp_path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"fake-png")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as http_client:
            return await ProviderClient(http_client).generate_image(
                image2_provider(), "key", "prompt", [str(source)], "4:5"
            )

    with pytest.raises(RuntimeError, match="LISTINGO_PUBLIC_ASSET_BASE_URL"):
        asyncio.run(run())


def test_image2_failed_task_uses_error_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-failed", "status": "queued"})
        return httpx.Response(
            200,
            json={"task_id": "task-failed", "status": "failed", "error": {"message": "prompt rejected"}},
        )

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                image2_provider(), "key", "prompt", [], "1:1"
            )

    with pytest.raises(RuntimeError, match="prompt rejected"):
        asyncio.run(run())


def test_image2_generation_retries_http_429_once() -> None:
    post_calls = 0
    provider = image2_provider()
    provider.config_json = json.dumps({"size": "follow_ratio", "max_retries": 1, "poll_interval_seconds": 0, "max_poll_attempts": 3})

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.method == "POST":
            post_calls += 1
        if request.method == "POST" and post_calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "rate limit"}})
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-retry", "status": "queued"})
        if str(request.url).endswith("/v1/images/task-retry"):
            return httpx.Response(200, json={"status": "completed", "data": [{"url": "https://cdn.example.test/retry.png"}]})
        return httpx.Response(200, content=b"retried")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider, "key", "prompt", [], "4:5"
            )

    assert asyncio.run(run()) == b"retried"
    assert post_calls == 2


def test_image2_generation_reports_rate_limit_after_retries() -> None:
    post_calls = 0
    provider = image2_provider()
    provider.config_json = json.dumps({"size": "follow_ratio", "max_retries": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        post_calls += 1
        return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "rate limit"}})

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider, "key", "prompt", [], "4:5"
            )

    with pytest.raises(RuntimeError, match="HTTP 429 Too Many Requests"):
        asyncio.run(run())
    assert post_calls == 2


def test_live_http_client_forces_ipv4_on_windows() -> None:
    client = build_async_http_client(30)
    assert client._transport._pool._local_address == "0.0.0.0"  # type: ignore[attr-defined]
    asyncio.run(client.aclose())


def test_image2_has_an_explicit_size_route_for_every_core_prompt_ratio() -> None:
    assert set(IMAGE2_SIZE_MAP) == {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "970:600", "1464:600", "600:450"}
    assert IMAGE2_SIZE_MAP["2:3"] == "1024x1792"
    assert IMAGE2_SIZE_MAP["21:9"] == "1792x1024"
    assert IMAGE2_SIZE_MAP["970:600"] == "1792x1024"
    assert IMAGE2_SIZE_MAP["1464:600"] == "1792x1024"
    assert IMAGE2_SIZE_MAP["600:450"] == "1792x1024"


def png_bytes(size: tuple[int, int] = (640, 640)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "#f5f1ea").save(buffer, format="PNG")
    return buffer.getvalue()


class GeneratedImageProviderClient:
    def __init__(self, size: tuple[int, int] = (640, 640)) -> None:
        self.size = size

    async def generate_image(self, *_args, **_kwargs) -> bytes:
        return png_bytes(self.size)

    async def call_llm(self, *_args, **_kwargs) -> str:
        return json.dumps({"schema_version": "1.0", "passed": True, "categories": [], "issues": []})


class BlockedSafetyProviderClient(GeneratedImageProviderClient):
    async def call_llm(self, *_args, **_kwargs) -> str:
        return json.dumps(
            {
                "schema_version": "1.0",
                "passed": False,
                "categories": ["politics"],
                "issues": ["出现政治领导人"],
            }
        )


class InvalidImageProviderClient:
    async def generate_image(self, *_args, **_kwargs) -> bytes:
        return b"not-an-image"

    async def call_llm(self, *_args, **_kwargs) -> str:
        raise AssertionError("image QA LLM should not be called")


def add_provider(session, cipher, code: str, capability: str, *, default: bool = False, fallback: bool = False) -> Provider:
    provider = session.scalar(select(Provider).where(Provider.code == code))
    if not provider:
        provider = Provider(
            code=code,
            label=code,
            capability=capability,
            adapter="test",
            base_url="https://example.test",
            model_name="test-model",
            config_json="{}",
        )
        session.add(provider)
    provider.enabled = True
    provider.is_default = default
    provider.is_fallback = fallback
    provider.encrypted_api_key = cipher.encrypt("test-key")
    return provider


def add_prompt_version(session, code: str, content: str = "prompt") -> PromptVersion:
    prompt = session.scalar(select(Prompt).where(Prompt.code == code))
    if not prompt:
        prompt = Prompt(code=code, name=code, description="")
        session.add(prompt)
        session.flush()
    version = PromptVersion(prompt_id=prompt.id, version_no=99, content=content, content_sha256=f"test-{code}")
    session.add(version)
    session.flush()
    prompt.active_version_id = version.id
    return version


@pytest.mark.parametrize("image_size, aspect_ratio", [((640, 640), "1:1"), ((640, 480), "1:1")])
def test_live_item_saves_any_valid_generated_image_without_review_gate(client, image_size, aspect_ratio) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    cipher = client.app.state.cipher
    with session_factory() as session:
        add_provider(session, cipher, "yunwu-nano-pro", "image")
        add_provider(session, cipher, "gpt-default", "llm", default=True)
        add_provider(session, cipher, "gpt-fallback", "llm", fallback=True)
        meta_prompt = add_prompt_version(session, "ecommerce-meta")
        safety_prompt = add_prompt_version(session, "content-safety-review")
        workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
        workflow_version_id = workflow.active_version_id
        job = GenerationJob(
            status="running",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=meta_prompt.id,
            workflow_version_id=workflow_version_id,
        )
        session.add(job)
        session.flush()
        item = GenerationItem(
            job_id=job.id,
            index=0,
            route_symbol="#@",
            image_type="单卖点证明图",
            prompt_text=json.dumps(
                {
                    "route_symbol": "#@",
                    "image_type": "单卖点证明图",
                    "picture_requirement": "1:1 商品图，保持产品外观不变。",
                    "copywriting_requirements": "中文标题",
                },
                ensure_ascii=False,
            ),
            status="queued",
        )
        session.add(item)
        session.commit()
        item_id = item.id
        job_id = job.id

    asyncio.run(
        _run_live_item(
            item_id,
            session_factory,
            settings,
            cipher,
            GeneratedImageProviderClient(image_size),
            ["yunwu-nano-pro"],
            [],
            aspect_ratio,
            {
                "platform": "京东",
                "language": "中文",
                "aspect_ratio": aspect_ratio,
                "_prompt_versions": {"content-safety-review": safety_prompt.id},
            },
        )
    )

    with session_factory() as session:
        item = session.get(GenerationItem, item_id)
        job = session.get(GenerationJob, job_id)
        assert item.status == "succeeded"
        assert item.current_version_id is not None
        assert item.error is None
        assert len(item.versions) == 1
        version = item.versions[0]
        assert version.url.startswith("/files/results/")
        assert Path(version.file_path).exists()
        metadata = json.loads(version.metadata_json)
        assert metadata == {"dry_run": False, "provider": "yunwu-nano-pro", "actual_size": list(image_size)}
        serialized = serialize_job(job)
        assert "qa_status" not in serialized["items"][0]
        assert "qa_issues" not in serialized["items"][0]
        assert serialized["items"][0]["status"] == "succeeded"


def test_live_item_blocks_generated_image_when_content_safety_fails(client) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    cipher = client.app.state.cipher
    before_files = set(settings.results_dir.glob("*.png"))
    with session_factory() as session:
        add_provider(session, cipher, "yunwu-nano-pro", "image")
        add_provider(session, cipher, "gpt-default", "llm", default=True)
        add_provider(session, cipher, "gpt-fallback", "llm", fallback=True)
        meta_prompt = add_prompt_version(session, "ecommerce-meta")
        safety_prompt = add_prompt_version(session, "content-safety-review")
        workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
        job = GenerationJob(
            status="running",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=meta_prompt.id,
            workflow_version_id=workflow.active_version_id,
        )
        session.add(job)
        session.flush()
        item = GenerationItem(
            job_id=job.id,
            index=0,
            route_symbol="#@",
            image_type="单卖点证明图",
            prompt_text=json.dumps(
                {
                    "route_symbol": "#@",
                    "image_type": "单卖点证明图",
                    "picture_requirement": "1:1 商品图，保持产品外观不变。",
                    "copywriting_requirements": "中文标题",
                },
                ensure_ascii=False,
            ),
            status="queued",
        )
        session.add(item)
        session.commit()
        item_id = item.id

    asyncio.run(
        _run_live_item(
            item_id,
            session_factory,
            settings,
            cipher,
            BlockedSafetyProviderClient(),
            ["yunwu-nano-pro"],
            [],
            "1:1",
            {
                "platform": "京东",
                "language": "中文",
                "aspect_ratio": "1:1",
                "_prompt_versions": {"content-safety-review": safety_prompt.id},
            },
        )
    )

    with session_factory() as session:
        item = session.get(GenerationItem, item_id)
        assert item.status == "failed"
        assert item.current_version_id is None
        assert item.versions == []
        assert "内容安全拦截" in item.error
    assert set(settings.results_dir.glob("*.png")) == before_files


def test_live_item_rejects_invalid_image_bytes_without_version(client) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    cipher = client.app.state.cipher
    with session_factory() as session:
        add_provider(session, cipher, "yunwu-nano-pro", "image")
        meta_prompt = add_prompt_version(session, "ecommerce-meta")
        workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
        job = GenerationJob(
            status="running",
            dry_run=False,
            params_json="{}",
            asset_ids_json="[]",
            count=1,
            prompt_version_id=meta_prompt.id,
            workflow_version_id=workflow.active_version_id,
        )
        session.add(job)
        session.flush()
        item = GenerationItem(
            job_id=job.id,
            index=0,
            route_symbol="#@",
            image_type="单卖点证明图",
            prompt_text=json.dumps(
                {
                    "route_symbol": "#@",
                    "image_type": "单卖点证明图",
                    "picture_requirement": "1:1 商品图，保持产品外观不变。",
                    "copywriting_requirements": "中文标题",
                },
                ensure_ascii=False,
            ),
            status="queued",
        )
        session.add(item)
        session.commit()
        item_id = item.id

    asyncio.run(
        _run_live_item(
            item_id,
            session_factory,
            settings,
            cipher,
            InvalidImageProviderClient(),
            ["yunwu-nano-pro"],
            [],
            "1:1",
            {"platform": "京东", "language": "中文", "aspect_ratio": "1:1"},
        )
    )

    with session_factory() as session:
        item = session.get(GenerationItem, item_id)
        assert item.status == "failed"
        assert item.current_version_id is None
        assert item.versions == []
        assert item.error
