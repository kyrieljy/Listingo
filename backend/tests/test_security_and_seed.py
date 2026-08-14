import hashlib
import json

from sqlalchemy import select

from backend.app.models import Provider, Prompt, PromptVersion, Workflow, WorkflowVersion
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


def test_seed_creates_nano_pro_primary_nano2_fallback_and_versioned_assets(client) -> None:
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
        assert {provider_config(provider).get("provider_group") for provider in providers if provider.capability in {"image", "video"}} == {
            item["key"] for item in PROVIDER_GROUPS
        }
        doubao = next(provider for provider in providers if provider.code == "doubao-seed-2-0-mini")
        qwen = next(provider for provider in providers if provider.code == "qwen-3-6")
        assert doubao.is_default is True and doubao.is_fallback is False
        assert qwen.is_default is False and qwen.is_fallback is True
        assert provider_route_roles(doubao) == {"llm": "primary"}
        assert provider_route_roles(qwen) == {"llm": "backup1"}
        by_code = {provider.code: provider for provider in providers}
        for route_key, chain in DEFAULT_ROUTE_CHAINS.items():
            for index, provider_code in enumerate(chain[: len(ROUTE_SLOT_ORDER)]):
                assert provider_route_roles(by_code[provider_code])[route_key] == ROUTE_SLOT_ORDER[index]
        ratio_only_image2_codes = {
            "apimodels-gpt-image-2-generate",
            "apimodels-gpt-image-2-edit",
            "kie-gpt-image-2-generate",
            "kie-gpt-image-2-edit",
            "wavespeed-gpt-image-2-generate",
            "wavespeed-gpt-image-2-edit",
            "replicate-gpt-image-2-generate",
            "replicate-gpt-image-2-edit",
        }
        for route_key in ("suite_layout", "aplus_detail", "aplus_mobile", "image_edit"):
            assert not (ratio_only_image2_codes & set(DEFAULT_ROUTE_CHAINS[route_key]))
        nano_pro = by_code["apimodels-nano-pro-generate"]
        nano = by_code["kie-nano-2-generate"]
        image2 = by_code["atlas-gpt-image-2-generate"]
        aplus_mobile = by_code["atlas-gpt-image-2-edit"]
        video = by_code["hellobabygo-seedance-2-0-video"]
        apimodels_providers = [provider for provider in providers if provider_config(provider).get("provider_group") == "apimodels"]
        assert nano_pro.adapter == "media_image"
        assert nano.adapter == "media_image"
        assert image2.adapter == "media_image"
        assert aplus_mobile.adapter == "media_image"
        assert video.adapter == "hellobabygo_video_generation"
        assert apimodels_providers
        assert all(provider.base_url.startswith("https://apimodels.app/api/v1/") for provider in apimodels_providers)
        assert not any("api.apimodels.app" in provider.base_url for provider in apimodels_providers)
        apimodels_image2_config = provider_config(by_code["apimodels-gpt-image-2-generate"])
        assert by_code["apimodels-gpt-image-2-generate"].model_name == "gpt-image-2"
        assert apimodels_image2_config["size_param_mode"] == "aspect_ratio_resolution"
        assert apimodels_image2_config["resolution"] == "1K"
        assert apimodels_image2_config["max_reference_images"] == 16
        assert apimodels_image2_config["supports_exact_custom_size"] is False
        assert "quality" not in apimodels_image2_config
        assert "quality" not in {item["key"] for item in apimodels_image2_config["parameter_schema"]}
        assert by_code["apimodels-nano-pro-generate"].model_name == "gemini-3-pro-image-gemini"
        assert by_code["apimodels-nano-2-generate"].model_name == "nanobanana2/gemini-3.1-flash-image-preview"
        assert by_code["atlas-gpt-image-2-generate"].model_name == "openai/gpt-image-2/text-to-image"
        assert provider_config(by_code["atlas-gpt-image-2-generate"])["edit_model_name"] == "openai/gpt-image-2/edit"
        assert provider_config(by_code["atlas-gpt-image-2-generate"])["size_alignment"] == 16
        assert provider_config(by_code["atlas-gpt-image-2-generate"])["enable_sync_mode"] is True
        assert provider_config(by_code["atlas-gpt-image-2-generate"])["enable_base64_output"] is True
        assert by_code["atlas-gpt-image-2-edit"].model_name == "openai/gpt-image-2/edit"
        assert provider_config(by_code["atlas-gpt-image-2-edit"])["size_param_mode"] == "size_string"
        assert provider_config(by_code["atlas-gpt-image-2-edit"])["size_alignment"] == 16
        assert provider_config(by_code["atlas-gpt-image-2-edit"])["enable_sync_mode"] is True
        assert provider_config(by_code["atlas-gpt-image-2-edit"])["enable_base64_output"] is True
        exact_image2_codes = {
            "atlas-gpt-image-2-generate",
            "atlas-gpt-image-2-edit",
            "cometapi-gpt-image-2-generate",
            "cometapi-gpt-image-2-edit",
            "runware-gpt-image-2-generate",
            "runware-gpt-image-2-edit",
            "fal-gpt-image-2-generate",
            "fal-gpt-image-2-edit",
            "openrouter-gpt-image-2-generate",
            "openrouter-gpt-image-2-edit",
        }
        for provider_code in exact_image2_codes:
            config = provider_config(by_code[provider_code])
            assert config["model_family"] == "gpt-image-2"
            assert config["supports_exact_custom_size"] is True
            assert config["size_alignment"] == 16
        assert by_code["atlas-nano-2-generate"].model_name == "google/nano-banana-2/text-to-image"
        assert provider_config(by_code["atlas-nano-2-generate"])["edit_model_name"] == "google/nano-banana-2/edit"
        assert provider_config(by_code["fal-gpt-image-2-generate"])["edit_base_url"].endswith("/openai/gpt-image-2/edit")
        assert by_code["wavespeed-gpt-image-2-generate"].base_url.endswith("/openai/gpt-image-2/text-to-image")
        assert provider_config(by_code["wavespeed-gpt-image-2-generate"])["edit_base_url"].endswith("/openai/gpt-image-2/edit")
        assert provider_config(by_code["wavespeed-gpt-image-2-edit"])["size_param_mode"] == "aspect_ratio_resolution"
        assert by_code["wavespeed-nano-2-generate"].base_url.endswith("/google/nano-banana-2/text-to-image")
        assert by_code["kie-gpt-image-2-generate"].model_name == "gpt-image-2-text-to-image"
        assert provider_config(by_code["kie-gpt-image-2-generate"])["edit_model_name"] == "gpt-image-2-image-to-image"
        assert by_code["kie-seedance-2-0-video"].model_name == "bytedance/seedance-2"
        assert by_code["hellobabygo-seedance-2-0-video"].base_url == "https://api.hellobabygo.com/v1/videos"
        assert by_code["hellobabygo-seedance-2-0-video"].model_name == "seedance-2.0"
        assert by_code["fal-seedance-2-0-video"].base_url.endswith("/bytedance/seedance-2.0/image-to-video")
        assert provider_config(by_code["cometapi-nano-2-generate"])["api_shape"] == "gemini_generate_content"
        assert provider_config(nano_pro)["supports_custom_size"] is True
        assert provider_config(image2)["supports_custom_size"] is True
        assert provider_config(image2)["supports_exact_custom_size"] is True
        assert provider_config(aplus_mobile)["supports_edit"] is True
        assert provider_config(video)["model_family"] == "seedance-2.0"
        assert DEFAULT_ROUTE_CHAINS["video"][0] == "hellobabygo-seedance-2-0-video"
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


def test_route_provider_codes_skips_unkeyed_primary_and_uses_backup(client) -> None:
    with client.app.state.session_factory() as session:
        primary = session.scalar(select(Provider).where(Provider.code == "atlas-gpt-image-2-generate"))
        backup = session.scalar(select(Provider).where(Provider.code == "cometapi-gpt-image-2-generate"))
        assert primary is not None and backup is not None
        primary.enabled = True
        primary.encrypted_api_key = None
        backup.enabled = True
        backup.encrypted_api_key = client.app.state.cipher.encrypt("backup-key")
        session.commit()

        assert route_provider_codes(session, "suite_layout") == ["cometapi-gpt-image-2-generate"]


def test_seed_updates_provider_contract_but_preserves_admin_parameters(client) -> None:
    session_factory = client.app.state.session_factory
    with session_factory() as session:
        provider = session.scalar(select(Provider).where(Provider.code == "wavespeed-gpt-image-2-generate"))
        config = provider_config(provider)
        config.update(
            {
                "quality": "high",
                "resolution": "2K",
                "edit_base_url": "https://old.example.test/wrong-edit",
                "size_param_mode": "size_string",
                "route_roles": {"suite_layout": "backup4"},
            }
        )
        provider.config_json = json.dumps(config, ensure_ascii=False)
        session.commit()

        seed_database(session)
        session.commit()

        refreshed = session.scalar(select(Provider).where(Provider.code == "wavespeed-gpt-image-2-generate"))
        refreshed_config = provider_config(refreshed)
        assert refreshed_config["quality"] == "high"
        assert refreshed_config["resolution"] == "2K"
        assert refreshed_config["size_param_mode"] == "aspect_ratio_resolution"
        assert refreshed_config["edit_base_url"] == "https://api.wavespeed.ai/api/v3/openai/gpt-image-2/edit"
        assert provider_route_roles(refreshed) == {}
        for index, provider_code in enumerate(DEFAULT_ROUTE_CHAINS["suite_layout"]):
            provider = session.scalar(select(Provider).where(Provider.code == provider_code))
            assert provider_route_roles(provider)["suite_layout"] == ROUTE_SLOT_ORDER[index]


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
