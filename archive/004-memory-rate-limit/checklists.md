# Checklists

## Implementation

- [x] `backend/app/core/storage/base.py` 定义 `RateLimitStorage` 抽象接口、原子 `set_if_absent()` 和计数结果对象。
- [x] `backend/app/core/storage/memory.py` 实现线程安全、TTL、30 秒后台清理、LRU/最旧优先淘汰和 10000 条硬上限。
- [x] `MemoryStorage` 类文档字符串与启动日志包含单进程部署警告原文；非测试环境 `WEB_CONCURRENCY > 1` 时启动失败。
- [x] Nonce TTL 固定为 60 秒，容量满时新 Nonce 被拒绝并返回 `429`，既有 Nonce 不因容量压力被淘汰。
- [x] `backend/app/core/rate_limit.py` 提供三个需求指定 bool 函数，并为路由提供可生成准确响应头的原子结果接口。
- [x] `backend/app/middleware/ip_block.py` 在路由前检查封禁 IP，命中返回 `403`，且不影响 CORS 响应头。
- [x] `backend/app/config.py` 增加 `storage_backend="memory"`、容量与清理配置，未支持后端启动即失败。
- [x] `backend/app/main.py` 挂载 IP Block 中间件，管理内存存储生命周期，并输出红色内存模式警告。
- [x] `backend/app/api/public.py` 的套图与视频创建入口在业务校验前执行共享每分钟限流，两接口合并后的第 21 次返回 `429` 和完整 `X-RateLimit-*` 头。
- [x] `backend/app/api/auth.py` 的密码登录执行限流、失败计数和成功清零；失败 5 次封禁 1800 秒，并保留图形验证码缺失风险注释。
- [x] 改密与模拟支付接入一次性 Nonce；两个现有前端调用均生成并发送唯一 `X-Request-Nonce`。
- [x] `frontend/nginx.conf` 透传 `X-Forwarded-For`，生产代理后可按真实客户端 IP 隔离限流与封禁。
- [x] `TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md` 记录内存后端、单 Worker 单实例约束、容量配置和 `WEB_CONCURRENCY` 熔断。

## Verification

- [x] 新增存储测试覆盖并发 `incr()`、原子 `set_if_absent()`、TTL 过期、30 秒清理逻辑、LRU 淘汰和 `max_size` 拒绝。
- [x] 新增限流测试断言套图与视频请求合并后第 20 次允许、第 21 次返回 `429`，且 `Limit/Remaining/Reset` 响应头准确。
- [x] 新增 Nonce 测试断言首次接受、重复拒绝、缺失或格式错误返回 `400`、容量满返回 `429`。
- [x] 新增登录测试断言同一 IP 第 5 次失败后写封禁，后续请求返回 `403`，成功登录会清理失败计数。
- [x] 新增应用装配测试断言非测试环境 `WEB_CONCURRENCY=2` 启动失败，测试环境不受影响。
- [x] 断言每次 TestClient 生命周期结束后存储清理线程停止，重复创建应用不会累积线程。
- [x] 运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_rate_limit.py backend/tests/test_config.py backend/tests/test_security_and_seed.py backend/tests/test_sms_phone.py`。
- [x] 运行 `.venv/Scripts/python.exe -m pytest backend/tests`。
- [x] 运行 `git diff --check`。

## Regression

- [x] 现有注册、短信登录、密码登录、管理员二验和登出行为保持不变。
- [x] 改密、订单创建与模拟支付在携带有效 Nonce 时保持现有响应契约。
- [x] 套图与视频生成在未触发限流时仍按原顺序完成资产校验、安全审查、额度扣减和任务创建。
- [x] 健康检查、静态文件、CORS 预检和未封禁 IP 的既有请求不受中间件影响。
- [x] 后端测试套件不依赖真实 Redis、外部 Provider 或等待真实 30 秒/60 秒时钟。
