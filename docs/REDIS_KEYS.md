# Redis 键命名规范与清单

> 本文件是 Listingo「Redis 仅保存带 TTL 的临时态」约束的键层面事实来源。
> 由 `changes/008-redis-usage-optimization` 建立安全态键规范；`changes/009-redis-scenario-expansion` 在保持同一约束的前提下，将 Redis 用途从「仅安全态」扩展为「安全态 + 派生态」；`changes/014-sensitive-information-detection` 引入敏感词检测常驻快照键（无 TTL、不参与淘汰），集中键构造器位于 `backend/app/core/storage/keys.py`。

## 命名约定

- 全键形态：`{prefix}:{module}:{purpose}:{id}`
  - `prefix`：由 `config.redis_key_prefix` 配置，默认 `listingo`，由 `RedisStorage._key` 在写入时统一追加。
  - `module`：业务域（`rate` / `nonce` / `login` / `sms` / `cache` / `session` / `batch` / `lock` / `metric` / `queue`）。
  - `purpose`：具体功能。
  - `id`：身份标识（IP、手机号哈希、Nonce 哈希、窗口 ID、域/版本号、token 哈希、batch id、锁范围、日期等）。
- **单一事实来源**：所有键必须经 `backend/app/core/storage/keys.py` 的构造器生成，禁止在业务代码中散写 f-string，避免命名漂移。
- **环境隔离**：多环境共用同一 Redis 实例时，调整 `LISTINGO_REDIS_KEY_PREFIX` 即可实现 key 前缀隔离。

## 架构边界（PostgreSQL 事实 + Redis 派生态）

- **PostgreSQL 仍是业务事实的唯一来源**：用户、套餐、Provider 配置、Prompt/Workflow 版本、任务、订单、额度台账、审计事件全部落在 PostgreSQL。
- **Redis 只保存可再生的派生态、短 TTL 状态与正确性令牌**：
  - 派生态（热点缓存 / 实时计数）：Provider 快照、Prompt/Workflow 激活版本、套餐与额度规则、OCR 结果、当日埋点计数。Redis 异常时回源 PostgreSQL 或跳过计数（**fail-open**），不放大故障。
  - 短 TTL 状态：会话元数据（`session_id`/`user_id`/`expires_at`，不含 token 明文）、批量任务详情快照。命中后仍回 PostgreSQL 校验事实行。
  - 正确性令牌（分布式锁）：生图 / 生视频队列 worker 租约、额度预留、订单创建、模拟支付。Redis 异常时请求失败（**fail-closed，503**），避免无锁放行破坏一致性。
  - 队列缓冲（任务排队顺序）：`queue:generation` 保存普通生图 ID 与 `batch_item:{item_id}` token，`queue:video` 保存视频任务 ID，是**执行链路的正确性依赖**。与上面几类不同，它**不设 TTL、不参与淘汰**，也不是数据的副本——队列丢失时由 PostgreSQL 的 `queued` 任务按序重建；Redis 异常时创建 / 重试请求失败（**fail-closed，503**），见「队列缓冲（来自 010）」。
- memory 后端（`LISTINGO_STORAGE_BACKEND=memory`）复用现有 `MemoryStorage`，行为一致但无跨进程语义，仅用于本地/测试。

## 键清单

### 安全态（来自 008）

| 构造器 | 内部键模板 | 完整键示例 | 用途 | TTL 来源 | 所属模块 |
|---|---|---|---|---|---|
| `rate_limit_key(id, window_id)` | `rate:{id}:{window_id}` | `listingo:rate:203.0.113.8:12345` | 固定窗口限流计数 | 限流窗口 `window` | `core/rate_limit.py` |
| `nonce_key(hash)` | `nonce:{sha256}` | `listingo:nonce:a1b2...` | Nonce 防重放 | `LISTINGO_REDIS_NONCE_TTL_SECONDS`（默认 60） | `core/rate_limit.py` |
| `login_failure_key(ip, window_id)` | `login_failure:{ip}:{window_id}` | `listingo:login_failure:203.0.113.8:12345` | 登录失败计数 | 登录失败窗口 `LISTINGO_REDIS_LOGIN_FAIL_WINDOW_SECONDS`（默认 60） | `core/rate_limit.py` |
| `login_block_key(ip)` | `login_block:{ip}` | `listingo:login_block:203.0.113.8` | 登录封禁标记 | `LISTINGO_REDIS_LOGIN_BLOCK_SECONDS`（默认 1800） | `core/rate_limit.py` |
| `sms_daily_key(id)` | `sms:daily:{id}` | `listingo:sms:daily:<sha256>` | 短信日限额滑动窗口 | `LISTINGO_REDIS_SMS_DAILY_WINDOW_SECONDS`（默认 86400） | `services/sms.py` |
| `sms_cooldown_key(id)` | `sms:cooldown:{id}` | `listingo:sms:cooldown:<sha256>` | 短信发送冷却 | DB `SmsConfig.cooldown_seconds`（per-phone 覆盖） | `services/sms.py` |
| `sms_code_key(id)` | `sms:code:{id}` | `listingo:sms:code:<sha256>` | 短信验证码哈希 | DB `SmsConfig.code_ttl_seconds`（per-phone 覆盖） | `services/sms.py` |
| `sms_attempts_key(id)` | `sms:attempts:{id}` | `listingo:sms:attempts:<sha256>` | 验证码尝试计数 | 同 `sms:code` TTL | `services/sms.py` |

> 说明：`sms:*` 的 `code_ttl` / `cooldown` / `daily_limit` 仍由 DB `SmsConfig` 承担 per-phone 覆盖；全局默认窗口与最大尝试次数分别由 `LISTINGO_REDIS_SMS_DAILY_WINDOW_SECONDS` 与 `LISTINGO_REDIS_SMS_MAX_ATTEMPTS` 控制。

### 派生态 / 短 TTL 状态 / 锁（来自 009）

| 构造器 | 内部键模板 | 完整键示例 | 用途 | TTL 来源 | 所属模块 |
|---|---|---|---|---|---|
| `cache_key(domain, id)` | `cache:{domain}:{id}` | `listingo:cache:provider:code:atlas-gpt-image-2-generate` | 热点配置/激活版本/套餐规则/OCR 结果等派生态缓存 | `LISTINGO_REDIS_CACHE_TTL_SECONDS`（默认 300，另含版本键兜底） | `core/runtime.py` + 各服务 |
| `cache_version_key(domain)` | `cache:{domain}:version` | `listingo:cache:provider:version` | 域版本号，用于免 SCAN 批量失效；数据键带版本前缀 | `LISTINGO_REDIS_CACHE_VERSION_TTL_SECONDS`（默认 7 天） | `core/runtime.py` |
| `session_cache_key(token_hash)` | `session:{sha256(token)}` | `listingo:session:9f2c...` | 会话元数据缓存（不含 token 明文），TTL 取配置与会话剩余时长较小者 | `LISTINGO_REDIS_SESSION_CACHE_TTL_SECONDS`（默认 300）与剩余时长较小值 | `services/auth.py` |
| `batch_status_key(batch_id)` | `batch:status:{batch_id}` | `listingo:batch:status:b-1234` | 批量任务详情序列化快照（含 children 媒体汇总） | `LISTINGO_REDIS_BATCH_STATUS_TTL_SECONDS`（默认 3） | `services/batch_jobs.py` |
| `lock_key(scope, id)` | `lock:{scope}:{id}` | `listingo:lock:order-pay:o-5678` | 分布式锁（`SET NX EX` + token，释放校验 token），覆盖批量认领/额度预留/订单创建/模拟支付 | `LISTINGO_REDIS_LOCK_TTL_SECONDS`（默认 30） | `core/runtime.py` + `services/subscriptions.py` |
| `metric_daily_key(day, name)` | `metric:daily:{YYYYMMDD}:{name}` | `listingo:metric:daily:20260823:total` | 当日实时计数（total / event_type:* / business_type:*） | `LISTINGO_REDIS_METRIC_TTL_SECONDS`（默认 2 天） | `services/metrics.py` |

> 说明：OCR 结果缓存复用 `cache_key("ocr-result", fingerprint)`，指纹由「文件路径 + mtime + size + language_hint + 全部 OCR 设置（引擎/模型/阈值/尺寸过滤/增强变体）」SHA256 构成，设置或文件变化即换键；命中时不构造临时图片变体、不重复跑 OCR 引擎。

### 队列缓冲（来自 010）

| 构造器 | 内部键模板 | 完整键示例 | 用途 | TTL 来源 | 所属模块 |
|---|---|---|---|---|---|
| `queue_key(kind)` | `queue:{kind}` | `listingo:queue:generation` | 生图 / 生视频任务 FIFO 缓冲队列；生图元素为普通 `GenerationJob.id` 或 `batch_item:{BatchItem.id}`，视频元素为 `VideoJob.id` | **无 TTL**：由 PostgreSQL 中仍为 `queued` 的普通生图任务、批量 item 与视频任务重建 | `services/generation_queue_service.py`、`services/generation_queues.py` |

> 说明：`kind` 取值仅为 `generation` / `video`，两个队列相互独立、各自顺序消费，因此一个长视频任务不会阻塞生图任务，但同类型任务严格按提交顺序执行。
>
> 队列**不是**派生态缓存，不适用本文件其余键的 TTL / 淘汰 / 版本失效语义：元素是任务的排队顺序而非数据副本，完整任务事实始终在 PostgreSQL。服务启动时先停旧 worker，再清空并按 `created_at, id` 从 PostgreSQL 中状态仍为 `queued` 的普通生图任务、批量 item 与视频任务重建两类队列，因此队列丢失不会丢任务。Redis 入队失败时创建 / 重试接口 fail-closed 返回 503（见「降级语义」）。

### 常驻快照（来自 014）

| 构造器 | 内部键模板 | 完整键示例 | 用途 | TTL 来源 | 所属模块 |
|---|---|---|---|---|---|
| `sensitive_word_meta_key()` | `sensitive:words:meta` | `listingo:sensitive:words:meta` | 敏感词快照元信息（enabled / source_digest / word_count / variant_count / payload_bytes），检测期只读 meta 决定是否跳过与是否需要 reload | **无 TTL**：常驻，由 `set_persistent_many` 原子替换 | `services/sensitive_words.py` + `core/storage/*` |
| `sensitive_word_snapshot_key()` | `sensitive:words:snapshot` | `listingo:sensitive:words:snapshot` | 完整敏感词快照 JSON（含每个词的 variants / boundary），进程启动时按 digest 编译 Aho-Corasick 自动机 | **无 TTL**：常驻，同上 | `services/sensitive_words.py` + `core/storage/*` |

> 架构边界：敏感词快照是「可被 PostgreSQL 重建的派生态」，但**检测路径要求常驻、低延迟、跨进程一致**，因此两个键与 `queue:*` 一样**不设 TTL、不参与淘汰**。两个键通过存储适配层的 `set_persistent_many` 用 pipeline 事务（Redis）或进程锁（memory）原子替换，保证 meta 与 snapshot 永远成对更新。
>
> **PostgreSQL fallback**：`SensitiveWordSnapshot` 表保存最近 20 版完整 JSON，是 Redis 丢失时的唯一回源；检测阶段若 Redis meta/快照不可读，则读取 PostgreSQL 最新有效快照并补偿写回 Redis，二者 digest 不一致时以 PostgreSQL 为准（回源重建）。
>
> **跳过检测策略（fail-open）**：检测开启但 Redis meta 与 snapshot 均不可读、且 PostgreSQL 快照也不可用或校验失败时，**跳过本次敏感词检测**、记 warning 指标、不阻断普通生成任务；这与「内容安全本地审查 + LLM 链路」相互独立，关闭敏感词检测不影响既有黄赌毒 / 政治固定审查。
>
> **运维保护**：`sensitive:words:*` 与 `queue:*` 同属无 TTL 常驻键，`volatile-lru` 不会淘汰它们；⚠️ 切勿将 `maxmemory-policy` 改为 `allkeys-lru` / `allkeys-random`，否则常驻快照可能被逐出导致检测退化为 PostgreSQL 回源或跳过。

## 失效策略（版本域模式）

热点配置缓存采用「域版本号键 + 数据键带版本」模式，避免 SCAN/批量删除：

1. 读：`cache_key(domain, f"{version}:{identifier}")`，版本号键读时续期（`cache_version`）。
2. 写（管理端提交后）：递增对应域版本号（`invalidate` / `invalidate_best_effort`），旧数据键因自身 TTL 自然过期。
3. 域：`provider`（Provider/路由链/健康检查写回）、`prompt`、`workflow`、`subscription`（套餐/规则/用户套餐）。

批量状态缓存不强依赖版本键：创建/取消/重试/调度推进时直接 `delete` 对应 `batch:status:{id}`（fail-open）。

## 降级语义

- **可选缓存 / 计数（fail-open）**：Redis 读/写异常时回源 PostgreSQL 或跳过计数，不放大故障；`RuntimeStateService` 的 `cached` / `cached_versioned` / `*_best_effort` 系列即此语义。
- **分布式锁（fail-closed）**：`acquire_lock` 在 Redis 异常时抛出 `StorageUnavailableError`，由应用统一返回 503，避免无锁放行破坏额度/订单/调度一致性。
- **队列缓冲（fail-closed）**：`queue:*` 入队失败时同样抛出 `StorageUnavailableError`；创建 / 重试接口随即补偿（把已置为 `queued` 的任务取消并释放本次预留额度）后返回 503，绝不留下「接口报错但任务稍后仍被自动执行」的模糊状态。

## 运维约定（服务端）

- 连接池：由 `LISTINGO_REDIS_MAX_CONNECTIONS`（默认 50）与 `LISTINGO_REDIS_HEALTH_CHECK_INTERVAL_SECONDS`（默认 30）控制。
- 内存上限：`docker-compose.yml` 的 redis 服务已配置 `--maxmemory-policy volatile-lru`，防止带 TTL 临时键无限增长。
- 队列键保护：`queue:*` **不设 TTL**，因此 `volatile-lru` 不会淘汰它（该策略只淘汰带 TTL 的键）。⚠️ 切勿将 `maxmemory-policy` 改为 `allkeys-lru` / `allkeys-random`，否则排队中的任务可能被逐出。队列一旦丢失，通过重启服务从 PostgreSQL 重建即可。
- 持久化：redis 服务开启 AOF（`appendonly yes`），重启后安全态计数器可恢复，避免限流/封禁记录因重启清空产生的防护窗口。
- 锁释放：`delete_if_equal(key, token)` 仅释放本请求持有的 token，防止过期持有者误删新锁。
