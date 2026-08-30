from __future__ import annotations

from sqlalchemy import select

from backend.app.models import SensitiveWord


def _terms(client) -> set[str]:
    resp = client.get("/api/v1/admin/sensitive-words")
    assert resp.status_code == 200, resp.text
    return {w["term"] for w in resp.json()["words"]}


def test_bulk_create_distinct_words(client) -> None:
    resp = client.post(
        "/api/v1/admin/sensitive-words/bulk",
        json={"terms": ["违禁词A", "违禁词B", "违禁词C"], "enabled": True, "note": "批量测试"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 3
    assert body["skipped"] == 0
    assert body["total"] == 3
    assert body["errors"] == []
    # 快照重建已交由后台任务，响应仅做调度标记；校验通过列表接口确认快照最终同步。
    assert body["rebuild_scheduled"] is True
    listed = client.get("/api/v1/admin/sensitive-words").json()
    assert listed["snapshot"]["redis"] is not None
    assert listed["snapshot"]["in_sync"] is True
    assert {"违禁词A", "违禁词B", "违禁词C"}.issubset(_terms(client))


def test_bulk_splits_and_ignores_empty(client) -> None:
    # 逗号、中文逗号、换行混合；首尾空白与空项应被忽略。
    text = "  词一 , 词二，\n词三\n\n   \n词四  "
    terms = [t.strip() for t in text.replace("，", ",").replace("\n", ",").split(",") if t.strip()]
    resp = client.post("/api/v1/admin/sensitive-words/bulk", json={"terms": terms})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 4
    assert {"词一", "词二", "词三", "词四"}.issubset(_terms(client))


def test_bulk_skips_existing_and_within_batch_duplicates(client) -> None:
    seed = client.post("/api/v1/admin/sensitive-words", json={"term": "已存在词"})
    assert seed.status_code == 200, seed.text

    resp = client.post(
        "/api/v1/admin/sensitive-words/bulk",
        json={"terms": ["已存在词", "新词X", "新词X", "新词Y"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 已存在 1 个跳过；本批内重复 1 个只创建一次（同样计入 skipped）→ 净新增 2、跳过 2。
    assert body["created"] == 2
    assert body["skipped"] == 2
    assert {"新词X", "新词Y"}.issubset(_terms(client))


def test_bulk_collects_invalid_and_continues(client) -> None:
    resp = client.post(
        "/api/v1/admin/sensitive-words/bulk",
        json={"terms": ["有效词", "x" * 200, "   "]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 超长与空项计入 errors/忽略，有效词仍创建。
    assert body["created"] == 1
    assert any("120" in e["error"] for e in body["errors"])
    assert "有效词" in _terms(client)


def test_bulk_respects_enabled_flag(client) -> None:
    resp = client.post(
        "/api/v1/admin/sensitive-words/bulk",
        json={"terms": ["停用词样例"], "enabled": False},
    )
    assert resp.status_code == 200, resp.text
    with client.app.state.session_factory() as session:
        word = session.scalar(select(SensitiveWord).where(SensitiveWord.term == "停用词样例"))
        assert word is not None
        assert word.enabled is False


def test_bulk_rejects_empty_list(client) -> None:
    resp = client.post("/api/v1/admin/sensitive-words/bulk", json={"terms": []})
    assert resp.status_code == 422


def test_bulk_large_batch_schedules_rebuild_and_eventually_syncs(client) -> None:
    # 较大批量：请求应立即返回（仅落库），快照重建在后台完成，避免同步重建导致超时。
    big = [f"批量词{i:04d}" for i in range(300)]
    resp = client.post("/api/v1/admin/sensitive-words/bulk", json={"terms": big})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 300
    assert body["rebuild_scheduled"] is True
    # 后台任务在测试客户端中随请求完成；列表接口应反映已同步的全量快照。
    listed = client.get("/api/v1/admin/sensitive-words").json()
    assert listed["snapshot"]["in_sync"] is True
    assert listed["snapshot"]["redis"]["word_count"] == 300
    assert {"批量词0001", "批量词0299"}.issubset(_terms(client))
