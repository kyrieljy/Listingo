# 验证清单 - 优化现有安全态 Redis 使用

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] `config.py` 新增 7 项 Redis `LISTINGO_*` 配置（nonce_ttl / login_fail_window / login_block / sms_daily_window / sms_max_attempts / max_connections / health_check_interval）并通过字段校验（ge 约束）
- [x] `rate_limit.py` TTL / 阈值改读 Settings，函数形参仍可覆盖（保持向后兼容与可测）
- [x] `sms.py` 日限额窗口 / 最大尝试改读 Settings，DB `SmsConfig` 仍 per-phone 覆盖优先
- [x] 新增 `core/storage/keys.py` 集中键构造器，现存 Redis 键字面量已迁移
- [x] `docs/REDIS_KEYS.md` 键清单与命名约定产出
- [x] `redis.py` 支持 `max_connections` / `health_check_interval`，连接池上限生效
- [x] fail-closed 在限流 / Nonce / 封禁 / 短信四路径一致（统一抛 `StorageUnavailableError` → 全局 503）

## 测试
- [x] 单元测试通过（`test_redis_optimization.py` 7 项：settings 透传、键构造器、前缀隔离、连接池、sms 阈值）
- [x] 集成 / 端到端验证：受影响既有套件 `test_rate_limit.py` / `test_redis_storage.py` / `test_sms_phone.py` / `test_config.py` 共 43 项全部通过；Redis 不可用 → 安全中间件返回 503（既有 `test_storage_unavailable_returns_503` 覆盖）

## 规范检查
- [x] 符合 `.coderules`（未引入新场景、未破坏现有功能）
- [x] 更新 `docs/CONTEXT_SUMMARY.md` 索引纳入 `docs/REDIS_KEYS.md`

## 回归
- [x] 未破坏现有功能（限流 / Nonce / 封禁 / 短信既有行为不变；默认 60 / 1800 行为保留，既有测试全绿）
- [x] 已满足项回归测试通过（`set nx ex` 原子性、`_key` 前缀隔离、sliding-window WATCH 由 `test_redis_storage.py` 既有用例覆盖）
