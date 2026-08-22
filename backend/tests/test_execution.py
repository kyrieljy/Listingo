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

from backend.app.config import Settings
from backend.app.models import (
    AplusItem,
    AplusJob,
    Asset,
    GenerationItem,
    GenerationJob,
    GenerationVersion,
    Prompt,
    PromptVersion,
    Provider,
    Workflow,
)
from backend.app.schemas import ImageTextEditLine
from backend.app.services.execution import parse_plan_with_one_repair, run_image_route
from backend.app.services import aplus_jobs, image_text_edit
from backend.app.services import jobs as jobs_service
from backend.app.services.jobs import _run_live_item, image_provider_route
from backend.app.services.providers import (
    IMAGE2_SIZE_MAP,
    ProviderClient,
    _provider_request_image_size_for_config,
    append_requested_size_to_prompt,
    build_async_http_client,
)
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
    assert image_provider_route("fidelity") == [
        "apimodels-nano-pro-generate",
        "kie-nano-2-generate",
        "atlas-nano-2-generate",
        "apimodels-nano-2-generate",
        "runware-nano-2-generate",
    ]
    assert image_provider_route("layout") == [
        "atlas-gpt-image-2-generate",
        "cometapi-gpt-image-2-generate",
        "runware-gpt-image-2-generate",
        "fal-gpt-image-2-generate",
        "openrouter-gpt-image-2-generate",
    ]


def test_image_text_ocr_lines_are_sorted_and_prompt_is_rendered(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "source.png"
    Image.new("RGB", (200, 200), "#ffffff").save(image_path)

    class StubOcr:
        def __call__(self, _: str):
            return [
                ([[60, 80], [160, 80], [160, 110], [60, 110]], "Second", 0.81),
                ([[20, 20], [120, 20], [120, 48], [20, 48]], "First", 0.95),
            ]

    monkeypatch.setattr(image_text_edit, "_load_ocr_engine", lambda _settings=None: StubOcr())
    monkeypatch.setattr(image_text_edit, "_prepare_ocr_variants", lambda path, _settings=None: [(str(path), 1.0, False)])

    result = image_text_edit.detect_text_lines_with_status(image_path)
    lines = result.lines
    assert [line.text for line in lines] == ["First", "Second"]
    assert lines[0].bbox.x == 20

    replacements = [
        ImageTextEditLine(index=0, original_text="First", text="Updated", bbox=lines[0].bbox),
        ImageTextEditLine(index=1, original_text="Second", text="Second", bbox=lines[1].bbox),
    ]
    table = image_text_edit.build_replacements_table(replacements)
    prompt = image_text_edit.render_text_edit_prompt("Replace:\n{{REPLACEMENTS_TABLE}}", replacements)
    assert 'original="First", new="Updated"' in table
    assert 'original="Second"' not in table
    assert "Replace:" in prompt and "Updated" in prompt


def test_paddleocr_rows_are_normalized_and_english_noise_is_filtered(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "source.png"
    Image.new("RGB", (300, 220), "#ffffff").save(image_path)

    class PaddleStub:
        def predict(self, _: str):
            return [
                {
                    "res": {
                        "rec_texts": ["Closure:", "哥", "Zipper & Buckle", "回"],
                        "rec_scores": [0.97, 0.99, 0.96, 0.99],
                        "rec_polys": [
                            [[20, 20], [130, 20], [130, 48], [20, 48]],
                            [[20, 62], [48, 62], [48, 92], [20, 92]],
                            [[20, 108], [190, 108], [190, 136], [20, 136]],
                            [[20, 150], [48, 150], [48, 180], [20, 180]],
                        ],
                    }
                }
            ]

    engine = image_text_edit.FallbackOcrEngine(
        [image_text_edit.OcrRunner("PaddleOCR", "PP-OCRv6", PaddleStub(), uses_predict=True)]
    )
    monkeypatch.setattr(image_text_edit, "_load_ocr_engine", lambda _settings=None: engine)
    monkeypatch.setattr(image_text_edit, "_prepare_ocr_variants", lambda path, _settings=None: [(str(path), 1.0, False)])

    result = image_text_edit.detect_text_lines_with_status(
        image_path,
        Settings(testing=True, ocr_engine="paddleocr"),
        language_hint="英文",
    )

    assert [line.text for line in result.lines] == ["Closure:", "Zipper & Buckle"]


def test_paddleocr_runtime_falls_back_from_v6_to_v5(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "source.png"
    Image.new("RGB", (300, 220), "#ffffff").save(image_path)
    calls: list[str] = []

    class PaddleStub:
        def __init__(self, model: str) -> None:
            self.model = model

        def predict(self, _: str):
            calls.append(self.model)
            if self.model == "PP-OCRv6":
                raise RuntimeError("temporary model failure")
            return [
                {
                    "res": {
                        "rec_texts": ["Closure:"],
                        "rec_scores": [0.97],
                        "rec_polys": [[[20, 20], [130, 20], [130, 48], [20, 48]]],
                    }
                }
            ]

    def create_runner(model: str, _settings: Settings):
        return image_text_edit.OcrRunner("PaddleOCR", model, PaddleStub(model), uses_predict=True)

    class RapidStub:
        def __call__(self, _: str):
            raise AssertionError("RapidOCR should not be used")

    monkeypatch.setattr(image_text_edit, "_OCR_RUNNER_CACHE", {})
    monkeypatch.setattr(image_text_edit, "_create_paddleocr_runner", create_runner)
    monkeypatch.setattr(
        image_text_edit,
        "_create_rapidocr_runner",
        lambda _settings: image_text_edit.OcrRunner("RapidOCR", "test", RapidStub()),
    )
    monkeypatch.setattr(image_text_edit, "_prepare_ocr_variants", lambda path, _settings=None: [(str(path), 1.0, False)])

    result = image_text_edit.detect_text_lines_with_status(
        image_path,
        Settings(testing=True, ocr_engine="paddleocr", ocr_primary_model="PP-OCRv6", ocr_fallback_model="PP-OCRv5"),
        language_hint="英文",
    )

    assert [line.text for line in result.lines] == ["Closure:"]
    assert calls == ["PP-OCRv6", "PP-OCRv5"]
    assert result.warning and "PP-OCRv6 OCR failed" in result.warning
    assert "using PaddleOCR PP-OCRv5" in result.warning


def test_paddleocr_primary_success_does_not_initialize_fallback(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "source.png"
    Image.new("RGB", (300, 220), "#ffffff").save(image_path)
    created_models: list[str] = []

    class PaddleStub:
        def __init__(self, model: str) -> None:
            self.model = model

        def predict(self, _: str):
            return [
                {
                    "res": {
                        "rec_texts": ["Closure:"],
                        "rec_scores": [0.97],
                        "rec_polys": [[[20, 20], [130, 20], [130, 48], [20, 48]]],
                    }
                }
            ]

    def create_runner(model: str, _settings: Settings):
        created_models.append(model)
        return image_text_edit.OcrRunner("PaddleOCR", model, PaddleStub(model), uses_predict=True)

    monkeypatch.setattr(image_text_edit, "_OCR_RUNNER_CACHE", {})
    monkeypatch.setattr(image_text_edit, "_create_paddleocr_runner", create_runner)
    monkeypatch.setattr(
        image_text_edit,
        "_create_rapidocr_runner",
        lambda _settings: (_ for _ in ()).throw(AssertionError("RapidOCR should not be initialized")),
    )
    monkeypatch.setattr(image_text_edit, "_prepare_ocr_variants", lambda path, _settings=None: [(str(path), 1.0, False)])

    result = image_text_edit.detect_text_lines_with_status(
        image_path,
        Settings(testing=True, ocr_engine="paddleocr", ocr_primary_model="PP-OCRv6", ocr_fallback_model="PP-OCRv5"),
        language_hint="English",
    )

    assert [line.text for line in result.lines] == ["Closure:"]
    assert created_models == ["PP-OCRv6"]


def test_ocr_enhanced_variants_are_opt_in(tmp_path) -> None:
    image_path = tmp_path / "source.png"
    Image.new("RGB", (300, 220), "#ffffff").save(image_path)

    assert image_text_edit._prepare_ocr_variants(image_path, Settings(testing=True)) == [(str(image_path), 1.0, False)]

    variants = image_text_edit._prepare_ocr_variants(
        image_path,
        Settings(testing=True, ocr_use_enhanced_variants=True),
    )
    try:
        assert len(variants) == 2
        assert variants[0] == (str(image_path), 1.0, False)
        assert variants[1][2] is True
    finally:
        for variant_path, _, is_temp in variants:
            if is_temp:
                Path(variant_path).unlink(missing_ok=True)


def test_image_text_edit_rejects_unchanged_lines() -> None:
    with pytest.raises(ValueError, match="No text changes"):
        image_text_edit.changed_text_lines([
            ImageTextEditLine(index=0, original_text="Same", text="Same"),
        ])


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


def test_apimodels_health_check_uses_free_balance_endpoint() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"balance": 1})

    provider = Provider(
        code="apimodels-gpt-image-2-generate",
        label="API Models GPT Image 2",
        capability="image",
        adapter="media_image",
        base_url="https://apimodels.app/api/v1/images/generations",
        model_name="gpt-image-2",
        enabled=True,
        is_default=False,
        is_fallback=False,
        config_json=json.dumps({"provider_group": "apimodels", "timeout_seconds": 60}),
    )
    client = ProviderClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = asyncio.run(client.health_check(provider, "apimodels-secret"))

    assert result["ok"] is True
    assert seen == {
        "url": "https://apimodels.app/api/v1/balance",
        "authorization": "Bearer apimodels-secret",
    }


def test_openrouter_image_health_check_uses_image_models_endpoint() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": []})

    provider = Provider(
        code="openrouter-gpt-image-2-generate",
        label="OpenRouter GPT Image 2",
        capability="image",
        adapter="media_image",
        base_url="https://openrouter.ai/api/v1/images",
        model_name="openai/gpt-image-2",
        enabled=True,
        is_default=False,
        is_fallback=False,
        config_json=json.dumps({"provider_group": "openrouter", "timeout_seconds": 60}),
    )
    client = ProviderClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = asyncio.run(client.health_check(provider, "openrouter-secret"))

    assert result["ok"] is True
    assert seen == {
        "url": "https://openrouter.ai/api/v1/images/models",
        "authorization": "Bearer openrouter-secret",
    }


def test_runware_health_check_uses_runware_api_key_header() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization")
        seen["runware_api_key"] = request.headers.get("Runware-API-Key")
        return httpx.Response(200, json={"data": []})

    provider = Provider(
        code="runware-gpt-image-2-generate",
        label="Runware GPT Image 2",
        capability="image",
        adapter="media_image",
        base_url="https://api.runware.ai/v1",
        model_name="openai:gpt-image@2",
        enabled=True,
        is_default=False,
        is_fallback=False,
        config_json=json.dumps({"provider_group": "runware", "timeout_seconds": 60, "health_check": {"url": "https://api.runware.ai/v1/models"}}),
    )
    client = ProviderClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = asyncio.run(client.health_check(provider, "runware-secret"))

    assert result["ok"] is True
    assert seen == {
        "authorization": "Bearer runware-secret",
        "runware_api_key": "runware-secret",
    }


def test_apimodels_media_task_poll_uses_query_parameter() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["post_url"] = str(request.url)
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "task 123", "state": "processing"}})
        if request.method == "GET" and "task_id=task%20123" in str(request.url):
            seen["poll_url"] = str(request.url)
            return httpx.Response(200, json={"code": 200, "data": {"state": "completed", "resultUrls": ["https://cdn.example.test/apimodels.png"]}})
        seen["download_url"] = str(request.url)
        return httpx.Response(200, content=b"apimodels")

    provider = media_image_provider(
        "apimodels-gpt-image-2-generate",
        "apimodels",
        "gpt-image-2",
        {
            "model_name": "gpt-image-2",
            "size_param_mode": "aspect_ratio_resolution",
            "resolution": "2K",
        },
    )
    provider.base_url = "https://apimodels.app/api/v1/images/generations"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source-1.png")), str(Path("source-2.png"))],
                "1:1",
                input_urls=["https://assets.example.test/source-1.png", "https://assets.example.test/source-2.png"],
            )

    assert asyncio.run(run()) == b"apimodels"
    assert seen["post_url"] == "https://apimodels.app/api/v1/images/generations"
    assert seen["poll_url"] == "https://apimodels.app/api/v1/images/generations?task_id=task%20123"
    assert seen["body"]["model"] == "gpt-image-2"
    assert seen["body"]["image_urls"] == ["https://assets.example.test/source-1.png", "https://assets.example.test/source-2.png"]
    assert seen["body"]["aspect_ratio"] == "1:1"
    assert seen["body"]["resolution"] == "2K"
    assert "image" not in seen["body"]
    assert "images" not in seen["body"]
    assert "image_url" not in seen["body"]
    assert "size" not in seen["body"]
    assert "quality" not in seen["body"]
    assert "format" not in seen["body"]


def test_atlas_media_task_poll_uses_prediction_endpoint() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["post_authorization"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": {"id": "pred_abc", "status": "processing"}})
        if request.method == "GET" and str(request.url).endswith("/api/v1/model/prediction/pred_abc"):
            seen["poll_url"] = str(request.url)
            seen["poll_authorization"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"data": {"status": "completed", "outputs": ["https://cdn.example.test/atlas.png"]}})
        return httpx.Response(200, content=b"atlas")

    provider = media_image_provider(
        "atlas-gpt-image-2-generate",
        "atlas",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2/text-to-image",
            "size_param_mode": "size_string",
        },
    )
    provider.base_url = "https://api.atlascloud.ai/api/v1/model/generateImage"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(provider, "Bearer key", "prompt", [], "16:9")

    assert asyncio.run(run()) == b"atlas"
    assert seen["body"]["model"] == "openai/gpt-image-2/text-to-image"
    assert seen["poll_url"] == "https://api.atlascloud.ai/api/v1/model/prediction/pred_abc"
    assert seen["post_authorization"] == "Bearer key"
    assert seen["poll_authorization"] == "Bearer key"


def test_existing_media_task_auth_failure_submits_fresh_task() -> None:
    seen: dict[str, Any] = {"submitted": []}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "GET" and url.endswith("/api/v1/model/prediction/pred_stale"):
            seen["stale_poll_url"] = url
            return httpx.Response(401, json={"message": "Unauthorized"})
        if request.method == "POST":
            seen["post_count"] = seen.get("post_count", 0) + 1
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": {"id": "pred_fresh", "status": "processing"}})
        if request.method == "GET" and url.endswith("/api/v1/model/prediction/pred_fresh"):
            seen["fresh_poll_url"] = url
            return httpx.Response(200, json={"data": {"status": "completed", "outputs": ["https://cdn.example.test/atlas-fresh.png"]}})
        if request.method == "GET" and url == "https://cdn.example.test/atlas-fresh.png":
            return httpx.Response(200, content=b"atlas-fresh")
        return httpx.Response(500, json={"error": f"unexpected request {request.method} {url}"})

    provider = media_image_provider(
        "atlas-gpt-image-2-generate",
        "atlas",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2/text-to-image",
            "size_param_mode": "size_string",
        },
    )
    provider.base_url = "https://api.atlascloud.ai/api/v1/model/generateImage"

    async def remember_task_id(task_id: str) -> None:
        seen["submitted"].append(task_id)

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [],
                "16:9",
                existing_task_id="pred_stale",
                on_task_submitted=remember_task_id,
            )

    assert asyncio.run(run()) == b"atlas-fresh"
    assert seen["stale_poll_url"] == "https://api.atlascloud.ai/api/v1/model/prediction/pred_stale"
    assert seen["post_count"] == 1
    assert seen["fresh_poll_url"] == "https://api.atlascloud.ai/api/v1/model/prediction/pred_fresh"
    assert seen["submitted"] == ["pred_fresh"]


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


def media_image_provider(code: str, group: str, model_family: str, config: dict[str, Any]) -> Provider:
    return Provider(
        code=code,
        label=code,
        capability="image",
        adapter="media_image",
        base_url="https://api.example.test/v1/images/generations",
        model_name=config.pop("model_name", "gpt-image-2"),
        enabled=True,
        is_default=True,
        is_fallback=False,
        config_json=json.dumps(
            {
                "provider_group": group,
                "operation": config.pop("operation", "generate"),
                "model_family": model_family,
                "size_param_mode": config.pop("size_param_mode", "size_string"),
                "preflight_before_call": False,
                "poll_interval_seconds": 0,
                "max_poll_attempts": 3,
                **config,
            }
        ),
    )


def media_video_provider(code: str, group: str, config: dict[str, Any]) -> Provider:
    return Provider(
        code=code,
        label=code,
        capability="video",
        adapter="media_video",
        base_url="https://api.example.test/v1/videos",
        model_name=config.pop("model_name", "bytedance/seedance-2.0"),
        enabled=True,
        is_default=True,
        is_fallback=False,
        config_json=json.dumps(
            {
                "provider_group": group,
                "operation": "video",
                "model_family": "seedance-2.0",
                "preflight_before_call": False,
                **config,
            }
        ),
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
    assert seen["body"]["model"] == "nano_banana_2"
    assert seen["body"]["prompt"].startswith("prompt\n\n")
    assert "1536x864" in seen["body"]["prompt"]
    assert "16:9" in seen["body"]["prompt"]
    assert seen["body"]["n"] == 1
    assert seen["body"]["resolution"] == "2K"
    assert seen["body"]["size"] == "auto"
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


def test_media_image_payload_uses_runware_provider_parameters() -> None:
    provider = media_image_provider(
        "runware-gpt-image-2-generate",
        "runware",
        "gpt-image-2",
        {
            "model_name": "openai:gpt-image@2",
            "size_param_mode": "width_height",
            "size": "follow_frontend",
            "format": "jpeg",
            "quality": "high",
            "numberResults": 3,
            "outputQuality": 91,
            "includeCost": True,
            "checkNSFW": True,
            "seed": 1234,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/runware.png"}]})
        return httpx.Response(200, content=b"runware")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "970:600",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"runware"
    task = seen["body"][0]
    assert task["width"] == 1040
    assert task["height"] == 640
    assert task["numberResults"] == 3
    assert task["outputFormat"] == "JPEG"
    assert task["outputQuality"] == 91
    assert task["includeCost"] is True
    assert task["checkNSFW"] is True
    assert task["seed"] == 1234
    assert task["providerSettings"]["openai"]["quality"] == "high"
    assert task["referenceImages"] == ["https://assets.example.test/source.png"]
    assert "1040x640" in task["positivePrompt"]
    assert "970x600" not in task["positivePrompt"]


def test_media_image_payload_uses_atlas_dynamic_parameters() -> None:
    provider = media_image_provider(
        "atlas-gpt-image-2-generate",
        "atlas",
        "gpt-image-2",
        {
            "size": "970x600",
            "quality": "high",
            "format": "webp",
            "n": 2,
            "output_compression": 88,
            "enable_sync_mode": True,
            "enable_base64_output": True,
            "seed": 99,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/atlas.webp"}]})
        return httpx.Response(200, content=b"atlas")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [],
                "1:1",
            )

    assert asyncio.run(run()) == b"atlas"
    assert seen["body"]["size"] == "1040x640"
    assert seen["body"]["aspect_ratio"] == "1:1"
    assert seen["body"]["quality"] == "high"
    assert seen["body"]["format"] == "webp"
    assert seen["body"]["output_format"] == "webp"
    assert seen["body"]["n"] == 2
    assert seen["body"]["output_compression"] == 88
    assert seen["body"]["enable_sync_mode"] is True
    assert seen["body"]["enable_base64_output"] is True
    assert seen["body"]["seed"] == 99


def test_atlas_media_image_prefers_base64_result_over_archived_url() -> None:
    provider = media_image_provider(
        "atlas-gpt-image-2-edit",
        "atlas",
        "gpt-image-2",
        {
            "operation": "edit",
            "model_name": "openai/gpt-image-2/edit",
            "size_param_mode": "size_string",
            "supports_edit": True,
            "enable_sync_mode": True,
            "enable_base64_output": True,
        },
    )
    provider.base_url = "https://api.atlascloud.ai/api/v1/model/generateImage"
    encoded = base64.b64encode(b"atlas-base64-result").decode()
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "completed",
                        "outputs": [
                            f"data:image/png;base64,{encoded}",
                            "https://cdn.example.test/archived.png",
                        ],
                    }
                },
            )
        raise AssertionError(f"unexpected result download: {request.method} {request.url}")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).edit_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "1464:600",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"atlas-base64-result"
    assert seen["body"]["enable_base64_output"] is True


def test_media_image_payload_aligns_custom_size_for_provider_constraints() -> None:
    provider = media_image_provider(
        "atlas-gpt-image-2-generate",
        "atlas",
        "gpt-image-2",
        {
            "size_param_mode": "size_string",
            "size_alignment": 16,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/atlas.png"}]})
        return httpx.Response(200, content=b"atlas")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(provider, "key", "prompt", [], "1464:600")

    assert asyncio.run(run()) == b"atlas"
    assert seen["body"]["size"] == "1472x608"
    assert "1472x608" in seen["body"]["prompt"]
    assert "1464x600" not in seen["body"]["prompt"]


def test_provider_client_keeps_aligned_provider_output_size() -> None:
    provider = media_image_provider(
        "atlas-gpt-image-2-generate",
        "atlas",
        "gpt-image-2",
        {
            "size_param_mode": "size_string",
            "size_alignment": 16,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/atlas.png"}]})
        return httpx.Response(200, content=png_bytes((1472, 608)))

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(provider, "key", "prompt", [], "1464:600")

    result = asyncio.run(run())
    with Image.open(BytesIO(result)) as image:
        assert image.size == (1472, 608)
    assert seen["body"]["size"] == "1472x608"


def test_openrouter_image_reference_payload_uses_documented_objects() -> None:
    provider = media_image_provider(
        "openrouter-gpt-image-2-generate",
        "openrouter",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2",
            "size_param_mode": "size_string",
            "quality": "medium",
        },
    )
    provider.base_url = "https://openrouter.ai/api/v1/images"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/openrouter.png"}]})
        return httpx.Response(200, content=b"openrouter")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "970:600",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"openrouter"
    assert seen["body"]["input_references"] == [
        {"type": "image_url", "image_url": {"url": "https://assets.example.test/source.png"}}
    ]
    assert seen["body"]["size"] == "1040x640"
    assert "1040x640" in seen["body"]["prompt"]
    assert "970x600" not in seen["body"]["prompt"]


def test_atlas_generate_with_reference_switches_to_edit_model() -> None:
    provider = media_image_provider(
        "atlas-gpt-image-2-generate",
        "atlas",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2/text-to-image",
            "size_param_mode": "size_string",
            "quality": "medium",
            "edit_model_name": "openai/gpt-image-2/edit",
        },
    )
    provider.base_url = "https://api.atlascloud.ai/api/v1/model/generateImage"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/atlas-edit.png"}]})
        return httpx.Response(200, content=b"atlas-edit")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "16:9",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"atlas-edit"
    assert seen["body"]["model"] == "openai/gpt-image-2/edit"
    assert seen["body"]["images"] == ["https://assets.example.test/source.png"]
    assert seen["body"]["size"] == "1536x864"
    assert "aspect_ratio" not in seen["body"]
    assert "image" not in seen["body"]


def test_atlas_gpt_image2_edit_uses_aligned_mobile_canvas() -> None:
    provider = media_image_provider(
        "atlas-gpt-image-2-edit",
        "atlas",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2/edit",
            "operation": "edit",
            "size_param_mode": "size_string",
            "supports_edit": True,
            "quality": "medium",
        },
    )
    provider.base_url = "https://api.atlascloud.ai/api/v1/model/generateImage"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/atlas-mobile.png"}]})
        return httpx.Response(200, content=b"atlas-mobile")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).edit_image(
                provider,
                "key",
                "prompt",
                [str(Path("web.png"))],
                "600:450",
                input_urls=["https://assets.example.test/web.png"],
            )

    assert asyncio.run(run()) == b"atlas-mobile"
    assert seen["body"]["model"] == "openai/gpt-image-2/edit"
    assert seen["body"]["images"] == ["https://assets.example.test/web.png"]
    assert seen["body"]["size"] == "944x704"
    assert "944x704" in seen["body"]["prompt"]
    assert "600x450" not in seen["body"]["prompt"]
    assert "aspect_ratio" not in seen["body"]


def test_atlas_nano_reference_uses_edit_model_and_lowercase_resolution() -> None:
    provider = media_image_provider(
        "atlas-nano-2-generate",
        "atlas",
        "nano-banana-2",
        {
            "model_name": "google/nano-banana-2/text-to-image",
            "size_param_mode": "aspect_ratio_resolution",
            "resolution": "2K",
            "edit_model_name": "google/nano-banana-2/edit",
        },
    )
    provider.base_url = "https://api.atlascloud.ai/api/v1/model/generateImage"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/atlas-nano.png"}]})
        return httpx.Response(200, content=b"atlas-nano")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "9:16",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"atlas-nano"
    assert seen["body"]["model"] == "google/nano-banana-2/edit"
    assert seen["body"]["images"] == ["https://assets.example.test/source.png"]
    assert seen["body"]["aspect_ratio"] == "9:16"
    assert seen["body"]["resolution"] == "2k"


def test_kie_gpt_image2_reference_switches_to_image_to_image_model() -> None:
    provider = media_image_provider(
        "kie-gpt-image-2-generate",
        "kie",
        "gpt-image-2",
        {
            "model_name": "gpt-image-2-text-to-image",
            "size_param_mode": "aspect_ratio",
            "edit_model_name": "gpt-image-2-image-to-image",
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": {"url": "https://cdn.example.test/kie-gpt.png"}})
        return httpx.Response(200, content=b"kie-gpt")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "4:5",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"kie-gpt"
    assert seen["body"]["model"] == "gpt-image-2-image-to-image"
    assert seen["body"]["input"]["input_urls"] == ["https://assets.example.test/source.png"]
    assert "image_input" not in seen["body"]["input"]


def test_kie_nano_reference_uses_image_input_field() -> None:
    provider = media_image_provider(
        "kie-nano-2-generate",
        "kie",
        "nano-banana-2",
        {
            "model_name": "nano-banana-2",
            "size_param_mode": "aspect_ratio_resolution",
            "resolution": "1K",
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": {"url": "https://cdn.example.test/kie-nano.png"}})
        return httpx.Response(200, content=b"kie-nano")

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "1:1",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"kie-nano"
    assert seen["body"]["model"] == "nano-banana-2"
    assert seen["body"]["input"]["image_input"] == ["https://assets.example.test/source.png"]
    assert "input_urls" not in seen["body"]["input"]


def test_replicate_image_reference_fields_match_model_family() -> None:
    gpt_provider = media_image_provider(
        "replicate-gpt-image-2-generate",
        "replicate",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2",
            "size_param_mode": "aspect_ratio",
            "quality": "medium",
        },
    )
    nano_provider = media_image_provider(
        "replicate-nano-2-generate",
        "replicate",
        "nano-banana-2",
        {
            "model_name": "google/nano-banana-2",
            "size_param_mode": "aspect_ratio_resolution",
            "resolution": "1K",
        },
    )
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"output": ["https://cdn.example.test/replicate.png"]})
        return httpx.Response(200, content=b"replicate")

    async def run(provider: Provider) -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "1:1",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run(gpt_provider)) == b"replicate"
    assert asyncio.run(run(nano_provider)) == b"replicate"
    assert seen[0]["input"]["input_images"] == ["https://assets.example.test/source.png"]
    assert "image_input" not in seen[0]["input"]
    assert seen[1]["input"]["image_input"] == ["https://assets.example.test/source.png"]
    assert "input_images" not in seen[1]["input"]


def test_media_video_payload_uses_openrouter_dynamic_parameters() -> None:
    provider = media_video_provider(
        "openrouter-seedance-2-0-video",
        "openrouter",
        {
            "size": "1536x864",
            "aspect_ratio": "16:9",
            "duration": "10",
            "resolution": "720p",
            "generate_audio": True,
            "seed": 42,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "video-task", "status": "queued"})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).submit_video_task(
                provider,
                "key",
                "video prompt",
                ["https://assets.example.test/source.png"],
                aspect_ratio="9:16",
                duration=15,
                resolution="1080p",
                generate_audio=False,
            )

    assert asyncio.run(run())["id"] == "video-task"
    assert seen["body"]["aspect_ratio"] == "16:9"
    assert seen["body"]["duration"] == 10
    assert seen["body"]["resolution"] == "720p"
    assert seen["body"]["size"] == "1536x864"
    assert seen["body"]["generate_audio"] is True
    assert seen["body"]["seed"] == 42
    assert seen["body"]["frame_images"] == [{"frame_type": "first_frame", "url": "https://assets.example.test/source.png"}]
    assert seen["body"]["input_references"] == [{"type": "image", "url": "https://assets.example.test/source.png"}]


def test_media_video_payload_uses_runware_inputs_frame_images() -> None:
    provider = media_video_provider(
        "runware-seedance-2-0-video",
        "runware",
        {
            "model_name": "bytedance:seedance@2.0",
            "aspect_ratio": "16:9",
            "duration": "10",
            "resolution": "720p",
            "generate_audio": True,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"data": [{"taskUUID": "video-task", "status": "queued"}]})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).submit_video_task(
                provider,
                "key",
                "video prompt",
                ["https://assets.example.test/first.png", "https://assets.example.test/last.png"],
                aspect_ratio="9:16",
                duration=5,
                resolution="1080p",
                generate_audio=False,
            )

    assert asyncio.run(run())["data"][0]["taskUUID"] == "video-task"
    task = seen["body"][0]
    assert task["model"] == "bytedance:seedance@2.0"
    assert task["inputs"] == {
        "frameImages": ["https://assets.example.test/first.png", "https://assets.example.test/last.png"]
    }
    assert "frameImages" not in task
    assert task["settings"]["audio"] is True


def test_media_video_payload_uses_kie_seedance_contract() -> None:
    provider = media_video_provider(
        "kie-seedance-2-0-video",
        "kie",
        {
            "model_name": "bytedance/seedance-2",
            "aspect_ratio": "16:9",
            "duration": "8",
            "resolution": "720p",
            "generate_audio": True,
            "camera_fixed": True,
            "watermark": False,
        },
    )
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"code": 200, "data": {"taskId": "task_bytedance_1"}})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).submit_video_task(
                provider,
                "key",
                "video prompt",
                [
                    "https://assets.example.test/first.png",
                    "https://assets.example.test/last.png",
                    "https://assets.example.test/ref.png",
                ],
                aspect_ratio="9:16",
                duration=5,
                resolution="1080p",
                generate_audio=False,
                camera_fixed=False,
                watermark=True,
            )

    assert asyncio.run(run())["data"]["taskId"] == "task_bytedance_1"
    assert seen["body"]["model"] == "bytedance/seedance-2"
    assert "input_urls" not in seen["body"]["input"]
    assert seen["body"]["input"]["first_frame_url"] == "https://assets.example.test/first.png"
    assert seen["body"]["input"]["last_frame_url"] == "https://assets.example.test/last.png"
    assert seen["body"]["input"]["reference_image_urls"] == ["https://assets.example.test/ref.png"]
    assert seen["body"]["input"]["aspect_ratio"] == "16:9"
    assert seen["body"]["input"]["duration"] == 8
    assert seen["body"]["input"]["generate_audio"] is True
    assert seen["body"]["input"]["fixed_lens"] is True
    assert seen["body"]["input"]["nsfw_checker"] is False


def test_media_video_payload_uses_cometapi_seedance_content_output_shape() -> None:
    provider = media_video_provider(
        "cometapi-seedance-2-0-video",
        "cometapi",
        {
            "model_name": "doubao-seedance-2-pro",
            "aspect_ratio": "16:9",
            "duration": "10",
            "resolution": "720p",
        },
    )
    provider.base_url = "https://api.cometapi.com/volc/v3/contents/generations/tasks"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "comet-video-task", "status": "queued"})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).submit_video_task(
                provider,
                "key",
                "video prompt",
                ["https://assets.example.test/first.png", "https://assets.example.test/ref.png"],
                aspect_ratio="9:16",
                duration=5,
                resolution="1080p",
            )

    assert asyncio.run(run())["id"] == "comet-video-task"
    assert seen["body"]["content"] == [
        {"type": "text", "text": "video prompt"},
        {"type": "image", "url": "https://assets.example.test/first.png"},
        {"type": "image", "url": "https://assets.example.test/ref.png"},
    ]
    assert seen["body"]["output"] == {"ratio": "16:9", "duration_s": 10, "resolution": "720p"}
    assert "duration_s" not in {key for key in seen["body"] if key != "output"}
    assert "ratio" not in {key for key in seen["body"] if key != "output"}


def test_media_video_payload_uses_wavespeed_seedance_shape() -> None:
    provider = media_video_provider(
        "wavespeed-seedance-2-0-video",
        "wavespeed",
        {
            "model_name": "bytedance/seedance-2.0/image-to-video-turbo",
            "aspect_ratio": "16:9",
            "duration": "10",
            "resolution": "720p",
            "generate_audio": True,
            "camera_fixed": True,
            "watermark": False,
        },
    )
    provider.base_url = "https://api.wavespeed.ai/api/v3/bytedance/seedance-2.0/image-to-video-turbo"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"data": {"id": "wavespeed-video-task", "status": "processing"}})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).submit_video_task(
                provider,
                "key",
                "video prompt",
                ["https://assets.example.test/first.png", "https://assets.example.test/last.png"],
                aspect_ratio="9:16",
                duration=5,
                resolution="1080p",
                generate_audio=False,
                camera_fixed=False,
                watermark=True,
            )

    assert asyncio.run(run())["data"]["id"] == "wavespeed-video-task"
    assert "model" not in seen["body"]
    assert seen["body"]["image"] == "https://assets.example.test/first.png"
    assert seen["body"]["images"] == [
        "https://assets.example.test/first.png",
        "https://assets.example.test/last.png",
    ]
    assert seen["body"]["aspect_ratio"] == "16:9"
    assert seen["body"]["duration"] == 10
    assert seen["body"]["resolution"] == "720p"
    assert seen["body"]["generate_audio"] is True
    assert seen["body"]["camera_fixed"] is True
    assert seen["body"]["watermark"] is False


def test_wavespeed_image_omits_model_and_switches_to_edit_url_for_references() -> None:
    source = Path("source.png")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": {"outputs": ["https://cdn.example.test/wavespeed.png"]}})
        return httpx.Response(200, content=b"wavespeed")

    provider = media_image_provider(
        "wavespeed-nano-2-generate",
        "wavespeed",
        "nano-banana-2",
        {
            "model_name": "google/nano-banana-2/text-to-image",
            "size_param_mode": "aspect_ratio_resolution",
            "resolution": "1K",
            "edit_base_url": "https://api.wavespeed.ai/api/v3/google/nano-banana-2/edit",
        },
    )
    provider.base_url = "https://api.wavespeed.ai/api/v3/google/nano-banana-2/text-to-image"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(source)],
                "16:9",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"wavespeed"
    assert seen["url"] == "https://api.wavespeed.ai/api/v3/google/nano-banana-2/edit"
    assert "model" not in seen["body"]
    assert seen["body"]["resolution"] == "1k"
    assert seen["body"]["aspect_ratio"] == "16:9"
    assert seen["body"]["images"] == ["https://assets.example.test/source.png"]
    assert seen["body"]["image"] == "https://assets.example.test/source.png"


def test_wavespeed_gpt_image2_generate_switches_to_edit_url_for_references() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": {"outputs": ["https://cdn.example.test/wavespeed-gpt.png"]}})
        return httpx.Response(200, content=b"wavespeed-gpt")

    provider = media_image_provider(
        "wavespeed-gpt-image-2-generate",
        "wavespeed",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2/text-to-image",
            "size_param_mode": "aspect_ratio_resolution",
            "resolution": "1K",
            "quality": "medium",
            "edit_base_url": "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/edit",
        },
    )
    provider.base_url = "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/text-to-image"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(Path("source.png"))],
                "16:9",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"wavespeed-gpt"
    assert seen["url"] == "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/edit"
    assert "model" not in seen["body"]
    assert seen["body"]["images"] == ["https://assets.example.test/source.png"]
    assert seen["body"]["resolution"] == "1k"
    assert seen["body"]["aspect_ratio"] == "16:9"


def test_fal_image_uses_key_auth_and_endpoint_payload_without_model() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["authorization"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"images": [{"url": "https://cdn.example.test/fal.png"}]})
        return httpx.Response(200, content=b"fal")

    provider = media_image_provider(
        "fal-gpt-image-2-generate",
        "fal",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2",
            "size_param_mode": "image_size_object",
            "quality": "medium",
            "auth_header_mode": "fal_key",
        },
    )
    provider.base_url = "https://fal.run/openai/gpt-image-2"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(provider, "fal-secret", "prompt", [], "970:600")

    assert asyncio.run(run()) == b"fal"
    assert seen["url"] == "https://fal.run/openai/gpt-image-2"
    assert seen["authorization"] == "Key fal-secret"
    assert "model" not in seen["body"]
    assert seen["body"]["image_size"] == {"width": 1040, "height": 640}
    assert seen["body"]["quality"] == "medium"


def test_fal_gpt_image2_generate_switches_to_edit_url_for_references() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["authorization"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"images": [{"url": "https://cdn.example.test/fal-edit.png"}]})
        return httpx.Response(200, content=b"fal-edit")

    provider = media_image_provider(
        "fal-gpt-image-2-generate",
        "fal",
        "gpt-image-2",
        {
            "model_name": "openai/gpt-image-2",
            "size_param_mode": "image_size_object",
            "quality": "medium",
            "auth_header_mode": "fal_key",
            "edit_base_url": "https://fal.run/openai/gpt-image-2/edit",
        },
    )
    provider.base_url = "https://fal.run/openai/gpt-image-2"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "fal-secret",
                "prompt",
                [str(Path("source.png"))],
                "3:2",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"fal-edit"
    assert seen["url"] == "https://fal.run/openai/gpt-image-2/edit"
    assert seen["authorization"] == "Key fal-secret"
    assert seen["body"]["image_urls"] == ["https://assets.example.test/source.png"]
    assert seen["body"]["image_size"] == {"width": 1536, "height": 1024}


def test_cometapi_gemini_image_uses_generate_content_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"comet").decode("ascii")}}
                            ]
                        }
                    }
                ]
            },
        )

    provider = media_image_provider(
        "cometapi-nano-2-generate",
        "cometapi",
        "nano-banana-2",
        {
            "model_name": "gemini-3.1-flash-image-preview",
            "size_param_mode": "aspect_ratio_resolution",
            "api_shape": "gemini_generate_content",
            "auth_header_mode": "raw_authorization",
            "resolution": "2K",
        },
    )
    provider.base_url = "https://api.cometapi.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "comet-secret",
                "prompt",
                [str(Path("source.png"))],
                "9:16",
                input_urls=["https://assets.example.test/source.png"],
            )

    assert asyncio.run(run()) == b"comet"
    assert seen["url"].endswith("/v1beta/models/gemini-3.1-flash-image-preview:generateContent")
    assert seen["authorization"] == "comet-secret"
    assert seen["body"]["generationConfig"]["imageConfig"] == {"aspectRatio": "9:16", "imageSize": "2K"}
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["text"].startswith("prompt")
    assert parts[1]["file_data"]["file_uri"] == "https://assets.example.test/source.png"


def test_cometapi_gpt_image2_reference_uses_multipart_edits(tmp_path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"fake-png")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["url"] = str(request.url)
            seen["content_type"] = request.headers.get("content-type")
            seen["body_text"] = request.content.decode("utf-8", errors="ignore")
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.test/comet-gpt.png"}]})
        return httpx.Response(200, content=b"comet-gpt")

    provider = media_image_provider(
        "cometapi-gpt-image-2-generate",
        "cometapi",
        "gpt-image-2",
        {
            "model_name": "gpt-image-2",
            "size_param_mode": "size_string",
            "quality": "medium",
        },
    )
    provider.base_url = "https://api.cometapi.com/v1/images/generations"

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await ProviderClient(http_client).generate_image(
                provider,
                "key",
                "prompt",
                [str(source)],
                "970:600",
            )

    assert asyncio.run(run()) == b"comet-gpt"
    assert seen["url"] == "https://api.cometapi.com/v1/images/edits"
    assert seen["content_type"].startswith("multipart/form-data")
    assert 'name="model"' in seen["body_text"]
    assert "gpt-image-2" in seen["body_text"]
    assert 'name="size"' in seen["body_text"]
    assert "1040x640" in seen["body_text"]
    assert 'name="image"; filename="source.png"' in seen["body_text"]


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
    assert IMAGE2_SIZE_MAP["2:3"] == "1024x1536"
    assert IMAGE2_SIZE_MAP["21:9"] == "1792x768"
    assert IMAGE2_SIZE_MAP["970:600"] == "970x600"
    assert IMAGE2_SIZE_MAP["1464:600"] == "1464x600"
    assert IMAGE2_SIZE_MAP["600:450"] == "600x450"


@pytest.mark.parametrize("size_param_mode", ["width_height", "image_size_object", "size_string"])
def test_gpt_image2_exact_size_modes_enforce_min_total_pixels(size_param_mode: str) -> None:
    config = {"model_family": "gpt-image-2", "size_param_mode": size_param_mode}

    assert _provider_request_image_size_for_config(config, "970:600")["size"] == "1040x640"
    assert _provider_request_image_size_for_config(config, "600:450")["size"] == "944x704"
    assert _provider_request_image_size_for_config(config, "1464:600")["size"] == "1472x608"


def test_gpt_image2_prompt_uses_aligned_canvas_and_business_ratio() -> None:
    config = {"model_family": "gpt-image-2", "size_param_mode": "size_string"}

    mobile_prompt = append_requested_size_to_prompt("生成 A+ 移动端", "600:450", config)
    standard_prompt = append_requested_size_to_prompt("生成普通 A+", "970:600", config)

    assert "Target canvas size: 944x704 px" in mobile_prompt
    assert "业务目标比例: 600:450" in mobile_prompt
    assert "600x450" not in mobile_prompt
    assert "Target canvas size: 1040x640 px" in standard_prompt
    assert "业务目标比例: 970:600" in standard_prompt
    assert "970x600" not in standard_prompt


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


class RecordingVersionProviderClient:
    def __init__(self) -> None:
        self.generate_calls: list[dict[str, Any]] = []
        self.edit_calls: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    async def generate_image(
        self,
        provider: Provider,
        _api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        **kwargs: Any,
    ) -> bytes:
        call = {
            "type": "generate",
            "provider": provider.code,
            "prompt": prompt,
            "input_paths": input_paths,
            "aspect_ratio": aspect_ratio,
            "kwargs": kwargs,
        }
        self.generate_calls.append(call)
        self.calls.append(call)
        return png_bytes()

    async def edit_image(
        self,
        provider: Provider,
        _api_key: str,
        prompt: str,
        input_paths: list[str],
        aspect_ratio: str,
        **kwargs: Any,
    ) -> bytes:
        call = {
            "type": "edit",
            "provider": provider.code,
            "prompt": prompt,
            "input_paths": input_paths,
            "aspect_ratio": aspect_ratio,
            "kwargs": kwargs,
        }
        self.edit_calls.append(call)
        self.calls.append(call)
        return png_bytes()

    async def call_llm(
        self,
        _provider: Provider,
        _api_key: str,
        system_prompt: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> str:
        if system_prompt == "edit prompt":
            return json.dumps({"prompt": "rewritten edit prompt"})
        return json.dumps({"schema_version": "1.0", "passed": True, "categories": [], "issues": []})


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


def create_live_aplus_generation_job(
    session,
    settings,
    cipher,
    *,
    output_modes: list[str],
) -> tuple[str, str]:
    add_provider(session, cipher, "atlas-gpt-image-2-generate", "image")
    add_provider(session, cipher, "atlas-gpt-image-2-edit", "image")
    prompt_version = add_prompt_version(session, "aplus-meta")
    asset_path = settings.uploads_dir / "aplus-source.png"
    asset_bytes = png_bytes()
    asset_path.write_bytes(asset_bytes)
    asset = Asset(
        original_name="aplus-source.png",
        mime_type="image/png",
        file_path=str(asset_path),
        url="/files/uploads/aplus-source.png",
        width=640,
        height=640,
        byte_size=len(asset_bytes),
        sha256="test-aplus-source",
    )
    session.add(asset)
    session.flush()
    output_targets = [
        {
            "mode": output_mode,
            "aspect_ratio": "600:450" if output_mode == "amazon_aplus_advanced_mobile" else "1464:600",
        }
        for output_mode in output_modes
    ]
    job = AplusJob(
        job_type="generation",
        status="queued",
        dry_run=False,
        params_json=json.dumps({"output_targets": output_targets, "plan_params": {}}),
        asset_ids_json=json.dumps([asset.id]),
        count=len(output_modes),
        progress=0,
        prompt_version_id=prompt_version.id,
    )
    session.add(job)
    session.flush()
    web_item: AplusItem | None = None
    for index, output_mode in enumerate(output_modes):
        item = AplusItem(
            job_id=job.id,
            index=index,
            module_index=1,
            module_name="商品主视觉",
            output_mode=output_mode,
            aspect_ratio="600:450" if output_mode == "amazon_aplus_advanced_mobile" else "1464:600",
            image_prompt="高级 A+ 商品主视觉，保持产品和卖点一致。",
            copy_requirements="主标题: Premium bottle\n副标题: Built for commuting",
            prompt_text="module payload",
            source_web_item_id=web_item.id if output_mode == "amazon_aplus_advanced_mobile" and web_item else None,
            status="queued",
        )
        session.add(item)
        session.flush()
        if output_mode == "amazon_aplus_advanced_web":
            web_item = item
    session.commit()
    return job.id, str(asset_path)


def test_aplus_live_advanced_mobile_derives_from_web_master_with_atlas_edit(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    settings.public_asset_base_url = "https://assets.example.test"
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(aplus_jobs, "ProviderClient", lambda: recording_client)

    with session_factory() as session:
        job_id, asset_path = create_live_aplus_generation_job(
            session,
            settings,
            cipher,
            output_modes=["amazon_aplus_advanced_web", "amazon_aplus_advanced_mobile"],
        )

    asyncio.run(aplus_jobs.run_aplus_generation_job(job_id, session_factory, settings, cipher))

    assert [(call["type"], call["provider"]) for call in recording_client.calls] == [
        ("generate", "atlas-gpt-image-2-generate"),
        ("edit", "atlas-gpt-image-2-edit"),
    ]
    assert recording_client.generate_calls[0]["input_paths"] == [asset_path]
    mobile_edit = recording_client.edit_calls[0]
    assert mobile_edit["aspect_ratio"] == "600:450"
    assert len(mobile_edit["input_paths"]) == 1
    assert mobile_edit["input_paths"] != [asset_path]
    assert Path(mobile_edit["input_paths"][0]).is_file()
    assert str(settings.results_dir) in mobile_edit["input_paths"][0]
    assert "唯一视觉母版" in mobile_edit["prompt"]
    assert "不新增" in mobile_edit["prompt"]
    assert "弱参考" in mobile_edit["prompt"]
    assert "逐字保留" in mobile_edit["prompt"]
    assert "禁止翻译" in mobile_edit["prompt"]
    assert "Do not translate" in mobile_edit["prompt"]
    assert "画面需求" not in mobile_edit["prompt"]
    assert "文案需求" not in mobile_edit["prompt"]
    assert "Premium bottle" not in mobile_edit["prompt"]

    with session_factory() as session:
        job = session.get(AplusJob, job_id)
        items = session.scalars(select(AplusItem).where(AplusItem.job_id == job_id).order_by(AplusItem.index)).all()
        assert job.status == "succeeded"
        assert [item.status for item in items] == ["succeeded", "succeeded"]


def test_aplus_live_mobile_only_uses_direct_atlas_mobile_generation(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    settings.public_asset_base_url = "https://assets.example.test"
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(aplus_jobs, "ProviderClient", lambda: recording_client)

    with session_factory() as session:
        job_id, asset_path = create_live_aplus_generation_job(
            session,
            settings,
            cipher,
            output_modes=["amazon_aplus_advanced_mobile"],
        )

    asyncio.run(aplus_jobs.run_aplus_generation_job(job_id, session_factory, settings, cipher))

    assert [(call["type"], call["provider"]) for call in recording_client.calls] == [
        ("generate", "atlas-gpt-image-2-edit"),
    ]
    assert recording_client.generate_calls[0]["input_paths"] == [asset_path]
    assert recording_client.generate_calls[0]["aspect_ratio"] == "600:450"
    assert recording_client.edit_calls == []
    assert "移动端独立生成模式" in recording_client.generate_calls[0]["prompt"]
    assert "不依赖 Web 母版" in recording_client.generate_calls[0]["prompt"]


def test_aplus_live_atlas_failure_does_not_fallback_to_backup_provider(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    settings.public_asset_base_url = "https://assets.example.test"
    cipher = client.app.state.cipher
    attempted: list[str] = []

    class FailingAtlasClient:
        async def generate_image(
            self,
            provider: Provider,
            *_args: Any,
            **_kwargs: Any,
        ) -> bytes:
            attempted.append(provider.code)
            raise RuntimeError("atlas down")

        async def edit_image(
            self,
            provider: Provider,
            *_args: Any,
            **_kwargs: Any,
        ) -> bytes:
            attempted.append(provider.code)
            raise RuntimeError("atlas edit down")

    monkeypatch.setattr(aplus_jobs, "ProviderClient", FailingAtlasClient)

    with session_factory() as session:
        job_id, _asset_path = create_live_aplus_generation_job(
            session,
            settings,
            cipher,
            output_modes=["amazon_aplus_advanced_web"],
        )
        add_provider(session, cipher, "cometapi-gpt-image-2-generate", "image")
        session.commit()

    asyncio.run(aplus_jobs.run_aplus_generation_job(job_id, session_factory, settings, cipher))

    assert attempted == ["atlas-gpt-image-2-generate"]
    with session_factory() as session:
        job = session.get(AplusJob, job_id)
        item = session.scalar(select(AplusItem).where(AplusItem.job_id == job_id))
        assert job.status == "failed"
        assert item.status == "failed"
        assert "atlas down" in item.error


def create_live_suite_item_with_version(
    session,
    settings,
    cipher,
    *,
    model_preference: str,
    provider_code: str,
) -> tuple[str, str]:
    provider = add_provider(session, cipher, provider_code, "image")
    add_provider(session, cipher, "doubao-seed-2-0-mini", "llm", default=True)
    add_provider(session, cipher, "qwen-3-6", "llm", fallback=True)
    meta_prompt = add_prompt_version(session, "ecommerce-meta")
    edit_prompt = add_prompt_version(session, "edit-rewrite", "edit prompt")
    safety_prompt = add_prompt_version(session, "content-safety-review", "safety prompt")
    workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
    job = GenerationJob(
        status="succeeded",
        dry_run=False,
        params_json=json.dumps(
            {
                "aspect_ratio": "1:1",
                "model_preference": model_preference,
                "_prompt_versions": {
                    "edit-rewrite": edit_prompt.id,
                    "content-safety-review": safety_prompt.id,
                },
            },
            ensure_ascii=False,
        ),
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
        image_type="single selling point",
        prompt_text=json.dumps(
            {
                "route_symbol": "#@",
                "image_type": "single selling point",
                "picture_requirement": "Keep the product unchanged.",
                "copywriting_requirements": "No text overlay.",
            },
            ensure_ascii=False,
        ),
        status="succeeded",
        provider_id=provider.id,
    )
    session.add(item)
    session.flush()
    current_path = settings.results_dir / f"current-{item.id}.png"
    current_path.write_bytes(png_bytes())
    version = GenerationVersion(
        item_id=item.id,
        version_no=1,
        instruction="initial",
        file_path=str(current_path),
        url=f"/files/results/{current_path.name}",
        metadata_json=safe_json({"dry_run": False, "provider": provider_code}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    session.commit()
    return item.id, version.id


def test_suite_empty_instruction_regenerate_prefers_original_provider(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(jobs_service, "ProviderClient", lambda: recording_client)
    with session_factory() as session:
        item_id, current_version_id = create_live_suite_item_with_version(
            session,
            settings,
            cipher,
            model_preference="fidelity",
            provider_code="apimodels-nano-pro-generate",
        )
        item = session.get(GenerationItem, item_id)
        version = asyncio.run(jobs_service.create_live_child_version(session, item, "", settings, cipher))
        metadata = json.loads(version.metadata_json)

    assert [call["provider"] for call in recording_client.generate_calls] == ["apimodels-nano-pro-generate"]
    assert recording_client.edit_calls == []
    assert version.parent_version_id == current_version_id
    assert version.instruction == ""
    assert metadata["edit_type"] == "regenerate"
    assert metadata["route_key"] == "suite_fidelity"
    assert metadata["provider"] == "apimodels-nano-pro-generate"
    assert metadata["source_provider_preferred"] is True


def test_suite_empty_instruction_regenerate_falls_back_when_original_provider_unavailable(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(jobs_service, "ProviderClient", lambda: recording_client)
    with session_factory() as session:
        item_id, _ = create_live_suite_item_with_version(
            session,
            settings,
            cipher,
            model_preference="fidelity",
            provider_code="apimodels-nano-pro-generate",
        )
        add_provider(session, cipher, "kie-nano-2-generate", "image")
        original = session.scalar(select(Provider).where(Provider.code == "apimodels-nano-pro-generate"))
        original.enabled = False
        session.commit()
        item = session.get(GenerationItem, item_id)
        version = asyncio.run(jobs_service.create_live_child_version(session, item, "", settings, cipher))
        metadata = json.loads(version.metadata_json)

    assert [call["provider"] for call in recording_client.generate_calls] == ["kie-nano-2-generate"]
    assert recording_client.edit_calls == []
    assert metadata["route_key"] == "suite_fidelity"
    assert metadata["provider"] == "kie-nano-2-generate"
    assert metadata["source_provider_preferred"] is False


def test_suite_layout_empty_instruction_regenerate_uses_layout_route(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(jobs_service, "ProviderClient", lambda: recording_client)
    with session_factory() as session:
        item_id, _ = create_live_suite_item_with_version(
            session,
            settings,
            cipher,
            model_preference="layout",
            provider_code="atlas-gpt-image-2-generate",
        )
        item = session.get(GenerationItem, item_id)
        version = asyncio.run(jobs_service.create_live_child_version(session, item, "", settings, cipher))
        metadata = json.loads(version.metadata_json)

    assert [call["provider"] for call in recording_client.generate_calls] == ["atlas-gpt-image-2-generate"]
    assert recording_client.edit_calls == []
    assert metadata["route_key"] == "suite_layout"
    assert metadata["provider"] == "atlas-gpt-image-2-generate"


def test_suite_non_empty_instruction_still_uses_image_edit_route(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    settings.public_asset_base_url = "https://assets.example.test"
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(jobs_service, "ProviderClient", lambda: recording_client)
    with session_factory() as session:
        item_id, _ = create_live_suite_item_with_version(
            session,
            settings,
            cipher,
            model_preference="fidelity",
            provider_code="apimodels-nano-pro-generate",
        )
        add_provider(session, cipher, "atlas-gpt-image-2-edit", "image")
        session.commit()
        item = session.get(GenerationItem, item_id)
        version = asyncio.run(
            jobs_service.create_live_child_version(session, item, "make the background brighter", settings, cipher)
        )
        metadata = json.loads(version.metadata_json)

    assert recording_client.generate_calls == []
    assert [call["provider"] for call in recording_client.edit_calls] == ["atlas-gpt-image-2-edit"]
    assert metadata["provider"] == "atlas-gpt-image-2-edit"
    assert metadata.get("edit_type") != "regenerate"


def test_live_generation_text_version_still_uses_image_edit_route(client, monkeypatch) -> None:
    session_factory = client.app.state.session_factory
    settings = client.app.state.settings
    settings.public_asset_base_url = "https://assets.example.test"
    cipher = client.app.state.cipher
    recording_client = RecordingVersionProviderClient()
    monkeypatch.setattr(image_text_edit, "ProviderClient", lambda: recording_client)
    with session_factory() as session:
        item_id, _ = create_live_suite_item_with_version(
            session,
            settings,
            cipher,
            model_preference="fidelity",
            provider_code="apimodels-nano-pro-generate",
        )
        add_prompt_version(session, "image-text-edit", "replace text {{REPLACEMENTS_TABLE}}")
        add_provider(session, cipher, "atlas-gpt-image-2-edit", "image")
        session.commit()
        item = session.get(GenerationItem, item_id)
        version = asyncio.run(
            image_text_edit.create_live_generation_text_version(
                session,
                item,
                "1:1",
                [ImageTextEditLine(index=0, original_text="Old", text="New")],
                settings,
                cipher,
            )
        )
        metadata = json.loads(version.metadata_json)

    assert recording_client.generate_calls == []
    assert [call["provider"] for call in recording_client.edit_calls] == ["atlas-gpt-image-2-edit"]
    assert metadata["edit_type"] == "text"
    assert metadata["provider"] == "atlas-gpt-image-2-edit"


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
        assert metadata == {
            "dry_run": False,
            "provider": "yunwu-nano-pro",
            "actual_size": list(image_size),
            "requested_size": {"aspect_ratio": "1:1", "width": 1024, "height": 1024, "size": "1024x1024"},
        }
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
