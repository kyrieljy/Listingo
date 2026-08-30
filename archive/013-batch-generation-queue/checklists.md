# 验证清单 - BATCH_GENERATION_QUEUE

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] 批量创建后仅落库并入生图 Redis 队列，接口不直接触发 Provider。
- [x] 批量 retry-failed 后仅失败项重新进入生图队列。
- [x] 普通生图、批量套图、批量 A+ 由同一个生图 worker 顺序执行。
- [x] 视频任务仍由唯一视频 worker 顺序执行，且不与生图互相阻塞。
- [x] 等待中批量取消成功并删除全部对应 Redis token。
- [x] 生成中批量取消返回 409，且不把状态改为 cancelling。
- [x] 批量父任务与项的状态聚合、进度、完成时间正确。
- [x] 批量终态只写入一条幂等站内信。
- [x] 批量 UI 提交后提示后台运行，等待中 / 生成中 / 终态展示符合状态映射。
- [x] Redis 入队失败 fail-closed 返回 503，并补偿已落库任务与额度。
- [x] Redis 队列丢失后能从 PostgreSQL 重建普通生图、批量项与视频队列。

## 测试
- [x] 新增批量队列服务单元测试通过：token 解析、入队、删除、重建、条件认领。
- [x] 新增 API 集成测试通过：创建、retry、取消竞态、通知、fail-closed。
- [x] 批量套图执行测试通过。
- [x] 批量 A+ plan -> generation 两段执行测试通过。
- [x] `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=.pytest-run-tmp backend/tests/test_generation_video_queues.py backend/tests/test_batch_generation_queue.py backend/tests/test_batch_jobs.py` 通过。
- [x] `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp=.pytest-run-tmp backend/tests` 通过。
- [x] `frontend/` 下 `npm run test:run` 通过。

## 规范检查
- [x] 不保留任何用户请求直接调用 Provider 执行函数的生图 / 生视频路径。
- [x] 生产 lifespan 只启动生图与视频各一个队列 worker。
- [x] Redis 键仍由 `backend/app/core/storage/keys.py` 构造，队列键无 TTL 且不参与淘汰。
- [x] PostgreSQL 仍是批量任务、子任务、状态与通知事实源。
- [x] 不回滚或覆盖用户已有未提交变更。
- [x] `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` 已同步批量队列语义。
- [x] 符合 `.coderules` 与现有 FastAPI / SQLAlchemy / Vue 代码风格。
