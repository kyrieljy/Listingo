# Change: redis rate limit verification

## 变更标题
将 API 限流防刷状态与短信验证码从进程内存 / SQLite 迁移到 Redis

Date: 2026-08-23

## 变更背景 / 上下文
- 来源需求：基于已完成的 `changes/004-memory-rate-limit`，补齐 Redis 实现；Redis 地址必须通过环境变量配置，便于后期独立部署。
- 关联模块：`backend/app/core/storage/`、`backend/app/core/rate_limit.py`、`backend/app/middleware/ip_block.py`、`backend/app/services/sms.py`、`backend/app/main.py`、`backend/app/config.py`、`docker-compose.yml`。
- 004 已交付的临时状态包括：套图/视频共享固定窗口计数、登录 IP 固定窗口计数、Nonce 防重放、登录失败计数、登录 IP 封禁记录。当前全部落在 `MemoryStorage`。
- 短信链路当前把验证码哈希、有效期、尝试次数、发送 IP 与 Provider 返回写入 SQLite 的 `SmsVerificationCode` 表，并用该表推导同手机号冷却与滚动 24 小时发送次数。按本次要求，这些临时安全状态也必须迁到 Redis。
- 当前 `docker-compose.yml` 只有 backend/frontend，没有 Redis；`backend/requirements.txt` 也没有 Redis 客户端。
- 现有 Alembic head 为 `4d5e6f7a8b9c`；`sms_verification_code` 表由 `3c4d5e6f7a8b` 创建。
- 工作树已有与本次无关的用户改动（例如 `README.md` 删除、`SPEC.md`/`TECH_STACK.md` 修改、OCR 相关修改）。coding 阶段不得回退这些内容。

## 目标
- 在 Compose 中安装并运行 Redis，新增 `LISTINGO_REDIS_URL` 环境变量；后端只通过该地址连接 Redis，不把主机名写死在业务代码。
- 生产/常规运行默认使用 Redis 后端，限流计数、Nonce、登录失败计数、IP 封禁、短信验证码、验证码尝试次数、发送冷却与 24 小时发送次数全部写入 Redis。
- 保持 004 的外部行为：套图与视频共享 20 次/分钟；Nonce TTL 60 秒；同 IP 60 秒内 5 次密码登录失败封禁 30 分钟；短信验证码 5 次尝试后拒绝。
- Redis 操作使用原子语义，多个后端进程或 Worker 共享同一份状态；Redis 模式不再触发单 Worker 熔断。
- 移除运行时对 SQLite 验证码表的读写，新增迁移删除 `sms_verification_code` 表；业务持久数据仍保留在 SQLite。

## 方案设计
### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/requirements.txt` | 修改 | 新增 Redis 客户端与测试用 Fake Redis 依赖并固定版本 |
| `backend/app/config.py` | 修改 | 新增 `redis_url`、`redis_key_prefix` 等配置；默认运行后端改为 Redis |
| `backend/app/core/storage/redis.py` | 新增 | Redis 适配器：TTL key、原子计数、NX 写入、Lua 原子操作、连接生命周期 |
| `backend/app/core/storage/base.py` | 修改 | 按验证码与滚动窗口所需原子能力扩展存储契约 |
| `backend/app/core/storage/memory.py` | 修改 | 仅作为显式测试/本地兼容后端补齐同等原子语义 |
| `backend/app/core/storage/__init__.py` | 修改 | 导出 Redis 适配器 |
| `backend/app/core/rate_limit.py` | 修改 | 工厂按配置选择 Redis；生产不隐式回落 Memory；保留 bool API |
| `backend/app/middleware/ip_block.py` | 修改 | 封禁记录读取改为 Redis 语义，并处理存储不可用 |
| `backend/app/services/sms.py` | 修改 | 验证码、尝试次数、冷却与滚动 24 小时计数改用 Redis |
| `backend/app/models.py` | 修改 | 删除 `SmsVerificationCode` ORM 模型 |
| `backend/app/main.py` | 修改 | Redis 启动检查、生命周期关闭连接、按后端处理 Worker 约束 |
| `backend/migrations/versions/` | 新增 | 基于 `4d5e6f7a8b9c` 的迁移，删除验证码表及索引 |
| `docker-compose.yml` | 修改 | 新增 Redis 服务、数据卷、健康检查与后端环境变量 |
| `.env.local` / `.env.production` | 修改 | 增加 Redis 后端与地址配置；生产可替换为独立 Redis URL |
| `backend/tests/` | 修改 | 增加 Redis 适配器、限流、Nonce、封禁与短信验证码测试 |
| `TECH_STACK.md` | 修改 | 记录 Redis 依赖、环境变量、部署与扩容约束 |
| `docs/CONTEXT_SUMMARY.md` | 修改 | 同步模块索引与近期变更 |

### 实现要点
1. **Redis 安装与配置**
   - `backend/requirements.txt` 新增 `redis==5.2.1`；为不依赖真实服务的单元测试新增 `fakeredis==2.26.2`。
   - `docker-compose.yml` 新增 `redis:7.4-alpine` 服务，启用 AOF，配置 `redis-data` 卷与健康检查 `redis-cli ping`。
   - 后端环境注入 `LISTINGO_REDIS_URL=${LISTINGO_REDIS_URL:-redis://redis:6379/0}`；`.env.local` 与 `.env.production` 均显式记录该变量。独立部署时只替换 URL，支持 `redis://`、`rediss://`、用户名/密码与自定义主机端口。
   - 新增 `LISTINGO_REDIS_KEY_PREFIX`，默认 `listingo`，避免多环境共用 Redis 时 key 冲突。
   - Redis 模式启动时执行有限重试的 `PING`；超时或连接失败直接启动失败，不允许静默降级为内存后端。

2. **Redis 限流适配器**
   - `RedisStorage` 使用 `redis.Redis.from_url()` 的线程安全连接池；应用 lifespan 结束时关闭连接。
   - `incr()` 使用 Lua 或等价原子命令保证计数初始化与 TTL 绑定，避免 `INCR` 后进程异常导致无过期 key。
   - `set_if_absent()` 使用 `SET key value NX EX ttl` 的原子语义，保证并发 Nonce 只能被消费一次。
   - `get/exists/delete/expire/setex` 均尊重 Redis 剩余 TTL；`cleanup_expired()` 与清理线程为 no-op，由 Redis 原生过期处理。
   - 所有 key 加统一前缀，例如 `listingo:rate:*`、`listingo:nonce:*`、`listingo:login_failure:*`、`listingo:login_block:*`、`listingo:sms:*`。
   - Redis 连接异常转换为受控的存储不可用错误；IP Block 中间件与相关路由返回 `503`，不得绕过防护或回落内存。
   - `MemoryStorage` 仅在显式配置 `LISTINGO_STORAGE_BACKEND=memory` 时可用，并继续保留单 Worker 熔断；生产默认与 Compose 均为 Redis。

3. **限流与防刷行为迁移**
   - 保留 `RateLimitService` 与 004 要求的 bool 入口；工厂按 `Settings.storage_backend` 创建 Redis 或 Memory 适配器。
   - 套图/视频共享计数、登录 IP 计数、Nonce、登录失败计数与封禁 key 的业务语义不变，但状态跨进程共享。
   - Redis 模式允许 `WEB_CONCURRENCY > 1`；`_validate_single_worker()` 只在 memory 后端生效。
   - 单进程红色警告只在 memory 模式输出；Redis 模式输出后端与 key 前缀信息，不输出误导性的重启失效提示。
   - 移除生产路径隐式 `MemoryStorage()` 默认服务；未显式使用的兼容 bool 入口也不能成为隐藏内存状态来源。

4. **短信验证码与计数迁移**
   - Redis 中保存验证码的 SHA-256 哈希，不保存明文验证码；key 按 `phone + purpose` 派生，避免手机号明文暴露在 key 中。
   - Redis key 设计：验证码 `sms:code:*`、尝试次数 `sms:attempts:*`、发送冷却 `sms:cooldown:*`、滚动 24 小时发送记录 `sms:daily:*`；全部带全局前缀和 TTL。
   - 发送前原子预留冷却与 24 小时额度；Provider 发送失败时按唯一 reservation token 回滚，避免失败请求消耗额度。发送成功后写入新验证码并重置尝试次数。
   - 管理员短信二验的既有 `bypass_rate_limit` 只跳过冷却与每日次数，验证码本体仍写入 Redis。
   - 校验使用 Lua/事务原子完成：检查验证码存在、尝试次数小于 5、比对哈希；错误尝试递增并延续 TTL，正确验证码一次性删除并同时清理尝试次数。
   - 冷却时间为 0 时跳过冷却 key；`code_ttl_seconds` 非法时启动/发送前受控报错。
   - `SmsConfig` 仍保留模板、开关、TTL、冷却与每日上限等运营配置在 SQLite；`SmsVerificationCode` 不再作为运行时存储。
   - 新增 Alembic 迁移删除 `sms_verification_code` 表和索引。迁移不搬运仍在有效期内的验证码；发布窗口内未使用的旧验证码失效，用户重新获取即可。

5. **测试与部署验证**
   - Fake Redis 单元测试覆盖 TTL、原子 `incr`、NX、并发 Nonce、封禁 TTL、连接关闭与错误转换。
   - API 测试覆盖 Redis 后端下 004 的限流/Nonce/封禁行为，以及短信冷却、每日上限、管理员 bypass、错误尝试、一次性消费和验证码重置。
   - 断言发送验证码后 SQLite 不新增 `sms_verification_code` 行，相关状态只出现在 Fake Redis。
   - 断言 Redis 不可用时启动失败或相关请求返回 `503`，且没有内存回落。
   - 运行 Alembic 单头检查、后端全量测试与 `docker compose config`；如本机 Docker 可用，再启动 Redis 并验证健康检查。

## 范围外
- 不引入 Celery、分布式任务队列、Redis Stream 或对象存储。
- 不迁移用户会话、订阅额度、登录事件、AnalyticsEvent 等持久业务数据；这些仍属 SQLite 事实记录。
- 不将 `ProviderConcurrencyLimiter` 改为 Redis 分布式信号量；它是 Provider 调用并发控制，不属于 004 的 API 限流状态。
- 不新增图形验证码，不改变前端请求契约；`X-Request-Nonce` 仍由现有前端生成。
- 不支持 Redis Cluster / Sentinel 自动发现；独立部署通过标准单地址 URL 连接。

## 验收标准
- [ ] `docker compose config` 展示 Redis 服务、健康检查、持久卷和 `LISTINGO_REDIS_URL` 注入，后端镜像依赖包含 `redis==5.2.1`。
- [ ] 默认运行配置为 Redis；仅显式选择 memory 时保留 004 行为和单 Worker 熔断。
- [ ] 套图与视频共享限流、登录限流、Nonce、登录失败封禁在 Redis 后端下行为与 004 一致。
- [ ] 短信验证码、尝试次数、冷却与滚动 24 小时次数全部只写入 Redis；`sms_verification_code` 表从 ORM 与数据库迁移中移除。
- [ ] Redis 连接失败不会静默降级；常规后端测试、Alembic 检查和 Compose 配置检查通过。
- [ ] `TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md` 记录 Redis 架构、环境变量、key 语义与部署更新要求。

## Open Questions
None.
