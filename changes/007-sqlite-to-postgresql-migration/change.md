# Change: SQLite to PostgreSQL Migration

## 变更标题
将 Listingo 的生产持久化数据库从 SQLite 迁移到 PostgreSQL，并提供可验证的一次性数据迁移与回滚路径。

## 变更背景 / 上下文
- 来源需求：用户要求分析项目结构，定位 SQLite 配置与 schema，制定 PostgreSQL 迁移的依赖、数据脚本和连接配置方案；根目录《SQLite替换为PostgreSQL.md》作为原始输入，但其中与环境现状不一致的建议需按当前代码修正。
- 关联模块：
  - 配置：`backend/app/config.py`
  - 连接与会话：`backend/app/database.py`
  - ORM schema：`backend/app/models.py`
  - 启动建库 / 运行时修复：`backend/app/main.py`
  - Alembic：`backend/alembic.ini`、`backend/migrations/env.py`、`backend/migrations/versions/`
  - 部署：`backend/Dockerfile`、`docker-compose.yml`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md`
- 当前事实：
  - `Settings.database_url` 使用 `LISTINGO_DATABASE_URL`，未设置时回落到 `data/listingo.sqlite3`；`backend/migrations/env.py` 已动态覆盖 `alembic.ini` 的 URL。
  - 运行时是同步 SQLAlchemy 2.0，不需要 `asyncpg` 或 AsyncSession。
  - ORM 共 31 张表，链路为 `dca93ecfbff1 -> 8b35f1d2e6ac -> c15a9e7d4f02 -> b7d2c6a9e8f1 -> 2a8f76b1d9c4 -> 3c4d5e6f7a8b -> 4d5e6f7a8b -> 5f6a7b8c9d0e`。
  - 对空 SQLite 执行当前迁移 head 后与 ORM 比对，发现缺少 3 个 `analytics_event` 索引和 5 个 `user_id` 外键；新 PostgreSQL 空库必须先用新 revision 对齐。
  - 当前业务库约 9.5 MB，31 张现行表均存在，另含旧 `sms_verification_code` 表 18 行；源库 `alembic_version` 停在 `dca93ecfbff1`，而应用 `create_all` 已补建后续表，因此禁止直接在源 SQLite 上执行 `upgrade head`。
  - 当前源数据有 2 条历史 `execution_log` 引用不存在的 `generation_job` / `generation_item`；这两个字段可为空，迁移时应仅将复制到目标库的失效引用置空并记录报告，保留日志行。

## 目标
- 业务事实唯一持久化到 PostgreSQL；迁移验证成功后，SQLite 在本地和生产环境均永久弃用，Redis 职责不变，文件资产仍在 `data/`。
- 使用 Alembic 管理 PostgreSQL schema，消除 ORM metadata 与迁移 head 的漂移。
- 提供幂等可审计的 SQLite 到 PostgreSQL 数据迁移脚本，包含迁移前检查、类型规范化、行数 / 摘要 / 外键校验和明确异常报告。
- Compose / 非容器配置均连接当前设备已安装的外部 PostgreSQL；账号密码只进入被 Git 忽略的 env 文件或 CI secret。
- 单元测试与集成测试也使用 PostgreSQL 独立临时库，不再保留 SQLite 测试路径。

## 非目标
- 不迁移到 AsyncSession，不引入 `asyncpg`。
- 不重构业务表、不把 `Text` JSON 字段改为 `JSONB`，避免与一次性切换混在一起。
- 不迁移上传图片、生成结果、导出 ZIP、`.secret_key` 或 Redis 数据。
- 不使用 `pgloader` 直接建目标 schema，避免绕过 Alembic 版本链和当前 schema 差异。

## 方案设计
### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/requirements.txt` | 修改 | 增加 `psycopg2-binary` 固定版本，作为同步 SQLAlchemy 的 PostgreSQL 驱动。 |
| `backend/app/config.py` | 修改 | 必须显式配置 `LISTINGO_DATABASE_URL`，只接受 PostgreSQL URL，并增加连接池参数。 |
| `backend/app/database.py` | 修改 | 移除 SQLite 分支；PostgreSQL 启用 pre-ping、pool recycle、pool size / max overflow 和 keepalive。 |
| `backend/app/main.py` | 修改 | 启动不再 `create_all` / 执行 SQLite 修复 SQL，改为校验数据库连通性与 Alembic head；testing 也使用 PostgreSQL 临时库。 |
| `backend/migrations/versions/NNNN_align_schema_for_postgresql.py` | 新增 | 补齐 `analytics_event` 3 个索引和 5 个 `user_id` 外键；downgrade 可恢复当前 head 形态。 |
| `backend/migrations/env.py` | 修改 | 保持 `Settings.resolved_database_url` 单一来源；为 PostgreSQL 显式启用 `compare_server_default` 与事务化迁移。 |
| `backend/alembic.ini` | 修改 | 将硬编码 SQLite URL 改为被 `env.py` 覆盖的空占位，避免误导。 |
| `backend/scripts/migrate_sqlite_to_postgres.py` | 新增 | 目标库只允许 Alembic head 且业务表为空；备份 SQLite、校验源数据、按 `Base.metadata.sorted_tables` 复制、规范化 `TIMESTAMPTZ` / Boolean / 字符串长度、处理白名单孤儿引用、输出 JSON 报告；支持 `--check-only` 与 `--verify-only`。 |
| `backend/tests/conftest.py`、`backend/tests/test_config.py`、新增迁移测试 | 修改 | 测试统一使用外部 PostgreSQL 的独立临时库；`LISTINGO_TEST_DATABASE_URL` 控制连接，测试内创建 / 销毁隔离数据库。 |
| `docker-compose.yml` | 修改 | 不新增内置 PostgreSQL 服务；移除 backend 对 SQLite 的强制覆盖，改为从 env 连接外部 PostgreSQL，并在启动前检查连通性。 |
| `TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` | 修改 | 同步数据库、依赖、环境变量、迁移和回滚说明。 |
| `.env.local` / `.env.production` | 部署配置 | 运行环境手工设置 `LISTINGO_DATABASE_URL`、PostgreSQL 密码和连接池参数；文件被忽略，不提交。 |

### 依赖与连接
1. 仅新增 `psycopg2-binary`，建议固定 `2.9.11`；生产 URL 形态为 `postgresql+psycopg2://listingo:<percent-encoded-password>@postgres:5432/listingo`。
2. `LISTINGO_DATABASE_URL` 保持唯一入口；不采用根目录输入文档中的 `DATABASE_URL` / `sync_database_url` 方案，也不提供 SQLite fallback。
3. 当前部署使用本机已安装的外部 PostgreSQL；连接凭据已由用户确认，真实值只写入 `.env.local` / `.env.production` / CI secret，不提交 Git。
4. 连接池默认建议 `pool_size=5`、`max_overflow=10`、`pool_recycle=1800`、`pool_pre_ping=True`，并开放环境变量便于多实例调优。

### Schema 与数据迁移
1. 空目标库顺序：
   1. 创建 UTF8 / UTC PostgreSQL 数据库和 `listingo` 应用账号。
   2. `LISTINGO_DATABASE_URL=<pg-url> .venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head`。
   3. 确认新 head、31 张表、索引和外键与 `Base.metadata` autogenerate diff 为空。
2. 源库处理：
   - 停止 backend 和 `BatchScheduler`，确认没有进程写 SQLite。
   - 用 SQLite backup API 或文件复制生成带时间戳备份，并记录 SHA256。
   - 不修改源库、不尝试修补源库 Alembic 版本；SQLite 只读复制。
3. 数据复制：
   - 按依赖顺序复制 ORM 31 张表；忽略 `alembic_version` 和旧 `sms_verification_code`。
   - `asset.product_category`、`asset.product_tags_json` 等 ORM 外历史列不复制。
   - SQLite naive datetime 按 UTC 转成 aware 值写入 `TIMESTAMPTZ`；Boolean 归一为 Python bool；`VARCHAR(n)` 先做长度校验。
   - 全表单一事务写入 PostgreSQL，失败即回滚，目标库不得处于半迁移状态。
   - 仅对确认的 `execution_log` 失效引用置空，并将原值与行 ID 写入迁移报告。
4. 验证：
   - 逐表比较行数。
   - 按主键顺序计算规范化后的行摘要，并比较全局 digest。
   - 对比 ORM 元数据、检查所有 PostgreSQL 外键、唯一约束和 `alembic_version`。
   - 抽查 Provider / Prompt / Workflow seed、用户、订阅、任务历史和运营日志 API。
   - 保持 `.secret_key` 不轮换，验证已加密 Provider API Key 与短信密钥可解密。
5. 切换：
   1. 停止旧 backend 和批量调度，确认 SQLite 停写并创建冻结备份。
   2. 初始化 / 升级空 PostgreSQL 到新 head。
   3. 在维护窗口内执行迁移脚本并通过 `--verify-only`。
   4. 为切换前 PostgreSQL 状态创建 `pg_dump` 快照。
   5. 在 `.env.production` 配置 PostgreSQL URL 后部署新版 backend，确认健康检查和关键 API。
   6. 保留 SQLite 备份与迁移报告仅作审计；监控 PostgreSQL 连接、锁和外键错误。

### 回滚
- 迁移验证成功并部署新版 backend 后，不得回滚到 SQLite；PostgreSQL 是唯一事实源。
- 目标库初始化或数据复制失败时丢弃 / 重建该 PostgreSQL 目标库；冻结的 SQLite 备份仅用于重新演练，不作为切换后的运行库。
- 若切换后发现问题，以 PostgreSQL 为事实源修复，或恢复切换前立即创建的 `pg_dump` 快照；不得反向写回旧 SQLite。
- Alembic 空库验证需同时执行 `upgrade head` 与 `downgrade base`，确保 schema revision 可逆；生产数据 downgrade 不作为回滚手段。

## 验收标准
- [ ] 空 PostgreSQL UTF8 数据库 `upgrade head` 后，Alembic autogenerate 对 ORM metadata 无差异，表数为 31。
- [ ] 当前 SQLite 备份能完整复制到测试 PostgreSQL；除报告列明的 2 条 `execution_log` 失效引用外，31 张表行数和规范化摘要一致。
- [ ] 目标库所有外键检查通过，旧 `sms_verification_code` 不存在，`alembic_version` 等于新 head。
- [ ] `backend/tests` 使用外部 PostgreSQL 临时测试库通过，测试结束清理临时库。
- [ ] `docker compose config` 校验通过，backend 在外部 PostgreSQL 连接检查通过后启动，健康检查返回 ok。
- [ ] 生产启动不再执行 `Base.metadata.create_all`，数据库缺失或版本落后时启动失败并给出明确错误。

## Open Questions
> 以下为待人工确认的问题。AI 不得自行猜测；必须回答后方可继续 coding。
- [x] Q1: SQLite 兼容边界是什么？ - Decision: 迁移成功后 SQLite 永久弃用，包括本地和生产；测试也统一使用 PostgreSQL 临时库，不保留 SQLite fallback、SQLite 测试配置或 SQLite 专用运行时 schema 修补。
- [x] Q2: PostgreSQL 运行形态和版本是什么？ - Decision: 使用当前设备已安装的外部托管 PostgreSQL，不新增 Compose PostgreSQL 服务；本地与生产均通过 `LISTINGO_DATABASE_URL` 连接外部实例，账号密码由 env 文件注入。
- [x] Q3: 是否接受迁移脚本对 2 条历史 `execution_log` 的失效 `job_id` / `item_id` 在 PostgreSQL 中置空并保留日志与原值报告？ - Decision: 接受；仅处理白名单内 2 条记录，迁移报告必须包含行 ID、字段和原值。
