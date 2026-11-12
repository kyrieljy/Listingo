import hashlib
import json

from sqlalchemy import select

from backend.app.models import Provider, Prompt, PromptVersion, User, Workflow, WorkflowVersion
from backend.app.security import ApiKeyCipher, mask_api_key
from backend.app.seed import LEGACY_VIDEO_PROVIDER_CODE, PROMPT_PATH, VIDEO_PROVIDER_CODE, seed_database
from backend.app.services.provider_catalog import (
    DEFAULT_ROUTE_CHAINS,
    PROVIDER_GROUPS,
    ROUTE_SLOT_ORDER,
    media_provider_presets,
)
from backend.app.services.provider_routing import provider_config, provider_route_roles
from backend.app.services.provider_routing import route_provider_codes


def test_api_key_encrypts_at_rest_and_masks_response(tmp_path) -> None:
    cipher = ApiKeyCipher(tmp_path / ".secret_key")
    encrypted = cipher.encrypt("sk-listingo-super-secret")

    assert encrypted != "sk-listingo-super-secret"
    assert "super-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "sk-listingo-super-secret"
    assert mask_api_key("sk-listingo-super-secret") == "sk-l••••••••cret"


def test_production_seed_preserves_existing_bootstrap_account_settings(client) -> None:
    with client.app.state.session_factory() as session:
        admin = session.scalar(select(User).where(User.username == "admin"))
        admin.phone = "13900000001"
        admin.role = "user"
        admin.status = "disabled"
        admin.current_plan_code = "free"
        session.commit()

        seed_database(session, admin_phone="13900000002", production=True)
        session.refresh(admin)
        assert (admin.phone, admin.role, admin.status, admin.current_plan_code) == (
            "13900000001", "user", "disabled", "free",
        )


def test_seed_creates_molink26_and_versioned_assets(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        providers = session.scalars(select(Provider).order_by(Provider.code)).all()
        prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-meta"))
        workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
        workflows = session.scalars(select(Workflow).order_by(Workflow.code)).all()

        assert len(providers) == 3 + len(media_provider_presets())
        assert all(provider.enabled is False for provider in providers)
        assert not any(provider.code.startswith("yunwu-") for provider in providers)
        assert VIDEO_PROVIDER_CODE not in {provider.code for provider in providers}
        assert {provider_config(p)["provider_group"] for p in providers if p.capability in {"image", "video"}} == {
            "molink", "hellobabygo",
        }
        doubao = next(p for p in providers if p.code == "doubao-seed-2-0-mini")
        qwen = next(p for p in providers if p.code == "qwen-3-6")
        assert provider_route_roles(doubao) == {"llm": "primary"}
        assert provider_route_roles(qwen) == {"llm": "backup1"}
        by_code = {p.code: p for p in providers}
        for route, chain in DEFAULT_ROUTE_CHAINS.items():
            for index, code in enumerate(chain):
                assert provider_route_roles(by_code[code])[route] == ROUTE_SLOT_ORDER[index]
        for provider in providers:
            if provider.capability != "image":
                continue
            config = provider_config(provider)
            assert provider.model_name in {"gpt-image-2.6-flare", "gpt-image-2.6-sunburst"}
            assert provider.base_url.startswith("https://www.getmolinkapi.com/v1/images/")
            assert config["timeout_seconds"] == 240 and config["size_alignment"] == 16
            assert "quality" not in config and "complexity" not in config
        assert doubao.base_url.endswith("/api/v1/chat/completions")
        assert doubao.model_name == "bytedance/doubao-seed-2-0-mini"
        assert prompt is not None and prompt.active_version_id is not None
        assert workflow is not None and workflow.active_version_id is not None
        prompt_version = session.get(PromptVersion, prompt.active_version_id)
        assert prompt_version.content == PROMPT_PATH.read_bytes().decode("utf-8-sig")
        assert prompt_version.content_sha256 == hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest().upper()
        assert session.get(WorkflowVersion, workflow.active_version_id).version_no == 1
        assert {item.code for item in workflows} == {"aplus-detail-v1", "product-suite-v1", "video-v1"}
        assert all(item.active_version_id for item in workflows)
        copywriting = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
        image_text_edit = session.scalar(select(Prompt).where(Prompt.code == "image-text-edit"))
        video_prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-video-meta-15s"))
        aplus_prompt = session.scalar(select(Prompt).where(Prompt.code == "aplus-meta"))
        assert image_text_edit is not None and image_text_edit.active_version_id is not None
        assert "{{REPLACEMENTS_TABLE}}" in session.get(PromptVersion, image_text_edit.active_version_id).content
        assert video_prompt is not None and video_prompt.active_version_id is not None
        assert aplus_prompt is not None and aplus_prompt.active_version_id is not None
        assert "电商 AI 视频 Meta Prompt" in session.get(PromptVersion, video_prompt.active_version_id).content
        assert "A+详情页提示词0729" in session.get(PromptVersion, aplus_prompt.active_version_id).content
        assert "module_selections" in session.get(PromptVersion, aplus_prompt.active_version_id).content
        copywriting_version = session.get(PromptVersion, copywriting.active_version_id)
        for required_rule in [
            "仅有图",
            "图+文",
            "文字描述的事实为唯一依据",
            "3 个高频、具体的日常使用画面",
            "5 大核心卖点",
            "150 字至 200 字",
            "严禁捏造",
            "输出语言必须为简体中文",
            "图片语言只用于后续图片文案",
            "### 1. 商品定位",
        ]:
            assert required_rule in copywriting_version.content


def test_image_edit_route_requires_configured_primary_provider(client) -> None:
    with client.app.state.session_factory() as session:
        try:
            route_provider_codes(session, "image_edit")
        except RuntimeError as exc:
            assert "API Key" in str(exc)
        else:
            raise AssertionError("image_edit route should require an enabled provider with an API key")


def test_seed_retires_old_models_and_copies_molink_credential(client) -> None:
    with client.app.state.session_factory() as session:
        legacy = Provider(
            code="molink-image-2-generate", label="Legacy MoLink", capability="image",
            adapter="media_image", base_url="https://getmolinkapi.com/v1/images/generations",
            model_name="gpt-image-2", enabled=True,
            encrypted_api_key=client.app.state.cipher.encrypt("test-key"),
            config_json=json.dumps({"route_roles": {"suite_fidelity": "primary"}}),
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
        for _ in range(2):
            seed_database(session)
            assert session.get(Provider, legacy_id) is not None
            assert not legacy.enabled and provider_config(legacy)["hidden_legacy"]
            assert provider_route_roles(legacy) == {}
            for route, chain in DEFAULT_ROUTE_CHAINS.items():
                if route == "llm" or route == "video":
                    continue
                assert route_provider_codes(session, route) == chain
                selected = session.scalar(select(Provider).where(Provider.code == chain[0]))
                assert selected.encrypted_api_key == legacy.encrypted_api_key


def test_seed_upgrades_an_existing_legacy_workflow_once(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        workflow = session.scalar(select(Workflow).where(Workflow.code == "product-suite-v1"))
        active = session.get(WorkflowVersion, workflow.active_version_id)
        active.graph_json = '{"schema_version":"1.0","nodes":[{"id":"input","type":"input"}],"edges":[]}'
        session.commit()
        seed_database(session)
        session.refresh(workflow)
        upgraded = session.get(WorkflowVersion, workflow.active_version_id)
        assert upgraded.version_no == 2
        assert "product_vision" in upgraded.graph_json
        seed_database(session)
        assert len(session.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)).all()) == 2


def test_seed_migrates_legacy_video_provider_without_duplicate_insert(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        legacy = Provider(
            code=LEGACY_VIDEO_PROVIDER_CODE,
            label="Legacy Seedance",
            capability="video",
            adapter="hellobabygo_video_generation",
            base_url="https://api.hellobabygo.com/v1/videos",
            model_name="bytedance/doubao-seedance-1-5-pro",
            enabled=True,
            is_default=True,
            is_fallback=False,
            config_json=json.dumps({"route_roles": {"video": "primary"}}),
        )
        session.add(legacy)
        session.commit()

        seed_database(session)

        current_video = session.scalar(select(Provider).where(Provider.code == VIDEO_PROVIDER_CODE))
        legacy_video = session.scalar(select(Provider).where(Provider.code == LEGACY_VIDEO_PROVIDER_CODE))
        providers = session.scalars(select(Provider)).all()
        assert current_video is not None
        assert legacy_video is None
        assert current_video.enabled is False
        assert current_video.is_default is False
        assert current_video.is_fallback is False
        assert current_video.adapter == "hellobabygo_video_generation"
        assert provider_config(current_video)["hidden_legacy"] is True
        assert provider_route_roles(current_video) == {}
        assert len(providers) == 3 + len(media_provider_presets()) + 1


def test_seed_upgrades_legacy_copywriting_prompt_once(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        prompt = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
        active = session.get(PromptVersion, prompt.active_version_id)
        active.content = "# 旧版 AI 帮写\n\n仅输出 JSON。"
        active.content_sha256 = "LEGACY"
        session.commit()

        seed_database(session)
        session.refresh(prompt)
        upgraded = session.get(PromptVersion, prompt.active_version_id)
        assert upgraded.version_no == 2
        assert "文字描述的事实为唯一依据" in upgraded.content
        assert "输出语言必须为简体中文" in upgraded.content
        assert "### 3. 5大核心卖点" in upgraded.content

        seed_database(session)
        versions = session.scalars(select(PromptVersion).where(PromptVersion.prompt_id == prompt.id)).all()
        assert len(versions) == 2
