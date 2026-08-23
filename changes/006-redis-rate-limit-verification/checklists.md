# 验证清单 - redis rate limit verification

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] `backend/requirements.txt` 固定 Redis 客户端与 Fake Redis 测试依赖，并完成本地依赖安装。
- [FAIL] `docker-compose.yml` 新增 Redis 7.4 服务、AOF、数据卷、健康检查，并通过 `docker compose config` 校验。
- [x] `.env.local` 与 `.env.production` 显式配置 `LISTINGO_STORAGE_BACKEND=redis`、`LISTINGO_REDIS_URL` 与 `LISTINGO_REDIS_KEY_PREFIX`。
- [x] `Settings` 支持 Redis URL、key 前缀和连接配置；Redis 后端缺少必要配置时给出可定位错误。
- [x] 应用 lifespan 启动时有限重试执行 Redis `PING`，关闭时释放连接；连接失败不回落内存。
- [x] Redis 模式允许 `WEB_CONCURRENCY > 1`；仅 memory 模式保留单 Worker 熔断和警告。
- [x] 套图与视频创建在 Redis 后端下继续共享 20 次/分钟，第 21 次返回 `429` 和完整 `X-RateLimit-*` 头。
- [x] 同一 Nonce 首次请求成功、并发重复只成功一次、普通重复返回 `409`；TTL 为 60 秒。
- [x] 同 IP 60 秒内 5 次密码登录失败写入 Redis 封禁，后续请求返回 `403`，封禁 TTL 为 1800 秒；成功登录清理失败计数。
- [x] Redis 中不保存短信验证码明文，只保存 `phone + purpose + code` 的 SHA-256 哈希并设置验证码 TTL。
- [x] 短信发送冷却与滚动 24 小时次数由 Redis 原子控制；Provider 发送失败不消耗冷却或每日额度。
- [x] 管理员短信二验 bypass 只跳过冷却与每日次数，验证码与尝试次数仍写入 Redis。
- [x] 验证码错误尝试计入 Redis；第 5 次错误后拒绝，正确验证码一次性消费且不能重复使用。
- [x] 重新发送验证码会覆盖旧哈希并重置尝试次数；验证码过期后不可校验。
- [x] 发送或校验短信验证码不再读写 `SmsVerificationCode`，SQLite 中不再新增验证码记录。
- [x] 新增 Alembic 迁移删除 `sms_verification_code` 表及索引，当前迁移链保持单头。
- [x] `TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md` 同步 Redis 后端、环境变量、key 语义、扩容与部署说明。

## 测试
- [x] 新增 Redis 适配器单元测试：TTL、`incr` 原子性、`set_if_absent`、`get/delete/expire`、并发 Nonce、连接关闭与错误转换。
- [x] 新增或更新限流 API 测试：共享窗口、登录窗口、Nonce 状态、失败封禁、CORS 403/429 响应与 Redis 不可用时的 `503`。
- [x] 新增或更新短信测试：冷却、滚动 24 小时上限、管理员 bypass、尝试 5 次上限、一次性消费、重发重置、TTL 过期与 SQLite 无新增行。
- [x] 运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_redis_storage.py backend/tests/test_rate_limit.py backend/tests/test_sms_phone.py`。
- [x] 运行 `.venv/Scripts/python.exe -m pytest backend/tests` 全量回归。
- [x] 运行 `.venv/Scripts/python.exe -m alembic -c backend/alembic.ini heads`，确认单头。
- [FAIL] 运行 `docker compose config` 校验服务与环境变量注入。
- [FAIL] 如本机 Docker 可用，运行 `docker compose up -d redis` 并确认健康状态为 healthy；不可用时在 result.md 记录环境限制。
- [x] 运行 `git diff --check`。

## 规范检查
- [x] 符合 `.coderules`：修改逻辑有测试，文档索引同步，未回退用户已有改动。
- [x] 生产路径没有隐藏内存限流回落；Memory 只保留为显式测试/本地兼容后端。
- [x] Redis key 均有统一前缀和 TTL，没有无过期计数或封禁 key。
- [x] 环境文件只新增配置，不提交密钥或本机运行数据。
- [x] 部署说明包含镜像 rebuild、依赖安装、Redis URL 替换与 Alembic 迁移提醒。
