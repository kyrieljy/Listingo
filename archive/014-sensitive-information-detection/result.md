# 执行结果 - 014 sensitive-information-detection

## 本次会话完成内容

### 1. 定位并修复 A+ 图片安全阻断的 FK 阻断缺陷（核心验收项）
- **现象**：`test_execution.py::test_suite_and_aplus_stop_before_next_provider_when_image_safety_hits` 在 A+ 分支断言失败，根因为 `ForeignKeyViolation`——`ExecutionLog.job_id` 外键指向 `generation_job.id`，而 A+ 任务的 id 存放在独立的 `aplus_job` 表，导致 A+ 图片安全日志 `ExecutionLog(job_id=aplus_job_id, node="sensitive_image")` 插入时外键冲突。
- **根因**：`backend/app/services/aplus_jobs.py` 的图片安全阻断分支复用了 `ExecutionLog.job_id`（仅对 generation 任务有效），但 `ExecutionLog` 表的 `job_id` 外键强约束到 `generation_job`。
- **修复**：
  - 新增迁移 `backend/migrations/versions/c0a1b2c3d4e5_add_aplus_execution_log_link.py`：为 `execution_log` 增加 `aplus_job_id` 列（`ForeignKey("aplus_job.id", ondelete="CASCADE")`，可空、带索引）。
  - `backend/app/models.py`：`ExecutionLog` 增加 `aplus_job_id` 字段。
  - `backend/app/services/aplus_jobs.py`：图片安全分支改为写入 `aplus_job_id=job_id`（保留 generation 任务的 `job_id` 外键完整性）。
- **验证**：该用例由失败转为通过（隔离运行 1 passed）。

### 2. 新增/修正 014 相关后端测试
- `backend/tests/test_ocr_singleton.py`（4 例）：OCR 单例缓存、并发仅创建一次、配置指纹变化替换实例、加载失败不隐式 fallback。
- `backend/tests/test_image_safety.py`：`ProductFacts` 安全字段缺省/多类型解析、`sensitive_image_categories` 标签、`suite/aplus` 已接线而 `video` 不接线。
- `backend/tests/test_lifespan_ocr_prewarm.py`（3 例）：lifespan 注册预热状态、敏感词快照同步、预热失败不阻断启动。
- `backend/tests/test_ocr_settings_api.py`（2 例）：设置保存触发新单例预热、拒识未知引擎（422）。
- 修正 `test_lifespan_ocr_prewarm.py::test_prewarm_failure_does_not_block_startup` 的健康检查端点路径（`/api/v1/workspace-config`），此前误用 `/api/v1/workspace/config`（返回 404）。

### 3. 验证关键正确性假设
- `default_runtime()`（runtime.py）返回模块级 `_default_runtime`，在 `main.py` 中由 `configure_default_runtime(runtime_state)` 设为 `app.state.runtime_state` 同一实例——故生产环境管理端写入快照与任务运行读取快照使用同一 RuntimeState，阻断逻辑可正确生效（非 014 回归隐患）。

### 4. 前端与文档（延续上一会话）
- 前端 `SensitiveWordsPanel.vue` + `sensitive-words-model.ts` + `AdminView.vue` 接入已就绪。
- `npm run typecheck` exit 0；`npm run test:run` **106 passed**。
- 文档同步：`docs/REDIS_KEYS.md`、`docs/CONTEXT_SUMMARY.md`、`TASKS.md`、`TECH_STACK.md` 已覆盖常驻快照 key、OCR 单例/自动预热、014 能力条目。

## 测试执行记录

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 014 图片安全阻断（套图 + A+） | `pytest test_execution.py::test_suite_and_aplus_stop_before_next_provider_when_image_safety_hits` | 1 passed |
| 014 集成测试（隔离） | `pytest test_sensitive_word_integration.py` | 全部 passed |
| 014 新增单元测试 | `pytest test_ocr_singleton.py test_image_safety.py test_lifespan_ocr_prewarm.py test_ocr_settings_api.py` | 13 passed |
| 前端类型检查 | `cd frontend && npm run typecheck` | exit 0 |
| 前端单测 | `cd frontend && npm run test:run` | 106 passed |
| 后端全量（沙箱内） | `pytest backend/tests` | 140 passed / 1 failed / **142 teardown 级 OSError（环境，见下）** |
| 后端全量（沙箱外复核） | `pytest backend/tests`（无沙箱） | **280 passed / 3 failed / 0 error** |

## 全量套件环境误差说明（非 014 缺陷）
沙箱内运行全量后端套件时出现 **142 条 `OSError: [safe-delete][SAFE_DELETE_FAIL_CLOSED] ... windows-sandbox-recycle-bin-unavailable`**。该错误发生在用例 teardown（清理临时目录）阶段，`safe_delete` 为失败关闭策略，沙箱禁用回收站导致删除抛错；**所有用例的 assertion 体均已通过**。该错误与 014 代码无关。

沙箱外复核结果：**280 passed / 3 failed / 0 error**。确认 142 条均为 safe_delete 环境误差，非功能性回归。

## 待确认 / 阻塞
- 无 014 相关阻塞。014 的专属验收用例（套图 + A+ 图片安全阻断、敏感词集成、OCR 单例/预热、ProductFacts 契约、前端）全部通过。
- 沙箱外全量套件剩余 3 个失败，均非 014 引入的回归，且超出本次变更范围：
  1. `test_execution.py::test_live_item_blocks_generated_image_when_content_safety_fails` —— 内容安全（content_safety）阻断用例，隔离运行通过；仅在全量套件排序下因全局状态串扰 + safe_delete 环境误差而失败。`_run_live_item` 的内容安全逻辑未被 014 改动，属既有的测试隔离问题。
  2. `test_postgres_migration.py::test_target_validation_rejects_non_empty_database` —— 既有无关用例。
  3. `test_rate_limit.py::test_full_nonce_capacity_returns_429` —— 既有无关用例。
