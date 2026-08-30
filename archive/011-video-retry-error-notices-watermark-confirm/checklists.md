# Checklists

## Implementation

- [x] Add video retry cooldown state with a 2000 ms timer and cleanup on reset/unmount/history change.
- [x] Guard `retryFailed()` against duplicate clicks, active generation, missing failed items, and optimistic IDs.
- [x] Optimistically mark only failed video items as retrying on the first click and restore/failed-mark them if the request fails.
- [x] Disable `重试失败` for the full cooldown and hide `取消任务` during the same interval.
- [x] Render `取消任务` after cooldown only when the video job is still active.
- [x] Add an environment-aware generation failure helper for request, job, and item error text.
- [x] Route suite, A+, and video generation failures through AntD top `message.error`.
- [x] Show detailed errors only in development/test builds and phase-specific generic messages in production.
- [x] Remove raw exception text from suite toolbar/script, A+ result cards, and video result cards.
- [x] Preserve success and cancellation messages.
- [x] Add the exact no-watermark legal copy to `WatermarkDownloadMenu.vue`.
- [x] Require the `我已知悉` checkbox before enabling the red/danger `确定` action.
- [x] Leave watermark state unchanged when the acknowledgement modal is cancelled.
- [x] Keep no-subscription users locked out of the off-toggle and preserve the upsell action.
- [x] Update existing tests that assert the old modal/inline-error behavior.

## Verification

- [x] Run `npm run test:run -- workspace.test.ts` in `frontend/` and confirm all workspace tests pass.
- [x] Run `npm run typecheck` in `frontend/`.
- [x] Run `npm run build` in `frontend/`.
- [x] Verify with fake timers that one valid retry click makes exactly one retry API call.
- [x] Verify repeated clicks before 2000 ms make neither a second retry call nor a cancel call.
- [x] Verify the cancel button appears after 2000 ms for an active job and remains absent for a terminal job.
- [x] Verify a failed retry request restores a retryable failed job after cooldown and shows the unified message.
- [x] Verify detailed generation errors appear in development/test mode.
- [x] Verify production mode shows exactly `生成图片失败，请稍后重试` for suite/A+ and `生成视频失败，请稍后重试` for video.
- [x] Verify suite, A+, and video no longer expose raw backend errors in result chrome, cards, or script dialogs.
- [x] Verify the watermark acknowledgement modal uses the supplied wording verbatim.
- [x] Verify the red OK button is disabled until `我已知悉` is checked.
- [x] Verify confirmed off-toggle and immediate on-toggle behavior for subscribed users.
- [x] Verify locked behavior and upsell behavior for non-subscribed users.

## Regression

- [x] Normal suite and A+ retry buttons remain usable and keep their existing loading guards.
- [x] Video generation, history restore, polling, cancellation, and secondary edit still work.
- [x] Existing video queue/cancellation behavior from change `010`, if implemented before this change, remains intact; in particular, do not show cancel for a running job that the queue design says cannot be cancelled.
- [x] Watermark overlays and download query parameters still reflect the confirmed preference in suite and A+.
- [x] Batch-result group watermark preferences still update independently after confirmation.
- [x] Production users cannot enable detailed exception text from the browser alone.
