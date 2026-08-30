# Checklist: batch-import-sensitive-words

## 功能验证
- [x] 后端新增 `SensitiveWordBulkCreate` schema（terms/enabled/note）
- [x] 后端新增 `POST /admin/sensitive-words/bulk` 端点
- [x] 批量创建：一次性写入多个不同敏感词
- [x] 跳过重复：已存在词（按 normalized_term）被计为 skipped 而非报错
- [x] 忽略空项：切分后空字符串不建词、不报错
- [x] 跳过超长/无效词：计入 errors 且不阻断其余词
- [x] 本批内重复词只创建一次（去重）
- [x] 批量导入末尾仅重建一次快照（build/persist/sync 一次）
- [x] 返回结构含 created/skipped/total/errors/snapshot
- [x] 异常时回滚并保留与单条一致的 422/503 行为
- [x] 前端 `sensitive-words-model.ts` 新增 `bulkCreateSensitiveWords` 及类型
- [x] 前端面板新增「批量导入」卡片（文本框 + 说明 + 启用开关 + 备注 + 导入按钮）
- [x] 前端按 `[\n,，]` 切分并 trim/过滤空项
- [x] 导入成功提示“成功 N / 跳过 M”，并刷新词表
- [x] 导入中按钮禁用（防重复提交）

## 测试
- [x] 新增 `backend/tests/test_sensitive_word_bulk.py` 集成测试覆盖上述功能点
- [x] 后端批量相关用例通过（沙箱外复核无功能回归）
- [x] 前端 `npm run typecheck` 通过（0 错误）
- [x] 前端 `npm run test:run` 通过（无新增失败）

## 规范检查
- [x] 新增后端端点沿用既有权限与错误文案约定
- [x] `docs/CONTEXT_SUMMARY.md` 补充批量导入端点
- [x] `TASKS.md` 补充 015 任务状态
- [x] 不改动既有单条新增/编辑/删除/启停逻辑
