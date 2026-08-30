# Change: BATCH_GENERATION_QUEUE

## 变更标题
将批量托管任务并入统一生图缓冲队列

## 变更背景 / 上下文
- 来源需求：用户要求生图 / 生视频流程在单个任务与批量任务提交后都先进入 Redis + PostgreSQL 缓冲清单，界面提示“任务在后台运行”并显示“生成中”；后台只保留生图、生视频各一个 worker；完成后更新数据库、发站内信并展示结果；仅在任务仍处于等待中时允许取消。
- 相关已交付能力：`changes/010-generation-video-buffer-queues` 已把普通套图任务 `/generation-jobs` 与视频任务 `/video-jobs` 改为 `queue:generation` / `queue:video` 两条 Redis FIFO，并由 `GenerationQueueScheduler` 各启动一个顺序 worker。
- 当前批量入口：`backend/app/api/public.py` 的 `POST /batch-jobs` 创建 `BatchJob` / `BatchItem` 后立即调用 `BatchScheduler.tick`；`POST /batch-jobs/{batch_id}/retry-failed` 同样立即触发调度。
- 当前批量执行旁路：`backend/app/services/batch_scheduler.py` 直接扫描 PostgreSQL 中 queued 的 `BatchItem`，按 `max_active_batch_items` 并发认领，并直接调用 `run_generation_job`、`run_aplus_plan_job`、`run_aplus_generation_job`。该路径没有经过 Redis 队列，因此违反本次“用户操作只能进入缓冲区、统一由 worker 处理”的规则。
- 当前批量取消：`backend/app/services/batch_jobs.py::cancel_batch_job` 会把批量任务置为 `cancelling`，还会尝试取消 running 子任务；本次规则要求 running 后用户不可干预。
- 当前批量 UI：`BatchHostingModal.vue` 提交后仅提示“批量生成托管任务已提交”，未显式提示后台运行；`BatchHistoryDrawer.vue` 已有 queued / running 状态文案，可作为状态刷新与“生成中”占位的基础。
- 通知现状：`notifications.py::create_job_result_notification_once` 已提供按任务 ID 幂速写站内信能力；单任务队列已使用该能力。
- 数据事实：`models.py` 中 `BatchJob` / `BatchItem` 与其子任务状态仍是任务事实源。数据库保留现有细分状态，界面按“等待中 / 生成中 / 已取消 / 已生成 / 失败”语义映射。

## 目标
1. 批量套图与批量 A+ 的每个 `BatchItem` 都进入现有生图队列，与普通生图任务共用同一个顺序 worker；生视频继续使用现有视频队列与唯一视频 worker。
2. `POST /batch-jobs` 与批量 retry-failed 只落库、入队并返回 `queued`，不直接触发任何 Provider 执行。
3. 批量父任务聚合 `BatchItem` 与子任务状态：等待中显示排队，认领后显示生成中，终态后展示结果并提供下载。
4. 批量父任务进入终态后写入一条幂等站内信；单任务维持 `010` 的终态通知行为。
5. 仅当批量任务仍在缓冲区（父任务和全部待执行项均为 queued）时允许取消；取消时移除 Redis 元素、批量任务与项写为 cancelled，并释放未消耗额度。任何项已 running 后取消返回 409。
6. Redis 入队失败保持 fail-closed：接口返回 503，不留下会稍后自动执行的批量 queued 任务，并补偿本次预留额度。

## Scope

### In Scope
- `POST /batch-jobs`、`POST /batch-jobs/{batch_id}/retry-failed` 的入队与立即返回。
- 批量取消接口的等待中语义与 Redis 删除。
- `BatchItem` 在统一生图 worker 中的条件认领、执行、失败落库、父任务聚合与终态通知。
- 移除生产运行中的独立 `BatchScheduler` 执行 worker；相关执行逻辑抽取为队列 worker 可调用的服务。
- 批量提交后的后台运行提示、状态展示与生成中占位。
- 队列元素格式、启动重建、通知补偿、Redis 文档与相关测试。

### Out of Scope
- 不改变普通单任务套图 / 视频队列行为，只做回归确认。
- 不新增批量视频能力；当前仓库没有批量视频模型或接口，视频侧继续覆盖现有单个视频任务。
- 不改变 Provider 调用算法、Prompt、额度计价和水印规则。
- 不把数据库状态字面量强制迁移为五个值；保留 `partial_failed` 等历史细分状态并做界面语义映射。
- 不提供远端 Provider 任务撤销。

## 方案设计

### 涉及文件
| 文件 | 类型 | 说明 |
|---|---|---|
| `backend/app/services/generation_queues.py` | 未修改（实现偏差） | 保留普通生图 / 生视频调度基类与原有 worker 生命周期 |
| `backend/app/services/generation_queue_service.py` | 新增 | 扩展队列 token 解析、`BatchItem` 条件认领与分发、批量终态通知、普通生图与批量项混合重建 |
| `backend/app/services/batch_execution.py` | 新增 | 从 `BatchScheduler` 抽取套图 / A+ 批量项执行逻辑，供生图队列 worker 调用 |
| `backend/app/services/batch_scheduler.py` | 删除或收缩 | 移除独立扫描认领 worker；保留必要的启动恢复辅助逻辑时不得再直接执行任务 |
| `backend/app/services/batch_jobs.py` | 修改 | 批量创建 / retry / cancel 与队列服务协作；取消语义收紧为仅 queued |
| `backend/app/api/public.py` | 修改 | 批量创建与 retry 只入队；cancel 使用条件锁；移除 `batch_scheduler.tick` 旁路 |
| `backend/app/main.py` | 修改 | lifespan 只启动 `GenerationQueueScheduler`，停止启动独立 `BatchScheduler` |
| `backend/app/core/storage/keys.py` | 修改 | 如需增加 token 构造 helper，仅限现有两个队列键，不新增第三条执行队列 |
| `backend/app/services/notifications.py` | 修改 | 增加批量父任务终态通知 helper，沿用确定性 ID 去重 |
| `frontend/src/features/workspace/BatchHostingModal.vue` | 修改 | 提交 / retry 成功后提示“任务已在后台运行” |
| `frontend/src/features/workspace/BatchHistoryDrawer.vue` | 修改 | 等待中 / 生成中状态、取消入口、生成中占位与终态结果展示、轮询刷新 |
| `frontend/src/api/client.ts` | 修改 | 适配取消 409 文案与批量任务响应状态（如现有类型无需变更则不改） |
| `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` | 修改 | 记录队列 token、批量入队、重建与两个 worker 边界 |
| `backend/tests/test_batch_generation_queue.py` | 新增 | 覆盖创建、顺序执行、取消竞态、A+ 两段执行、通知、重建、fail-closed |
| 现有批量与队列测试 | 修改 | 适配移除独立 `BatchScheduler` 后的调度断言 |

### 实现要点
1. **队列 token**：`queue:generation` 的元素改为 `generation:{job_id}` 与 `batch_item:{item_id}` 两类字符串 token；`queue:video` 继续使用 `video:{job_id}` 或兼容现有裸视频 ID。解析时把旧版裸生图 ID 视为普通 `GenerationJob`，避免重启边界丢任务。完整任务参数仍只在 PostgreSQL。
2. **批量入队**：批量创建在一个数据库事务中创建父任务、项、子任务记录并预留额度；提交后按 `created_at, index` 把所有 `BatchItem` token 推入生图队列。若任一 push 失败，删除本次已推入 token、把该批量置为 cancelled 并释放额度，接口返回 503。
3. **唯一 worker**：生图 worker 每次 pop 一个 token，按类型用 `SELECT ... FOR UPDATE` 条件认领。普通生图按 `010` 现状执行；`batch_item` 认领 `BatchItem: queued -> running`，父任务转 running，然后复用抽取出的批量执行服务处理套图或 A+ 两段链路。视频 worker 不变。
4. **父任务聚合**：每个 `BatchItem` 结束后同步子任务状态、更新进度并调用 `aggregate_batch_job`。所有项终态后父任务进入 succeeded / partial_failed / failed / cancelled；不因中途单项失败中断同批其他等待项。
5. **取消语义**：取消接口锁定 `BatchJob` 与其项，只有父状态为 queued 且所有可执行项均为 queued 时成功；随后逐个从 Redis 删除 `batch_item:{id}`，项与父任务写 cancelled、完成时间与额度释放。发现任何 running 项立即 409，终态直接幂等返回。worker 与取消并发时以行锁条件更新为准，输掉的一方只丢弃队列元素或返回 409。
6. **批量 retry**：仅把 failed / partial_failed 批量中的失败项重置为 queued 并入队；父任务回到 queued / running 聚合状态。接口立即返回，不触发 Provider。
7. **启动恢复**：先执行现有子任务恢复逻辑，保留可续传的远端任务，不能续传的 running 项回到 queued；然后清空并重建生图队列，顺序为普通生图与批量项共同按 `created_at, id/index` 排列。批量父任务不会因存在等待项而被遗漏。视频队列沿用 `010` 重建。
8. **站内信**：每个批量父任务终态只写一条通知，metadata 包含 `batch_job_id`、`business_type`、`status`、成功 / 失败数量。通知失败不影响任务终态，启动补偿按确定性通知 ID 去重。
9. **界面状态**：批量提交与 retry 成功后显示“任务已在后台运行，可在消息中心查看结果”；历史列表等待中显示“等待中”，生成中显示“生成中”，未产出图片的位置使用稳定占位，终态后显示缩略图 / 结果与下载入口。取消按钮仅 queued 可见，running 后隐藏并给出 409 文案。
10. **测试模式**：保留 `settings.testing` 不自动启动 worker 的做法，但测试需显式调用队列 `tick("generation")` 推进；移除对 `BatchScheduler.tick` 的测试依赖。

## 验收标准
- [x] 批量创建后数据库存在 queued 的 `BatchJob` / `BatchItem` / 子任务，Redis 生图队列包含对应 token，接口立即返回且不发生 Provider 调用。
- [x] 普通生图、批量套图、批量 A+ 共用同一个生图 worker 并按 FIFO 执行；视频 worker 独立且不被批量任务阻塞。
- [x] 批量任务等待中取消成功：Redis token 被删除、父项状态为 cancelled、额度释放；running 后取消返回 409 且不改动执行状态。
- [x] worker 认领批量项后界面显示生成中；单项与整批终态后展示结果并更新数据库。
- [x] 批量父任务终态只产生一条站内信，重复 tick / 重启补偿不重复。
- [x] Redis 部分入队失败时接口返回 503，已写入 token 和 queued 任务均被清理或取消，不会稍后自动执行。
- [x] 清空 Redis 后重启，普通生图、批量套图、批量 A+ 的 queued 项按数据库顺序重建并执行。
- [x] 后端目标测试、后端回归与前端测试通过。

## Implementation Notes
- 实现偏差：编码期间 `backend/app/services/generation_queues.py` 曾被外部 Windows 进程锁定，无法安全修改；最终保持该基类未改，新增 `backend/app/services/generation_queue_service.py::UnifiedGenerationQueueScheduler` 完成批量 token、执行、通知与重建扩展，并由 `main.py` 装配该子类。行为仍在原 scope 内，且避免直接编辑被外部进程持有的文件。
- 测试文件偏差：原验证计划中的 `test_batch_limits_cancel_and_retry.py` 与 `test_batch_validation_fixtures.py` 在当前仓库合并为 `backend/tests/test_batch_jobs.py`。

## Verification Plan
- 后端目标测试：`.venv/Scripts/python.exe -m pytest backend/tests/test_generation_video_queues.py backend/tests/test_batch_generation_queue.py backend/tests/test_batch_jobs.py`。
- 后端回归：`.venv/Scripts/python.exe -m pytest backend/tests`。
- 前端回归：在 `frontend/` 执行 `npm run test:run`。
- 手工 Dryrun：提交普通生图、批量套图、批量 A+、单个视频，观察两个 worker 并发而同队列顺序执行，检查 Redis token、数据库状态、站内信与批量历史 UI。
- 手工竞态：分别在批量项认领前后取消，确认 queued 成功、running 409。
- 手工恢复：让批量项 queued 后清空 Redis 并重启，确认从 PostgreSQL 重建并完成。

## Open Questions
> 以下为待人工确认的问题。AI 不得自行猜测；必须回答后方可继续 coding。
- [x] Q1: 本次“批量任务”是否按仓库现状覆盖现有批量托管的套图与 A+ 图片生成，不新增当前不存在的批量视频功能？（若你还要求新增批量视频提交界面与模型，需要另开后续变更。） - Decision: 用户回复“执行方案”，确认按现有批量套图与 A+ 图片生成实施，不新增批量视频功能。
