from __future__ import annotations


def test_ocr_settings_patch_preserves_legacy_fallback_and_triggers_prewarm(client) -> None:
    # OCR 配置保存应返回最新设置，遗留 fallback 字段保留用于兼容，但不参与活动模型选择。
    before = client.get("/api/v1/admin/ocr-settings")
    assert before.status_code == 200, before.text
    fallback_before = before.json().get("ocr_fallback_model")

    updated = client.patch(
        "/api/v1/admin/ocr-settings",
        json={"ocr_primary_model": "PP-OCRv6", "ocr_fallback_model": fallback_before},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["ocr_primary_model"] == "PP-OCRv6"
    # 遗留字段仍返回，保证旧环境与 API 兼容
    assert "ocr_fallback_model" in body
    # 保存后触发预热，返回预热状态
    assert "prewarm_status" in body
    assert isinstance(body["prewarm_status"], dict)


def test_ocr_settings_rejects_unknown_engine(client) -> None:
    bad = client.patch("/api/v1/admin/ocr-settings", json={"ocr_engine": "bogus"})
    assert bad.status_code == 422
