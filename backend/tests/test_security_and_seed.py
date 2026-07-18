from sqlalchemy import select

from backend.app.models import Provider, Prompt, PromptVersion, Workflow, WorkflowVersion
from backend.app.security import ApiKeyCipher, mask_api_key
from backend.app.seed import seed_database


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

        assert len(providers) == 7
        assert all(provider.enabled is False for provider in providers)
        assert {provider.model_name for provider in providers} == {
            "bytedance/doubao-seed-2-0-mini",
            "openai/gpt-5.4-mini",
            "ali/qwen3.6-plus",
            "gemini-3.1-flash-image",
            "gemini-3-pro-image",
            "gpt-image-2",
            "bytedance/doubao-seedance-1-5-pro",
        }
        doubao = next(provider for provider in providers if provider.code == "doubao-seed-2-0-mini")
        qwen = next(provider for provider in providers if provider.code == "qwen-3-6")
        nano_pro = next(provider for provider in providers if provider.code == "yunwu-nano-pro")
        nano = next(provider for provider in providers if provider.code == "yunwu-nano")
        image2 = next(provider for provider in providers if provider.code == "yunwu-image-2")
        video = next(provider for provider in providers if provider.code == "shengsuanyun-seedance-1-5-pro")
        assert doubao.is_default is True and doubao.is_fallback is False
        assert qwen.is_default is False and qwen.is_fallback is True
        assert nano_pro.is_default is True and nano_pro.is_fallback is False
        assert nano.is_default is False and nano.is_fallback is True
        assert image2.is_default is False and image2.is_fallback is False
        assert video.capability == "video"
        assert video.is_default is True and video.is_fallback is False
        assert video.base_url.endswith("/api/v1/tasks/generations")
        assert doubao.base_url.endswith("/api/v1/chat/completions")
        assert doubao.model_name == "bytedance/doubao-seed-2-0-mini"
        assert nano_pro.base_url.endswith("/v1beta/models/gemini-3-pro-image:generateContent")
        assert nano.base_url.endswith("/v1beta/models/gemini-3.1-flash-image:generateContent")
        assert prompt is not None and prompt.active_version_id is not None
        assert workflow is not None and workflow.active_version_id is not None
        assert session.get(PromptVersion, prompt.active_version_id).content.startswith(
            "# 电商套图 Meta 提示词（完整修订版）"
        )
        assert session.get(PromptVersion, prompt.active_version_id).content_sha256 == (
            "EF5A14BED89A92B21F0B5EC01E666F788FDE92FF7829D050D011885F7B6C6120"
        )
        assert session.get(WorkflowVersion, workflow.active_version_id).version_no == 1
        copywriting = session.scalar(select(Prompt).where(Prompt.code == "copywriting-assist"))
        video_prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-video-meta-15s"))
        assert video_prompt is not None and video_prompt.active_version_id is not None
        assert "电商 AI 视频 Meta Prompt" in session.get(PromptVersion, video_prompt.active_version_id).content
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
