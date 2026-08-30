from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import backend.app.services.image_text_edit as ite
from backend.app.config import Settings


def _fake_runner(code: str, model: str) -> SimpleNamespace:
    return SimpleNamespace(code=code, model=model, runner=None, uses_predict=False)


def _patch_creators(monkeypatch, calls, created):
    def make_rapidocr(settings):
        calls.append(("rapidocr", settings.ocr_primary_model))
        created.append(_fake_runner("rapidocr", settings.ocr_primary_model or "PP-OCRv5"))
        return created[-1]

    def make_paddleocr(model_version, settings):
        calls.append(("paddleocr", model_version))
        created.append(_fake_runner("paddleocr", model_version))
        return created[-1]

    monkeypatch.setattr(ite, "_create_rapidocr_runner", make_rapidocr)
    monkeypatch.setattr(ite, "_create_paddleocr_runner", make_paddleocr)


def test_singleton_returns_same_instance_and_caches_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    ite.clear_ocr_engine_cache()
    calls: list[tuple[str, str]] = []
    created: list[object] = []
    _patch_creators(monkeypatch, calls, created)

    first = ite._load_ocr_engine(Settings(ocr_engine="rapidocr", ocr_primary_model="PP-OCRv5"))
    second = ite._load_ocr_engine(Settings(ocr_engine="rapidocr", ocr_primary_model="PP-OCRv5"))

    assert first is second
    assert len(calls) == 1  # 第二次命中缓存，不再创建
    assert ite.ocr_cache_size() == 1


def test_concurrent_initialization_creates_single_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    ite.clear_ocr_engine_cache()
    calls: list[tuple[str, str]] = []
    created: list[object] = []
    _patch_creators(monkeypatch, calls, created)

    settings = Settings(ocr_engine="rapidocr", ocr_primary_model="PP-OCRv5")
    results: list[object] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(ite._load_ocr_engine(settings))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8
    assert all(item is results[0] for item in results)
    assert len(calls) == 1  # 锁串行化后只真正创建一次


def test_config_fingerprint_change_replaces_instance_and_clears_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    ite.clear_ocr_engine_cache()
    calls: list[tuple[str, str]] = []
    created: list[object] = []
    _patch_creators(monkeypatch, calls, created)

    first = ite._load_ocr_engine(Settings(ocr_engine="rapidocr", ocr_primary_model="PP-OCRv5"))
    second = ite._load_ocr_engine(Settings(ocr_engine="rapidocr", ocr_primary_model="PP-OCRv6"))

    assert first is not second
    assert len(calls) == 2
    assert ite.ocr_cache_size() == 1  # 旧实例缓存已被清空


def test_load_failure_does_not_implicitly_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    ite.clear_ocr_engine_cache()

    def boom(_settings):
        raise RuntimeError("模型文件缺失")

    monkeypatch.setattr(ite, "_create_rapidocr_runner", boom)

    with pytest.raises(RuntimeError, match="模型文件缺失"):
        ite._load_ocr_engine(Settings(ocr_engine="rapidocr", ocr_primary_model="PP-OCRv5"))

    assert ite._ACTIVE_OCR_RUNNER is None
    assert ite._ACTIVE_OCR_FINGERPRINT is None
    assert ite._LAST_OCR_ERROR is not None
