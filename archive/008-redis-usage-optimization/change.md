# Change: 优化现有安全态 Redis 使用

## 变更标题
在不引入新场景、保持 fail-closed 的前提下，对 Listingo 既有的「Redis 仅存带 TTL 临时安全态」使用方式做四项收敛式优化：差异化 TTL 可配置化、键命名规范固化与文档、连接池显式配置、降级策略一致化。

## 变更背景 / 上下文
- 来源需求：用户基于 `redis-analysis.md` 要求优化 Redis 使用。经代码复核，该文档「第三节 优化建议」中多项已被 `changes/006-redis-rate-limit-verification` 实现，本变更只补齐尚未落地的项，并显式排除「第二节 新场景」。
- 关联模块（依据 `docs/CONTEXT_SUMMARY.md` §2）：
  - 限流防刷与临时安全状态：`backend/app/core/storage/`、`backend/app/core/rate_limit.py`、`backend/app/middleware/ip_block.py`、`backend/app/services/sms.py`
  - 配置：`backend/app/config.py`
- 影响范围：上述后端文件 + 新增键清单文档 + `docker-compose.yml` Redis 服务端参数（可选加固，见 Open Q1）。

## 已满足项（本次不重复实现，仅补回归测试）
经复核，`redis-analysis.md` 第三节以下建议已被 `changes/006` 实现，本次仅补充回归测试以固化行为：
- **键前缀隔离**：`config.py` 的 `redis_key_prefix`（默认 `listingo`）已由 `RedisStorage._key` 统一加前缀。
- **连接管理**：redis-py `from_url` 默认走连接池；本次仅补充显式 `max_connections` / `health_check_interval` 配置（见 G3）。
- **数据结构选型 / 原子性**：`incr` 采用 `set nx ex` 首写定 TTL + 后续 `incr`，sliding window 采用 WATCH 乐观锁 + 重试，已规避 `INCR+EXPIRE` 竞态。
- **错误降级框架**：`StorageUnavailableError` 已在 `ip_block.py` 与 `main.py` 全局异常处理中转为 503（fail-closed）。

## 目标
- **G1 差异化 TTL 可配置**：Nonce、登录失败窗口、登录封禁、短信日限额/次数等场景的 TTL 与阈值改为 `LISTINGO_*` 环境变量，运维可调参，无需改代码。
- **G2 键命名规范固化**：盘点全部现存 Redis 键，统一定义 `{prefix}:{module}:{purpose}:{id}` 约定，集中到键构造器并写出键清单文档。
- **G3 连接池显式配置**：暴露 `max_connections` 与 `health_check_interval`，提升高并发与长连接健壮性。
- **G4 降级策略一致化**：维持 fail-closed（Redis 不可用 → 503），确保限流 / Nonce / 封禁 / 短信四条路径行为统一，并以测试固化。

## 方案设计
### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/config.py` | 修改 | 新增 Redis TTL/阈值与连接池相关 `LISTINGO_*` 配置项及校验 |
| `backend/app/core/rate_limit.py` | 修改 | `NONCE_TTL_SECONDS`、登录失败窗口、封禁时长改读 Settings；统一调用集中键构造器 |
| `backend/app/services/sms.py` | 修改 | 短信日限额窗口、最大尝试次数默认值改读 Settings（DB `SmsConfig` 仍作为 per-phone 覆盖优先） |
| `backend/app/core/storage/redis.py` | 修改 | 接受显式连接池参数（`max_connections`、`health_check_interval`） |
| `backend/app/core/storage/keys.py` | 新增 | 集中定义 Redis 键构造器与命名约定（rate / nonce / login_failure / login_block / sms_*） |
| `backend/app/middleware/ip_block.py` | 修改（验证为主） | 确认 fail-closed 行为一致；补充 Redis 不可用单测 |
| `docs/REDIS_KEYS.md` | 新增 | Redis 键清单与命名规范文档 |
| `docs/CONTEXT_SUMMARY.md` | 修改 | 索引新增 `docs/REDIS_KEYS.md` |
| `docker-compose.yml` | 修改（可选） | Redis 服务端 `maxmemory-policy=volatile-lru`、RDB 快照（运维加固，见 Open Q1） |

### 实现要点
1. **G1 — TTL / 阈值可配置化**
   - `config.py` 新增：`redis_nonce_ttl_seconds`（默认 60，ge>=1）、`redis_login_fail_window_seconds`（默认 60）、`redis_login_block_seconds`（默认 1800）、`redis_sms_daily_window_seconds`（默认 86400）、`redis_sms_max_attempts`（默认 5）。命名遵循 `LISTINGO_*` 约定。
   - `rate_limit.py`：`NONCE_TTL_SECONDS` 改为从 `settings` 读取；`record_failure_and_block` 的 `window` / `block_seconds` 默认值改读 settings；保留函数形参以便测试覆盖。
   - `sms.py`：`SMS_DAILY_WINDOW_SECONDS`、`SMS_MAX_CODE_ATTEMPTS` 默认值改读 settings，DB `SmsConfig` 仍按 per-phone 覆盖优先（见 Open Q3）。
2. **G2 — 键命名规范**
   - 新增 `core/storage/keys.py`，导出 `rate_key(key, window_id)`、`nonce_key(hash)`、`login_failure_key(ip, window_id)`、`login_block_key(ip)`、`sms_code_key(...)`、`sms_attempts_key(...)` 等构造器，统一加 `{prefix}:` 前缀（前缀由 `RedisStorage` 注入，与现有 `_key` 保持一致）。
   - 盘点并迁移现存散落的键字面量到构造器，避免字符串漂移；写出 `docs/REDIS_KEYS.md` 清单（键模板、用途、TTL、所属模块）。
3. **G3 — 连接池显式配置**
   - `config.py` 新增 `redis_max_connections`（默认 50，ge>=1）、`redis_health_check_interval_seconds`（默认 30，ge>=0）。
   - `redis.py`：`RedisStorage.__init__` 接受可选 `max_connections` / `health_check_interval`，构造 `ConnectionPool`（或在 `from_url` 基础上补充 `health_check_interval`），确保池上限与空闲健康检查生效。
4. **G4 — 降级策略一致化**
   - 维持 fail-closed：Redis 不可用时安全中间件一律返回 503（当前 `ip_block.py` 已实现；`rate_limit.py` / `sms.py` 触发的 `StorageUnavailableError` 已有全局 503 handler）。
   - 补充单测：FakeRedis 断连 / 抛 `StorageUnavailableError` 场景下，限流、Nonce 校验、封禁、短信四条路径均返回 503 / 拒绝，且不留安全敞口。
5. **回归测试（已满足项固化）**：验证 `set nx ex` 首写定 TTL 非竞态、键前缀隔离、sliding-window WATCH 重试。

## 验收标准
- [ ] `config.py` 新增 7 项 Redis `LISTINGO_*` 配置（nonce_ttl / login_fail_window / login_block / sms_daily_window / sms_max_attempts / max_connections / health_check_interval）并通过字段校验（ge 约束）。
- [ ] `rate_limit.py` 与 `sms.py` 的 TTL / 阈值默认值改读 Settings，函数形参仍可覆盖（保持向后兼容与可测）。
- [ ] 新增 `core/storage/keys.py`，现存 Redis 键字面量已迁移至集中构造器；`docs/REDIS_KEYS.md` 键清单与命名约定产出。
- [ ] `redis.py` 支持显式 `max_connections` 与 `health_check_interval`，连接池上限生效（单测或启动健康检查通过）。
- [ ] fail-closed 策略在限流 / Nonce / 封禁 / 短信四条路径一致，且 Redis 不可用场景单测全部返回 503 / 拒绝。
- [ ] 后端 pytest 全量通过；`.coderules` 合规（不引入新场景、不破坏现有功能）。
- [ ] 更新 `docs/CONTEXT_SUMMARY.md` 索引以纳入 `docs/REDIS_KEYS.md`。

## 非目标（NON-GOAL，防止范围蔓延）
- 不引入 `redis-analysis.md` 第二节的「新 Redis 场景」（热点数据缓存、用户会话存储、分布式锁、任务状态缓存、审计实时计数、临时文件缓存）。理由：与项目架构约束「Redis 仅存带 TTL 临时安全态、业务事实只在 PostgreSQL」直接冲突，已与用户确认排除。
- 不实现 Redis 监控 / 健康检查运营面板（用户未选该项）。
- 不改动 `storage_backend` 在 redis / memory 之间的切换机制本身。
- 不将业务事实（PostgreSQL）迁移进 Redis。

## Open Questions
> 兜底机制：以下未定义 / 有歧义项，用户在 `coding` 阶段以「执行方案」指令授权，且本变更草案已给出推荐默认，故统一按推荐默认决议落地；如需调整，改 env / `docker-compose.yml` 即可。
- [x] Q1: 服务端加固——已采纳：新增 `--maxmemory-policy volatile-lru`；持久化方面 `docker-compose.yml` 的 redis 已开启 `appendonly yes`（AOF），重启后安全态计数器可恢复，缓解「重启清空」窗口。RDB 未额外启用（AOF 已覆盖）。
- [x] Q2: 连接池默认值——已采纳推荐：`max_connections=50`、`health_check_interval_seconds=30`，均可通过 `LISTINGO_REDIS_MAX_CONNECTIONS` / `LISTINGO_REDIS_HEALTH_CHECK_INTERVAL_SECONDS` 覆盖。
- [x] Q3: sms 阈值优先级——已采纳推荐：env（`LISTINGO_REDIS_SMS_DAILY_WINDOW_SECONDS` / `LISTINGO_REDIS_SMS_MAX_ATTEMPTS`）作为全局默认；DB `SmsConfig` 的 `code_ttl_seconds` / `cooldown_seconds` / `daily_limit_per_phone` 仍按 per-phone 覆盖优先。
- [x] Q4: 索引——已采纳推荐：`docs/REDIS_KEYS.md` 已建立，并在 `docs/CONTEXT_SUMMARY.md` 权威文档映射表新增索引条目。
