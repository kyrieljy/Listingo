# Result

## Implementation Summary

- Added `det_model_path=None` to the RapidOCR constructor call. This is the package default and satisfies the legacy requirement that `model_path` be present whenever any `det_*` option is supplied.
- Preserved the configured recognition threshold (`text_score`) and detector threshold (`det_box_thresh`).
- Added constructor-argument coverage and a real installed-package prewarm regression.

## Commands and Checks

- `.venv/Scripts/python.exe -m pytest backend/tests/test_execution.py -k rapidocr`
  - Passed: `2 passed, 71 deselected, 1 warning`.
- `.venv/Scripts/python.exe -m pytest backend/tests/test_api_dryrun.py::test_admin_ocr_settings_can_be_updated_and_prewarmed`
  - Passed: `1 passed, 1 warning`.
- `.venv/Scripts/python.exe -m pytest backend/tests`
  - Passed: `183 passed, 1 warning in 136.93s`.
- `.venv/Scripts/python.exe -m pip check`
  - Passed: `No broken requirements found`.
  - Emitted two pre-existing warnings about the invalid temporary distribution directory `.venv/Lib/site-packages/~ip`.
- `git diff --check -- backend/app/services/image_text_edit.py backend/tests/test_execution.py changes/005-rapidocr-model-path-fix`
  - Passed with no whitespace errors. Git warned that line endings in the two modified backend files may be normalized from LF to CRLF on a future touch.

## Evidence

- The real prewarm regression exercised the installed `rapidocr-onnxruntime` package and bundled ONNX files, asserting `ok=True`, `active_engine=RapidOCR`, and `active_model=PP-OCRv4-onnx`.
- Before the fix, the same environment reproduced `KeyError: 'model_path'` at `rapidocr_onnxruntime/utils.py:251` during construction.
- After the fix, constructor inspection confirmed `text_score=0.62`, detector `box_thresh=0.6`, and successful model initialization.
- The admin OCR settings API regression passed without response-contract changes.

## Failures and Blockers

- No unresolved test failures or implementation blockers.
- The local runtime still differs from `backend/requirements.txt`: Python is 3.13.14 and `rapidocr-onnxruntime` is 1.2.3 while the file pins 1.4.4. The compatibility fix covers the currently installed 1.2.3 behavior; realignment or rebuilding the environment remains a deployment task outside this change scope.
