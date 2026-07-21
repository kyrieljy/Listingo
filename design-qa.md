# Listingo Design QA

final result: passed

## Source and target

- Source: DesignKit product workspace at 1440×900, captured from the live reference page.
- Target: Listingo `/app/suite` at 1440×900 and 390×844.
- The reference page displayed its own promotional modal during the final capture; comparison used the still-visible shell, header, navigation rail, parameter panel, canvas proportions, density and control geometry, together with the earlier unobstructed source inspection.

## Blocking findings

- P0: none.
- P1: none.
- P2: none.

## Verified

- Desktop shell matches the reference structure: 54px header, narrow phase rail, fixed parameter panel and large gray preview canvas.
- Listingo brand, four requested phase names, no membership/payment/user flow.
- Phase 1 sample upload, 7-image Dryrun task, per-image results, selection, edit modal and child version creation.
- Phase 2 A+ demo reaches a completed result while explicitly stating that no external model is called.
- Phase 3 and 4 routes render their own interactive demo surfaces.
- Admin provider page renders four disabled presets without keys.
- Admin prompt page visibly locks the content source to the uploaded MD and displays the imported v1 content.
- Mobile 390×844 uses a parameter drawer and fixed bottom phase navigation with no horizontal overflow.
- Browser console: no application errors observed in the verified flows.

## P3 follow-up ideas

- Split the large Ant Design vendor chunk if cold-start network performance becomes important; this is not material for the local Demo.
- Add richer in-canvas node property editing when the Workflow feature moves from demonstration to production use.

## 2026-07-17 uploaded-thumbnail close control

- Source visual truth: `C:\Users\54901\AppData\Local\Temp\codex-clipboard-bdb85163-64f3-4235-9ef7-1437e4f7b272.png`.
- Implementation screenshots: `C:\Users\54901\AppData\Local\Temp\listingo-close-button-full.png` and `C:\Users\54901\AppData\Local\Temp\listingo-close-button-mobile.png`.
- Viewports: default desktop viewport and 390×844 mobile viewport.
- State: one Listingo sample product uploaded; upload thumbnail and its removal control visible.
- Full-view evidence: desktop and mobile captures show the removal control remains attached to the thumbnail without changing the surrounding upload layout.
- Focused evidence: browser geometry measured a 24×24 button and 12×12 `CloseOutlined` icon with `centerDelta.x = 0` and `centerDelta.y = 0`; a separate crop was not used because the browser clip output did not preserve the intended viewport region reliably.
- Interaction tested: “使用 Listingo 演示商品” → thumbnail appears → “删除已上传商品图” → thumbnail and removal control both disappear.
- Console check: no relevant warnings or errors.
- Fonts and typography: the font-dependent `×` glyph was removed; the standard icon library now controls stroke shape independently of text baseline.
- Spacing and layout rhythm: the circle remains at the thumbnail corner; explicit padding and line-height prevent default button metrics from shifting the icon.
- Colors and visual tokens: the existing dark translucent circle and white foreground treatment are preserved.
- Image quality and asset fidelity: the product image, crop and thumbnail mask are unchanged; the close mark uses the existing Ant Design vector icon rather than a text symbol or custom drawing.
- Copy and content: the control adds the accessible name “删除已上传商品图”; no visible copy changed.
- Findings: no actionable P0, P1 or P2 differences remain for the requested close-control correction.
- Comparison history: initial evidence showed a visibly uneven text glyph; the fix replaced it with `CloseOutlined`, removed native padding/line-height, and the post-fix browser measurement confirmed exact geometric centering.

final result: passed

## 2026-07-17 model preference dropdown

- Source visual truth: `C:\Users\54901\AppData\Local\Temp\codex-clipboard-8cfe02da-01a4-41f5-868f-41af8e161c19.png`, `C:\Users\54901\AppData\Local\Temp\codex-clipboard-fe6ecb35-0784-4799-bee7-4abb9cda6007.png`, `C:\Users\54901\AppData\Local\Temp\codex-clipboard-ddb447eb-6997-4bfd-ba38-fa65d09ae527.png`, and refinement screenshot `C:\Users\54901\xwechat_files\q549017020_91fe\temp\RWTemp\2026-07\8c210ed8be08a67eaba4d9eb0b74ddc4\27c2b6408e7bb9178ac47b28c0d94a83.png`.
- Implementation screenshot: `C:\Users\54901\AppData\Local\Temp\listingo-model-preference-compact.png`.
- Viewport and state: latest local frontend at `http://127.0.0.1:5174/app/suite`, dropdown open under “商品卖点与要求”.
- Full-view evidence: the former “商品保持优先” switch is no longer inside “套图结构配置”; the control now appears directly below the selling-points textarea.
- Focused evidence: browser DOM measurement returned trigger `110×30`, trigger font `12px`, menu width `206`, old `.preference-switch` count `0`, and deleted Live explanatory copy `false`.
- Interaction tested: opening the dropdown, selecting “视觉排版优先”, and verifying the trigger text updates while the menu closes.
- Browser limitation: the in-app Browser viewport override reported `innerWidth = 1280` after a requested 390×844 run, so this pass does not claim a fresh mobile-width visual verification.
- Fonts and typography: label and option text were reduced to match the smaller utility-control density.
- Spacing and layout rhythm: the removed Live explanatory paragraph reduces vertical clutter; the dropdown remains between the textarea and “套图结构配置”.
- Colors and visual tokens: the trigger uses the existing quiet gray control treatment; selected option uses a subtle gray row and standard Ant Design check icon.
- Image quality and asset fidelity: no image assets changed.
- Copy and content: the requested Live explanatory sentence was removed; model names remain hidden behind business preference labels.
- Findings: no actionable P0, P1 or P2 differences remain for the requested size and placement change.

final result: passed

## 2026-07-17 DesignKit generation setting options

- Source visual truth: `https://www.designkit.cn/product-kit/?from=home`, opened in the in-app browser and inspected by opening each generation-setting dropdown.
- Implementation screenshot: `C:\Users\54901\AppData\Local\Temp\listingo-designkit-options.png`.
- Viewport and state: latest local frontend at `http://127.0.0.1:5174/app/suite`, generation settings visible.
- Full-view evidence: the local panel now shows the same default values as DesignKit: “亚马逊 / 美国 / 英文 / 1:1”.
- Focused evidence: browser DOM read returned platform options `亚马逊, 淘宝天猫, 1688, Temu, TikTok Shop, 拼多多, 抖音电商, OZON, 独立站, Shopee, 阿里国际站, 速卖通, SHEIN, 京东, 美客多, Coupang, Wayfair`; market options `美国, 欧洲, 中国, 俄罗斯, 东南亚, 西班牙, 德国, 日本, 韩国, 巴西, 墨西哥`; language options `英文, 中文, 俄语, 西语, 德语, 日语, 韩语, 葡萄牙语, 印尼语, 泰语, 无文字`; ratio options `1:1, 3:4, 9:16, 16:9`.
- Interaction tested: reference dropdowns were opened in DesignKit to capture current options; local page was reloaded and all native select options were read from DOM.
- Fonts and typography: no style changes were required.
- Spacing and layout rhythm: shorter option lists reduce dropdown scanning load without changing panel layout.
- Colors and visual tokens: no token changes.
- Image quality and asset fidelity: no image assets changed.
- Copy and content: labels remain “电商平台 / 目标市场 / 图片语言 / 画面比例”; option copy now follows DesignKit.
- Findings: no actionable P0, P1 or P2 differences remain for the requested option-list alignment.

final result: passed

## 2026-07-21 doc-sync from source

- Source truth: repository source under `backend/app/**` and `frontend/src/**`, specifically `services/content_safety.py`, `services/jobs.py`, `services/video_jobs.py`, `services/providers.py`, `services/workflow_registry.py`, `services/prompt_contract.py`, `seed.py`, `config.py`, `api/public.py`, `api/admin.py`, `schemas.py`, plus `frontend/src/features/workspace/workspace-model.ts` and `frontend/src/api/client.ts`.
- Docs updated: `README.md`, `TECH_STACK.md`, `SPEC.md`, `开发计划.md`, `TASKS.md`.
- Concrete corrections applied to the docs:
  - Concurrency ceiling changed from “3” to “default 4, configurable 1–8 via `LISTINGO_MAX_JOB_CONCURRENCY`”.
  - Preset provider matrix rewritten to reflect the 7 seeded providers: `doubao-seed-2-0-mini` (default LLM via router.shengsuanyun.com), `qwen-3-6` (fallback LLM), `gpt-5-4-mini` (preset only), `yunwu-nano-pro`, `yunwu-nano`, `yunwu-image-2`, `shengsuanyun-seedance-1-5-pro` (video default).
  - Video phase reclassified from “local simulation only” to a real Seedance 1.5 Pro Live path: `shengsuanyun_tasks_generation` adapter, `ecommerce-video-meta-15s` prompt, `submit_video_task` + `get_video_task` polled 180 × 5s, mp4 persisted to `data/results/`.
  - Prompt asset roster changed from 5 (with `image-quality-review`) to 6: `ecommerce-meta`, `product-vision`, `copywriting-assist`, `edit-rewrite`, `content-safety-review`, `ecommerce-video-meta-15s`.
  - Workflow reference updated from 9-node to 8-node / 7-edge form. `image_qa` node removed by seed migration; `REQUIRED_NODE_TYPES = ["input", "product_vision", "meta_prompt", "llm", "contract", "semantic_validator", "image_generate", "aggregate"]`.
  - Content-safety pipeline documented: local keyword filter + LLM `content-safety-review`, applied at generation input, generation plan, per-image output, video input, video script; failures surface as `ContentSafetyBlocked` (HTTP 4xx).
  - Video Live requires `LISTINGO_PUBLIC_ASSET_BASE_URL` (non-`localhost/127.0.0.1`); admin `/runtime-settings` reads/writes this value.
- Not covered in this pass: no browser regression, no Pytest/Vitest run, no Live smoke. Any interactive verification of the video path still requires a valid Seedance key and a public asset base URL.
- Findings: no actionable P0/P1/P2 remain for the requested doc-sync; source is now the single source of truth and the five docs mirror it.

final result: passed
