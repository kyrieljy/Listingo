from __future__ import annotations

from backend.app.main import create_app


def test_lifespan_registers_ocr_prewarm_state(client) -> None:
    # TestClient 上下文会执行 lifespan；敏感词快照与 OCR 自动预热状态应在启动后就绪。
    state = getattr(client.app.state, "ocr_prewarm", None)
    assert isinstance(state, dict)
    assert "status" in state
    assert state["status"] in {"pending", "skipped_testing", "running", "succeeded", "failed", "superseded"}


def test_lifespan_sensitive_word_snapshot_synced(client) -> None:
    # 启动流程应已从 PostgreSQL 生成 / 校验并同步敏感词快照，管理端可读到一致状态。
    response = client.get("/api/v1/admin/sensitive-words")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "config" in body and "words" in body and "snapshot" in body
    assert body["snapshot"]["in_sync"] is True


def test_prewarm_failure_does_not_block_startup(client) -> None:
    # 即便 OCR 预热在测试环境失败 / 被跳过，应用仍应完成启动且可服务请求。
    assert client.app.state.ocr_prewarm is not None
    health = client.get("/api/v1/workspace-config")
    assert health.status_code == 200  # 服务可达即说明启动未被阻断
