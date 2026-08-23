from __future__ import annotations

import json
import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.core.runtime import RuntimeStateService, default_runtime
from backend.app.core.storage.keys import cache_key
from backend.app.models import (
    AplusItem,
    AplusVersion,
    ExecutionLog,
    GenerationItem,
    GenerationVersion,
    PromptVersion,
)
from backend.app.schemas import ImageTextEditLine, ImageTextLineOut
from backend.app.security import ApiKeyCipher
from backend.app.services.content_safety import ensure_content_safe, run_local_text_safety_review
from backend.app.services.execution import run_image_route
from backend.app.services.provider_limiter import provider_slot
from backend.app.services.provider_routing import (
    cached_provider_by_code,
    provider_display_names_by_code,
    route_provider_codes,
)
from backend.app.services.runtime_cache import active_prompt_version_id
from backend.app.services.providers import ProviderClient, provider_requires_public_urls, requested_image_size
from backend.app.services.redaction import safe_json
from backend.app.services.storage import public_file_url


IMAGE_TEXT_EDIT_PROMPT_CODE = "image-text-edit"
_LAST_OCR_ERROR: str | None = None
_LAST_OCR_WARNING: str | None = None
_OCR_RUNNER_CACHE: dict[tuple[str, str, str, float, float], "OcrRunner"] = {}
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
SUPPORTED_OCR_ENGINES = ("paddleocr", "rapidocr", "auto")
SUPPORTED_OCR_MODELS = ("PP-OCRv6", "PP-OCRv5", "PP-OCRv4", "PP-OCRv3")


@dataclass
class OcrDetectionResult:
    lines: list[ImageTextLineOut]
    warning: str | None = None


@dataclass(frozen=True)
class OcrRunner:
    code: str
    model: str
    runner: Any
    uses_predict: bool = False

    @property
    def label(self) -> str:
        return f"{self.code} {self.model}".strip()

    def run(self, image_path: str) -> Any:
        if self.uses_predict:
            return self.runner.predict(image_path)
        return self.runner(image_path)


@dataclass(frozen=True)
class OcrCandidate:
    code: str
    model: str
    cache_key: tuple[str, str, str, float, float]
    factory: Callable[[], OcrRunner]

    @property
    def label(self) -> str:
        return f"{self.code} {self.model}".strip()

    def runner(self) -> OcrRunner:
        return _cached_runner(self.cache_key, self.factory)


class FallbackOcrEngine:
    def __init__(self, runners: list[OcrRunner | OcrCandidate], init_warning: str | None = None) -> None:
        self.candidates = [
            runner
            if isinstance(runner, OcrCandidate)
            else OcrCandidate(
                runner.code,
                runner.model,
                (runner.code.lower(), runner.model, "", 0, 0),
                lambda runner=runner: runner,
            )
            for runner in runners
        ]
        self.init_warning = init_warning
        self.runtime_warning: str | None = None
        self._active_index = 0

    @property
    def warning(self) -> str | None:
        warnings = [warning for warning in (self.init_warning, self.runtime_warning) if warning]
        return "; ".join(warnings) if warnings else None

    def __call__(self, image_path: str) -> Any:
        errors: list[str] = []
        for index in range(self._active_index, len(self.candidates)):
            candidate = self.candidates[index]
            try:
                runner = candidate.runner()
                result = runner.run(image_path)
                if index > 0 and errors:
                    self.runtime_warning = f"{errors[0]}; using {runner.label}"
                self._active_index = index
                return result
            except Exception as error:
                errors.append(f"{candidate.label} OCR failed: {error}")
        raise RuntimeError("; ".join(errors) or "OCR failed")

    def prewarm_all(self, image_path: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        first_success_index: int | None = None
        errors: list[str] = []
        for index, candidate in enumerate(self.candidates):
            started_at = perf_counter()
            try:
                runner = candidate.runner()
                raw = runner.run(image_path)
                elapsed_ms = int(round((perf_counter() - started_at) * 1000))
                results.append(
                    {
                        "engine": runner.code,
                        "model": runner.model,
                        "ok": True,
                        "elapsed_ms": elapsed_ms,
                        "result_count": len(raw) if isinstance(raw, list) else 1,
                    }
                )
                if first_success_index is None:
                    first_success_index = index
            except Exception as error:
                elapsed_ms = int(round((perf_counter() - started_at) * 1000))
                message = f"{candidate.label} OCR failed: {error}"
                errors.append(message)
                results.append(
                    {
                        "engine": candidate.code,
                        "model": candidate.model,
                        "ok": False,
                        "elapsed_ms": elapsed_ms,
                        "error": str(error),
                    }
                )
        if first_success_index is None:
            raise RuntimeError("; ".join(errors) or "OCR prewarm failed")
        self._active_index = first_success_index
        if first_success_index > 0 and errors:
            self.runtime_warning = f"{errors[0]}; using {self.candidates[first_success_index].label}"
        return results


def _bbox_from_points(points: Any, scale: float = 1.0) -> dict[str, int] | None:
    if not isinstance(points, (list, tuple)):
        return None
    xy: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            xy.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if not xy:
        return None
    xs = [point[0] for point in xy]
    ys = [point[1] for point in xy]
    left = max(0, int(round(min(xs) / scale)))
    top = max(0, int(round(min(ys) / scale)))
    right = max(left, int(round(max(xs) / scale)))
    bottom = max(top, int(round(max(ys) / scale)))
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _points_from_box(points: Any) -> Any:
    values = _as_list(points)
    if len(values) == 4 and all(isinstance(value, (int, float)) for value in values):
        left, top, right, bottom = values
        return [[left, top], [right, top], [right, bottom], [left, bottom]]
    return values or points


def _paddle_result_mapping(value: Any) -> dict[str, Any] | None:
    candidates: list[Any] = [value]
    for attr_name in ("res", "json"):
        attr = getattr(value, attr_name, None)
        if attr is not None:
            if callable(attr):
                try:
                    candidates.append(attr())
                except Exception:
                    pass
            else:
                candidates.append(attr)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            candidates.append(to_dict())
        except Exception:
            pass

    for candidate in candidates:
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except ValueError:
                continue
        if not isinstance(candidate, dict):
            continue
        nested = candidate.get("res")
        if isinstance(nested, dict):
            return nested
        return candidate
    return None


def _paddleocr_rows(raw: Any) -> list[Any]:
    raw_results = raw if isinstance(raw, list) else [raw]
    rows: list[Any] = []
    for result in raw_results:
        mapping = _paddle_result_mapping(result)
        if not mapping:
            continue
        texts = _as_list(_first_present(mapping, ("rec_texts", "texts", "txts")))
        if not texts:
            continue
        scores = _as_list(_first_present(mapping, ("rec_scores", "scores")))
        boxes = _as_list(_first_present(mapping, ("rec_polys", "rec_boxes", "dt_polys", "boxes")))
        for index, text in enumerate(texts):
            points = _points_from_box(boxes[index]) if index < len(boxes) else None
            score = scores[index] if index < len(scores) else 0
            rows.append((points, text, score))
    return rows


def _looks_like_ocr_row(row: Any) -> bool:
    return isinstance(row, (list, tuple)) and len(row) >= 2 and not isinstance(row[0], (str, bytes))


def _rapidocr_rows(raw: Any) -> list[Any]:
    if isinstance(raw, tuple):
        return list(raw[0] or [])
    if isinstance(raw, list):
        if raw and all(_looks_like_ocr_row(row) for row in raw):
            return raw
        if len(raw) == 1 and isinstance(raw[0], list) and all(_looks_like_ocr_row(row) for row in raw[0]):
            return raw[0]
        return raw
    result = getattr(raw, "result", None)
    if isinstance(result, list):
        return result
    boxes = getattr(raw, "boxes", None)
    texts = getattr(raw, "txts", None) or getattr(raw, "texts", None)
    scores = getattr(raw, "scores", None)
    if boxes is not None and texts is not None:
        return list(zip(boxes, texts, scores or []))
    return []


def _ocr_rows(raw: Any) -> list[Any]:
    return _paddleocr_rows(raw) or _rapidocr_rows(raw)


def _normalize_ocr_model_version(model: str | None) -> str:
    normalized = (model or "").strip()
    lowered = normalized.lower().replace("_", "-")
    if lowered in {"", "pp-ocrv6", "ppocrv6", "ocrv6", "v6"}:
        return "PP-OCRv6"
    if lowered in {"pp-ocrv5", "ppocrv5", "ocrv5", "v5"}:
        return "PP-OCRv5"
    return normalized


def _create_paddleocr_runner(model_version: str, settings: Settings) -> OcrRunner:
    from paddleocr import PaddleOCR  # type: ignore

    kwargs: dict[str, Any] = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "ocr_version": model_version,
        "device": settings.ocr_device or "cpu",
        "engine": "paddle",
    }
    try:
        runner = PaddleOCR(**kwargs)
    except TypeError as first_error:
        compatible_kwargs = dict(kwargs)
        compatible_kwargs.pop("engine", None)
        try:
            runner = PaddleOCR(**compatible_kwargs)
        except TypeError:
            raise first_error
    return OcrRunner(code="PaddleOCR", model=model_version, runner=runner, uses_predict=True)


def _create_rapidocr_runner(settings: Settings) -> OcrRunner:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore
    try:
        runner = RapidOCR(
            text_score=settings.ocr_text_score_threshold,
            det_box_thresh=settings.ocr_box_score_threshold,
            # RapidOCR 1.2.x requires det_model_path whenever a det_* option is supplied.
            det_model_path=None,
        )
    except TypeError:
        runner = RapidOCR()
    return OcrRunner(code="RapidOCR", model="PP-OCRv4-onnx", runner=runner)


def _cached_runner(key: tuple[str, str, str, float, float], factory: Callable[[], OcrRunner]) -> OcrRunner:
    runner = _OCR_RUNNER_CACHE.get(key)
    if runner is None:
        runner = factory()
        _OCR_RUNNER_CACHE[key] = runner
    return runner


def clear_ocr_engine_cache() -> None:
    global _LAST_OCR_ERROR, _LAST_OCR_WARNING
    _OCR_RUNNER_CACHE.clear()
    _LAST_OCR_ERROR = None
    _LAST_OCR_WARNING = None


def ocr_cache_size() -> int:
    return len(_OCR_RUNNER_CACHE)


def _load_ocr_engine(settings: Settings | None = None) -> Any | None:
    global _LAST_OCR_ERROR, _LAST_OCR_WARNING
    _LAST_OCR_ERROR = None
    _LAST_OCR_WARNING = None
    resolved = settings or Settings()
    engine_name = (resolved.ocr_engine or "paddleocr").strip().lower()
    candidates: list[OcrCandidate] = []

    if engine_name in {"paddleocr", "auto"}:
        paddle_models = [
            _normalize_ocr_model_version(resolved.ocr_primary_model),
            _normalize_ocr_model_version(resolved.ocr_fallback_model),
        ]
        for model_version in dict.fromkeys(model for model in paddle_models if model):
            key = (
                "paddleocr",
                model_version,
                resolved.ocr_device or "cpu",
                resolved.ocr_text_score_threshold,
                resolved.ocr_box_score_threshold,
            )
            candidates.append(
                OcrCandidate(
                    "PaddleOCR",
                    model_version,
                    key,
                    lambda model_version=model_version: _create_paddleocr_runner(model_version, resolved),
                )
            )

    if engine_name in {"paddleocr", "rapidocr", "auto"}:
        key = (
            "rapidocr",
            "PP-OCRv4-onnx",
            resolved.ocr_device or "cpu",
            resolved.ocr_text_score_threshold,
            resolved.ocr_box_score_threshold,
        )
        candidates.append(OcrCandidate("RapidOCR", "PP-OCRv4-onnx", key, lambda: _create_rapidocr_runner(resolved)))

    if not candidates:
        _LAST_OCR_ERROR = f"OCR engine {engine_name!r} is not supported"
        return None

    return FallbackOcrEngine(candidates)


def prewarm_ocr_engine(settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or Settings()
    engine = _load_ocr_engine(resolved)
    if engine is None:
        raise RuntimeError(_LAST_OCR_ERROR or "OCR engine unavailable")
    started_at = perf_counter()
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            temp_path = temp_file.name
        Image.new("RGB", (320, 120), "#ffffff").save(temp_path)
        if hasattr(engine, "prewarm_all"):
            warmed = engine.prewarm_all(temp_path)
        else:
            raw = engine(temp_path)
            warmed = [
                {
                    "engine": getattr(engine, "code", "OCR"),
                    "model": getattr(engine, "model", ""),
                    "ok": True,
                    "elapsed_ms": int(round((perf_counter() - started_at) * 1000)),
                    "result_count": len(raw) if isinstance(raw, list) else 1,
                }
            ]
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
    succeeded = [item for item in warmed if item.get("ok")]
    active = succeeded[0] if succeeded else {}
    return {
        "ok": bool(succeeded),
        "active_engine": active.get("engine"),
        "active_model": active.get("model"),
        "elapsed_ms": int(round((perf_counter() - started_at) * 1000)),
        "warmed": warmed,
        "warning": getattr(engine, "warning", None) or _LAST_OCR_WARNING,
        "cache_size": ocr_cache_size(),
    }


def _language_is_english(language_hint: str | None) -> bool:
    normalized = (language_hint or "").strip().lower()
    return normalized in {"en", "eng", "english", "英文", "英语"} or "english" in normalized or "英文" in normalized


def _is_watermark_noise(
    text: str,
    bbox: dict[str, int],
    image_size: tuple[int, int] | None,
    settings: Settings,
) -> bool:
    if not settings.ocr_filter_watermark_text or not image_size:
        return False
    normalized = re.sub(r"\s+", "", text).lower()
    watermark_tokens = ("listingo", "aigenerated", "ai-generated", "generatedbyai", "ai生成", "由ai生成")
    if not any(token in normalized for token in watermark_tokens):
        return False
    image_width, image_height = image_size
    center_x = bbox["x"] + bbox["width"] / 2
    center_y = bbox["y"] + bbox["height"] / 2
    return center_x >= image_width * 0.55 and center_y >= image_height * 0.72


def _is_noise_text(
    text: str,
    confidence: float,
    bbox: dict[str, int],
    settings: Settings,
    language_hint: str | None = None,
    image_size: tuple[int, int] | None = None,
) -> bool:
    normalized = text.strip()
    compact = re.sub(r"\s+", "", normalized)
    if not compact or confidence < settings.ocr_text_score_threshold:
        return True
    if (
        bbox["width"] < settings.ocr_min_box_width
        or bbox["height"] < settings.ocr_min_box_height
        or bbox["width"] * bbox["height"] < settings.ocr_min_box_area
    ):
        return True
    if _is_watermark_noise(normalized, bbox, image_size, settings):
        return True
    if len(compact) == 1 and confidence < settings.ocr_short_text_score_threshold:
        return True
    if settings.ocr_filter_isolated_cjk and _language_is_english(language_hint) and len(compact) == 1 and _CJK_RE.fullmatch(compact):
        return True
    return False


def _parse_row_text_and_confidence(row: Any) -> tuple[str, float]:
    text_source = row[1] if len(row) > 1 else ""
    confidence_source = row[2] if len(row) > 2 else 0
    if isinstance(text_source, (list, tuple)) and len(text_source) >= 2:
        confidence_source = text_source[1]
        text_source = text_source[0]
    text = str(text_source or "").strip()
    try:
        confidence = float(confidence_source)
    except (TypeError, ValueError):
        confidence = 0
    return text, max(0, min(1, confidence))


def _parse_ocr_rows(
    raw: Any,
    scale: float,
    settings: Settings,
    language_hint: str | None = None,
    image_size: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in _ocr_rows(raw):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        text, confidence = _parse_row_text_and_confidence(row)
        bbox = _bbox_from_points(_points_from_box(row[0]), scale)
        if not bbox:
            continue
        if _is_noise_text(text, confidence, bbox, settings, language_hint, image_size):
            continue
        parsed.append({"text": text, "confidence": confidence, "bbox": bbox})
    return parsed


def _prepare_ocr_variants(path: Path, settings: Settings | None = None) -> list[tuple[str, float, bool]]:
    resolved = settings or Settings()
    variants: list[tuple[str, float, bool]] = [(str(path), 1.0, False)]
    if not resolved.ocr_use_enhanced_variants:
        return variants
    temp_paths: list[str] = []
    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            scale = 2.0 if max(width, height) < 2600 else 1.5
            resized = rgb.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
            enhanced = ImageOps.grayscale(resized)
            enhanced = ImageEnhance.Contrast(enhanced).enhance(1.65)
            enhanced = ImageEnhance.Sharpness(enhanced).enhance(2.2)
            enhanced = enhanced.filter(ImageFilter.SHARPEN).convert("RGB")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                temp_path = temp_file.name
            enhanced.save(temp_path)
            temp_paths.append(temp_path)
            variants.append((temp_path, scale, True))
    except Exception:
        for temp_path in temp_paths:
            Path(temp_path).unlink(missing_ok=True)
    return variants


def _dedupe_ocr_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def compact(text: str) -> str:
        return "".join(text.split()).strip()

    def same_line(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_text = compact(left["text"])
        right_text = compact(right["text"])
        if not left_text or not right_text:
            return False
        related = left_text == right_text or left_text in right_text or right_text in left_text
        if not related:
            return False
        left_box = left["bbox"]
        right_box = right["bbox"]
        left_center = (left_box["x"] + left_box["width"] / 2, left_box["y"] + left_box["height"] / 2)
        right_center = (right_box["x"] + right_box["width"] / 2, right_box["y"] + right_box["height"] / 2)
        return abs(left_center[0] - right_center[0]) <= max(left_box["width"], right_box["width"], 40) and abs(
            left_center[1] - right_center[1]
        ) <= max(left_box["height"], right_box["height"], 24)

    parsed: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item["confidence"], reverse=True):
        if any(same_line(row, existing) for existing in parsed):
            continue
        parsed.append(row)
    parsed.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
    return parsed


def _ocr_cache_key(path: Path, settings: Settings, language_hint: str | None) -> str:
    stat = path.stat()
    identity = {
        "path": str(path.resolve()),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "language": language_hint or "",
        "engine": settings.ocr_engine,
        "primary_model": settings.ocr_primary_model,
        "fallback_model": settings.ocr_fallback_model,
        "device": settings.ocr_device,
        "text_score": settings.ocr_text_score_threshold,
        "box_score": settings.ocr_box_score_threshold,
        "short_text_score": settings.ocr_short_text_score_threshold,
        "min_width": settings.ocr_min_box_width,
        "min_height": settings.ocr_min_box_height,
        "min_area": settings.ocr_min_box_area,
        "filter_isolated_cjk": settings.ocr_filter_isolated_cjk,
        "filter_watermark": settings.ocr_filter_watermark_text,
        "enhanced_variants": settings.ocr_use_enhanced_variants,
    }
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return cache_key("ocr-result", fingerprint)


def _cached_ocr_result(key: str, runtime: RuntimeStateService | None) -> OcrDetectionResult | None:
    if runtime is None:
        return None
    cached = runtime.get_json_best_effort(key)
    if not isinstance(cached, dict) or not isinstance(cached.get("lines"), list):
        return None
    try:
        return OcrDetectionResult(
            lines=[ImageTextLineOut.model_validate(line) for line in cached["lines"]],
            warning=None,
        )
    except ValueError:
        runtime.delete_best_effort(key)
        return None


def _store_ocr_result(
    key: str,
    result: OcrDetectionResult,
    runtime: RuntimeStateService | None,
) -> None:
    if runtime is None or result.warning is not None:
        return
    runtime.set_json_best_effort(
        key,
        {"lines": [line.model_dump() for line in result.lines]},
        runtime.ttls.ocr,
    )


def detect_text_lines_with_status(
    image_path: str | Path,
    settings: Settings | None = None,
    language_hint: str | None = None,
) -> OcrDetectionResult:
    path = Path(image_path)
    if not path.exists():
        raise ValueError("Current image file does not exist")
    resolved = settings or Settings()
    runtime = default_runtime()
    result_cache_key = _ocr_cache_key(path, resolved, language_hint)
    cached_result = _cached_ocr_result(result_cache_key, runtime)
    if cached_result is not None:
        return cached_result
    engine = _load_ocr_engine(resolved)
    if engine is None:
        return OcrDetectionResult(lines=[], warning=_LAST_OCR_ERROR or "OCR engine unavailable")
    rows: list[dict[str, Any]] = []
    variants = _prepare_ocr_variants(path, resolved)
    temp_paths = [variant_path for variant_path, _, is_temp in variants if is_temp]
    image_size: tuple[int, int] | None = None
    try:
        with Image.open(path) as image:
            image_size = image.size
    except Exception:
        image_size = None
    try:
        for variant_path, scale, _ in variants:
            try:
                rows.extend(_parse_ocr_rows(engine(variant_path), scale, resolved, language_hint, image_size))
            except Exception as error:
                return OcrDetectionResult(lines=[], warning=f"OCR failed: {error}")
    finally:
        for temp_path in temp_paths:
            Path(temp_path).unlink(missing_ok=True)
    parsed = _dedupe_ocr_rows(rows)
    warning = getattr(engine, "warning", None) or _LAST_OCR_WARNING
    result = OcrDetectionResult(lines=[
        ImageTextLineOut(id=f"line-{index + 1:03d}", index=index, text=item["text"], confidence=item["confidence"], bbox=item["bbox"])
        for index, item in enumerate(parsed)
    ], warning=warning)
    _store_ocr_result(result_cache_key, result, runtime)
    return result

def changed_text_lines(lines: list[ImageTextEditLine]) -> list[ImageTextEditLine]:
    changed: list[ImageTextEditLine] = []
    for line in sorted(lines, key=lambda item: item.index):
        original = line.original_text or ""
        new = line.text or ""
        if original != new:
            changed.append(line)
    if not changed:
        raise ValueError("No text changes were submitted")
    return changed


def build_replacements_table(lines: list[ImageTextEditLine]) -> str:
    rows: list[str] = []
    for offset, line in enumerate(changed_text_lines(lines), start=1):
        if line.bbox:
            bbox = f"bbox=(x:{line.bbox.x},y:{line.bbox.y},w:{line.bbox.width},h:{line.bbox.height})"
        else:
            bbox = "bbox=(manual)"
        original = json.dumps(line.original_text or "", ensure_ascii=False)
        new = json.dumps(line.text or "", ensure_ascii=False)
        rows.append(f"{offset}. {bbox}, original={original}, new={new}")
    return "\n".join(rows)


def render_text_edit_prompt(template: str, lines: list[ImageTextEditLine], context: dict[str, Any] | None = None) -> str:
    table = build_replacements_table(lines)
    prompt = template.replace("{{REPLACEMENTS_TABLE}}", table)
    if prompt == template:
        prompt = f"{template.rstrip()}\n\nDetected text lines and requested replacements:\n{table}"
    if context:
        prompt += "\n\nContext:\n" + json.dumps(context, ensure_ascii=False, indent=2)
    return prompt


def _active_text_edit_prompt(session: Session) -> PromptVersion:
    version_id = active_prompt_version_id(session, IMAGE_TEXT_EDIT_PROMPT_CODE)
    prompt_version = session.get(PromptVersion, version_id)
    if not prompt_version:
        raise RuntimeError("Image text edit Prompt is not enabled")
    return prompt_version


def create_dryrun_generation_text_version(
    session: Session,
    item: GenerationItem,
    lines: list[ImageTextEditLine],
    settings: Settings,
) -> GenerationVersion:
    current = session.get(GenerationVersion, item.current_version_id)
    if not current:
        raise ValueError("Current version does not exist")
    changed = changed_text_lines(lines)
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    result_name = f"{item.job_id}-{item.index + 1}-text-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    shutil.copy2(current.file_path, destination)
    version = GenerationVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=f"文字编辑 {len(changed)} 行",
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": True, "edit_type": "text", "replacements": [line.model_dump() for line in changed]}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    session.commit()
    session.refresh(version)
    return version


def create_dryrun_aplus_text_version(
    session: Session,
    item: AplusItem,
    lines: list[ImageTextEditLine],
    settings: Settings,
) -> AplusVersion:
    current = next((version for version in item.versions if version.id == item.current_version_id), None)
    current = current or (item.versions[-1] if item.versions else None)
    if not current:
        raise ValueError("Current version does not exist")
    changed = changed_text_lines(lines)
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    result_name = f"aplus-{item.job_id}-{item.index + 1}-text-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    shutil.copy2(current.file_path, destination)
    version = AplusVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=f"文字编辑 {len(changed)} 行",
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json({"dry_run": True, "edit_type": "text", "replacements": [line.model_dump() for line in changed]}),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    session.commit()
    session.refresh(version)
    return version


async def _run_live_text_edit(
    session: Session,
    *,
    item_id: str,
    job_id: str,
    current_file_path: str,
    aspect_ratio: str,
    lines: list[ImageTextEditLine],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> tuple[bytes, str, str, list[ImageTextEditLine]]:
    changed = changed_text_lines(lines)
    prompt_version = _active_text_edit_prompt(session)
    if not prompt_version:
        raise RuntimeError("Image text edit Prompt active version does not exist")
    edit_prompt = render_text_edit_prompt(
        prompt_version.content,
        changed,
        {"item_id": item_id, "job_id": job_id, "aspect_ratio": aspect_ratio},
    )
    ensure_content_safe(run_local_text_safety_review(build_replacements_table(changed)), "Input content safety blocked")
    provider_codes = route_provider_codes(session, "image_edit")
    provider_display_names = provider_display_names_by_code(session, provider_codes)
    client = ProviderClient()
    input_paths = [current_file_path]

    async def generate(provider_code: str) -> bytes:
        provider = cached_provider_by_code(session, provider_code)
        if not provider or not provider.encrypted_api_key:
            raise RuntimeError(f"Provider {provider_code} is unavailable")
        input_urls = (
            [public_file_url(settings, path) for path in input_paths]
            if provider_requires_public_urls(provider)
            else None
        )
        async with provider_slot(settings.max_provider_concurrency):
            return await client.edit_image(
                provider,
                cipher.decrypt(provider.encrypted_api_key),
                edit_prompt,
                input_paths,
                aspect_ratio,
                input_urls=input_urls,
                idempotency_key=f"{item_id}:text-edit:{build_replacements_table(changed)}",
            )

    image_bytes, used_code = await run_image_route(provider_codes, generate, provider_display_names)
    with Image.open(BytesIO(image_bytes)) as image:
        image.verify()
    return image_bytes, used_code, prompt_version.id, changed


async def create_live_generation_text_version(
    session: Session,
    item: GenerationItem,
    aspect_ratio: str,
    lines: list[ImageTextEditLine],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> GenerationVersion:
    current = session.get(GenerationVersion, item.current_version_id)
    if not current:
        raise ValueError("Current version does not exist")
    image_bytes, used_code, prompt_version_id, changed = await _run_live_text_edit(
        session,
        item_id=item.id,
        job_id=item.job_id,
        current_file_path=current.file_path,
        aspect_ratio=aspect_ratio,
        lines=lines,
        settings=settings,
        cipher=cipher,
    )
    with Image.open(BytesIO(image_bytes)) as image:
        width, height = image.size
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    result_name = f"{item.job_id}-{item.index + 1}-text-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    destination.write_bytes(image_bytes)
    version = GenerationVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=f"文字编辑 {len(changed)} 行",
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json(
            {
                "dry_run": False,
                "edit_type": "text",
                "provider": used_code,
                "prompt_code": IMAGE_TEXT_EDIT_PROMPT_CODE,
                "prompt_version_id": prompt_version_id,
                "requested_size": requested_image_size(aspect_ratio),
                "actual_size": [width, height],
                "replacements": [line.model_dump() for line in changed],
            }
        ),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    provider = cached_provider_by_code(session, used_code)
    item.provider_id = provider.id if provider else item.provider_id
    session.add(
        ExecutionLog(
            job_id=item.job_id,
            item_id=item.id,
            node="image_text_edit",
            provider_id=item.provider_id,
            status="succeeded",
            request_summary=safe_json({"line_count": len(changed), "prompt_version_id": prompt_version_id, "requested_size": requested_image_size(aspect_ratio)}),
            response_summary=safe_json({"url": version.url, "version_no": version_no}),
            dry_run=False,
        )
    )
    session.commit()
    session.refresh(version)
    return version


async def create_live_aplus_text_version(
    session: Session,
    item: AplusItem,
    lines: list[ImageTextEditLine],
    settings: Settings,
    cipher: ApiKeyCipher,
) -> AplusVersion:
    current = next((version for version in item.versions if version.id == item.current_version_id), None)
    current = current or (item.versions[-1] if item.versions else None)
    if not current:
        raise ValueError("Current version does not exist")
    image_bytes, used_code, prompt_version_id, changed = await _run_live_text_edit(
        session,
        item_id=item.id,
        job_id=item.job_id,
        current_file_path=current.file_path,
        aspect_ratio=item.aspect_ratio,
        lines=lines,
        settings=settings,
        cipher=cipher,
    )
    with Image.open(BytesIO(image_bytes)) as image:
        width, height = image.size
    version_no = max((version.version_no for version in item.versions), default=0) + 1
    result_name = f"aplus-{item.job_id}-{item.index + 1}-text-v{version_no}-{uuid4().hex[:8]}.png"
    destination = settings.results_dir / result_name
    destination.write_bytes(image_bytes)
    version = AplusVersion(
        item_id=item.id,
        parent_version_id=current.id,
        version_no=version_no,
        instruction=f"文字编辑 {len(changed)} 行",
        file_path=str(destination),
        url=f"/files/results/{result_name}",
        metadata_json=safe_json(
            {
                "dry_run": False,
                "edit_type": "text",
                "provider": used_code,
                "prompt_code": IMAGE_TEXT_EDIT_PROMPT_CODE,
                "prompt_version_id": prompt_version_id,
                "requested_size": requested_image_size(item.aspect_ratio),
                "actual_size": [width, height],
                "replacements": [line.model_dump() for line in changed],
            }
        ),
    )
    session.add(version)
    session.flush()
    item.current_version_id = version.id
    provider = cached_provider_by_code(session, used_code)
    item.provider_id = provider.id if provider else item.provider_id
    session.add(
        ExecutionLog(
            job_id=item.job_id,
            item_id=item.id,
            node="image_text_edit",
            provider_id=item.provider_id,
            status="succeeded",
            request_summary=safe_json({"line_count": len(changed), "prompt_version_id": prompt_version_id, "requested_size": requested_image_size(item.aspect_ratio)}),
            response_summary=safe_json({"url": version.url, "version_no": version_no}),
            dry_run=False,
        )
    )
    session.commit()
    session.refresh(version)
    return version
