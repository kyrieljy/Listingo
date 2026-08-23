# Result

## Implementation Summary

- Added the backend-neutral `RateLimitStorage` adapter contract and bounded `MemoryStorage` implementation with TTL expiry, LRU eviction, a 10,000-record hard limit, and a stoppable 30-second cleanup thread.
- Added `RateLimitService` with fixed-window counters, atomic one-time Nonce consumption (60-second TTL), login-failure blocking, and `X-RateLimit-*` header data.
- Mounted IP-block middleware inside CORS, added the memory-mode startup warning, and made `WEB_CONCURRENCY > 1` fail startup outside testing.
- Applied the confirmed shared 20 requests/minute limit to suite and video generation, added password-login rate limiting/failure blocking, and required fresh Nonces for password change and mock payment.
- Updated the two frontend calls to send secure random `X-Request-Nonce` headers and configured Nginx to pass `X-Forwarded-For`.
- Synchronized `TECH_STACK.md` and `docs/CONTEXT_SUMMARY.md`.

## Commands and Checks

- `.\.venv\Scripts\python.exe -m compileall -q backend\app backend\tests` - passed.
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_rate_limit.py backend\tests\test_config.py backend\tests\test_security_and_seed.py backend\tests\test_sms_phone.py -q` - 30 passed.
- `.\.venv\Scripts\python.exe -m pytest backend\tests -q` - 181 passed.
- `cd frontend; npm run test:run` - 94 passed across 4 files.
- `cd frontend; npm run typecheck` - passed.
- `git diff --check -- backend frontend changes/004-memory-rate-limit TECH_STACK.md docs/CONTEXT_SUMMARY.md` - passed.

## Evidence

- `backend/tests/test_rate_limit.py` verifies concurrent atomic `set_if_absent()`, expiry cleanup, LRU behavior, nonce capacity rejection, cleanup-thread shutdown, shared suite/video limiting, response headers, five-failure blocking, CORS-annotated 403 responses, and startup rejection for `WEB_CONCURRENCY=2`.
- The 429 response on the combined 21st suite/video request exposes `X-RateLimit-Limit=20`, `X-RateLimit-Remaining=0`, and a `Reset` between 1 and 60 seconds.
- The blocked-login test confirms a 1,800-second block for the forwarded IP while another client remains unaffected.
- Full backend regression passed after the final middleware-order adjustment.

## Failures and Blockers

- The first focused run had one test assertion error: with `max_size=2`, the second unique nonce was incorrectly expected to be rejected. The test was corrected to expect rejection on the third nonce; subsequent runs pass.
- Backend runs report the pre-existing Starlette TestClient deprecation warning (`httpx` with `starlette.testclient`), unrelated to this change.
- No unresolved blocker remains. The worktree also contains pre-existing staged changes outside this change; they were not reverted or altered.
