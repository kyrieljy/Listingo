from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.config import Settings
from backend.app.services import image_text_edit


def test_concurrent_initialization_loads_one_active_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def create_runner(model: str, _settings: Settings):
        calls.append(model)
        return image_text_edit.OcrRunner("PaddleOCR", model, object(), uses_predict=False)

    monkeypatch.setattr(image_text_edit, "_create_paddleocr_runner", create_runner)
    settings = Settings(testing=True, ocr_engine="paddleocr", ocr_primary_model="PP-OCRv6", ocr_fallback_model="PP-OCRv5")

    with ThreadPoolExecutor(max_workers=8) as executor:
        runners = list(executor.map(lambda _: image_text_edit._load_ocr_engine(settings), range(8)))

    assert calls == ["PP-OCRv6"]
    assert len({id(runner) for runner in runners}) == 1


def test_configuration_fingerprint_replaces_active_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[object] = []

    def create_runner(model: str, _settings: Settings):
        runner = image_text_edit.OcrRunner("PaddleOCR", model, object(), uses_predict=False)
        created.append(runner)
        return runner

    monkeypatch.setattr(image_text_edit, "_create_paddleocr_runner", create_runner)
    first = image_text_edit._load_ocr_engine(Settings(testing=True, ocr_engine="paddleocr", ocr_primary_model="PP-OCRv6"))
    second = image_text_edit._load_ocr_engine(Settings(testing=True, ocr_engine="paddleocr", ocr_primary_model="PP-OCRv5"))

    assert first is not second
    assert image_text_edit.active_ocr_identity() == {"engine": "PaddleOCR", "model": "PP-OCRv5"}
    assert image_text_edit._load_ocr_engine(Settings(testing=True, ocr_engine="paddleocr", ocr_primary_model="PP-OCRv5")) is second
    assert len(created) == 2


def test_initialization_failure_does_not_load_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_runner(_model: str, _settings: Settings):
        raise RuntimeError("primary unavailable")

    def create_rapid(_settings: Settings):
        raise AssertionError("fallback must not be loaded")

    monkeypatch.setattr(image_text_edit, "_create_paddleocr_runner", create_runner)
    monkeypatch.setattr(image_text_edit, "_create_rapidocr_runner", create_rapid)

    with pytest.raises(RuntimeError, match="primary unavailable"):
        image_text_edit._load_ocr_engine(Settings(testing=True, ocr_engine="paddleocr"))

    assert image_text_edit.active_ocr_identity() is None


def test_manual_prewarm_does_not_overwrite_a_newer_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    state = image_text_edit.new_ocr_prewarm_state()
    state["generation"] = 1

    def old_prewarm(_settings: Settings):
        state.update(generation=2, status="pending", result=None, finished_at=None)
        return {"ok": True}

    monkeypatch.setattr(image_text_edit, "prewarm_ocr_engine", old_prewarm)
    async def run():
        return await image_text_edit.prewarm_ocr_engine_async(Settings(testing=True), state)

    result = asyncio.run(run())

    assert result == {"ok": True}
    assert state["status"] == "pending"


def test_scheduled_prewarm_reports_public_state(monkeypatch: pytest.MonkeyPatch) -> None:
    state = image_text_edit.new_ocr_prewarm_state()
    monkeypatch.setattr(image_text_edit, "prewarm_ocr_engine", lambda _settings: {"ok": True})

    image_text_edit.schedule_ocr_prewarm(Settings(testing=False), state)
    asyncio.run(state["_task"])

    public = image_text_edit._public_prewarm_state(state)
    assert state["status"] == "succeeded"
    assert public["result"] == {"ok": True}
    assert "_task" not in public


def test_testing_mode_does_not_load_a_real_model() -> None:
    state = image_text_edit.new_ocr_prewarm_state()

    image_text_edit.schedule_ocr_prewarm(Settings(testing=True), state)

    assert state["status"] == "skipped_testing"
    assert "_task" not in state
