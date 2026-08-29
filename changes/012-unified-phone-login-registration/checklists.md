# 验证清单 - Unified Phone Login And Registration

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## Implementation

- [x] Confirm and record the compatibility decision for legacy `/auth/register` and `SmsLoginCreate.mode=register`.
- [x] Change default `/auth/sms/login` to verify the `login` purpose and create the user when the phone number is absent.
- [x] Reuse an existing user instead of duplicating it when the phone number is already registered.
- [x] Handle the concurrent first-login unique-phone case by reusing the winning user rather than returning 409.
- [x] Preserve active-user checks, session issuance, SMS login events, registration notifications, and transaction behavior.
- [x] Keep legacy SMS register-purpose verification compatible for clients that already obtained a register code.
- [x] Remove the frontend register mode, register SMS timer/state, password registration form, and login/register mode switch.
- [x] Make the unified SMS form always request `purpose=login` and submit default login mode.
- [x] Keep password login and admin second-factor behavior unchanged.
- [x] Remove register-mode prop plumbing from `WorkspaceView.vue`.
- [x] Update focused backend and frontend tests for the unified flow.
- [x] Update `docs/CONTEXT_SUMMARY.md` and, if needed, `TASKS.md` for the new auth capability.

## Verification

- [x] Backend: a previously absent phone number sends a `login` code and logs in successfully through default `/auth/sms/login`.
- [x] Backend: the auto-created user is active, on the free plan, normalized by phone, and has a session and `sms` login event.
- [x] Backend: the same phone number logs in again as the same user after a fresh `login` code.
- [x] Backend: a used code is rejected, five wrong attempts lock the code, and cooldown/daily limits still apply.
- [x] Backend: a disabled existing user cannot log in.
- [x] Backend: legacy `mode=register` compatibility behaves according to the Open Questions decision.
- [x] Frontend: the auth modal exposes SMS and password login only, with no explicit registration branch.
- [x] Frontend: SMS code requests use `purpose=login`.
- [x] Frontend: new and existing SMS users both reach the authenticated workspace state.
- [x] Frontend: password login, admin second-factor, first-password, agreement, country selector, and close/open behavior remain usable.
- [x] Run `.venv/Scripts/python.exe -m pytest backend/tests/test_sms_phone.py`.
- [x] Run the broader backend auth/API tests affected by this change.
- [x] From `frontend/`, run `npm run test:run -- auth-model.test.ts`.
- [x] From `frontend/`, run `npm run typecheck`.

## Regression

- [x] Existing SMS login users are not recreated and keep their plan, quota, profile, notifications, and sessions.
- [x] Existing password users can still log in, including admins with SMS second verification.
- [x] Users without a password can still set one from account settings.
- [x] Change-phone verification still uses its dedicated purpose and is not accepted by the login endpoint.
- [x] Admin verification still uses its dedicated purpose and bypass rules.
- [x] Auth modal layout remains stable on supported mobile and desktop sizes.
- [x] No unrelated dirty-worktree changes are reverted or included.
