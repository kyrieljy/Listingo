def test_provider_api_masks_key_and_requires_explicit_test(client) -> None:
    providers = client.get("/api/v1/admin/providers").json()
    provider = next(item for item in providers if item["code"] == "yunwu-nano")
    response = client.patch(
        f"/api/v1/admin/providers/{provider['id']}",
        json={"api_key": "yunwu-secret-key", "enabled": True, "timeout_seconds": 60},
    )
    assert response.status_code == 200, response.text
    updated = response.json()

    assert updated["has_api_key"] is True
    assert updated["api_key_masked"] == "yunw••••••••-key"
    assert "secret" not in str(updated)


def test_prompt_version_can_be_saved_compared_and_activated(client) -> None:
    prompt = client.get("/api/v1/admin/prompts").json()[0]
    original = client.get(f"/api/v1/admin/prompts/{prompt['id']}").json()
    response = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions",
        json={
            "content": original["active_version"]["content"] + "\n\n# 运营备注\n只用于版本演示。",
            "change_note": "演示版本管理",
        },
    )
    assert response.status_code == 201
    new_version = response.json()
    compare = client.get(
        f"/api/v1/admin/prompts/{prompt['id']}/compare",
        params={"from_version": 1, "to_version": new_version["version_no"]},
    )
    assert compare.status_code == 200
    assert "+# 运营备注" in compare.json()["diff"]

    activate = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/{new_version['id']}/activate"
    )
    assert activate.status_code == 200
    assert activate.json()["active_version_id"] == new_version["id"]


def test_prompt_md_or_txt_can_be_uploaded_as_version_and_activated(client) -> None:
    prompt = client.get("/api/v1/admin/prompts").json()[0]
    uploaded_content = "# 新提示词资产\n\n这是运营上传的完整提示词版本，用于后续 Live 任务。"

    response = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/upload",
        files={"file": ("listing-prompt.md", uploaded_content.encode("utf-8"), "text/markdown")},
        data={"change_note": "上传测试版本"},
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["content"] == uploaded_content
    assert version["change_note"] == "上传测试版本"

    activate = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/{version['id']}/activate"
    )
    assert activate.status_code == 200
    detail = client.get(f"/api/v1/admin/prompts/{prompt['id']}").json()
    assert detail["active_version_id"] == version["id"]

    rejected = client.post(
        f"/api/v1/admin/prompts/{prompt['id']}/versions/upload",
        files={"file": ("prompt.json", b"{}", "application/json")},
    )
    assert rejected.status_code == 422
