# Change: batch-import-sensitive-words

## 变更标题
运营后台敏感词界面新增「批量导入」功能（文本框一次性粘贴，按换行或逗号切分）

## 变更背景 / 上下文
- 来源需求：运营在维护敏感词清单时，经常需要一次性录入大量词。当前界面仅支持单条新增（填词 + 别名 + 备注），逐条录入效率低。
- 目标：在敏感词面板新增一个「批量导入」卡片，提供一个多行文本框，运营可直接粘贴大量敏感词，前端按换行符或逗号（含中文逗号）切分后，通过后端批量接口一次性创建。
- 复用既有能力：
  - 后端敏感词快照逻辑（`build/persist/sync_sensitive_word_snapshot`）、`normalize_sensitive_text`、`get_sensitive_word_config`、`SensitiveWord` 模型。
  - 前端 `SensitiveWordsPanel.vue` 与 `sensitive-words-model.ts` 已存在的 API 封装与错误提示模式。

## 目标
1. 后端新增 `POST /api/v1/admin/sensitive-words/bulk`，接收 `{terms: string[], enabled?: bool, note?: str}`，批量建词。
2. 批量接口对每词做规范化、去重（与已存在词及本次列表内重复比较），跳过无效/已存在项并统计 `created` / `skipped` / `errors`，末尾仅重建一次快照（避免 N 次重建）。
3. 前端 `SensitiveWordsPanel.vue` 新增「批量导入」卡片：多行文本框 + 切分说明 + 启用开关 + 可选备注 + 导入按钮 + 结果反馈。
4. 切分规则与既有别名解析一致：`split(/[\n,，]/)` 后 `trim` 并过滤空项。
5. 提供后端集成测试覆盖：批量创建、跳过重复、保留空项被忽略、跳过超长/无效项、快照同步。

## 方案设计

### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/schemas.py` | 修改 | 新增 `SensitiveWordBulkCreate`（`terms: list[str]`，`enabled`、`note`） |
| `backend/app/api/admin.py` | 修改 | 新增 `bulk_create_sensitive_words` 端点；复用 `_locked_sensitive_config` / `build/persist/sync_sensitive_word_snapshot` |
| `frontend/src/features/admin/sensitive-words-model.ts` | 修改 | 新增 `bulkCreateSensitiveWords` 及类型 `SensitiveWordBulkPayload` / `SensitiveWordBulkResponse` |
| `frontend/src/features/admin/SensitiveWordsPanel.vue` | 修改 | 新增批量导入卡片与 `submitBatch` 逻辑 |
| `backend/tests/test_sensitive_word_bulk.py` | 新增 | 批量导入端点集成测试 |
| `docs/CONTEXT_SUMMARY.md` | 修改 | 在敏感词管理 API 条目补充批量导入端点 |
| `TASKS.md` | 修改 | 补充 015 任务状态 |

### 后端批量接口设计
- 入参：`{ terms: string[]（1..2000 项）, enabled: bool = True, note: str = ""（≤500）}`。
- 处理（单个 DB 事务 + 配置行 `WITH FOR UPDATE` 锁）：
  1. 读取已存在词的 `normalized_term` 集合。
  2. 遍历 `terms`：规范化；空/无效跳过计入 `errors`；已存在（含本批内重复）计入 `skipped`；否则建 `SensitiveWord`（空别名、给定 enabled/note）。
  3. 汇总全部词后 `build_sensitive_word_snapshot` → `persist` → `sync`，仅一次。
- 返回：`{ created, skipped, total, errors: [{term, error}], rebuild_scheduled, snapshot }`。
- 异常：命中 `SensitiveWordError` 或快照同步失败 → 回滚并 422/503（保持与单条创建一致）。
- **超时修复（批量体量大时）**：全量快照重建（变体生成 + Redis 同步 + 多轮 DB 读写 + `SensitiveWordConfig` 行锁）重量级，若放在请求内同步执行，词量大或 DB 延迟高时会超过前端 20s 默认超时（`ECONNABORTED`）。改为：请求内仅创建并提交词，随后通过 `BackgroundTasks` 异步重建并同步快照；响应立即返回并带 `rebuild_scheduled: true`。前端 `bulkCreateSensitiveWords` 单独设置 `timeout: 180_000`。

## 验收标准
- 后端：批量接口能正确创建多个词、跳过重复、忽略空项、跳过超长/无效项，并同步快照（`redis_synced` 且 `in_sync`）。
- 前端：文本框按换行或逗号切分；导入后提示成功数量与跳过数量；面板词表刷新；导入中按钮禁用。
- 测试：新增后端集成测试全部通过；前端 `typecheck` 与 `test:run` 保持绿。
- 规范：新增端点沿用既有权限/错误文案；文档（CONTEXT_SUMMARY / TASKS）同步更新。

## Open Questions
- 无（需求明确，复用既有快照与接口模式）。
