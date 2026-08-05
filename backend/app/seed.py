from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Prompt, PromptVersion, Provider, Workflow, WorkflowVersion
from backend.app.services.provider_routing import (
    PROVIDER_ROUTE_DEFINITIONS,
    default_route_roles_for_provider,
    normalize_route_roles,
    provider_config,
    write_provider_config,
)
from backend.app.services.workflow_registry import default_workflow_json, workflow_preset_dicts


PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "ecommerce_meta_prompt_v1.md"
APLUS_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "aplus_meta_prompt_0729.md"
LEGACY_VIDEO_PROVIDER_CODE = "shengsuanyun-seedance-1-5-pro"
VIDEO_PROVIDER_CODE = "shengsuanyun-doubao-seedance-2-0"
HELLOBABYGO_IMAGE_URL = "https://api.hellobabygo.com/v1/images/generations"
HELLOBABYGO_VIDEO_URL = "https://api.hellobabygo.com/v1/videos"

AUXILIARY_PROMPT_PRESETS = [
    ("product-vision", "商品视觉事实提取", "读取商品参考图，输出供核心 Meta Prompt 使用的结构化事实。", "product_vision_v1.md"),
    ("copywriting-assist", "AI 卖点帮写", "结合平台、市场、语言与商品事实进行事实型卖点改写。", "copywriting_assist_v1.md"),
    ("edit-rewrite", "二次编辑提示词转写", "将用户修改要求转写为保持商品本体的图片编辑提示词。", "edit_rewrite_v1.md"),
    ("content-safety-review", "内容安全审计", "拦截黄赌毒、政治内容、政治领导人等安全风险。", "content_safety_review_v1.md"),
    ("ecommerce-video-meta-15s", "电商 15 秒视频 Meta Prompt", "根据商品图、卖点、平台与视频类型输出 Seedance 可用的 15 秒电商视频导演脚本。", "ecommerce_video_meta_prompt_15s.md"),
]


PROVIDER_PRESETS = [
    {
        "code": "doubao-seed-2-0-mini",
        "label": "Doubao Seed 2.0 Mini",
        "capability": "llm",
        "adapter": "openai_chat",
        "base_url": "https://router.shengsuanyun.com/api/v1/chat/completions",
        "model_name": "bytedance/doubao-seed-2-0-mini",
        "is_default": True,
        "is_fallback": False,
        "config": {"temperature": 0.2, "timeout_seconds": 90, "response_format": "json_object", "route_roles": {"llm": "primary"}},
    },
    {
        "code": "gpt-5-4-mini",
        "label": "GPT‑5.4‑Mini",
        "capability": "llm",
        "adapter": "openai_chat",
        "base_url": "https://router.shengsuanyun.com/api/v1/chat/completions",
        "model_name": "openai/gpt-5.4-mini",
        "is_default": False,
        "is_fallback": False,
        "config": {"temperature": 0.2, "timeout_seconds": 90, "response_format": "json_object"},
    },
    {
        "code": "qwen-3-6",
        "label": "Qwen‑3.6",
        "capability": "llm",
        "adapter": "openai_chat",
        "base_url": "https://router.shengsuanyun.com/api/v1/chat/completions",
        "model_name": "ali/qwen3.6-plus",
        "is_default": False,
        "is_fallback": True,
        "config": {"temperature": 0.2, "timeout_seconds": 90, "response_format": "json_object", "route_roles": {"llm": "fallback"}},
    },
    {
        "code": "yunwu-nano-pro",
        "label": "HelloBabyGo Nano Banana Pro",
        "capability": "image",
        "adapter": "hellobabygo_image_generation",
        "base_url": HELLOBABYGO_IMAGE_URL,
        "model_name": "nano_banana_pro",
        "is_default": True,
        "is_fallback": False,
        "config": {
            "resolution": "2K",
            "allowed_resolutions": ["1K", "2K", "4K"],
            "size": "auto",
            "allowed_sizes": ["auto", "landscape", "portrait", "square"],
            "timeout_seconds": 600,
            "poll_interval_seconds": 5,
            "route_roles": {"suite_fidelity": "primary"},
        },
    },
    {
        "code": "yunwu-nano",
        "label": "HelloBabyGo Nano Banana 2",
        "capability": "image",
        "adapter": "hellobabygo_image_generation",
        "base_url": HELLOBABYGO_IMAGE_URL,
        "model_name": "nano_banana_2",
        "is_default": False,
        "is_fallback": True,
        "config": {
            "resolution": "1K",
            "allowed_resolutions": ["1K", "2K", "4K"],
            "size": "auto",
            "allowed_sizes": ["auto", "landscape", "portrait", "square"],
            "timeout_seconds": 600,
            "poll_interval_seconds": 5,
            "route_roles": {"suite_fidelity": "fallback"},
        },
    },
    {
        "code": "yunwu-image-2",
        "label": "HelloBabyGo GPT Image 2",
        "capability": "image",
        "adapter": "hellobabygo_image_generation",
        "base_url": HELLOBABYGO_IMAGE_URL,
        "model_name": "gpt-image-2",
        "is_default": False,
        "is_fallback": False,
        "config": {
            "size": "follow_ratio",
            "allowed_sizes": [
                "follow_ratio",
                "1024x1024",
                "1792x1024",
                "1024x1792",
            ],
            "timeout_seconds": 600,
            "poll_interval_seconds": 5,
            "route_roles": {"suite_layout": "primary", "aplus_detail": "primary"},
        },
    },
    {
        "code": "aplus-mobile-edit-low-cost",
        "label": "HelloBabyGo A+ Mobile Image",
        "capability": "image",
        "adapter": "hellobabygo_image_generation",
        "base_url": HELLOBABYGO_IMAGE_URL,
        "model_name": "gpt-image-2",
        "is_default": False,
        "is_fallback": False,
        "config": {
            "size": "follow_ratio",
            "allowed_sizes": [
                "follow_ratio",
                "1024x1024",
                "1792x1024",
                "1024x1792",
            ],
            "timeout_seconds": 600,
            "poll_interval_seconds": 5,
            "route_roles": {"aplus_mobile": "primary"},
        },
    },
    {
        "code": VIDEO_PROVIDER_CODE,
        "label": "HelloBabyGo Seedance 2.0",
        "capability": "video",
        "adapter": "hellobabygo_video_generation",
        "base_url": HELLOBABYGO_VIDEO_URL,
        "model_name": "seedance-2.0",
        "is_default": True,
        "is_fallback": False,
        "config": {
            "timeout_seconds": 900,
            "poll_interval_seconds": 20,
            "route_roles": {"video": "primary"},
        },
    },
]


def ensure_default_provider_route_roles(session: Session) -> None:
    providers = session.scalars(select(Provider)).all()
    assigned_route_keys: set[str] = set()
    for provider in providers:
        assigned_route_keys.update(normalize_route_roles(provider_config(provider).get("route_roles")).keys())
    missing_route_keys = set(PROVIDER_ROUTE_DEFINITIONS) - assigned_route_keys
    if not missing_route_keys:
        return
    by_code = {provider.code: provider for provider in providers}
    for provider_code, route_roles in ((code, default_route_roles_for_provider(code)) for code in by_code):
        relevant_roles = {route_key: role for route_key, role in route_roles.items() if route_key in missing_route_keys}
        if not relevant_roles:
            continue
        provider = by_code[provider_code]
        config = provider_config(provider)
        roles = normalize_route_roles(config.get("route_roles"))
        roles.update(relevant_roles)
        config["route_roles"] = roles
        write_provider_config(provider, config)


def seed_database(session: Session) -> None:
    legacy_video = session.scalar(select(Provider).where(Provider.code == LEGACY_VIDEO_PROVIDER_CODE))
    current_video = session.scalar(select(Provider).where(Provider.code == VIDEO_PROVIDER_CODE))
    if legacy_video and not current_video:
        legacy_video.code = VIDEO_PROVIDER_CODE
        session.flush()

    for preset in PROVIDER_PRESETS:
        existing = session.scalar(select(Provider).where(Provider.code == preset["code"]))
        if existing:
            existing.label = preset["label"]
            existing.adapter = preset["adapter"]
            existing.base_url = preset["base_url"]
            existing.model_name = preset["model_name"]
            existing.is_default = preset["is_default"]
            existing.is_fallback = preset["is_fallback"]
            if preset["capability"] in {"image", "video"}:
                existing_config = json.loads(existing.config_json or "{}")
                existing_roles = normalize_route_roles(existing_config.get("route_roles"))
                config = {**existing_config, **preset["config"]}
                if existing_roles:
                    config["route_roles"] = existing_roles
                if preset["capability"] == "image":
                    for key in ("aspect_ratio", "format", "compression", "quality", "style", "response_format"):
                        config.pop(key, None)
                if preset["capability"] == "video":
                    for key in (
                        "image_role",
                        "return_last_frame",
                        "draft",
                        "tools",
                        "duration",
                        "allowed_durations",
                        "resolution",
                        "allowed_resolutions",
                        "generate_audio",
                        "camera_fixed",
                        "watermark",
                    ):
                        config.pop(key, None)
                existing.config_json = json.dumps(config, ensure_ascii=False)
            continue
        session.add(
            Provider(
                code=preset["code"],
                label=preset["label"],
                capability=preset["capability"],
                adapter=preset["adapter"],
                base_url=preset["base_url"],
                model_name=preset["model_name"],
                enabled=False,
                is_default=preset["is_default"],
                is_fallback=preset["is_fallback"],
                config_json=json.dumps(preset["config"], ensure_ascii=False),
            )
        )
    session.flush()
    ensure_default_provider_route_roles(session)

    legacy_video = session.scalar(select(Provider).where(Provider.code == LEGACY_VIDEO_PROVIDER_CODE))
    if legacy_video:
        legacy_video.is_default = False
        legacy_video.is_fallback = False

    doubao = session.scalar(select(Provider).where(Provider.code == "doubao-seed-2-0-mini"))
    qwen = session.scalar(select(Provider).where(Provider.code == "qwen-3-6"))
    legacy_gpt = session.scalar(select(Provider).where(Provider.code == "gpt-5-4-mini"))
    llm_key_donor = next(
        (
            provider
            for provider in (qwen, legacy_gpt, doubao)
            if provider and provider.encrypted_api_key
        ),
        None,
    )
    if llm_key_donor:
        for provider in (doubao, qwen):
            if provider and not provider.encrypted_api_key:
                provider.encrypted_api_key = llm_key_donor.encrypted_api_key
                provider.enabled = llm_key_donor.enabled

    nano_pro = session.scalar(select(Provider).where(Provider.code == "yunwu-nano-pro"))
    nano2 = session.scalar(select(Provider).where(Provider.code == "yunwu-nano"))
    if nano_pro and nano2 and not nano_pro.encrypted_api_key and nano2.encrypted_api_key:
        # 同一中转站 API Key 可调用模型目录中的不同图片模型。
        nano_pro.encrypted_api_key = nano2.encrypted_api_key
        nano_pro.enabled = nano2.enabled
    image2 = session.scalar(select(Provider).where(Provider.code == "yunwu-image-2"))
    aplus_mobile = session.scalar(select(Provider).where(Provider.code == "aplus-mobile-edit-low-cost"))
    if image2 and aplus_mobile and not aplus_mobile.encrypted_api_key and image2.encrypted_api_key:
        aplus_mobile.encrypted_api_key = image2.encrypted_api_key
        aplus_mobile.enabled = image2.enabled

    prompt = session.scalar(select(Prompt).where(Prompt.code == "ecommerce-meta"))
    if not prompt:
        prompt = Prompt(
            code="ecommerce-meta",
            name="电商套图 Meta Prompt",
            description="用户提供的核心资产原文；运行时追加 JSON 输出契约。",
        )
        session.add(prompt)
        session.flush()
        prompt_bytes = PROMPT_PATH.read_bytes()
        prompt_version = PromptVersion(
            prompt_id=prompt.id,
            version_no=1,
            content=prompt_bytes.decode("utf-8-sig"),
            content_sha256=hashlib.sha256(prompt_bytes).hexdigest().upper(),
            change_note="导入用户提供的完整修订版原文",
        )
        session.add(prompt_version)
        session.flush()
        prompt.active_version_id = prompt_version.id

    for code, name, description, filename in AUXILIARY_PROMPT_PRESETS:
        auxiliary = session.scalar(select(Prompt).where(Prompt.code == code))
        content = (PROMPT_PATH.parent / filename).read_text(encoding="utf-8")
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest().upper()
        if auxiliary:
            if code == "copywriting-assist":
                active_version = (
                    session.get(PromptVersion, auxiliary.active_version_id)
                    if auxiliary.active_version_id
                    else None
                )
                if not active_version or active_version.content_sha256 != content_sha256:
                    versions = session.scalars(select(PromptVersion).where(PromptVersion.prompt_id == auxiliary.id)).all()
                    version = PromptVersion(
                        prompt_id=auxiliary.id,
                        version_no=max((item.version_no for item in versions), default=0) + 1,
                        content=content,
                        content_sha256=content_sha256,
                        change_note="升级 AI 帮写 Prompt：接入完整场景与卖点 workflow",
                    )
                    session.add(version)
                    session.flush()
                    auxiliary.active_version_id = version.id
                    auxiliary.description = description
            continue
        auxiliary = Prompt(code=code, name=name, description=description)
        session.add(auxiliary)
        session.flush()
        version = PromptVersion(
            prompt_id=auxiliary.id,
            version_no=1,
            content=content,
            content_sha256=content_sha256,
            change_note="内置 Prompt 工程首版",
        )
        session.add(version)
        session.flush()
        auxiliary.active_version_id = version.id

    aplus_prompt = session.scalar(select(Prompt).where(Prompt.code == "aplus-meta"))
    aplus_content = APLUS_PROMPT_PATH.read_text(encoding="utf-8-sig")
    aplus_content_sha256 = hashlib.sha256(aplus_content.encode("utf-8")).hexdigest().upper()
    if not aplus_prompt:
        aplus_prompt = Prompt(
            code="aplus-meta",
            name="A+ 详情页 Meta Prompt",
            description="二期详情页模块方案 Prompt，使用用户上传的 0729 版本作为首版。",
        )
        session.add(aplus_prompt)
        session.flush()
        version = PromptVersion(
            prompt_id=aplus_prompt.id,
            version_no=1,
            content=aplus_content,
            content_sha256=aplus_content_sha256,
            change_note="导入用户提供的 A+ 详情页提示词 0729",
        )
        session.add(version)
        session.flush()
        aplus_prompt.active_version_id = version.id
    else:
        active_version = (
            session.get(PromptVersion, aplus_prompt.active_version_id)
            if aplus_prompt.active_version_id
            else None
        )
        if not active_version or active_version.content_sha256 != aplus_content_sha256:
            versions = session.scalars(select(PromptVersion).where(PromptVersion.prompt_id == aplus_prompt.id)).all()
            version = PromptVersion(
                prompt_id=aplus_prompt.id,
                version_no=max((item.version_no for item in versions), default=0) + 1,
                content=aplus_content,
                content_sha256=aplus_content_sha256,
                change_note="升级 A+ 详情页 Meta Prompt：0729 版本",
            )
            session.add(version)
            session.flush()
            aplus_prompt.active_version_id = version.id
        aplus_prompt.description = "二期详情页模块方案 Prompt，使用用户上传的 0729 版本。"

    for preset in workflow_preset_dicts():
        graph_json = json.dumps(preset["graph"], ensure_ascii=False, separators=(",", ":"))
        workflow = session.scalar(select(Workflow).where(Workflow.code == preset["code"]))
        if not workflow:
            workflow = Workflow(
                code=preset["code"],
                name=preset["name"],
                description=preset["description"],
            )
            session.add(workflow)
            session.flush()
            workflow_version = WorkflowVersion(
                workflow_id=workflow.id,
                version_no=1,
                graph_json=graph_json,
                change_note=preset["change_note"],
            )
            session.add(workflow_version)
            session.flush()
            workflow.active_version_id = workflow_version.id
            continue
        workflow.name = preset["name"]
        workflow.description = preset["description"]
        active_workflow = session.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
        needs_default_version = not active_workflow
        if workflow.code == "product-suite-v1" and active_workflow:
            needs_default_version = "product_vision" not in active_workflow.graph_json or "image_qa" in active_workflow.graph_json
        if needs_default_version:
            versions = session.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)).all()
            upgraded = WorkflowVersion(
                workflow_id=workflow.id,
                version_no=max((item.version_no for item in versions), default=0) + 1,
                graph_json=graph_json if workflow.code != "product-suite-v1" else default_workflow_json(),
                change_note="移除生成审查节点，保留商品视觉事实与语义审查" if workflow.code == "product-suite-v1" else preset["change_note"],
            )
            session.add(upgraded)
            session.flush()
            workflow.active_version_id = upgraded.id

    session.commit()
