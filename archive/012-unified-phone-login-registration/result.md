# Result: Unified Phone Login And Registration

## Implementation Summary

- Added a phone-first get-or-create path to `/api/v1/auth/sms/login`. A valid `purpose=login` code now creates an active/free user on first login and reuses the existing user afterward.
- Preserved legacy `mode=register` verification for clients that already requested a register code, and kept `/auth/register` plus the frontend `registerApi` as compatibility surfaces.
- Handled concurrent first logins by reusing the winning user after either the phone pre-check conflict or the database unique-key conflict.
- Kept active-user validation, session issuance, registration notification, `sms` login event, SMS one-time consumption, attempt limits, cooldown, and daily quota behavior.
- Removed the explicit frontend register mode, password-registration form, register SMS timer/state, and login/register switch. The auth modal now offers SMS login/registration and password login.
- Updated the workspace auth entry so login and register events open the same unified modal.
- Updated focused backend/frontend tests, `docs/CONTEXT_SUMMARY.md`, and `TASKS.md`.

## Commands and Checks

- `.venv/Scripts/python.exe -m pytest backend/tests/test_sms_phone.py`
  - Passed: 13 tests.
- `.venv/Scripts/python.exe -m pytest backend/tests/test_rate_limit.py backend/tests/test_redis_optimization.py backend/tests/test_redis_runtime_features.py::test_session_cache_hit_still_checks_user_and_logout_invalidates`
  - Passed: 24 tests.
- From `frontend/`: `npm run test:run -- auth-model.test.ts`
  - Passed: 1 file, 9 tests.
- From `frontend/`: `npm run typecheck`
  - Passed.
- From `frontend/`: `npm run test:run`
  - Passed: 7 files, 106 tests.
- `git diff --check` over the files touched by this change
  - Passed with no whitespace errors.

## Evidence

- `backend/tests/test_sms_phone.py::test_sms_login_auto_creates_and_reuses_user` verifies first login creation, user fields, session, register notification, SMS login event, one-time code use, and second-login reuse.
- `backend/tests/test_sms_phone.py::test_sms_login_rejects_disabled_existing_user` verifies disabled users remain blocked.
- `backend/tests/test_sms_phone.py::test_concurrent_first_sms_login_reuses_unique_phone_winner` verifies both unique-key and pre-check conflict recovery paths.
- Existing tests continue to cover legacy `mode=register`, five wrong code attempts, cooldown, daily send limits, password login, admin second factor, and session invalidation.
- `frontend/src/features/auth/auth-model.test.ts` now asserts the source contract: one SMS flow, `purpose=login`, no `AuthMode`/`initialMode`/`switchMode`/`registerWithPassword` branch in the modal, and the simplified SMS payload.
- Full frontend Vitest confirms the modified workspace/auth wiring remains compatible with the current dirty worktree.

## Failures and Blockers

- No failure remains in the planned checks.
- One unrelated full-file run, `backend/tests/test_redis_runtime_features.py`, failed at `test_realtime_metrics_counters_and_ocr_result_cache` with `realtime_metrics.total` expected 2 but received 0. At execution time the host was `2026-08-29 07:32 +08:00` while UTC was `2026-08-28 23:32`; analytics counters use the UTC event day while realtime reads the local host day, so the two dates crossed. This metrics/timezone behavior is outside change 012 and was not modified. The auth/session test from that file and all other selected backend checks pass.
