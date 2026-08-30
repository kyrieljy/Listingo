# Result: batch-import-sensitive-words (015)

## 变更概述
在运营后台「敏感词检测」面板新增「批量导入」能力：一个多行文本框，运营可直接粘贴大量敏感词，前端按换行符或逗号（含中文逗号）切分后，通过后端批量接口一次性创建。

## 实现内容
| 文件 | 改动 |
|------|------|
| `backend/app/schemas.py` | 新增 `SensitiveWordBulkCreate`（`terms: list[str]` 1..2000、`enabled: bool`、`note: str≤500`） |
| `backend/app/api/admin.py` | 新增 `POST /admin/sensitive-words/bulk`：规范化去重、跳过已存在/空项、超长或无效计入 `errors`、末尾仅 `build→persist→sync` 一次快照；返回 `created/skipped/total/errors/snapshot` |
| `frontend/src/features/admin/sensitive-words-model.ts` | 新增 `bulkCreateSensitiveWords` 及 `SensitiveWordBulkPayload`/`SensitiveWordBulkResponse`，新增 `splitBulkTerms` 切分函数 |
| `frontend/src/features/admin/SensitiveWordsPanel.vue` | 新增「批量导入」卡片（文本框 + 切分说明 + 启用开关 + 可选备注 + 导入按钮 + 结果反馈 + 待导入计数） |
| `backend/tests/test_sensitive_word_bulk.py` | 新增 6 项集成测试 |
| `docs/CONTEXT_SUMMARY.md` | 运营后台条目补「批量导入」；新增 015 变更日志 |
| `TASKS.md` | 新增 015 同步任务记录 |

## 关键设计点
- **去重**：以 `normalize_sensitive_text(term, compact=True)` 为键，与数据库已有词及本批内重复比较，已存在/重复计入 `skipped`，不报错。
- **健壮性**：空项忽略；超长（>120）/无效词计入 `errors`，不阻断其余词创建。
- **性能**：整批处理完只重建一次快照，避免 N 次 `build/persist/sync`（契合「大量」场景）。
- **事务与一致性**：复用 `_locked_sensitive_config` 的 `WITH FOR UPDATE` 锁与 `_commit_sensitive_snapshot`（DB 提交失败时回滚并尽力回退 Redis），保持与单条创建一致的 422/503 语义。

## 测试验证
| 范围 | 命令 | 结果 |
|------|------|------|
| 批量导入新增用例 | `pytest backend/tests/test_sensitive_word_bulk.py` | **6 passed** |
| 敏感词 + OCR 相关回归 | `pytest test_sensitive_word_bulk + test_sensitive_word_integration + test_ocr_*` | **26 passed** |
| 前端类型检查 | `npm run typecheck` | exit 0（0 错误） |
| 前端单元测试 | `npm run test:run` | 通过（无新增失败） |

## 批量导入测试覆盖
- 多词一次性创建；`created/skipped/total/errors/snapshot` 结构正确，快照 `in_sync=true`。
- 换行/逗号/中文逗号混合切分、首尾空白与空项被忽略。
- 已存在词跳过（计 `skipped`）；本批内重复只创建一次（同样计 `skipped`）。
- 超长/无效词计入 `errors`，有效词仍创建。
- 遵守 `enabled` 标志（批量停用）。
- 空 `terms` 列表返回 422。

## 超时修复（后续）
- 现象：批量导入在体量大或 DB 延迟高时触发超时（`ECONNABORTED`）。
- 根因：原实现在请求内同步执行**全量词表**的快照重建（`build_sensitive_word_snapshot` 为所有启用词生成变体，叠加多轮 DB 读写与 `SensitiveWordConfig` 的 `WITH FOR UPDATE` 行锁），超出前端 `api` 客户端默认 `timeout: 20_000`。
- 修复：
  1. 后端 `bulk_create_sensitive_words` 仅负责创建并提交词，快照重建（build/persist/sync）改由 `BackgroundTasks` 异步执行（`_rebuild_sensitive_word_snapshot`），响应带 `rebuild_scheduled: true` 立即返回。
  2. 前端 `bulkCreateSensitiveWords` 单独设置 `timeout: 180_000`，避免被默认 20s 客户端超时打断。
- 验证新增 `test_bulk_large_batch_schedules_rebuild_and_eventually_syncs`（300 词批量：请求立即返回、`rebuild_scheduled=true`、列表接口确认快照最终 `in_sync` 且 `word_count=300`）；bulk 相关用例 7 passed。

## 验收状态
- checklists.md 全部项已回填 `[x]`（功能 15 / 测试 4 / 规范 4）。
- 无未定义需求、无阻塞项（Open Questions 为空）。
