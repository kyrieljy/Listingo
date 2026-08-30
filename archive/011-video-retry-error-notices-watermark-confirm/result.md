# Result

## Implementation Summary

- Failed-video retry now submits on the first valid click, optimistically marks only failed items as running, disables retry for 2 seconds, hides and guards cancellation during cooldown, and restores the failed snapshot when the retry request rejects.
- Suite, A+, and video generation failures now use the AntD top `message`. Development/test builds retain detailed request/job/item diagnostics; production builds always use the phase-specific fallback: images use `生成图片失败，请稍后重试` and video uses `生成视频失败，请稍后重试`.
- Raw generation errors were removed from suite result chrome/scripts, A+ cards/scripts, and video failed cards. Backend payloads and logs still retain diagnostics for operators.
- Subscribed users must acknowledge the supplied no-watermark notice before disabling `包含 AI 水印`. The acknowledgement resets on each open, the danger `确定` button stays disabled until `我已知悉` is checked, and cancel/mask close leaves watermark enabled. Non-subscribed users remain locked to watermark exports.
- Updated the workspace source-contract tests and added focused tests for failure-message resolution, watermark acknowledgement, and fake-timer video retry behavior.

## Commands and Checks

- `cd frontend; npm run test:run -- workspace.test.ts generation-errors.test.ts WatermarkDownloadMenu.test.ts VideoPhasePanel.test.ts` — 4 files / 79 tests passed.
- `cd frontend; npm run typecheck` — passed.
- `cd frontend; npm run test:run` — 7 files / 105 tests passed.
- `cd frontend; npm run build` — passed; Vite emitted existing large-chunk warnings.
- `git diff --check` — no whitespace errors; only the repository's existing CRLF conversion warnings.

## Evidence

- `VideoPhasePanel.test.ts` verifies one retry API call on the first click, no second retry/cancel before the 2-second boundary, cancel appearing only after cooldown for an active job, terminal jobs keeping cancel hidden, failed-request restoration, and cooldown cleanup on new task.
- `generation-errors.test.ts` verifies job/item/request details in detailed mode and exact production fallbacks by phase.
- `WatermarkDownloadMenu.test.ts` verifies the supplied copy verbatim, disabled danger confirmation, acknowledgement, cancel/close behavior, immediate watermark-on, and the non-subscribed lock/upsell route.
- `workspace.test.ts` verifies no covered generation surface imports `Modal.error` or renders `{{ item.error }}`.
- The production bundle was searched and contains both agreed fallback strings. Its generated helper receives `detailed: false`, and the `VITE_SHOW_DETAILED_GENERATION_ERRORS` key is not present in the emitted workspace chunk.

## Failures and Blockers

- No unresolved failures or blockers.
- Live provider/background-failure scenarios were not manually exercised; behavior is covered by component/model tests, source contracts, and production bundle inspection.
