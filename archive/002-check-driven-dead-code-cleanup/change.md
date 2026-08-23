# Change: check-driven dead code cleanup

## 变更标题
按 check.md 删除已确认死代码并收紧依赖声明

## 变更背景 / 上下文
- 来源需求：用户要求分析 `check.md`，删除确认无用的死代码，并批判性处理 `report.md` 的建议且保证功能正常。
- 关联模块：Provider 参数目录与路由、图片执行链路、OCR 改字、视频任务、前端认证组件与依赖声明。
- 影响范围：`backend/app/services` 的无生产调用函数、`backend/tests/test_execution.py` 的测试路径、`frontend/package.json` 与 lockfile、未引用的 `SmokeyBackground.vue`、依赖说明文档。
- 复核事实：`dayjs` 无应用源码引用，但 `ant-design-vue` 自身声明了 `dayjs` 传递依赖；`pytest-asyncio` 没有标记、fixture 或模式配置使用；六个候选函数均无生产调用，其中 `detect_text_lines` 与 `run_image_with_fallback` 仅被测试调用。

## 目标
- 删除确认无生产调用的组件、函数与测试专用兼容包装，不改变 API 契约和任务状态机。
- 移除应用层未直接使用的 `dayjs` 与 `pytest-asyncio` 声明，保留仍被运行时需要的传递依赖。
- 将 RapidOCR 初始化限定到 `requirements.txt` 已声明的 `rapidocr_onnxruntime`，避免依赖不存在的备用包名。
- 批判性排除 `report.md` 中的大范围建议，防止低风险清理变成架构或工具链重构。

## 方案设计
### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/services/video_jobs.py` | 修改 | 删除无调用的 `copy_video_file` 及随之无用的 `shutil` 导入。 |
| `backend/app/services/provider_routing.py` | 修改 | 删除无调用的 `set_provider_route_role`；API 现行逻辑保持不变。 |
| `backend/app/services/provider_catalog.py` | 修改 | 删除两个无调用的旧参数 schema helper，保留现行 Provider 专用 schema。 |
| `backend/app/services/execution.py` | 修改 | 删除仅被测试调用的旧双 Provider fallback helper。 |
| `backend/app/services/image_text_edit.py` | 修改 | 删除仅被测试调用的 `detect_text_lines` 包装；删除未声明的 `rapidocr` fallback 导入。 |
| `backend/tests/test_execution.py` | 修改 | 将 OCR 测试改走现行 `detect_text_lines_with_status`；删除旧双 Provider fallback 的重复测试。 |
| `frontend/src/features/auth/SmokeyBackground.vue` | 删除 | 全仓无引用的旧 WebGL 背景。 |
| `frontend/package.json` | 修改 | 移除应用直接依赖 `dayjs`。 |
| `frontend/package-lock.json` | 修改 | 同步 root 依赖声明；`dayjs` 仍作为 `ant-design-vue` 传递依赖保留。 |
| `backend/requirements.txt` | 修改 | 移除未使用的 `pytest-asyncio`。 |
| `TECH_STACK.md` / `SPEC.md` / `docs/CONTEXT_SUMMARY.md` | 修改 | 同步测试依赖事实与本次清理记录。 |
| `changes/002-check-driven-dead-code-cleanup/checklists.md` | 新增 | 记录实现与回归验证项。 |

### 实现要点
1. 高置信死代码直接删除：`copy_video_file`、`set_provider_route_role`、`_image_parameter_schema`、`_video_parameter_schema`、`SmokeyBackground.vue`。
2. 测试专用包装删除时同步调整测试：OCR 用例改测生产路径；旧 fallback 用例不再保留，现行 `run_image_route` 顺序回退已有覆盖。
3. `dayjs` 仅从应用直接依赖中移除，不尝试从依赖树剔除 Ant Design Vue 必需的传递版本。
4. `report.md` 建议处理边界：不迁移 AsyncSession、不全量下沉 API 业务逻辑、不引入 Ruff/mypy/ESLint/knip/vulture；这些属于独立架构或工具链决策，与本轮死代码清理无关。

## 验收标准
- [x] 被删除的函数、组件和依赖声明不再出现在源码或清单中；`dayjs` 只作为传递依赖存在。
- [x] OCR 改字检测、Provider 参数 schema、Provider 路由更新和视频保存行为不变。
- [x] 后端全部既有测试通过。
- [x] 前端全部既有 Vitest、严格类型检查和生产构建通过。
- [x] `git diff --check` 无新增空白错误。

## Open Questions
None.
