# 验证清单 - SQLite to PostgreSQL Migration

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] `backend/requirements.txt` 安装后仅新增同步 `psycopg2-binary` 依赖，未引入 `asyncpg`。
- [x] `LISTINGO_DATABASE_URL` 只接受 `postgresql://` / `postgresql+psycopg2://`，未配置或 SQLite URL 被 Settings 拒绝。
- [x] PostgreSQL 引擎启用 pre-ping、pool recycle、pool size / max overflow 和 keepalive；代码中不存在 SQLite fallback。
- [x] 启动不再 `create_all` 或执行 SQLite 专用 `ensure_runtime_schema`，并能拒绝非最新 Alembic head。
- [x] 新 schema alignment revision 在空 PostgreSQL 上补齐 3 个索引、5 个外键，downgrade 可执行。
- [x] 迁移脚本拒绝非空目标库、非 head 目标库、未备份源库和未知数据质量错误。
- [x] 迁移脚本按 ORM 依赖顺序复制 31 张表，排除 `alembic_version` 与 `sms_verification_code`。
- [x] 仅 2 条确认的 `execution_log` 失效引用被置空，原值和行 ID 出现在 JSON 迁移报告。
- [x] 逐表行数、规范化行摘要、外键检查、约束检查和 Alembic head 校验全部通过。
- [x] 迁移后 Provider API Key / 短信密钥仍能用原 `.secret_key` 解密，文件资产路径不需要改写。

## 测试
- [x] 新增 Settings URL / 连接池配置测试。
- [x] 新增迁移脚本预处理、类型规范化、孤儿引用白名单和报告生成测试。
- [x] `.venv/Scripts/python.exe -m pytest backend/tests` 使用外部 PostgreSQL 临时测试库通过。
- [x] PostgreSQL schema 与迁移集成测试通过，测试结束清理临时库。
- [x] 使用当前 SQLite 备份执行一次演练迁移并运行健康检查、登录、任务历史、Provider、Prompt、Workflow、订阅和运营日志冒烟。
- [FAIL] `docker compose config` 通过；Compose 后端在连接并校验外部 PostgreSQL 后可启动。

## 规范检查
- [x] 符合 `.coderules`，未混入无关重构。
- [x] 已同步 `TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md` 的数据库、依赖、环境变量、部署和回滚说明。
- [x] 迁移演练中的备份路径、SHA256、行数、digest 和异常处理记录已保留，未提交真实密码或业务数据。
