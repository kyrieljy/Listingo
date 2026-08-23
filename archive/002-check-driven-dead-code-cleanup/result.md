# Result: check-driven dead code cleanup

## Implementation Summary

- 删除无生产调用的 `copy_video_file`、`set_provider_route_role`、`_image_parameter_schema`、`_video_parameter_schema`、`run_image_with_fallback`、`detect_text_lines` 与未引用的 `SmokeyBackground.vue`。
- 将 OCR 排序/过滤用例改为调用现行生产入口 `detect_text_lines_with_status`；旧双 Provider fallback 的重复用例随死代码移除，现行 route 顺序回退链路仍由既有测试覆盖。
- 移除应用直接依赖 `dayjs` 与后端测试依赖 `pytest-asyncio`。`dayjs` 保留为 `ant-design-vue@4.2.6` 的传递依赖。
- RapidOCR 初始化不再尝试未声明的 `rapidocr` 包名，只导入 requirements 已锁定的 `rapidocr_onnxruntime`。
- 同步 `SPEC.md`、`TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md` 的测试依赖事实和变更索引；未采纳 `report.md` 的 AsyncSession、全量分层重构和工具链引入建议。

## Commands and Checks

- `npm install --package-lock-only --ignore-scripts --no-audit --no-fund` — passed；仅提示当前 Node 24.15.0 与声明 24.13.x 不同。
- `npm ls dayjs --omit=dev` — passed；显示 `dayjs@1.11.20` 仅位于 `ant-design-vue@4.2.6` 下。
- `.venv/Scripts/python.exe -m compileall -q backend/app backend/tests` — passed。
- `.venv/Scripts/python.exe -m pytest backend/tests` — passed: `162 passed, 1 warning`。
- `cd frontend; npm run test:run` — passed: `4 files, 94 tests passed`。
- `cd frontend; npm run typecheck` — passed。
- `cd frontend; npm run build` — passed；仅保留既有 large chunk 提示。
- `git diff --check` — passed；输出仅剩仓库既有 CRLF conversion warnings。

## Evidence

- `git grep` 复核删除项：旧组件与五个后端死函数无源码引用；Provider 目录只剩现行 `_provider_image_parameter_schema` / `_provider_video_parameter_schema`。
- OCR 用例现在直接断言 `detect_text_lines_with_status(...).lines`，排序、bbox 和替换表行为保持原有断言。
- `frontend/package.json` 无 `dayjs`；`frontend/package-lock.json` 中 root dependencies 无 `dayjs`，Ant Design Vue 依赖块仍声明 `dayjs: ^1.10.5`。
- `backend/requirements.txt`、`SPEC.md`、`TECH_STACK.md` 均无 `pytest-asyncio`；后端源码无 `from rapidocr import` fallback。
- 后端全量测试覆盖管理路由、Dryrun、Batch、执行、Prompt、安全种子与短信链路；前端全量测试和构建覆盖当前认证、工作台与后台 UI 依赖闭包。

## Failures and Blockers

- No failing checks remain.
- 本地既有 `.venv` 仍安装着 `pytest-asyncio`，因此测试头部仍显示插件；这不是 requirements 依赖，重建环境时不会安装。
- `pytest` 保留既有 `StarletteDeprecationWarning`，生产构建保留既有 chunk-size 警告；均与本轮清理无关。
