# Checklists

## Implementation

- [x] Preserve configured `text_score` and `det_box_thresh` while supplying `det_model_path=None` to RapidOCR.
- [x] Add focused coverage for RapidOCR constructor compatibility.
- [x] Add a real installed-package prewarm regression.

## Verification

- [x] `.venv/Scripts/python.exe -m pytest backend/tests/test_execution.py -k rapidocr`
- [x] `.venv/Scripts/python.exe -m pytest backend/tests/test_api_dryrun.py::test_admin_ocr_settings_can_be_updated_and_prewarmed`
- [x] `.venv/Scripts/python.exe -m pytest backend/tests`
- [x] `.venv/Scripts/python.exe -m pip check`

## Regression

- [x] RapidOCR prewarm reports a successful `RapidOCR PP-OCRv4-onnx` candidate.
- [x] Admin OCR settings behavior and API response remain unchanged.
