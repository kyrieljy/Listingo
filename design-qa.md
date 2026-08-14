# Listingo Design QA

final result: blocked

## Source Of Truth

- Repository source under `backend/app/**` and `frontend/src/**`.
- Runtime Prompt source files under `backend/app/prompts/**`.
- Local SQLite active Prompt versions are used only to confirm the current local runtime content before push.
- Historical runtime data, uploaded assets, generated results, encrypted keys, SMS credentials and user data are not source assets and must not be committed.

## Current Verified Product Facts

- Source Provider catalog now contains 47 presets: 3 LLM providers plus 44 image/video media providers across HelloBabyGo, fal.ai, Runware, OpenRouter, Atlas Cloud, Replicate, WaveSpeedAI, Kie.ai, CometAPI and API Models.
- Local SQLite may retain 5 legacy media Provider records from older Yunwu/Shengsuanyun configurations; they are runtime compatibility records, not the new source catalog.
- Provider routing is controlled by route chain slots `primary`, `backup1`, `backup2`, `backup3`, `backup4`; legacy `fallback` is normalized to `backup1`.
- Runtime Prompt roster contains 8 source-backed assets: `ecommerce-meta`, `aplus-meta`, `product-vision`, `copywriting-assist`, `edit-rewrite`, `image-text-edit`, `content-safety-review`, `ecommerce-video-meta-15s`.
- `aplus-meta` uses `backend/app/prompts/aplus_meta_prompt_0729.md`.
- `image-quality-review` may remain in a local SQLite database as a legacy prompt record, but current runtime Workflows do not call it.
- Admin Prompt tests can run LLM output tests and full-chain tests. Full-chain test jobs are flagged `is_admin_test=true` and filtered out of public task history.
- Video Live uses Seedance 2.0 through the `video` Provider route chain and current Provider adapters.
- Account center, auth modals, subscription plans, quota display, SMS settings, notifications, OCR text editing, AI watermark downloads, batch hosting, and admin monitoring are now part of the implemented surface.

## UI And Interaction Checks To Preserve

- `/app` remains the front office workspace with four phase entries.
- `/admin` remains the local operations console for Provider, Workflow, Prompt, logs, users, subscriptions, SMS, OCR, runtime settings and monitoring.
- The top bar supports logged-out CTA, logged-in avatar menu, account center, pricing and admin entry for admins.
- The A+ panel supports counted module selection and output target selection.
- The workspace supports suite/A+ batch hosting entry points and batch history.
- Suite and A+ generated images support OCR text detection and text-only edit versions.
- Download controls must respect paid/no-watermark access rules.
- The admin Provider page exposes route-role grouping, route completeness and group health checks.
- The admin Prompt page exposes upload, version activation, LLM test and full-chain test controls.
- Mobile layout must avoid horizontal overflow and keep phase navigation usable.

## 2026-08-13 Account Center Prototype QA

- Source visual truth path: `C:\Users\54901\.codex\generated_images\019ffb42-8765-7570-84ee-5164eb165478\call_fstY4X8EsdYRgP4vWP1xUVxQ.png`.
- Implementation target: `http://127.0.0.1:5173/app/suite`, account avatar dropdown, and `AccountModal` tabs.
- Implementation screenshot path: not captured.
- Viewport: intended desktop comparison at the source image's wide desktop state.
- Source pixels: `1718 x 1000` from the selected generated prototype.
- Implementation pixels / CSS size / density normalization: unavailable because Browser screenshot output did not return evidence.
- State: logged-in top-right avatar menu open, then personal center modal on each tab.
- Full-view comparison evidence: blocked; in-app Browser calls executed but returned no DOM, console, or screenshot payload.
- Focused region comparison evidence: blocked for avatar menu, account information, account settings, task history pagination, message center counts, and privacy toggles.
- Primary interactions tested by build-level checks: TypeScript compilation and production build passed; rendered browser interaction could not be observed.
- Console errors checked: blocked; Browser console output unavailable.

**Findings**
- [P1] Browser-rendered visual QA is not captured.
  Location: account center and avatar dropdown.
  Evidence: the source prototype is available, but the in-app Browser tool returned no inspectable screenshot/DOM output for the running local app.
  Impact: fidelity can be checked from code and build output, but cannot honestly be marked as visually passed.
  Fix: rerun visual QA once Browser output is available, capturing the dropdown open state and each account modal tab.

**Implementation Checklist**
- Capture the avatar dropdown open state and compare against the prototype's right-side menu.
- Capture `账户信息`, `套餐额度`, `账号设置`, `任务历史`, `消息中心`, and `隐私设置` modal states.
- Verify row clicks from the dropdown land on the corresponding modal tab.
- Verify task pagination stays fixed-height at 5 rows per page.
- Verify unread/read counts update after clicking an unread message.

Comparison history: first QA attempt blocked by missing browser-rendered evidence; no visual pass claimed.

## 2026-08-07 Auth UI QA

- Source references: user-provided auth button, login, account avatar and pricing modal screenshots.
- Verified in local browser at `http://127.0.0.1:5174/app/suite`.
- Logged-out state hides the History entry and shows the animated black arrow login/register CTA.
- Login/register CTA defaults to a 42px black circular arrow plus text; only pointer hover expands the black shape into a pill, while keyboard focus keeps the default shape with focus treatment.
- Login modal uses a light purple left panel with the Listingo logo and a larger local landscape WebGL water-ripple image; the ripple shader distorts the whole image with white light/shadow, and the surrounding dotted background, card border, heavy white frame, prior left-side marketing copy and stats are removed.
- Auth modal title subcopy is removed across login and registration states.
- Password login no longer asks for a bound phone number; password registration shows no explicit step indicator, uses `注册` for the credential submit state, then switches to phone verification with `完成注册`.
- Logged-in topbar shows only a circular avatar trigger; the account dropdown still exposes profile, billing and admin entry where applicable.
- Pricing cards are white by default and turn purple only on hover/focus with scale/translate animation.
- Validation completed: frontend production build passed, frontend Vitest passed, browser smoke check reported zero console errors.

## 2026-08-14 Doc And Prompt Sync QA

- Docs updated: `README.md`, `TECH_STACK.md`, `SPEC.md`, `开发计划.md`, `TASKS.md`, `design-qa.md`.
- Stale references corrected:
  - Prompt docs now state 8 source-backed runtime assets, including `image-text-edit`.
  - Provider docs now state 47 source Provider presets and separate legacy DB records from source facts.
  - Route docs now use `primary` and `backup1`-`backup4`.
  - Product docs now include auth, subscriptions, quota, mock orders, SMS, notifications, monitoring, OCR text editing, watermarks and batch hosting.
  - Deployment docs now call out backend requirements reinstall, frontend dependency install/build, Alembic upgrade and service restart.
- Validation completed before commit: 8 source Prompt files match local SQLite active versions; backend Pytest `163 passed`; frontend Vitest `94 passed`; frontend production build passed with known Vite large-chunk/plugin-timing warnings; Alembic has single head `4d5e6f7a8b9c`; staged-file safety check remains required immediately before commit.

## Known Residual Risk

- Full paid Live validation still requires valid API keys and, for video/image reference flows, a public `LISTINGO_PUBLIC_ASSET_BASE_URL`.
- Server runtime Provider keys, SMS credentials, user data and enabled route choices are intentionally not synchronized through Git.
- The frontend production build may continue to warn about a large bundled chunk; this is a known local-demo performance warning, not a functional failure.
