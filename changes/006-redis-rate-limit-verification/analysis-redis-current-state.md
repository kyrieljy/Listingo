# Redis 使用位置与运行状态分析（只读）

> 变更背景：`changes/006-redis-rate-limit-verification` 将 API 限流防刷状态与短信验证码从进程内存 / SQLite 迁移到 Redis。
> 本文件为**只读巡检**产物，未修改任何代码或配置。

## 一、变更内容摘要（来自 change.md）

- 新增 Redis 适配器 `RedisStorage`，统一承载：套图/视频共享固定窗口计数、Nonce 防重放、登录失败计数、IP 封禁、短信验证码、验证码尝试次数、发送冷却、滚动 24 小时发送次数。
- 默认运行后端改为 Redis（`LISTINGO_STORAGE_BACKEND=redis`），业务代码不写死主机名，仅通过 `LISTINGO_REDIS_URL` 连接。
- 移除 SQLite `SmsVerificationCode` 表（ORM 模型已删除，新增 Alembic 迁移 `5f6a7b8c9d0e` 删表）。
- `docker-compose.yml` 新增 `redis:7.4-alpine` 服务（AOF、数据卷、健康检查、`LISTINGO_REDIS_URL` 注入）。
- Redis 不可用时启动失败 / 请求返回 `503`，不再静默回落内存后端。

## 二、当前用到 Redis 的位置（源码证据）

### 1. 配置层
| 文件 | 行 | 内容 |
|------|----|------|
| `backend/app/config.py` | 39-44 | `storage_backend: Literal["redis","memory"]="redis"`；`redis_url`、`redis_key_prefix`、`redis_connect_timeout_seconds`、`redis_socket_timeout_seconds`、`redis_startup_timeout_seconds` |
| `backend/app/config.py` | 80-94 | `redis_url` / `redis_key_prefix` 校验器（`redis://` 或 `rediss://`） |
| `.env.local` | 31-39 | `LISTINGO_STORAGE_BACKEND=redis`、`LISTINGO_REDIS_URL=redis://127.0.0.1:6379/0`、`LISTINGO_REDIS_KEY_PREFIX=listingo` |
| `.env.production` | 31-39 | 同上，`LISTINGO_REDIS_URL=redis://redis:6379/0` |
| `docker-compose.yml` | 13-16,33-46 | backend 注入 `LISTINGO_REDIS_URL=${LISTINGO_REDIS_URL:-redis://redis:6379/0}` 并 `depends_on` redis healthy；redis 服务定义 |

### 2. 存储适配器层
| 文件 | 说明 |
|------|------|
| `backend/app/core/storage/redis.py` | `RedisStorage` 实现：TTL key、原子 `incr`(SET NX)、`set_if_absent`(SET NX EX)、`get/exists/delete/expire`、`reserve/release_sliding_window`(zset+WATCH)、`delete_if_equal`、`consume_hash_once`(Lua 式事务) |
| `backend/app/core/storage/base.py` | `RateLimitStorage` 抽象契约 + `StorageUnavailableError` |
| `backend/app/core/storage/__init__.py` | 导出 `RedisStorage`、`MemoryStorage` |
| `backend/app/core/storage/memory.py` | 仅显式 `memory` 后端时启用（本地兼容/测试） |

### 3. 限流与防刷核心
| 文件 | 行 | 使用 |
|------|----|------|
| `backend/app/core/rate_limit.py` | 150-166 | `create_rate_limiter()`：backend=redis 时实例化 `RedisStorage` |
| `backend/app/core/rate_limit.py` | 61-133 | `consume_rate_limit`/`consume_nonce`/`record_failure_and_block`/`is_ip_blocked` 等全部走 `self.storage`（即 Redis） |
| `backend/app/main.py` | 102,110,115,131,142-144 | 创建限流器；lifespan 启动时 `_wait_for_storage` 调 `storage.ping()` 重试；注册 `StorageUnavailableError → 503` 处理器；关闭时 `rate_limiter.close()` |
| `backend/app/middleware/ip_block.py` | 22-32 | 中间件读取 `rate_limiter.is_ip_blocked()`，存储不可用时返回 `503` |

### 4. API 路由（实际写入/读取 Redis 的入口）
| 文件 | 行 | 业务 | Redis key 前缀（统一 `+ "listingo:"`） |
|------|----|------|------|
| `backend/app/api/auth.py` | 77-90 | 登录限流 `login:{ip}` | `rate:*` |
| `backend/app/api/auth.py` | 93-105 | Nonce 防重放 | `nonce:*`（SHA-256 值） |
| `backend/app/api/auth.py` | 116 | 登录失败计数 + 封禁 | `login_failure:*` / `login_block:*` |
| `backend/app/api/auth.py` | 195, 367 | 发送短信验证码（login/change_phone） | `sms:daily:*` / `sms:cooldown:*` / `sms:code:*` / `sms:attempts:*` |
| `backend/app/api/auth.py` | 215,237,277,389 | 校验短信验证码 | `sms:code:*` / `sms:attempts:*` |
| `backend/app/api/auth.py` | 297 | 登录成功清理失败计数 | `login_failure:*` |
| `backend/app/api/public.py` | 141-150 | 套图/视频共享限流 `workspace:generation`（20 次/分钟） | `rate:*` |
| `backend/app/api/admin.py` | 864 | 管理员短信二验发送 | 同上 `sms:*` |
| `backend/app/services/sms.py` | 整文件 | 验证码哈希、尝试次数、冷却、24h 滚动计数全部经 `request.app.state.rate_limiter.storage`（Redis）读写；不再读写 SQLite |

### 5. 测试层（仅验证用，非运行时）
- `backend/tests/test_redis_storage.py`、`test_rate_limit.py`、`test_sms_phone.py`、`test_config.py`、`conftest.py`：使用 `fakeredis` 模拟 Redis，**不依赖真实服务**。
- `backend/requirements.txt`：第 8-9 行声明 `redis==5.2.1`、`fakeredis==2.26.2`。

## 三、Redis 是否已启动 —— 结论：未启动

实测（只读探测，未改动任何东西）：

| 检查项 | 结果 |
|--------|------|
| TCP `127.0.0.1:6379` 连接 | **超时/拒绝**（无监听） |
| Redis PING 协议探测 | 未建立连接，无响应 |
| `redis-cli` / `redis-server` 可执行文件 | 不在 PATH |
| `redis-server` 进程 | 不存在 |
| Docker / `docker compose` | 本环境不可用（`result.md` 亦记录 Docker 缺失） |
| Python 受管环境 `redis` 模块 | 受管 venv 未装（项目自带 `.venv` 内有 `redis 5.2.1`，但无服务可连） |

**判定**：当前 Redis **未运行**。

- 本机非容器部署的默认地址 `redis://127.0.0.1:6379/0`（`.env.local` 与 `config.py` 默认值）无服务监听。
- 容器部署地址 `redis://redis:6379/0`（`docker-compose.yml` / `.env.production`）依赖的 `redis` 容器未启动，且本机 Docker 不可用。

## 四、影响与后续建议（分析结论，非执行）

1. **默认配置下后端无法启动**：`storage_backend=redis` 时，`main.py` 的 lifespan 会调用 `_wait_for_storage()` 对 Redis 做 `PING` 重试（`redis_startup_timeout_seconds=5s`），连接失败直接抛 `RuntimeError`（"Redis is unavailable after 5s"），应用启动即失败，且**不会回落内存**。
2. **启动 Redis 的两条路径**：
   - 本机直接运行：安装并启动 `redis-server`（监听 `127.0.0.1:6379`），或显式设置 `LISTINGO_REDIS_URL` 指向可用实例。
   - 容器运行：在具备 Docker 的环境执行 `docker compose up -d redis`，待健康检查 `healthy` 后 backend 才能起。
3. **本地仅联调、不启 Redis 的替代**：临时把 `LISTINGO_STORAGE_BACKEND=memory`（仅测试/本地兼容，会重新启用单 Worker 熔断，且状态不跨进程），但生产/常规运行必须为 Redis。
4. **确认迁移已落地**：`SmsVerificationCode` 经全仓 grep 已无任何引用（ORM 模型与运行期读写均已移除），短信验证码状态现完全依赖 Redis。

> 本分析未修改任何文件；若需我执行"安装/启动 Redis"或"调整 backend 环境变量"等动作，请另行确认范围。
