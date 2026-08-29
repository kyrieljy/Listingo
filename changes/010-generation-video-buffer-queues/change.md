# Change: GENERATION_VIDEO_BUFFER_QUEUES

## 变更标题
为生图与生视频外部 API 调用增加相互独立的 Redis 缓冲队列

## 变更背景 / 上下文
- 来源需求：用户要求“对于生图、生视频调用外部 API 的环节分别做一个缓冲队列”；任务先入 Redis 缓冲区并保存数据库状态，等待中可取消、生成中不可中止，后台逐个处理并在结束后站内信通知。
- 现状入口：
  - `backend/app/api/public.py` 的 `POST /generation-jobs` 创建 `GenerationJob` 后立即通过 `BackgroundTasks` 调用 `run_generation_job`。
  - `POST /video-jobs` 创建 `VideoJob` 后立即通过 `BackgroundTasks` 调用 `run_video_job`。
  - 两个 retry-failed 入口也直接调用执行函数。
- 数据事实：`backend/app/models.py` 已有 `generation_job` / `generation_item` 与 `video_job` / `video_item`，`status` 默认 `queued`，并已有 `running`、`succeeded`、`failed`、`cancelled`、`partial_failed`、`partial_cancelled`、时间戳和额度关联字段。
- Redis 基础设施：`backend/app/core/storage/keys.py` 集中键构造，`backend/app/core/storage/redis.py` 与 `memory.py` 提供双后端，`backend/app/core/runtime.py` 提供 `RuntimeStateService`；`docs/REDIS_KEYS.md` 当前约束是“PostgreSQL 事实 + Redis 派生态”。
- 后台调度参考：`backend/app/main.py` 已在 lifespan 启动 `BatchScheduler`；`backend/app/services/batch_scheduler.py` 展示了轮询、认领、失败落库和停止清理的本地模式。
- 取消现状：`backend/app/services/jobs.py` 与 `video_jobs.py` 会把非终态任务置为 `cancelling`，执行链路多处响应取消；这与本次“开始处理后不能中止”的要求不同。
- 通知现状：`backend/app/services/notifications.py` 已提供 `create_notification`，`/notifications` 与前端个人中心消息页已可用。
- 前端现状：`WorkspaceView.vue` 与 `VideoPhasePanel.vue` 对 queued/running 均展示取消按钮，并轮询任务状态。
- 恢复现状：`backend/app/services/workspace_recovery.py` 启动时会把中断的 open job 置为 failed/cancelled；队列化后需要与 Redis 队列重建策略衔接。

## 目标
1. 生图与生视频使用两个独立 Redis FIFO 队列，同一时刻每个队列最多处理一个任务。
2. 数据库仍是任务事实源：任务创建后先落 `queued`，worker 认领后条件更新为 `running`，执行结束进入终态。
3. 仅 `queued` 任务允许用户取消；任务已被 worker 认领为 `running` 后取消接口返回 409，执行链路不再响应取消。
4. worker 在任务进入终态后创建站内信，通知生成完成、部分成功或失败；消息携带任务 ID 与结果状态。
5. Redis 队列丢失、服务重启或队列写入中断时，能依据 PostgreSQL 中的 `queued` 任务重建队列，避免任务永久卡住。

## Scope

### In Scope
- `POST /generation-jobs`、`POST /generation-jobs/{id}/retry-failed` 改为入生图队列。
- `POST /video-jobs`、`POST /video-jobs/{id}/retry-failed` 改为入生视频队列。
- 新增队列服务与后台消费者，生图、生视频各一个顺序 worker。
- 仅调整上述两条链路的取消语义和取消 UI。
- 任务终态后的 `Notification` 写入，以及前端任务结束后刷新站内信未读数。
- 生图/生视频提交与重试成功后，前端展示「任务已在后台运行」显式提示（如 `message.info`），与状态文案共同满足「界面提示后台运行」要求（2026-08-29 用户补充，见下）。
- 队列键、恢复策略、降级语义、配置项与测试。

### Out of Scope
- 不提供外部 Provider 已提交任务的远端撤销。
- 不改变图片/视频执行算法、Prompt、Provider 回退和额度结算规则。
- 不新增 WebSocket/SSE/邮件/短信通知。
- 默认不改动 A+ 生图、OCR 改字、二次编辑、管理端 Prompt 试跑和批量托管调度；是否纳入统一队列见 Open Questions。

## 方案设计

### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/core/storage/keys.py` | 修改 | 新增 `queue_key(kind)`，产出 `queue:generation` / `queue:video` 内部键 |
| `backend/app/core/storage/base.py` | 修改 | 抽象 FIFO 队列操作：入队、出队、移除、长度、清空重建 |
| `backend/app/core/storage/redis.py` | 修改 | Redis List 实现，保持 key prefix 与 `StorageUnavailableError` 语义 |
| `backend/app/core/storage/memory.py` | 修改 | 进程内 deque 实现，用于单进程本地与测试 |
| `backend/app/services/generation_queues.py` | 新增 | 队列封装、DB 条件认领、启动重建、终态通知与 worker 循环 |
| `backend/app/config.py` | 修改 | 队列轮询间隔、等待超时、worker 停止超时等配置 |
| `backend/app/main.py` | 修改 | 装配并随 lifespan 启停 `GenerationQueueScheduler` |
| `backend/app/api/public.py` | 修改 | 创建/重试接口入队；取消接口仅接受 queued；移除直接 BackgroundTasks 执行 |
| `backend/app/services/jobs.py` | 修改 | 取消函数收紧为 queued -> cancelled；执行链路取消检查按新语义处理或移除 |
| `backend/app/services/video_jobs.py` | 修改 | 同上，视频取消与执行链路适配 |
| `backend/app/services/workspace_recovery.py` | 修改 | 与队列重建衔接，避免启动恢复吞掉仍应排队或需要通知的任务 |
| `backend/app/services/notifications.py` | 修改 | 如需，增加任务通知文案 helper；复用现有 Notification 表 |
| `frontend/src/features/workspace/WorkspaceView.vue` | 修改 | queued 展示等待中与取消按钮；running 不展示取消；终态后刷新消息；提交/重试成功后展示「任务已在后台运行」提示 |
| `frontend/src/features/workspace/VideoPhasePanel.vue` | 修改 | 视频侧同等取消与状态展示；重试成功后展示「任务已在后台运行」提示 |
| `frontend/src/features/auth/auth-store.ts` | 修改 | 如需，提供终态后的轻量未读刷新 |
| `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` | 修改 | 记录队列键、持久化/恢复边界、环境变量和语义索引 |
| `backend/tests/test_generation_video_queues.py` | 新增 | 覆盖入队、顺序消费、取消竞态、通知、恢复与降级 |
| 现有后端/前端相关测试 | 修改 | 适配直接执行路径被队列替代后的断言 |

### 实现要点
1. **队列键与数据形态**：队列元素只保存 `job_id`，不复制任务参数；完整任务事实始终在 PostgreSQL。生产要求 Redis 后端；memory 后端仅保留单进程本地兼容与测试能力。
2. **FIFO 语义**：Redis 使用 List，生产端追加队尾，消费端从队首取出。两个队列完全独立，因此一个长视频任务不阻塞生图任务，但同类型任务严格按提交顺序执行。
3. **条件认领**：worker 出队后使用 `UPDATE ... WHERE id = :id AND status = 'queued'` 原子认领为 `running`。认领失败说明任务已取消或已终态，直接丢弃队列元素；认领成功后用户取消接口必须返回 409。
4. **取消语义**：取消接口在事务中锁定任务，仅当状态为 `queued` 时将 job 与仍为 queued 的 item 置为 `cancelled`、写完成时间并释放额度，然后从 Redis 队列移除该 ID。`running` 与终态均拒绝取消。
5. **顺序 worker**：`GenerationQueueScheduler` 为每个队列维护一个循环，当前任务 `await run_generation_job` / `await run_video_job` 完成并通知后才取下一个。服务内通过可续期的队列 leader lease 保证多实例部署时每个队列仍只有一个消费者。
6. **启动恢复**：启动时先停止旧 worker；清空并按 `created_at, id` 重建两类 Redis 队列，来源为 PostgreSQL 中非 admin test、用户创建且状态仍为 `queued` 的任务。已被历史恢复逻辑终态化的任务不重复入队。
7. **Redis 异常**：队列是正确性依赖，采用 fail-closed。创建/重试请求在 Redis 入队失败时返回 503，不制造“接口提示失败但任务可能稍后执行”的模糊状态；已有 DB 事务需回滚或补偿并释放本次预留额度。
8. **通知**：worker 等执行函数返回后重新读取任务终态，为 `succeeded`、`partial_failed`、`failed` 创建 `category='generation'` / `'video'` 的 Notification，metadata 包含 `job_id`、`status`、`dry_run`。通知写失败时记录错误并保留任务终态，重启后的通知补偿扫描需按 metadata 去重。
9. **状态呈现**：数据库保留现有细分状态，不强制迁移为五个字面量；对外按语义映射：`queued=等待中`，`running=生成中`，`succeeded/partial_failed=已完成`，`cancelled/partial_cancelled=已取消`，`failed=生成失败`。
10. **执行链路**：队列 worker 是唯一直接调用这两个执行函数的普通用户链路入口；执行内部不再因新的取消请求中断。已有远端 provider 任务恢复逻辑保持不变。
11. **后台运行提示（2026-08-29 补充）**：生图/生视频的创建接口与 retry-failed 接口改为入队并立即返回 `queued` 后，前端在拿到 `queued` 响应处调用一次 `message.info('任务已在后台运行，可在消息中心查看结果')`（或等价轻提示）；该提示不阻塞轮询，仅用于显式告知用户任务已在后台排队执行，与 `queued=等待中` / `running=生成中` 状态文案互补。
12. **文档边界**：`docs/REDIS_KEYS.md` 需明确队列 key 是由 PostgreSQL 可重建的运行时缓冲，不适用普通缓存 TTL/淘汰语义；Redis AOF 与数据库恢复共同保证任务不丢。

## 验收标准
- [ ] 创建生图任务后返回 `queued`，数据库存在 `GenerationJob`，Redis 生图队列包含任务 ID；生视频行为相同且使用独立键。
- [ ] 同类任务按提交顺序逐个执行；生图与生视频可同时各执行一个。
- [ ] `queued` 任务取消后，job 与未开始 item 变为 `cancelled`，额度释放，队列元素移除，并产生可见终态。
- [ ] worker 条件认领成功后状态为 `running`；此时调用取消接口返回 409，接口不把状态改为 `cancelling`。
- [ ] 取消请求与 worker 认领并发时只有一个方向成功：先取消则 worker 丢弃；先认领则取消拒绝。
- [ ] 任务成功、部分成功、失败后均产生一条站内信；重复消费或补偿扫描不产生重复通知。
- [ ] 清空 Redis 后重启服务，PostgreSQL 中仍为 `queued` 的任务按原顺序重建并执行。
- [ ] Redis 不可用时创建/重试返回 503，不留下会稍后自动执行的 queued 任务。
- [ ] 前端仅在等待中展示取消按钮；生成中按钮消失或明确不可用，409 文案清晰。
- [ ] 后端全量测试与前端相关测试通过。

## Verification Plan
- 后端目标测试：`.venv/Scripts/python.exe -m pytest backend/tests/test_generation_video_queues.py backend/tests/test_api_dryrun.py backend/tests/test_execution.py`。
- 后端回归：`.venv/Scripts/python.exe -m pytest backend/tests`。
- 前端回归：在 `frontend/` 执行 `npm run test:run`。
- 手工验证 Dryrun：分别连续提交生图与生视频任务，检查数据库状态、Redis `LLEN/LRANGE`、站内信列表与前端状态流转。
- 手工验证竞态：在 worker 认领前后分别调用取消接口，确认 queued 可取消、running 返回 409。
- 手工验证恢复：提交 queued 任务后重启服务或删除队列 key 再重启，确认任务从 PostgreSQL 重建并完成。

## Open Questions
> 以下为待人工确认的问题。AI 不得自行猜测；必须回答后方可继续 coding。
- [x] Q1: 队列覆盖范围是否按本分析处理为普通工作台套图生图 `/generation-jobs` 与 `/video-jobs`（含 retry-failed），暂不覆盖 A+ 生图、管理端试跑和批量托管？ - Decision: 用户回复“执行方案”，采纳建议：仅覆盖上述两条普通用户链路。
- [x] Q2: Redis 队列不可用时是否接受 fail-closed：创建/重试返回 503 且不落 queued 任务？备选是 PostgreSQL 先接单、Redis 恢复后自动入队，但用户会看到“提交失败但稍后可能执行”的模糊状态。 - Decision: 用户回复“执行方案”，采纳建议：fail-closed，返回 503 且不留下会自动执行的任务。
- [x] Q3: 数据库是否保留现有细分终态 `partial_failed` / `partial_cancelled`，仅在界面与通知中归入“已完成 / 已取消”？若要求库内状态字面量严格只有五个，需要额外迁移并重写额度与历史展示逻辑。 - Decision: 用户回复“执行方案”，采纳建议：保留数据库细分终态并做语义映射。
- [x] Q4: 队列 worker 运行在 FastAPI lifespan 内（当前部署改动最小，配合 leader lease 支持多实例），还是必须拆成独立进程/容器？独立 worker 会增加部署与环境变量边界。 - Decision: 用户回复“执行方案”，采纳建议：worker 内嵌 FastAPI lifespan，并用可续期 leader lease 支持多实例。
