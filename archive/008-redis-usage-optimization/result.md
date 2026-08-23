# Result — 优化现有安全态 Redis 使用

## 测试执行

### 1. 新增用例（本变更）
- 命令：`.venv/Scripts/python.exe -m pytest backend/tests/test_redis_optimization.py -q`
- 结果：**7 passed**
- 覆盖：`test_settings_propagate_to_rate_limiter`（settings 透传 nonce/block TTL 且保留默认 60/1800）、`test_defaults_preserve_historical_behavior`、`test_key_builders_match_convention`、`test_redis_key_prefix_isolation`、`test_redis_storage_builds_connection_pool_with_max_connections`、`test_sms_reserve_send_quota_uses_configurable_daily_window`、`test_verify_sms_code_uses_configurable_max_attempts_and_keys`

### 2. 受影响既有套件（回归）
- 命令（Windows 沙箱需指定本地临时根，见下方「环境备注」）：
  `TEMP=<proj>/.pytest_tmp TMP=<proj>/.pytest_tmp .venv/Scripts/python.exe -m pytest backend/tests/test_rate_limit.py backend/tests/test_redis_storage.py backend/tests/test_sms_phone.py backend/tests/test_config.py -q --basetemp=<proj>/.pytest_tmp -p no:cacheprovider`
- 结果：**43 passed**
- 说明：初跑出现 21 个 ERROR，经排查为 `tmp_path` fixture 在默认 `C:\Users\26904\AppData\Local\Temp\pytest-of-26904` 触发 `PermissionError: 拒绝访问`，与代码无关（22 个不依赖 `tmp_path` 的纯单元测试全部通过）。指定项目内 `--basetemp` 后全部转绿，证实无回归。

## 验证记录（对照 checklists）

| 验收项 | 证据 |
|---|---|
| config 7 项 LISTINGO_* 配置 | `config.py` 新增字段均带 `Field(ge=...)` 校验；`test_settings_propagate_to_rate_limiter` 断言透传 |
| rate_limit / sms TTL·阈值改读 Settings | `create_rate_limiter` 注入 3 个 TTL 字段；`sms._reserve_send_quota` / `verify_sms_code` 读 `settings.redis_sms_*`；默认形参保持兼容 |
| 集中键构造器 keys.py | `backend/app/core/storage/keys.py` 8 个构造器；`rate_limit.py` / `sms.py` 散落 f-string 已迁移；`test_key_builders_match_convention` 断言 |
| REDIS_KEYS.md 文档 | 新建 `docs/REDIS_KEYS.md`（命名约定 + 键清单 + 运维约定 + 非目标） |
| redis.py 连接池显式配置 | `RedisStorage.__init__` 新增 `max_connections` / `health_check_interval_seconds`，无 client 时构建 `ConnectionPool`；`test_redis_storage_builds_connection_pool_with_max_connections` 断言 `max_connections==7` |
| fail-closed 四路径一致 | 限流 / Nonce / 封禁 / 短信统一抛 `StorageUnavailableError`；`ip_block.py` 与 `main.py` 全局 handler 转 503；既有 `test_storage_unavailable_returns_503` 覆盖 |
| CONTEXT_SUMMARY 索引 | 权威文档映射表新增 `docs/REDIS_KEYS.md` 一行 |
| 未破坏现有功能 | 受影响既有套件 43 项全绿；默认 nonce=60 / block=1800 行为保留（`test_login_failures_block_ip_for_1800_seconds` 等仍通过） |

## 阻塞与问题
- 无代码级阻塞或 `[FAIL]`。
- 环境备注：本 Windows 沙箱默认 pytest 临时目录 `C:\Users\26904\AppData\Local\Temp\pytest-of-26904` 触发权限拒绝（`PermissionError: 拒绝访问`），导致依赖 `tmp_path` 的用例 setup 失败。已通过 `--basetemp` 指向项目内可写目录绕过，非代码缺陷。

## 采用的决策（原 Open Questions，按用户「执行方案」授权 + 变更草案推荐默认决议）
- Q1 服务端加固：新增 `--maxmemory-policy volatile-lru`；持久化沿用 `docker-compose.yml` 既有 `appendonly yes`（AOF），缓解重启计数器清空窗口。
- Q2 连接池默认：`max_connections=50`、`health_check_interval_seconds=30`，均可用 env 覆盖。
- Q3 sms 优先级：env 全局默认，DB `SmsConfig` per-phone 覆盖优先（已落地）。
- Q4 索引：`docs/REDIS_KEYS.md` 已建并纳入 `CONTEXT_SUMMARY` 索引。

## 结论
- checklists 全部 `[x]`，无 `[FAIL]`、无遗留 `[ ]`。
- 未引入 `redis-analysis.md` 第二节新场景，未破坏现有功能，符合 `.coderules` 与架构约束。
- **可以执行 `archive` 完成归档。**
