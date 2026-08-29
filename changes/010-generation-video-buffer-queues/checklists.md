# 验证清单 - GENERATION_VIDEO_BUFFER_QUEUES

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [ ] 生图任务创建后先落库为 `queued`，且只进入 Redis 生图队列。
- [ ] 生视频任务创建后先落库为 `queued`，且只进入 Redis 生视频队列。
- [ ] 同一队列任务逐个执行，两个队列之间互不阻塞。
- [ ] `queued` 任务取消成功，额度释放，队列元素移除。
- [ ] `running` 任务取消返回 409，状态不变为 `cancelling`。
- [ ] 取消与 worker 认领的并发竞态只允许一方成功。
- [ ] 成功、部分成功、失败任务各生成一条不重复站内信。
- [ ] 前端仅在等待中展示取消入口，并正确展示等待中/生成中文案。
- [ ] 生图/生视频提交与重试成功后，前端显式展示「任务已在后台运行」提示（不阻塞轮询）。
- [ ] 服务重启或 Redis 队列丢失后，能从 PostgreSQL `queued` 任务重建队列。
- [ ] Redis 不可用时创建/重试 fail-closed 返回 503，不留下会稍后自动执行的任务。

## 测试
- [ ] 新增队列服务单元测试通过：入队、出队、移除、长度、重建、memory/Redis 双后端行为。
- [ ] 新增 API 集成测试通过：创建、取消、认领竞态、通知、retry 入队。
- [ ] `.venv/Scripts/python.exe -m pytest backend/tests/test_generation_video_queues.py backend/tests/test_api_dryrun.py backend/tests/test_execution.py` 通过。
- [ ] `.venv/Scripts/python.exe -m pytest backend/tests` 通过。
- [ ] `frontend/` 下 `npm run test:run` 通过。

## 规范检查
- [ ] Redis 键全部经 `backend/app/core/storage/keys.py` 构造。
- [ ] PostgreSQL 仍是任务与通知事实源，Redis 队列可由数据库重建。
- [ ] 不回滚或覆盖用户已有未提交变更。
- [ ] `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` 已同步队列语义。
- [ ] 符合 `.coderules` 与现有 FastAPI/SQLAlchemy/Vue 代码风格。
