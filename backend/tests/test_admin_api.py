from io import BytesIO

import httpx
from PIL import Image
from sqlalchemy import select

import backend.app.api.admin as admin_api
import backend.app.services.prompt_testing as prompt_testing
from backend.app.models import Prompt, Provider


def make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#f2ede4").save(buffer, format="PNG")
    return buffer.getvalue()


def upload_asset(client) -> str:
    response = client.post(
        "/api/v1/assets",
        files={"file": ("product.png", make_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def enable_providers(client, capabilities: set[str]) -> None:
    with client.app.state.session_factory() as session:
        providers = session.scalars(select(Provider)).all()
        for provider in providers:
            if provider.capability in capabilities:
                provider.enabled = True
                provider.encrypted_api_key = client.app.state.cipher.encrypt("sk-test")
        session.commit()


def prompt_by_code(client, code: str) -> Prompt:
    with client.app.state.session_factory() as session:
        prompt = session.scalar(select(Prompt).where(Prompt.code == code))
        assert prompt is not None
        return prompt


def test_provider_api_masks_key_and_requires_explicit_test(client) -> None:
    providers = client.get("/api/v1/admin/providers").json()
    provider = next(item for item in providers if item["code"] == "yunwu-nano")
    response = client.patch(
        f"/api/v1/admin/providers/{provider['id']}",
        json={"api_key": "yunwu-secret-key", "enabled": True, "timeout_seconds": 60},
    )
    assert response.status_code == 200, response.text
    updated = response.json()

    assert updated["has_api_key"] is True
    assert updated["api_key_masked"] == "yunw••••••••-key"
    assert "secret" not in str(updated)


def test_provider_api_updates_business_route_roles_and_clears_peer_role(client) -> None:
    providers = client.get("/api/v1/admin/providers").json()
    image2 = next(item for item in providers if item["code"] == "yunwu-image-2")
    nano = next(item for item in providers if item["code"] == "yunwu-nano")

    response = client.patch(
        f"/api/v1/admin/providers/{nano['id']}",
        json={"route_roles": {"aplus_detail": "fallback", "suite_layout": "primary"}},
    )

    assert response.status_code == 200, response.text
    updated_nano = response.json()
    assert updated_nano["route_roles"]["aplus_detail"] == "fallback"
    assert updated_nano["route_roles"]["suite_layout"] == "primary"

    updated_image2 = next(item for item in client.get("/api/v1/admin/providers").json() if item["code"] == "yunwu-image-2")
    assert updated_image2["route_roles"]["aplus_detail"] == "primary"
    assert "suite_layout" not in updated_image2["route_roles"]

    rejected = client.patch(
        f"/api/v1/admin/providers/{image2['id']}",
        json={"route_roles": {"llm": "primary"}},
    )
    assert rejected.status_code == 422


def test_seedance_provider_test_does_not_require_openai_model_directory_membership(client, monkeypatch) -> None:
    providers = client.get("/api/v1/admin/providers").json()
    provider = next(item for item in providers if item["code"] == "shengsuanyun-doubao-seedance-2-0")
    update = client.patch(
        f"/api/v1/admin/providers/{provider['id']}",
        json={"api_key": "shengsuanyun-secret-key", "enabled": True, "timeout_seconds": 60},
    )
    assert update.status_code == 200, update.text
    seen: dict[str, str] = {}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url: str, headers: dict[str, str]):
            seen["url"] = url
            seen["authorization"] = headers["Authorization"]
            return httpx.Response(200, json={"data": [{"id": "openai/gpt-5.4-mini"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(admin_api, "build_async_http_client", lambda _timeout: FakeAsyncClient())

    response = client.post(f"/api/v1/admin/providers/{provider['id']}/test")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] is True
    assert seen["url"] == "https://router.shengsuanyun.com/api/v1/models"
    assert seen["authorization"].startswith("Bearer ")
    assert result["message"] == "连接可用，未发起计费视频任务"


def test_prompt_version_can_be_saved_compared_and_activated(client) -> None:
    prompt = client.get("/api/v1/admin/prompts").json()[0]
    original = client.get(f"/api/v1/admin/prompts/{prompt['id']}").json()
    response = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions",
        json={
            "content": original["active_version"]["content"] + "\n\n# 运营备注\n只用于版本演示。",
            "change_note": "演示版本管理",
        },
    )
    assert response.status_code == 201
    new_version = response.json()
    compare = client.get(
        f"/api/v1/admin/prompts/{prompt['id']}/compare",
        params={"from_version": 1, "to_version": new_version["version_no"]},
    )
    assert compare.status_code == 200
    assert "+# 运营备注" in compare.json()["diff"]

    activate = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/{new_version['id']}/activate"
    )
    assert activate.status_code == 200
    assert activate.json()["active_version_id"] == new_version["id"]


def test_prompt_md_or_txt_can_be_uploaded_as_version_and_activated(client) -> None:
    prompt = client.get("/api/v1/admin/prompts").json()[0]
    uploaded_content = "# 新提示词资产\n\n这是运营上传的完整提示词版本，用于后续 Live 任务。"

    response = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/upload",
        files={"file": ("listing-prompt.md", uploaded_content.encode("utf-8"), "text/markdown")},
        data={"change_note": "上传测试版本"},
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["content"] == uploaded_content
    assert version["change_note"] == "上传测试版本"

    activate = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/{version['id']}/activate"
    )
    assert activate.status_code == 200
    detail = client.get(f"/api/v1/admin/prompts/{prompt['id']}").json()
    assert detail["active_version_id"] == version["id"]

    rejected = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/upload",
        files={"file": ("prompt.json", b"{}", "application/json")},
    )
    assert rejected.status_code == 422


def test_prompt_llm_test_uses_editor_content_without_saving_version(client, monkeypatch) -> None:
    enable_providers(client, {"llm"})
    prompt = prompt_by_code(client, "copywriting-assist")
    seen: dict[str, str] = {}

    async def fake_call_llm(_client, default_provider, _fallback_provider, _cipher, system_prompt, user_prompt, **_kwargs):
        seen["system_prompt"] = system_prompt
        seen["user_prompt"] = user_prompt
        return "运营试跑输出", default_provider

    monkeypatch.setattr(prompt_testing, "_call_llm_with_fallback", fake_call_llm)
    editor_content = "UNSAVED EDITOR PROMPT CONTENT\n" + "请直接使用这份未保存提示词进行测试。"

    response = client.post(
        f"/api/v1/admin/prompts/{prompt.id}/test-runs",
        json={
            "test_type": "llm_output",
            "prompt_content": editor_content,
            "inputs": {"platform": "Amazon", "market": "US", "language": "English", "selling_points": "compact bottle"},
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "succeeded"
    assert result["raw_output"] == "运营试跑输出"
    assert result["parsed_output"] == {"text": "运营试跑输出"}
    assert seen["system_prompt"] == editor_content
    detail = client.get(f"/api/v1/admin/prompts/{prompt.id}").json()
    assert detail["active_version"]["content"] != editor_content


def test_prompt_llm_test_returns_409_when_llm_route_is_not_configured(client) -> None:
    prompt = prompt_by_code(client, "copywriting-assist")
    response = client.post(
        f"/api/v1/admin/prompts/{prompt.id}/test-runs",
        json={
            "test_type": "llm_output",
            "prompt_content": "这是一份足够长的提示词测试内容，用于验证 Provider 缺失时的错误。",
            "inputs": {"selling_points": "portable bottle"},
        },
    )

    assert response.status_code == 409


def test_prompt_llm_test_reports_meta_prompt_parse_errors(client, monkeypatch) -> None:
    enable_providers(client, {"llm"})
    prompt = prompt_by_code(client, "ecommerce-meta")

    async def fake_call_llm(_client, default_provider, _fallback_provider, _cipher, _system_prompt, _user_prompt, **_kwargs):
        return '{"schema_version":"1.0","images":[]}', default_provider

    monkeypatch.setattr(prompt_testing, "_call_llm_with_fallback", fake_call_llm)

    response = client.post(
        f"/api/v1/admin/prompts/{prompt.id}/test-runs",
        json={
            "test_type": "llm_output",
            "prompt_content": "核心提示词测试内容，要求输出结构化套图规划 JSON。",
            "inputs": {
                "platform": "Amazon",
                "market": "US",
                "language": "English",
                "aspect_ratio": "1:1",
                "selling_points": "portable bottle",
                "count": 7,
            },
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "succeeded"
    assert result["validation_errors"]
    assert result["parsed_output"] == {}


def test_full_chain_prompt_test_creates_admin_only_generation_job(client, monkeypatch) -> None:
    enable_providers(client, {"llm", "image"})
    asset_id = upload_asset(client)
    prompt = prompt_by_code(client, "ecommerce-meta")
    scheduled: list[str] = []

    async def fake_run_generation_job(job_id, *_args):
        scheduled.append(job_id)

    monkeypatch.setattr(admin_api, "run_generation_job", fake_run_generation_job)

    response = client.post(
        f"/api/v1/admin/prompts/{prompt.id}/test-runs",
        json={
            "test_type": "full_chain",
            "prompt_content": "后台完整链路测试使用的当前编辑器提示词内容，不自动保存版本。",
            "inputs": {
                "asset_ids": [asset_id],
                "platform": "Amazon",
                "market": "US",
                "language": "English",
                "aspect_ratio": "1:1",
                "selling_points": "portable bottle",
                "count": 7,
                "model_preference": "fidelity",
            },
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["test_type"] == "full_chain"
    assert result["related_job_type"] == "generation"
    assert scheduled == [result["related_job_id"]]
    history = client.get("/api/v1/generation-jobs").json()
    assert all(job["id"] != result["related_job_id"] for job in history)
