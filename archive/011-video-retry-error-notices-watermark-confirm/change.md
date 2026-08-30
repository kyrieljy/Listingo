# Change: VIDEO_RETRY_ERROR_NOTICES_WATERMARK_CONFIRM

Date: 2026-08-29

## Goal

Make failed-video retry submit on the first click without accidental cancellation, present generation failures consistently through the top message area with environment-aware detail, and require an explicit acknowledgement before a subscribed user can disable the AI watermark.

## Context

Repository evidence is concentrated in the Vue workspace modules indexed by `docs/CONTEXT_SUMMARY.md`:

- Video retry and cancellation UI/logic are in `frontend/src/features/workspace/VideoPhasePanel.vue`.
  - `retryFailed()` calls `retryFailedVideoItems(job.value.id)` once, then waits for the endpoint response and polling result.
  - The result toolbar retry button has no `:disabled="generating"` guard.
  - As soon as the retried job becomes active, the cancel button is inserted in the same toolbar area. A fast second click can therefore re-enter retry or hit the newly shown cancel control.
  - The backend endpoint in `backend/app/api/public.py` commits failed video items to `queued`, then awaits `run_video_job`. The pending unarchived `changes/010-generation-video-buffer-queues/` plans to make this endpoint enqueue and return quickly; this change must layer on either resulting timing.
- The three generation services persist raw exception strings:
  - Suite: `backend/app/services/jobs.py` sets `GenerationJob.error` / `GenerationItem.error` to `str(exc)`.
  - A+: `backend/app/services/aplus_jobs.py` does the same for plan jobs and A+ items.
  - Video: `backend/app/services/video_jobs.py` does the same for video jobs and items.
- Current frontend presentation differs:
  - Suite uses the top AntD `message` in `notifySuiteJobResult()` and retry catches, but also puts `generationFailureMessage(job)` in the toolbar and exposes item errors through the script dialog.
  - A+ uses the top `message` for generation/retry failures, but failed cards render `item.error` directly under the result metadata.
  - Video shows a generic terminal `message` for failed/partial statuses, renders `item.error` on failed cards, and routes request failures through `Modal.error` in `handleRequestError()`.
  - `frontend/src/api/client.ts` has request-error normalization, but no build-environment distinction for generation failures. Production can therefore receive the exact backend/provider exception stored in a job or item.
- Watermark preference is controlled by `frontend/src/features/workspace/WatermarkDownloadMenu.vue`.
  - A subscribed user can currently turn off `包含 AI 水印` immediately.
  - The menu is reused by both suite results (`WorkspaceView.vue`) and A+ results (`APlusPhasePanel.vue`), including per-batch-group preferences, so the confirmation belongs inside this reusable component.

## Scope

### In Scope

- Make video `重试失败` trigger the retry API on the first valid click.
- Keep the retry control non-interactive for exactly 2 seconds after that click and prevent the newly active cancel control from receiving an accidental click during that interval.
- Show `取消任务` after the cooldown only when the refreshed/optimistic job state is still active.
- Centralize suite, A+, and video generation-failure presentation in the AntD top `message`.
- Show detailed backend exception/request information in development/test builds.
- Show only the agreed generic production message for generation failures: suite/A+ uses the image wording and video uses the video wording.
- Remove raw generation exception text from result headers, failed cards, and script dialogs; status placeholders such as `生成失败` remain.
- Add an acknowledgement modal for disabling `包含 AI 水印` when `canExportWithoutWatermark` is true.
- Preserve the exact user-provided warning copy, require the `我已知悉` checkbox, and keep the red `确定` button disabled until it is checked.
- Update focused frontend tests and source-contract tests affected by the new behavior.

### Out of Scope

- Do not implement or alter the Redis generation/video queue, worker, quota, or backend cancellation semantics from change `010`.
- Do not change provider execution, retries, logging, database schemas, API routes, or the fact that backend errors remain available in job/item payloads for diagnostics.
- Do not change upload, copywriting, OCR, text edit, video secondary edit, or admin errors unless they occur as part of the covered generation lifecycle.
- Do not remove watermark eligibility checks or subscription upsell behavior for users who cannot export without a watermark.

## Implementation Plan

1. **Video retry guard and cooldown**
   - Add a monotonically sourced cooldown state in `VideoPhasePanel.vue`, for example `retryCooldownUntil`, plus a timer that clears it after 2000 ms.
   - Guard `retryFailed()` against `generating`, optimistic IDs, missing failed items, and active cooldown.
   - Snapshot the current terminal job, immediately mark failed items as retrying/running, clear their displayed errors, and set the job status active so the first click visibly starts the task.
   - Call `retryFailedVideoItems(job.id)` exactly once. On request/poll failure, restore the snapshot or mark those items failed again and show the unified failure message.
   - Bind the retry button to `:disabled="generating || retryCooldownActive"`.
   - Keep both cancel buttons hidden while the cooldown is active. After 2000 ms, render `取消任务` only when `videoJobActive` remains true, retaining the existing `cancelling` disabled state.
   - Clear the timer on unmount and when a different history job is opened or `startNewTask()` resets the panel.

2. **Generation failure message helper**
   - Add a small frontend-only helper beside the existing workspace model logic, with:
     - a stable production fallback constant;
     - a detail-enabled check based on Vite dev mode or an explicit non-production/test build flag such as `VITE_SHOW_DETAILED_GENERATION_ERRORS=true`;
     - request-error extraction through `userFacingApiErrorMessage`;
     - job/item extraction through `generationFailureMessage`.
   - For generation lifecycle failures in suite, A+, and video, call `message.error(...)` with the helper result. Do not open `Modal.error` for these failures.
   - Apply the helper to creation/retry request exceptions, terminal failed/partial-failed job notifications, and polling timeout/failure paths that currently report an exception.
   - Keep cancellation/success notifications unchanged; a user cancellation is not a generation exception.
   - Remove direct rendering of `item.error` and `job.error` from generation result surfaces. Keep status labels and retry affordances.

3. **Environment behavior**
   - Development/test: the top message contains the available detailed exception, prefixed only where necessary for clarity.
   - Production: suite and A+ covered exceptions show exactly `生成图片失败，请稍后重试`; video covered exceptions show exactly `生成视频失败，请稍后重试`.
   - Avoid embedding backend environment state in the response; use the frontend build mode so a production browser bundle cannot be switched to verbose errors without rebuilding.
   - Keep raw backend diagnostics available to operators through existing job payloads, execution logs, and admin tooling.

4. **Watermark acknowledgement**
   - In `WatermarkDownloadMenu.vue`, intercept any attempt to change `包含 AI 水印` from checked to unchecked when `canExportWithoutWatermark` is true.
   - Open a local confirmation modal with the exact copy supplied by the user. Keep the supplied legal wording unchanged.
   - Initialize `我已知悉` to unchecked every time the modal opens; disable the red/danger `确定` button while it is unchecked.
   - Cancel or backdrop/mask close leaves the current watermark state unchanged.
   - Only successful confirmation emits `update:includeWatermark(false)`; changing from unchecked to checked remains immediate.
   - Keep the current disabled/upsell path for users without export permission.
   - Add accessible labels and stable layout for the checkbox and modal body so long legal text remains readable on mobile.

5. **Tests**
   - Add focused component tests for video retry:
     - first click calls the API once;
     - second click during the first 1999 ms does not call retry or cancel;
     - cancel appears after 2000 ms only for an active job;
     - request failure restores a retryable failed state after cooldown.
   - Add tests for failure-message resolution in detailed and production modes.
   - Add watermark menu tests:
     - subscribed off-toggle opens the modal;
     - OK is disabled before checking `我已知悉`;
     - checking it enables the red OK action and emits `false`;
     - cancel emits nothing;
     - non-subscribed users still see the locked/upsell path.
   - Update existing raw-source expectations that currently require `Modal.error`, direct item-error rendering, or an unguarded video retry button.

## Verification Plan

- From `frontend/`, run `npm run test:run -- workspace.test.ts`.
- From `frontend/`, run `npm run typecheck`.
- From `frontend/`, run `npm run build` to verify production typing/bundling.
- Add or update component tests with fake timers for the exact 2-second boundary.
- Manual check in development:
  - create a video job with a failed item;
  - click `重试失败` once and confirm the API is called once and the button becomes disabled;
  - click repeatedly in the same area during 2 seconds and confirm no cancellation request is sent;
  - advance past 2 seconds and confirm `取消任务` appears only while the job is active.
- Manual generation-failure checks:
  - simulate suite, A+, and video background/item failures in development and confirm the detailed exception appears only in the top message;
  - run a production build and confirm the top message is exactly the agreed generic text and failed cards/toolbars/scripts do not show raw exceptions.
- Manual watermark checks:
  - with a subscription, turn the checkbox off, cancel, and confirm it remains on;
  - reopen it, verify OK is disabled, check `我已知悉`, and confirm only the red OK applies the no-watermark preference;
  - without a subscription, confirm the control remains locked and the upsell path still works.

## Open Questions

- [x] Q1: In production, should video failures also show the exact unified text `生成图片失败，请稍后重试`, as requested, rather than `生成视频失败，请稍后重试`? - Decision: 套图和 A+ 显示 `生成图片失败，请稍后重试`；视频显示 `生成视频失败，请稍后重试`。
- [x] Q2: Should content-safety interception also move from `Modal.error` to the top `message`, or remain a modal because it is a policy decision rather than a backend processing exception? - Decision: 都迁移到顶部 `message`。
