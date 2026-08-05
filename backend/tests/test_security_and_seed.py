import json

from sqlalchemy import select

from backend.app.models import Provider, Prompt, PromptVersion, Workflow, WorkflowVersion
from backend.app.security import ApiKeyCipher, mask_api_key
from backend.app.seed import LEGACY_VIDEO_PROVIDER_CODE, VIDEO_PROVIDER_CODE, seed_database


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

        assert len(providers) == 8
        assert all(provider.enabled is False for provider in providers)
        assert {provider.model_name for provider in providers} == {
            "bytedance/doubao-seed-2-0-mini",
            "openai/gpt-5.4-mini",
            "ali/qwen3.6-plus",
            "nano_banana_2",
            "nano_banana_pro",
            "gpt-image-2",
            "seedance-2.0",
        }
        aplus_mobile = next(provider for provider in providers if provider.code == "aplus-mobile-edit-low-cost")
        doubao = next(provider for provider in providers if provider.code == "doubao-seed-2-0-mini")
        qwen = next(provider for provider in providers if provider.code == "qwen-3-6")
        nano_pro = next(provider for provider in providers if provider.code == "yunwu-nano-pro")
        nano = next(provider for provider in providers if provider.code == "yunwu-nano")
        image2 = next(provider for provider in providers if provider.code == "yunwu-image-2")
        video = next(provider for provider in providers if provider.code == "shengsuanyun-doubao-seedance-2-0")
        assert doubao.is_default is True and doubao.is_fallback is False
        assert qwen.is_default is False and qwen.is_fallback is True
        assert nano_pro.is_default is True and nano_pro.is_fallback is False
        assert nano.is_default is False and nano.is_fallback is True
        assert image2.is_default is False and image2.is_fallback is False
        assert json.loads(image2.config_json)["route_roles"] == {"suite_layout": "primary", "aplus_detail": "primary"}
        assert image2.adapter == "hellobabygo_image_generation"
        assert image2.base_url == "https://api.hellobabygo.com/v1/images/generations"
        assert "quality" not in json.loads(image2.config_json)
        assert "style" not in json.loads(image2.config_json)
        assert "response_format" not in json.loads(image2.config_json)
        assert aplus_mobile.capability == "image"
        assert aplus_mobile.adapter == "hellobabygo_image_generation"
        assert aplus_mobile.base_url == "https://api.hellobabygo.com/v1/images/generations"
        assert aplus_mobile.is_default is False and aplus_mobile.is_fallback is False
        assert json.loads(aplus_mobile.config_json)["route_roles"] == {"aplus_mobile": "primary"}
        assert "quality" not in json.loads(aplus_mobile.config_json)
        assert "style" not in json.loads(aplus_mobile.config_json)
        assert "response_format" not in json.loads(aplus_mobile.config_json)
        assert video.capability == "video"
        assert video.is_default is True and video.is_fallback is False
        assert video.adapter == "hellobabygo_video_generation"
        assert video.base_url == "https://api.hellobabygo.com/v1/videos"
        assert video.model_name == "seedance-2.0"
        assert "image_role" not in json.loads(video.config_json)
        assert "duration" not in json.loads(video.config_json)
        assert "resolution" not in json.loads(video.config_json)
        assert "generate_audio" not in json.loads(video.config_json)
        assert "watermark" not in json.loads(video.config_json)
        assert json.loads(video.config_json)["route_roles"] == {"video": "primary"}
        assert json.loads(doubao.config_json)["route_roles"] == {"llm": "primary"}
        assert json.loads(qwen.config_json)["route_roles"] == {"llm": "fallback"}
        assert json.loads(nano_pro.config_json)["route_roles"] == {"suite_fidelity": "primary"}
        assert json.loads(nano.config_json)["route_roles"] == {"suite_fidelity": "fallback"}
        assert "quality" not in json.loads(nano_pro.config_json)
        assert "format" not in json.loads(nano_pro.config_json)
        assert "quality" not in json.loads(nano.config_json)
        assert "format" not in json.loads(nano.config_json)
        assert doubao.base_url.endswith("/api/v1/chat/completions")
        assert doubao.model_name == "bytedance/doubao-seed-2-0-mini"
        assert nano_pro.adapter == "hellobabygo_image_generation"
        assert nano.adapter == "hellobabygo_image_generation"
        assert nano_pro.base_url == "https://api.hellobabygo.com/v1/images/generations"
        assert nano.base_url == "https://api.hellobabygo.com/v1/images/generations"
        assert prompt is not None and prompt.active_version_id is not None
        assert workflow is not None and workflow.active_version_id is not None
        assert session.get(PromptVersion, prompt.active_version_id).content.startswith(
            "# 电商套图 Meta 提示词（完整修订版）"
        )
        assert session.get(PromptVersion, prompt.active_version_id).content_sha256 == (
            "EF5A14BED89A92B21F0B5EC01E666F788FDE92FF7829D050D011885F7B6C6120"
        )
        assert session.get(WorkflowVersion, workflow.active_version_id).version_no == 1
        assert {item.code for item in workflows} == {"aplus-detail-v1", "product-suite-v1", "video-v1"}
        assert all(item.active_version_id for item in workflows)
        copywriting = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
        video_prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-video-meta-15s"))
        aplus_prompt = session.scalar(select(Prompt).where(Prompt.code == "aplus-meta"))
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
        video = session.scalar(select(Provider).where(Provider.code == VIDEO_PROVIDER_CODE))
        video.code = LEGACY_VIDEO_PROVIDER_CODE
        video.model_name = "bytedance/doubao-seedance-1-5-pro"
        session.commit()

        seed_database(session)

        current_video = session.scalar(select(Provider).where(Provider.code == VIDEO_PROVIDER_CODE))
        legacy_video = session.scalar(select(Provider).where(Provider.code == LEGACY_VIDEO_PROVIDER_CODE))
        providers = session.scalars(select(Provider)).all()
        assert current_video is not None
        assert legacy_video is None
        assert current_video.model_name == "seedance-2.0"
        assert current_video.adapter == "hellobabygo_video_generation"
        assert "image_role" not in json.loads(current_video.config_json)
        assert len(providers) == 8


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
