# Change: Fix RapidOCR prewarm model_path error

Date: 2026-08-22

## Goal

Make the admin OCR prewarm action succeed when the installed `rapidocr-onnxruntime` is the currently present 1.2.x line, while preserving the configured recognition and detector thresholds.

## Context

- The admin button in `frontend/src/features/admin/AdminView.vue` calls `POST /admin/ocr-settings/prewarm`.
- `backend/app/api/admin.py` delegates to `prewarm_ocr_engine`.
- `backend/app/services/image_text_edit.py` constructs RapidOCR with `text_score` and `det_box_thresh`.
- The current backend environment contains `rapidocr-onnxruntime==1.2.3` even though `backend/requirements.txt` pins 1.4.4. In 1.2.3, passing any `det_*` option without `det_model_path` raises `KeyError: 'model_path'` inside the package.
- The bundled model files are present; the failure occurs during RapidOCR construction, before model verification or inference.

## Scope

### In Scope

- Make RapidOCR construction compatible with the old `det_*` parameter handling.
- Add focused backend coverage for the constructor arguments and a real RapidOCR prewarm regression.
- Record verification results in this change package.

### Out of Scope

- Replacing or upgrading the local Python virtual environment.
- Changing the admin OCR UI or API contract.
- Changing PaddleOCR behavior.
- Updating model assets or introducing model downloads.

## Implementation Plan

1. Pass `det_model_path=None` alongside `det_box_thresh` when constructing RapidOCR, which is the package default and supplies the key expected by 1.2.3's updater.
2. Add a unit test that captures the constructor arguments used by `_create_rapidocr_runner`.
3. Add a real RapidOCR prewarm regression that exercises the installed package and bundled model files.

## Verification Plan

- Run the focused OCR tests in `backend/tests/test_execution.py`.
- Run the admin OCR settings test in `backend/tests/test_api_dryrun.py`.
- Run the backend test suite.
- Confirm `pip check` and report the current environment's dependency drift without altering the environment.

## Open Questions

None.
