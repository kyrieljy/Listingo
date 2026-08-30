from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from sqlalchemy import delete, select

from backend.app.config import Settings
from backend.app.core.storage.keys import queue_key, sensitive_word_meta_key, sensitive_word_snapshot_key
from backend.app.models import AplusJob, BatchJob, GenerationJob, QuotaLedger, SensitiveWordSnapshot, User, VideoJob
from backend.app.services import sensitive_preflight


def make_png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (640, 640), "#ffffff").save(buffer, format="PNG")
    return buffer.getvalue()


def upload_asset(client) -> str:
    response = client.post("/api/v1/assets", files={"file": ("product.png", make_png(), "image/png")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def configure_word(client, term: str = "套图", enabled: bool = True) -> str:
    created = client.post("/api/v1/admin/sensitive-words", json={"term": term, "aliases": [], "enabled": True})
    assert created.status_code == 200, created.text
    settings = client.patch("/api/v1/admin/sensitive-words/settings", json={"enabled": enabled})
    assert settings.status_code == 200, settings.text
    return created.json()["id"]


def suite_payload(asset_id: str, selling_points: str = "便携保温，通勤便携") -> dict:
    return {
        "asset_ids": [asset_id],
        "platform": "Amazon",
        "market": "美国",
        "language": "English",
        "aspect_ratio": "1:1",
        "selling_points": selling_points,
        "mode": "smart",
        "count": 7,
        "dry_run": True,
    }


def aplus_payload(asset_id: str, product_info: str = "便携保温杯，适合通勤。") -> dict:
    return {
        "asset_ids": [asset_id],
        "platform": "亚马逊",
        "market": "美国",
        "language": "英文",
        "product_info": product_info,
        "module_selections": [{"name": "商品主视觉", "count": 1}],
        "output_targets": [{"mode": "detail", "aspect_ratio": "1:1"}],
        "dry_run": True,
    }


def video_payload(asset_id: str, selling_points: str = "便携、防漏、适合通勤") -> dict:
    return {
        "asset_ids": [asset_id],
        "platform": "TikTok",
        "market": "北美",
        "country": "美国",
        "language": "英语",
        "aspect_ratio": "9:16",
        "selling_points": selling_points,
        "video_types": ["UGC 种草"],
        "dry_run": True,
    }


def assert_no_runtime_side_effects(client) -> None:
    with client.app.state.session_factory() as session:
        assert session.scalar(select(GenerationJob).limit(1)) is None
        assert session.scalar(select(AplusJob).limit(1)) is None
        assert session.scalar(select(VideoJob).limit(1)) is None
        assert session.scalar(select(BatchJob).limit(1)) is None
        assert session.scalar(select(QuotaLedger).limit(1)) is None
    storage = client.app.state.runtime_state.storage
    assert storage.queue_length(queue_key("generation")) == 0
    assert storage.queue_length(queue_key("video")) == 0


def test_sensitive_word_admin_crud_preview_settings_and_snapshot(client) -> None:
    preview = client.post(
        "/api/v1/admin/sensitive-words/preview",
        json={"term": "套图", "aliases": ["tao圖"], "enabled": True},
    )
    assert preview.status_code == 200, preview.text
    assert "taotu" in preview.json()["previews"][0]["variants"]

    created = client.post("/api/v1/admin/sensitive-words", json={"term": "套图", "aliases": ["tao圖"], "enabled": True})
    assert created.status_code == 200, created.text
    assert created.json()["redis_synced"] is True
    assert "taotu" in created.json()["variants"]

    listed = client.get("/api/v1/admin/sensitive-words")
    assert listed.status_code == 200, listed.text
    assert listed.json()["config"]["enabled"] is False
    assert listed.json()["words"][0]["variant_count"] >= 2
    assert listed.json()["snapshot"]["in_sync"] is True

    enabled = client.patch("/api/v1/admin/sensitive-words/settings", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True

    storage = client.app.state.runtime_state.storage
    meta = storage.get(sensitive_word_meta_key())
    snapshot = storage.get(sensitive_word_snapshot_key())
    assert meta.expires_in_seconds is None
    assert snapshot.expires_in_seconds is None

    word_id = created.json()["id"]
    updated = client.patch(f"/api/v1/admin/sensitive-words/{word_id}", json={"note": "人工维护"})
    assert updated.status_code == 200, updated.text
    rebuilt = client.post("/api/v1/admin/sensitive-words/snapshot/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["snapshot"]["in_sync"] is True

    deleted = client.delete(f"/api/v1/admin/sensitive-words/{word_id}")
    assert deleted.status_code == 200, deleted.text


def test_sensitive_word_admin_requires_admin(client) -> None:
    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        user.role = "user"
        session.commit()
    try:
        assert client.get("/api/v1/admin/sensitive-words").status_code == 403
    finally:
        with client.app.state.session_factory() as session:
            user = session.scalar(select(User).where(User.username == "admin"))
            assert user is not None
            user.role = "admin"
            session.commit()


def test_generation_aplus_video_and_batch_text_hits_block_before_side_effects(client, monkeypatch) -> None:
    asset_id = upload_asset(client)
    configure_word(client)
    monkeypatch.setattr(
        sensitive_preflight,
        "detect_text_lines_with_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("text hit must skip OCR")),
    )

    suite = client.post("/api/v1/generation-jobs", json=suite_payload(asset_id, "需要套 图素材"))
    aplus = client.post("/api/v1/aplus-plan-jobs", json=aplus_payload(asset_id, "需要套 图素材"))
    video = client.post("/api/v1/video-jobs", json=video_payload(asset_id, "需要套 图素材"))
    batch = client.post(
        "/api/v1/batch-jobs",
        json={
            "business_type": "suite",
            "global_params": {"platform": "Amazon", "market": "美国", "language": "English"},
            "items": [{"asset_ids": [asset_id], "name": "suite", "selling_points": "需要套 图素材"}],
        },
    )

    assert [(item.status_code, item.json()) for item in (suite, aplus, video, batch)] == [
        (422, {"detail": "包含敏感信息"}),
        (422, {"detail": "包含敏感信息"}),
        (422, {"detail": "包含敏感信息"}),
        (422, {"detail": "包含敏感信息"}),
    ]
    assert_no_runtime_side_effects(client)


def test_batch_scans_every_item_before_any_partial_creation(client) -> None:
    asset_id = upload_asset(client)
    configure_word(client, "普通专属敏感token")

    response = client.post(
        "/api/v1/batch-jobs",
        json={
            "business_type": "suite",
            "global_params": {},
            "items": [
                {"asset_ids": [asset_id], "name": "safe", "selling_points": "普通描述"},
                {"asset_ids": [asset_id], "name": "blocked", "selling_points": "前缀普通专属敏感token后缀"},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "包含敏感信息"}
    assert_no_runtime_side_effects(client)


def test_uploaded_and_preflight_ocr_share_cached_sensitive_scan(client, monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "uploaded.png"
    calls: list[str] = []

    def fake_detect(path, _settings=None, _language_hint=None):
        calls.append(str(path))
        return SimpleNamespace(lines=[SimpleNamespace(text="OCR 识别到 tao图")], warning=None)

    monkeypatch.setattr(sensitive_preflight, "detect_text_lines_with_status", fake_detect)
    assert sensitive_preflight.prewarm_uploaded_asset_ocr(str(image_path), Settings(testing=True)) is None
    assert calls == []
    sensitive_preflight.prewarm_uploaded_asset_ocr(str(image_path), Settings(testing=False))
    assert calls == [str(image_path)]

    asset_id = upload_asset(client)
    configure_word(client)
    response = client.post("/api/v1/generation-jobs", json=suite_payload(asset_id, "普通卖点"))

    assert response.status_code == 422
    assert response.json() == {"detail": "包含敏感信息"}
    assert len(calls) == 2
    assert_no_runtime_side_effects(client)


def test_global_switch_disable_skips_configured_sensitive_detection(client) -> None:
    asset_id = upload_asset(client)
    configure_word(client, "uniquesecrettoken", enabled=False)

    response = client.post("/api/v1/generation-jobs", json=suite_payload(asset_id, "包含 uniquesecrettoken"))

    assert response.status_code == 201, response.text
    with client.app.state.session_factory() as session:
        assert session.scalar(select(GenerationJob).limit(1)) is not None


def test_redis_and_postgres_snapshot_double_miss_fails_open(client) -> None:
    asset_id = upload_asset(client)
    configure_word(client, "customdoublemisstoken")
    storage = client.app.state.runtime_state.storage
    storage.delete(sensitive_word_meta_key())
    storage.delete(sensitive_word_snapshot_key())
    with client.app.state.session_factory() as session:
        session.execute(delete(SensitiveWordSnapshot))
        session.commit()

    response = client.post("/api/v1/generation-jobs", json=suite_payload(asset_id, "包含 customdoublemisstoken"))

    assert response.status_code == 201, response.text
    with client.app.state.session_factory() as session:
        assert session.scalar(select(GenerationJob).limit(1)) is not None
