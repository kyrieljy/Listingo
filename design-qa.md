# Listingo Design QA

final result: passed

## Source Of Truth

- Repository source under `backend/app/**` and `frontend/src/**`.
- Runtime Prompt files under `backend/app/prompts/**`.
- Local SQLite active Prompt versions are used only to confirm the current local runtime content before push.
- Historical runtime data, uploaded assets, generated results and encrypted keys are not source assets and must not be committed.

## Current Verified Product Facts

- Provider seed now contains 8 providers, including `shengsuanyun-doubao-seedance-2-0` for video and `aplus-mobile-edit-low-cost` for A+ mobile output.
- Runtime Prompt roster now contains 7 active source-backed assets: `ecommerce-meta`, `aplus-meta`, `product-vision`, `copywriting-assist`, `edit-rewrite`, `content-safety-review`, `ecommerce-video-meta-15s`.
- `aplus-meta` uses `backend/app/prompts/aplus_meta_prompt_0729.md`.
- `image-quality-review` may remain in a local SQLite database as a legacy prompt record, but current runtime Workflows do not call it.
- Provider routing is controlled by route roles, not only by global default/fallback flags.
- Admin Prompt tests can run LLM output tests and full-chain tests. Full-chain test jobs are flagged `is_admin_test=true` and filtered out of public task history.
- Video Live uses Doubao-Seedance-2.0 through `shengsuanyun_tasks_generation`.

## UI And Interaction Checks To Preserve

- `/app` remains the front office workspace with four phase entries.
- `/admin` remains the local operations console for Provider, Workflow, Prompt and log management.
- The A+ panel supports counted module selection and output target selection.
- The admin Provider page exposes route-role grouping and route completeness.
- The admin Prompt page exposes upload, version activation, LLM test and full-chain test controls.
- Mobile layout must avoid horizontal overflow and keep the phase navigation usable.

## 2026-07-29 Doc Sync

- Docs updated: `README.md`, `TECH_STACK.md`, `SPEC.md`, `开发计划.md`, `TASKS.md`, `design-qa.md`.
- Stale references removed or corrected:
  - Video Provider docs now use `shengsuanyun-doubao-seedance-2-0` / `bytedance/doubao-seedance-2-0`.
  - Provider docs now state 8 seeded Providers.
  - Prompt docs now state 7 runtime Prompt assets, including `aplus-meta`.
  - A+ demo-only wording → A+ 0729 Prompt planning and generation chain.
  - Prompt backend display-only wording → Prompt upload, activation, LLM test and full-chain test.
- Validation completed before commit: backend Pytest `71 passed`, frontend Vitest `53 passed`, frontend production build passed with the known Vite large-chunk warning, Alembic has single head `b7d2c6a9e8f1`, and all 7 runtime Prompt file hashes match the local SQLite active versions.

## Known Residual Risk

- Full paid Live validation still requires valid API keys and, for video, a public `LISTINGO_PUBLIC_ASSET_BASE_URL`.
- The frontend production build may continue to warn about a large bundled chunk; this is a known local-demo performance warning, not a functional failure.
