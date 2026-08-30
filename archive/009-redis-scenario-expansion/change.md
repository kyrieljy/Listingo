# Change: REDIS_SCENARIO_EXPANSION

## 变更标题
落地 redis-analysis.md 第二节六类 Redis 场景：热点缓存、任务状态缓存、会话缓存、分布式锁、实时计数与 OCR 结果缓存

## 变更背景 / 上下文
- 来源需求：用户要求“分析 redis-analysis.md，实现其中‘二、适合引入 Redis 但尚未使用的场景’的内容”。
- 前置事实：`changes/008-redis-usage-optimization` 已建立 Redis 连接池、集中键构造器（`backend/app/core/storage/keys.py`）、`docs/REDIS_KEYS.md` 与“Redis 仅保存临时安全态”约束；本变更是用户明确采纳分析文档第二节后的约束演进，而非静默放宽。
- 关联模块（按 `docs/CONTEXT_SUMMARY.md` 定位）：
  - 应用装配：`backend/app/main.py`、`backend/app/config.py`
  - 运行时存储：`backend/app/core/storage/`、新增 `backend/app/core/runtime.py`
  - Provider/Prompt/Workflow/套餐热点读：`backend/app/services/provider_routing.py`、`jobs.py`、`video_jobs.py`、`aplus_jobs.py`、`image_text_edit.py`、`job_creation.py`、`subscriptions.py`
  - 会话：`backend/app/services/auth.py`、`backend/app/api/auth.py`
  - 批量状态与调度：`backend/app/services/batch_jobs.py`、`batch_scheduler.py`、`backend/app/api/public.py`
  - 监控计数：`backend/app/services/analytics.py`、新增 `backend/app/services/metrics.py`、`backend/app/api/admin.py`、前端 `MonitoringDashboard`/`monitoring-data.ts`
  - 文档：`docs/REDIS_KEYS.md`、`docs/CONTEXT_SUMMARY.md`、`TECH_STACK.md`

## 目标
1. 热点数据缓存：Provider 配置（按 capability/code 的只读快照）、Prompt/Workflow 激活版本、套餐与额度规则进入 Redis TTL 缓存，管理端变更显式失效。
2. 任务状态缓存：`GET /batch-jobs/{id}` 的重序列化结果短 TTL 缓存，创建/取消/重试/调度推进时失效。
3. 用户会话存储：按 token 哈希缓存 `UserSession` 元数据（session_id/user_id/expires_at），登出与过期即时失效；用户状态、套餐、角色仍每次读 PostgreSQL 事实行。
4. 分布式锁：批量调度认领、额度预留（user+action）、订单创建（user）与模拟支付（order）使用 token 化 Redis 锁，多实例下防重复认领/超额/重复支付。
5. 操作审计与实时监控计数：`AnalyticsEvent` 仍完整落 PostgreSQL（审计事实），同时 Redis INCR 维护当日 total/event_type/business_type 实时计数，并在运维监控响应与前端 KPI 中展示。
6. 临时文件/结果缓存：OCR 文字识别结果按（文件指纹 + 语言 + OCR 设置指纹）缓存，命中时不再构造临时图片变体、不再重复跑 OCR 引擎。

## 方案设计
### 架构原则
- PostgreSQL 仍是业务事实唯一来源；Redis 只保存可再生的派生态（缓存/计数）、短 TTL 状态（会话元数据/批量进度快照）与正确性令牌（锁）。
- 键继续全部经 `backend/app/core/storage/keys.py` 构造；`RedisStorage._key` 统一追加 `LISTINGO_REDIS_KEY_PREFIX`。
- 降级语义分级：
  - 可选缓存/计数：Redis 异常时回源 PostgreSQL 或跳过计数（fail-open），不放大故障。
  - 分布式锁：Redis 异常时请求失败（fail-closed，503），避免无锁放行破坏额度/订单/调度一致性。
  - memory 后端复用现有 `MemoryStorage`（单进程测试/本地兼容），行为一致但无跨进程语义。
- 失效策略：热点配置缓存使用“域版本号键 + 数据键带版本”模式（避免 SCAN/批量删除），管理端写路径提交后递增对应域版本；数据键另有 TTL 兜底（默认 300s）。

### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/core/storage/keys.py` | 修改 | 新增 cache/session/batch/lock/metric 键构造器 |
| `backend/app/core/runtime.py` | 新增 | `RuntimeStateService`：JSON 缓存、版本号、锁、计数；应用级默认实例装配 |
| `backend/app/config.py` | 修改 | 新增 Redis 缓存/会话/批量状态/锁/计数/OCR TTL 配置 |
| `backend/app/main.py` | 修改 | 装配 `app.state.runtime_state`，注入 BatchScheduler，应用关闭时复位默认运行时 |
| `backend/app/services/provider_routing.py` | 修改 | `ProviderSnapshot` 只读快照 + 按 capability/code 缓存 + 路由解析缓存 + 失效助手 |
| `backend/app/services/jobs.py` `video_jobs.py` `aplus_jobs.py` `image_text_edit.py` `job_creation.py` | 修改 | 读路径改用 Provider 快照/缓存路由；OCR 检测接结果缓存 |
| `backend/app/services/runtime_cache.py` | 新增 | Prompt/Workflow 激活版本缓存、套餐序列化与启用额度规则缓存及失效助手 |
| `backend/app/services/subscriptions.py` | 修改 | 套餐/规则缓存接入；额度预留与订单关键路径加锁 |
| `backend/app/services/auth.py` + `backend/app/api/auth.py` | 修改 | 会话元数据缓存查询与登出失效 |
| `backend/app/services/batch_jobs.py` `batch_scheduler.py` + `backend/app/api/public.py` | 修改 | 批量详情缓存、写路径失效、调度器认领锁 |
| `backend/app/services/metrics.py`（新增）、`analytics.py`、`backend/app/api/admin.py`、前端监控组件 | 修改 | Redis 日计数与运维监控 `realtime` 块/KPI 卡片 |
| `backend/app/schemas.py` | 修改 | `BatchJobOut` 补充 `user_id`（缓存负载所有权校验所需） |
| `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` | 修改 | 键清单、约束演进、环境变量与语义索引同步 |

### 实现要点
1. 共享基础设施：`RuntimeStateService` 包装现有 `RateLimitStorage`（Redis/Memory 双实现），提供 `get_json/set_json/delete/cached/acquire_lock/release_lock/increment`；版本键读时续期、失效时 INCR。
2. Provider 快照：`ProviderSnapshot` 携带执行链只读字段（id/code/label/capability/adapter/base_url/model_name/enabled/is_default/is_fallback/encrypted_api_key/config_json），管理端更新 Provider、路由链、健康检查写回后递增 provider 域版本。
3. Prompt/Workflow/套餐：任务创建时激活版本 ID 走单键 JSON 缓存；套餐列表/序列化/启用规则按 plan 缓存；管理端激活版本、更新套餐/规则/用户套餐后递增对应域版本。
4. 会话缓存：键为 `session:{sha256(token)}`，值不含 token 明文；TTL 取配置值与会话剩余时长较小者；`current_user_from_request` 命中后仍加载并校验 `User` 事实行。
5. 批量状态：详情序列化（含 children 媒体汇总）短 TTL 缓存；`cancel/retry/create` 及调度器 `_claim_available`/`_run_item` 提交后删除对应 batch 缓存（fail-open）。
6. 锁：`SET NX EX` + token、`delete_if_equal` 释放；批量认领锁 TTL 覆盖单次认领事务，额度/订单锁覆盖检查-写入临界区。
7. 实时计数：当日 `YYYYMMDD` 键（total/event_type/business_type），TTL 2 天；读取聚合进 `build_ops_monitoring` 的 `realtime_metrics`；前端在 KPI 条增加“今日实时事件”卡片并补充指标定义。
8. OCR 缓存：键含文件路径+mtime+size、language_hint、OCR 阈值/引擎设置指纹；命中直接重建响应对象；未命中计算后回写（fail-open）。

## 验收标准
- [ ] `RuntimeStateService` 在 FakeRedis 与 MemoryStorage 下：JSON 缓存命中/过期、token 锁互斥与安全释放、计数器 TTL 正确。
- [ ] Provider 路由解析第二次读取命中缓存（不触发 DB 查询），管理端更新 Provider/路由链后缓存版本变化并回源新值。
- [ ] 套图/A+/视频/OCR 任务创建所需的 Prompt/Workflow 激活版本与套餐规则读取走缓存；管理端激活/更新后失效。
- [ ] 登录后携带会话 Cookie 的请求命中 `session:{hash}` 缓存；登出后键删除且原 Cookie 无法继续访问。
- [ ] `GET /batch-jobs/{id}` 重复请求命中状态缓存；取消/重试/调度推进后返回新状态。
- [ ] 并发场景下：批量认领锁互斥、额度预留不超限、订单创建/支付不重复（锁语义测试）。
- [ ] 记录分析事件后 Redis 日计数增加；`/admin/ops-monitoring` 返回 `realtime_metrics` 且前端显示实时卡片。
- [ ] 同一图片 + 同一语言/OCR 设置的第二次 OCR 检测不调用 OCR 引擎；修改设置指纹后重新计算。
- [ ] `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` 与实现一致，明确“PostgreSQL 事实 + Redis 派生态”的新边界与降级语义。
- [ ] 后端测试 `.venv/Scripts/python.exe -m pytest backend/tests` 通过；前端如涉及监控组件则 `npm run test:run` 通过。

## Open Questions
> 以下为待人工确认的问题。AI 不得自行猜测；必须回答后方可继续 coding。
None.
