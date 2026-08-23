# Change: memory rate limit

## 变更标题
为 Listingo 后端增加进程内存限流、Nonce 防重放与登录封禁

Date: 2026-08-22

## Goal

在不引入 Redis 依赖的前提下，为现有 FastAPI 后端提供三类防护：

1. 套图与视频生成接口的固定窗口限流，超限返回 `429`，并返回标准 `X-RateLimit-*` 响应头。
2. 敏感接口的一次性 Nonce 防重放校验，Nonce TTL 固定为 60 秒。
3. 密码登录失败计数与 IP 自动封禁：同一 IP 60 秒内失败 5 次，封禁 30 分钟。

内存实现必须显式暴露单进程部署约束，达到容量上限时受控拒绝，不能因无界增长导致 OOM。

## Context

- 语义索引 `docs/CONTEXT_SUMMARY.md` 指向当前应用装配 `backend/app/main.py`、配置 `backend/app/config.py`、认证路由 `backend/app/api/auth.py` 与公开工作台路由 `backend/app/api/public.py`。
- 当前仓库不存在 `backend/app/api/v1/endpoints/workspace.py`，也没有 `/generate/suite` 路由。套图创建实际为 `POST /api/v1/generation-jobs`，视频创建实际为 `POST /api/v1/video-jobs`，二者都位于 `backend/app/api/public.py`。
- 当前登录路径实际为 `POST /api/v1/auth/password/login`；改密为 `POST /api/v1/account/password`；模拟支付为 `POST /api/v1/subscription/orders/{order_id}/mock-pay`。
- 当前后端由 `backend/Dockerfile` 中的单进程 Uvicorn 启动，未设置 `WEB_CONCURRENCY`；测试入口为 `.venv/Scripts/python.exe -m pytest backend/tests`。
- 当前 IP 获取函数位于 `backend/app/services/sms.py` 的 `client_ip()`，登录事件与会话已复用该函数。生产 Nginx 目前未显式传递 `X-Forwarded-For`，若直接按容器客户端地址封禁，经由 Nginx 的所有用户会共享同一 IP。
- 现有 `backend/tests/conftest.py` 会多次构造测试应用。内存清理线程必须可停止或可复用，不能让测试进程累积后台线程。

## Scope

### In Scope

- 新增 `backend/app/core/storage/base.py` 与 `backend/app/core/storage/memory.py`，以 `RateLimitStorage` 抽象接口隔离内存与未来 Redis 实现。
- 新增 `backend/app/core/rate_limit.py`，提供限流、Nonce、登录失败封禁的业务封装，并保留需求指定的 bool 函数入口。
- 新增 `backend/app/middleware/ip_block.py`，在请求入口检查封禁 IP。
- 在 `backend/app/config.py` 增加存储后端、容量上限、清理周期等配置；`storage_backend` 当前固定为 `memory`，配置为未支持后端时启动即失败。
- 在 `backend/app/main.py` 增加 `WEB_CONCURRENCY > 1` 启动熔断、内存模式醒目警告日志、IP Block 中间件挂载与测试友好的存储生命周期管理。
- 按现有路由结构接入 `backend/app/api/public.py` 的 `POST /generation-jobs` 与 `POST /video-jobs`，以及 `backend/app/api/auth.py` 的密码登录、改密和模拟支付。
- 为前端改密与模拟支付请求生成并发送唯一 `X-Request-Nonce`，并在前端 Nginx 代理中透传 `X-Forwarded-For`。
- 新增后端单元与 API 测试，覆盖限流头、Nonce 防重放、容量拒绝、失败封禁、启动熔断和清理逻辑。
- 同步 `TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md` 的单进程部署约束与模块索引。

### Out of Scope

- 不实现 Redis 后端、Redis 连接池、分布式锁或相关依赖。
- 不实现图形验证码；只在登录逻辑处添加风险注释，说明重启导致封禁清零且当前缺少二次人机校验。
- 不把计数、Nonce 或封禁状态持久化到 SQLite。
- 不新增 `backend/app/api/v1/endpoints/workspace.py`，不创建 `/generate/suite` 兼容路由；按当前仓库事实修改 `public.py`。
- 不重构现有路由分层，不调整认证、订单或任务创建的业务语义。

## Implementation Plan

1. **配置与启动约束**
   - 在 `Settings` 中新增 `storage_backend: Literal["memory"] = "memory"`、`rate_limit_max_size: int = 10000`、`rate_limit_cleanup_interval_seconds: int = 30`，均通过现有 `LISTINGO_*` 环境变量体系配置。
   - 在 `create_app()` 解析 Settings 后、初始化数据库与中间件前检查 `WEB_CONCURRENCY`：非测试环境下未设置或小于等于 1 允许启动；大于 1 抛出异常终止启动；非法数值同样启动失败，避免静默忽略运维误配。
   - 内存模式启动日志输出红色醒目警告，正文必须精确包含：`WARNING: Rate limiting is running in MEMORY mode. DO NOT scale horizontally or set Gunicorn workers > 1.`

2. **存储适配器**
   - `RateLimitStorage` 定义 `incr()`、`exists()`、`setex()`、`get()`、`delete()`、`expire()`，并额外定义原子 `set_if_absent()`；Nonce 防重放不能通过 `exists()` 加 `setex()` 两步实现，否则并发重放会穿透。
   - 接口值和 `incr()` 返回携带原子计数结果，供限流层计算 `Remaining` 与 `Reset`；固定窗口 key 包含窗口编号，TTL 覆盖窗口生命周期。
   - `MemoryStorage` 使用 `OrderedDict`、`threading.Lock`、单调时钟和绝对过期时间实现全局 `max_size` 硬上限；读取和写入会更新 LRU 顺序。
   - 后台 daemon 线程每 30 秒清理过期记录，并暴露受保护的 `close()` 与可测试的清理入口；应用 lifespan 结束时停止线程，测试 fixture 可安全复用或释放。
   - 容量满时先清理已过期项。计数和封禁类写入按 LRU/最旧优先淘汰低价值记录；Nonce 写入不得淘汰既有 Nonce 来腾空间，必须在容量满时返回“容量不足”，由路由转为 `429`。

3. **限流与防刷服务**
   - `backend/app/core/rate_limit.py` 只通过工厂选择 `RateLimitStorage` 实现；除该工厂与测试外，任何业务模块不得导入 `MemoryStorage`。
   - 保留 `check_rate_limit(key, limit, window) -> bool`、`check_and_consume_nonce(nonce, ttl=60) -> bool`、`record_failure_and_block(ip, fail_limit=5, window=60, block_seconds=1800) -> bool` 三个需求指定入口。
   - 为路由补充内部结果对象：`consume_rate_limit()` 返回 `allowed/count/reset_in_seconds`，`consume_nonce()` 区分 `accepted/duplicate/capacity_exceeded`。bool 函数是这些原子结果的薄封装，避免路由为了响应头二次读存储而产生竞态。
   - 限流触发时统一生成 `X-RateLimit-Limit`、`X-RateLimit-Remaining`、`X-RateLimit-Reset`；`Reset` 使用距离窗口重置的整数秒数。成功响应也返回相同头，便于客户端提前退避。
   - 登录失败计数 key 使用 IP 维度，失败第 5 次时写入 1800 秒封禁记录并清理失败计数；成功登录清理当前 IP 的失败计数。
   - Nonce key 加独立命名空间，TTL 固定 60 秒；校验长度并存储规范化 key，拒绝空值、超长值和重复值。

4. **IP Block 中间件**
   - 在 `backend/app/middleware/ip_block.py` 挂载全局请求中间件，命中封禁 key 时直接返回 `403`，不进入路由、数据库或后台任务逻辑。
   - 复用或抽取现有 `client_ip()`，与登录事件保持同一取值口径。
   - 中间件与 CORS 的挂载顺序需保证浏览器仍能收到带 CORS 头的 403/429 响应。
   - 因当前 Nginx 未传递 `X-Forwarded-For`，需补充代理头配置或在变更说明中明确仅直连 Uvicorn 场景可按真实 IP 生效；不能静默把 Nginx 后所有流量归为同一 IP。

5. **路由接入**
   - 在 `POST /api/v1/generation-jobs` 与 `POST /api/v1/video-jobs` 函数入口、参数校验和额度扣减之前执行共享限流；两个接口合并后的第 21 次/分钟请求返回 `429` 与完整限流头。
   - 在 `POST /api/v1/auth/password/login` 入口执行 IP 维度登录限流；坏密码、管理员短信二验失败、账号停用等失败路径记录失败计数，成功路径清零。
   - 在登录实现处添加醒目 `# WARNING` 注释：内存封禁重启即失效，且当前未实现图形验证码。
   - 在 `POST /api/v1/account/password` 与 `POST /api/v1/subscription/orders/{order_id}/mock-pay` 通过 `X-Request-Nonce` 请求头消费一次性 Nonce；缺失或格式错误返回 `400`，重复返回 `409`，容量满返回 `429`。
   - 前端 `changePasswordApi()` 与 `mockPayOrderApi()` 每次调用时生成安全随机 Nonce，并通过 `X-Request-Nonce` 发送；同一请求重试必须生成新 Nonce。
   - `frontend/nginx.conf` 透传 `X-Forwarded-For`，确保生产代理后的限流和封禁按真实客户端 IP 隔离。

6. **验证**
   - 新增 `backend/tests/test_rate_limit.py` 覆盖存储原子性、容量、过期清理、Nonce、登录封禁与限流头。
   - 扩展配置或应用装配测试覆盖 `WEB_CONCURRENCY` 熔断和启动警告。
   - 全量运行后端测试，确认既有认证、订单、套图、视频和 CORS 行为不回退。

## Verification Plan

- 运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_rate_limit.py backend/tests/test_config.py backend/tests/test_security_and_seed.py backend/tests/test_sms_phone.py`。
- 运行 `.venv/Scripts/python.exe -m pytest backend/tests` 做全量后端回归。
- 手工或测试断言套图与视频请求合并达到 20 次/分钟后，第 21 次生成请求返回 `429`，并且三个 `X-RateLimit-*` 头均为整数秒/整数值。
- 测试同一 Nonce 第二次请求被拒绝，且容量上限时新 Nonce 返回 `429` 而不是抛出未处理异常。
- 测试同一 IP 连续 5 次密码登录失败后，后续任意请求返回 `403`；封禁 TTL 为 1800 秒。
- 在非测试 Settings 下设置 `WEB_CONCURRENCY=2` 调用 `create_app()`，断言启动失败且错误信息指向内存限流单进程约束。
- 使用小容量 `rate_limit_max_size` 运行容量用例，确认不会因清理线程或多次 TestClient 构造泄漏线程。
- 运行 `git diff --check` 检查补丁格式。

## Open Questions

- [x] QUESTION - 仓库中不存在 `backend/app/api/v1/endpoints/workspace.py` 或 `/generate/suite`。是否确认按当前实际路由落地到 `backend/app/api/public.py` 的 `POST /api/v1/generation-jobs` 与 `POST /api/v1/video-jobs`，而不是新建旧路径兼容层？Decision: 是，按现有 `public.py` 路由落地。
- [x] QUESTION - “全局限流每分钟 20 次”是指套图与视频两个接口各自 20 次/分钟，还是两个接口合并共享 20 次/分钟？Decision: 两个接口合并共享 20 次/分钟。
- [x] QUESTION - Nonce 使用必选 `X-Request-Nonce` 后，现有前端改密与模拟支付必须同步生成并携带该头。是否同意在本次变更中包含这两个前端请求的最小适配？Decision: 是，允许同步最小前端改动。
- [x] QUESTION - 生产流量经过 `frontend/nginx.conf` 代理，但该配置未传递 `X-Forwarded-For`。是否允许同步补充 `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`，避免所有外部用户共享同一个封禁 IP？Decision: 是，允许补充 Nginx `X-Forwarded-For`。
