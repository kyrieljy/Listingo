from io import BytesIO
import json
from zipfile import ZipFile

from PIL import Image
from sqlalchemy import select

from backend.app.api.public import build_copywriting_user_prompt
from backend.app.models import Provider
from backend.app.schemas import CopywritingAssistCreate
from backend.app.services.aplus_jobs import DEMO_ASSETS


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


def test_dryrun_job_completes_without_external_calls_and_exports_zip(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "双层保温，防滑握持，通勤便携",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    detail = client.get(f"/api/v1/generation-jobs/{job['id']}").json()

    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert len(detail["items"]) == 7
    assert all(item["status"] == "succeeded" for item in detail["items"])
    assert all(item["versions"][0]["url"].startswith("/files/results/") for item in detail["items"])

    item_ids = ",".join(item["id"] for item in detail["items"][:3])
    archive = client.get(
        f"/api/v1/generation-jobs/{job['id']}/download",
        params={"item_ids": item_ids},
    )
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archive.content)) as zip_file:
        assert len(zip_file.namelist()) == 3

    long_image = client.get(
        f"/api/v1/generation-jobs/{job['id']}/download",
        params={"item_ids": item_ids, "format": "long_image"},
    )
    assert long_image.status_code == 200
    assert long_image.headers["content-type"] == "image/png"
    with Image.open(BytesIO(long_image.content)) as image:
        assert image.height > image.width


def test_aplus_dryrun_plan_and_generation_respect_amazon_a_plus_ratios(client) -> None:
    assert [asset.name for asset in DEMO_ASSETS] == [f"aplus-outdoor-module-{index:02d}.png" for index in range(1, 11)]
    assert len({asset.name for asset in DEMO_ASSETS}) == 10

    asset_id = upload_asset(client)
    plan_response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "便携保温杯，适合通勤。",
            "selected_modules": ["首屏主视觉", "核心卖点图"],
            "output_targets": [
                {"mode": "amazon_aplus_advanced_web", "aspect_ratio": "1464:600"},
                {"mode": "amazon_aplus_advanced_mobile", "aspect_ratio": "600:450"},
            ],
            "dry_run": True,
        },
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = client.get(f"/api/v1/aplus-plan-jobs/{plan_response.json()['id']}").json()
    assert plan["status"] == "succeeded"
    assert [item["module_name"] for item in plan["items"]] == ["首屏主视觉", "核心卖点图"]

    generation_response = client.post(
        "/api/v1/aplus-generation-jobs",
        json={
            "plan_job_id": plan["id"],
            "module_item_ids": [item["id"] for item in plan["items"]],
            "output_targets": plan["params"]["output_targets"],
            "dry_run": True,
        },
    )
    assert generation_response.status_code == 201, generation_response.text
    generation = client.get(f"/api/v1/aplus-generation-jobs/{generation_response.json()['id']}").json()
    assert generation["status"] == "succeeded"
    assert len(generation["items"]) == 4
    assert {item["aspect_ratio"] for item in generation["items"]} == {"1464:600", "600:450"}
    mobile_items = [item for item in generation["items"] if item["output_mode"] == "amazon_aplus_advanced_mobile"]
    assert len(mobile_items) == 2
    assert all(item["source_web_item_id"] for item in mobile_items)

    archive = client.get(
        f"/api/v1/aplus-generation-jobs/{generation['id']}/download",
        params={"item_ids": ",".join(item["id"] for item in generation["items"][:2])},
    )
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"


def test_aplus_advanced_mobile_only_uses_direct_generation_path(client) -> None:
    asset_id = upload_asset(client)
    plan_response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "便携保温杯，适合通勤。",
            "selected_modules": ["首屏主视觉", "核心卖点图"],
            "output_targets": [{"mode": "amazon_aplus_advanced_mobile", "aspect_ratio": "600:450"}],
            "dry_run": True,
        },
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = client.get(f"/api/v1/aplus-plan-jobs/{plan_response.json()['id']}").json()

    generation_response = client.post(
        "/api/v1/aplus-generation-jobs",
        json={
            "plan_job_id": plan["id"],
            "module_item_ids": [item["id"] for item in plan["items"]],
            "output_targets": plan["params"]["output_targets"],
            "dry_run": True,
        },
    )
    assert generation_response.status_code == 201, generation_response.text
    generation = client.get(f"/api/v1/aplus-generation-jobs/{generation_response.json()['id']}").json()

    assert generation["status"] == "succeeded"
    assert len(generation["items"]) == 2
    assert {item["output_mode"] for item in generation["items"]} == {"amazon_aplus_advanced_mobile"}
    assert all(item["aspect_ratio"] == "600:450" for item in generation["items"])
    assert all(item["source_web_item_id"] is None for item in generation["items"])


def test_aplus_rejects_mixed_output_specs(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "product_info": "",
            "selected_modules": ["首屏主视觉"],
            "output_targets": [
                {"mode": "detail", "aspect_ratio": "1:1"},
                {"mode": "amazon_aplus_standard", "aspect_ratio": "970:600"},
            ],
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "每次只能选择一个" in response.text


def test_aplus_rejects_amazon_a_plus_targets_for_non_amazon_platform(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/aplus-plan-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Temu",
            "market": "美国",
            "language": "英文",
            "product_info": "",
            "selected_modules": ["首屏主视觉"],
            "output_targets": [{"mode": "amazon_aplus_standard", "aspect_ratio": "970:600"}],
            "dry_run": True,
        },
    )
    assert response.status_code == 422
    assert "只支持亚马逊平台" in response.text


def test_video_dryrun_creates_one_item_per_selected_type(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/video-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "TikTok",
            "market": "北美",
            "country": "美国",
            "language": "英语",
            "aspect_ratio": "9:16",
            "selling_points": "便携、防漏、适合通勤",
            "video_types": ["UGC 种草", "痛点解决"],
            "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/video-jobs/{response.json()['id']}").json()

    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert all(item["versions"][0]["url"] == "/demo/video-skincare-result.png" for item in detail["items"])
    assert all("tumbler" not in item["versions"][0]["url"] for item in detail["items"])
    assert [item["video_type"] for item in detail["items"]] == ["UGC 种草", "痛点解决"]
    assert all(item["status"] == "succeeded" for item in detail["items"])
    assert all(item["script_markdown"].startswith("# 15 秒电商短视频脚本") for item in detail["items"])


def test_video_live_rejects_missing_public_asset_base_url_after_provider_checks(client) -> None:
    asset_id = upload_asset(client)
    session_factory = client.app.state.session_factory
    cipher = client.app.state.cipher
    with session_factory() as session:
        providers = session.scalars(select(Provider)).all()
        for provider in providers:
            if provider.capability in {"llm", "video"}:
                provider.enabled = True
                provider.encrypted_api_key = cipher.encrypt("sk-test")
        session.commit()

    response = client.post(
        "/api/v1/video-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "TikTok",
            "market": "北美",
            "country": "美国",
            "language": "英语",
            "aspect_ratio": "9:16",
            "selling_points": "便携、防漏、适合通勤",
            "video_types": ["UGC 种草"],
            "dry_run": False,
        },
    )

    assert response.status_code == 409
    assert "PUBLIC_ASSET_BASE_URL" in response.json()["detail"]


def test_dryrun_edit_creates_child_version_and_keeps_original(client) -> None:
    asset_id = upload_asset(client)
    job = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "1:1",
            "selling_points": "保温杯",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    ).json()
    detail = client.get(f"/api/v1/generation-jobs/{job['id']}").json()
    item = detail["items"][0]
    first_version = item["versions"][0]

    response = client.post(
        f"/api/v1/generation-items/{item['id']}/versions",
        json={"instruction": "背景改为更明亮的淡紫色，产品不变"},
    )
    assert response.status_code == 201, response.text
    child = response.json()

    assert child["version_no"] == 2
    assert child["parent_version_id"] == first_version["id"]
    assert child["url"] != first_version["url"]


def test_validation_rejects_four_uploads_and_invalid_count(client) -> None:
    asset_ids = [upload_asset(client) for _ in range(4)]
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": asset_ids,
            "platform": "Amazon",
            "market": "美国",
            "language": "English",
            "aspect_ratio": "2:3",
            "selling_points": "测试",
            "mode": "smart",
            "count": 6,
            "dry_run": True,
        },
    )
    assert response.status_code == 422


def test_custom_counts_drive_dryrun_plan_and_are_limited_to_four_each(client) -> None:
    asset_id = upload_asset(client)
    payload = {
        "asset_ids": [asset_id],
        "platform": "亚马逊",
        "market": "美国",
        "language": "英语",
        "aspect_ratio": "1:1",
        "selling_points": "双层保温，防滑握持，通勤便携",
        "mode": "custom",
        "count": 7,
        "custom_counts": {
            "white_background": 1,
            "scene": 2,
            "selling_point": 2,
            "other": 2,
        },
        "model_preference": "fidelity",
        "dry_run": True,
    }

    response = client.post("/api/v1/generation-jobs", json=payload)

    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/generation-jobs/{response.json()['id']}").json()
    assert [item["image_type"].split(" ")[0] for item in detail["items"]] == [
        "白底图",
        "场景图",
        "场景图",
        "卖点图",
        "卖点图",
        "其他图",
        "其他图",
    ]
    assert detail["params"]["custom_counts"] == payload["custom_counts"]
    assert detail["params"]["model_preference"] == "fidelity"

    too_many = {**payload, "count": 10, "custom_counts": {**payload["custom_counts"], "scene": 5}}
    invalid = client.post("/api/v1/generation-jobs", json=too_many)
    assert invalid.status_code == 422


def test_ai_copywriting_dryrun_uses_backend_prompted_flow(client) -> None:
    response = client.post(
        "/api/v1/copywriting-assist",
        json={
            "platform": "淘宝/天猫",
            "market": "中国大陆",
            "language": "简体中文",
            "selling_points": "保温杯，防滑",
            "dry_run": True,
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["dry_run"] is True
    assert result["provider_code"] is None
    assert "保温杯" in result["selling_points"]
    assert "### 1. 商品定位" in result["selling_points"]
    assert "### 2. 适用场景" in result["selling_points"]
    assert "### 3. 5大核心卖点" in result["selling_points"]
    assert "淘宝/天猫" not in result["selling_points"]


def test_ai_copywriting_rejects_unsafe_input_text_before_generation(client) -> None:
    response = client.post(
        "/api/v1/copywriting-assist",
        json={
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "selling_points": "使用习近平照片做宣传",
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "输入内容安全拦截" in response.json()["detail"]


def test_ai_copywriting_live_prompt_separates_image_language_from_output_language() -> None:
    prompt = build_copywriting_user_prompt(
        CopywritingAssistCreate(
            platform="亚马逊",
            market="美国",
            language="英文",
            selling_points="保温杯，防滑",
            dry_run=False,
        )
    )
    data = json.loads(prompt)

    assert data["output_language"] == "简体中文"
    assert data["image_text_language"] == "英文"
    assert data["input_mode"] == "image_with_text"
    assert "language" not in data
    assert "必须使用简体中文" in data["instruction"]

    image_only = json.loads(
        build_copywriting_user_prompt(
            CopywritingAssistCreate(platform="亚马逊", market="美国", language="英文", selling_points="")
        )
    )
    assert image_only["input_mode"] == "image_only"


def test_generation_job_accepts_structured_product_and_brand_inputs(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英语",
            "aspect_ratio": "2:3",
            "selling_points": "双层保温",
            "product_name": "通勤保温杯",
            "category": "饮水器具",
            "specifications": "500ml",
            "sku_info": "白色单品",
            "accessories": "杯盖",
            "certifications": "未提供",
            "target_audience": "通勤人群",
            "brand_style": "克制、现代、蓝灰色",
            "mode": "smart",
            "count": 8,
            "model_preference": "fidelity",
            "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["params"]["product_name"] == "通勤保温杯"
    assert job["params"]["aspect_ratio"] == "2:3"
    assert job["count"] == 8


def test_generation_job_rejects_unsafe_input_text_before_job_creation(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id],
            "platform": "亚马逊",
            "market": "美国",
            "language": "英文",
            "aspect_ratio": "1:1",
            "selling_points": "宣传赌博博彩玩法",
            "mode": "smart",
            "count": 7,
            "dry_run": True,
        },
    )

    assert response.status_code == 422
    assert "输入内容安全拦截" in response.json()["detail"]


def test_dryrun_executes_the_extended_prompt_workflow_without_external_calls(client) -> None:
    asset_id = upload_asset(client)
    response = client.post(
        "/api/v1/generation-jobs",
        json={
            "asset_ids": [asset_id], "platform": "亚马逊", "market": "美国", "language": "无文字",
            "aspect_ratio": "4:5", "selling_points": "双层保温", "brand_style": "现代克制",
            "mode": "smart", "count": 7, "model_preference": "fidelity", "dry_run": True,
        },
    )
    assert response.status_code == 201, response.text
    detail = client.get(f"/api/v1/generation-jobs/{response.json()['id']}").json()
    assert set(detail["params"]["_prompt_versions"]) == {
        "product-vision", "copywriting-assist", "edit-rewrite", "content-safety-review"
    }
    logs = client.get("/api/v1/admin/logs", params={"job_id": detail["id"], "page_size": 100}).json()["items"]
    nodes = {log["node"] for log in logs}
    assert {"product_vision", "meta_prompt", "semantic_validator", "image_generate", "aggregate"}.issubset(nodes)
    assert "image_qa" not in nodes
