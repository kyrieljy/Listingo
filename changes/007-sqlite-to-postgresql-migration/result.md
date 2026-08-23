# Result: SQLite to PostgreSQL Migration

## Implementation Summary

- 后端改为 PostgreSQL-only：`LISTINGO_DATABASE_URL` 必填且只接受 PostgreSQL URL；移除 SQLite fallback、启动时 `create_all` 和 SQLite 专用 schema 修补。
- `build_engine` 增加 pre-ping、连接池、连接回收和 PostgreSQL keepalive；新增 `psycopg2-binary==2.9.11`，未引入 `asyncpg`。
- 新增 Alembic revision `a7c4e9f21b68`，补齐 3 个 `analytics_event` 索引和 5 个 `user_id` 外键；启动时校验 dialect 与 Alembic head。
- 新增 `backend/scripts/migrate_sqlite_to_postgres.py`，支持 `--check-only` / `--verify-only`、冻结备份、ORM 顺序复制、类型/长度检查、白名单孤儿处理、逐表 digest 与 JSON 报告。
- 测试改为会话级外部 PostgreSQL 临时库，覆盖 Alembic upgrade / downgrade / upgrade 和用例隔离；同步 Compose、env、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md`。
- 修复用户复现的 `uvicorn --reload` 启动错误：Alembic `ScriptDirectory` 导入改为 `alembic.script`，配置本机 PostgreSQL URL，初始化 `listingo` 并迁移到 head。复现结果为 `Application startup complete`。

## Commands and Checks

```powershell
.\.venv\Scripts\python.exe -m pip install psycopg2-binary==2.9.11
```

结果：成功安装 `psycopg2-binary 2.9.11`。

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

结果：空 `listingo` PostgreSQL 库升级到 `a7c4e9f21b68`。

```powershell
.\.venv\Scripts\python.exe backend/scripts/migrate_sqlite_to_postgres.py --check-only --report data/backups/check-report.json
.\.venv\Scripts\python.exe backend/scripts/migrate_sqlite_to_postgres.py --report data/backups/migration-report.json
.\.venv\Scripts\python.exe backend/scripts/migrate_sqlite_to_postgres.py --verify-only --report data/backups/verification-report.json
```

结果：三者均 `passed`；31 张表、10639 行、逐表 digest 一致。

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

结果：`Application startup complete`；`GET /api/v1/health` 返回 `{"status":"ok","mode":"dryrun-default"}`，`GET /api/v1/workspace-config` 返回 200。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

结果：`208 passed, 90 warnings`。

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend
git diff --check
```

结果：均通过。

```powershell
docker compose --env-file .env.local config --quiet
```

结果：失败；当前 Windows 主机没有 `docker` 可执行文件。

## Evidence

- 迁移前检查：[check-report.json](E:/AI-project/Listingo/data/backups/check-report.json)
- 迁移报告：[migration-report.json](E:/AI-project/Listingo/data/backups/migration-report.json)
- 迁移后验证：[verification-report.json](E:/AI-project/Listingo/data/backups/verification-report.json)
- 源库 SHA256：`5409f3f3a40a5c4a8542f51e9496ff60aa1a4b5d3429de03a0cb2d0452949fc2`
- SQLite 冻结备份：`E:\AI-project\Listingo\data\backups\listingo-20260823T023505Z.sqlite3`
- 备份 SHA256：`02ee96b2587eef2908822ba5423aff0c7412af224260080bc72e9cd3c6de7f4d`
- PostgreSQL 切换快照：`E:\AI-project\Listingo\data\backups\listingo-postgres-switch.dump`（733946 bytes）
- 4 个白名单字段置空，对应 2 条历史 `execution_log`；原值均在迁移报告中。
- 迁移后 API 冒烟：health、Provider、Prompt、Workflow、套餐、运营日志、套图历史、视频历史、A+ 历史、批量历史均返回 200。
- 迁移后使用原 `.secret_key` 解密：15 个 Provider API Key、1 个短信密钥均通过。
- 当前 PostgreSQL 实例为 17.11；用户描述的 `admin/admin` 不是可用角色，实际验证角色为 `postgres/admin`，凭据只保留在被 Git 忽略的 env 文件。

## Failures and Blockers

- [FAIL] Docker Compose 配置验证未执行成功：`docker` 命令不存在。需要在装有 Docker 的主机运行 `docker compose --env-file .env.production config --quiet`，再启动后端验证外部 PostgreSQL 连接。
- 无其他未解决失败。
