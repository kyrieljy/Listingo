# Listingo 技术栈

## 运行时与框架

| 层级 | 技术 | 版本 | 用途 |
|---|---|---:|---|
| 前端运行时 | Node.js | 24.13.x | 本地开发与构建 |
| 前端框架 | Vue | 3.5.40 | 单页应用与组合式 API |
| 构建工具 | Vite | 8.1.5 | 开发服务器与生产构建 |
| 类型系统 | TypeScript | 7.0.2 | 前端静态类型 |
| UI | Ant Design Vue | 4.2.6 | 表单、弹窗、表格、反馈 |
| 图标 | `@ant-design/icons-vue` | 7.0.1 | 工作台与后台图标 |
| 图表 | ECharts / Vue ECharts | 6.1.0 / 8.1.0 | 运营监控和业务指标 |
| 工作流画布 | Vue Flow | 1.48.2 | Workflow 节点、连线、视口 |
| 状态管理 | Pinia | 4.0.2 | 前台任务、账号与后台状态 |
| 路由 | Vue Router | 5.2.0 | `/app`、`/admin` 与工作台阶段 |
| 前端测试 | Vitest | 4.1.10 | 单元与组件测试 |
| 后端运行时 | Python | 3.10.9 | API 与任务执行器 |
| Web 框架 | FastAPI | 0.139.2 | REST API 与 OpenAPI |
| 数据校验 | Pydantic | 2.13.4 | 请求、Prompt、任务契约 |
| ORM | SQLAlchemy | 2.0.51 | 同步 PostgreSQL 持久化 |
| PostgreSQL 驱动 | psycopg2-binary | 2.9.11 | SQLAlchemy 同步连接 |
| 迁移 | Alembic | 1.18.5 | 数据库版本管理 |
| HTTP 客户端 | HTTPX | 0.28.1 | LLM、图片、视频、短信模型调用 |
| 临时状态存储 | Redis / redis-py | 7.4 / 5.2.1 | API 限流、Nonce、登录封禁与短信验证码状态 |
| 加密 | Cryptography | 49.0.0 | API Key 本机加密 |
| 密码哈希 | argon2-cffi | 21.3.0 | 用户密码哈希 |
| 图片处理 | Pillow | 12.3.0 | 上传校验、图片写盘、Dryrun 资产、水印 |
| OCR / CV | NumPy / OpenCV / PaddleOCR / RapidOCR | 1.26.4 / 4.10.0.84 / 3.7.0 / 1.4.4 | OCR 改字、文本框检测与图像预处理 |
| 后端测试 | Pytest | 9.1.1 | API、服务、状态机测试 |
| Redis 测试替身 | FakeRedis | 2.26.2 | 覆盖 Redis 存储适配器的原子操作与 TTL |

## 架构边界

- 前端和后端独立开发，但作为一个本机/私有化演示单体交付。
- 外部 PostgreSQL 17 是业务事实的唯一持久化源；SQLite 已在迁移后弃用。Redis 是限流、Nonce、封禁与验证码等临时安全状态的共享存储；上传、结果、导出文件、密钥和数据库凭据不提交。
- 后端使用同步 SQLAlchemy 会话和进程内异步任务执行；单任务图片并发默认 4，可通过 `LISTINGO_MAX_JOB_CONCURRENCY` 在 1-8 间调整。
- 批量与普通任务共享进程级 Provider 并发限制，默认 `LISTINGO_MAX_PROVIDER_CONCURRENCY=4`。
- API 限流、Nonce 防重放、登录 IP 封禁、短信验证码哈希、验证码尝试次数、发送冷却与滚动 24 小时次数默认使用 Redis；套图与视频创建接口共享 20 次/分钟，Nonce TTL 固定 60 秒，同一 IP 60 秒内 5 次密码登录失败封禁 30 分钟，验证码错误 5 次后拒绝。
- Redis 通过 `LISTINGO_REDIS_URL` 连接，支持 Compose 内置 Redis 或独立部署实例；显式 `LISTINGO_STORAGE_BACKEND=memory` 仅保留为本地/测试兼容后端，并维持单 Worker 熔断。
- 不引入 Celery、对象存储、真实支付网关、SSO 或 Compose 内置业务数据库；业务 PostgreSQL 必须外部托管并由 Alembic 管理版本。
- Prompt、Workflow 和 Provider 都版本化/配置化；历史任务固定引用创建时的版本。
- 后台保存的 API Key、短信凭据、Provider 启用状态和 runtime settings 属于服务器本地运行态，不通过 Git 同步。

## Provider 与路由

外部模型通过 Provider 适配器隔离。源码 Provider 目录当前由 3 个 LLM 预设加 44 个图片/视频中转模型组成，共 47 个预设。

- `openai_chat`：Doubao Seed 2.0 Mini、Qwen-3.6、GPT-5.4-Mini，用于商品视觉事实、核心规划、帮写、编辑转写、内容安全和视频分镜。
- 图片生成/edit adapters：按中转站映射 GPT Image 2、Nano Banana Pro、Nano Banana 2 的 generation/edit API，覆盖 HelloBabyGo、fal.ai、Runware、OpenRouter、Atlas Cloud、Replicate、WaveSpeedAI、Kie.ai、CometAPI、API Models。
- 视频 adapters：按中转站映射 Seedance 2.0 任务提交、轮询和 mp4 下载，默认主线为 HelloBabyGo Seedance 2.0。

Provider route roles 由 `backend/app/services/provider_routing.py` 和 `backend/app/services/provider_catalog.py` 定义。当前 route key 为 `llm`、`suite_fidelity`、`suite_layout`、`aplus_detail`、`aplus_mobile`、`image_edit`、`video`。Route slot 为 `primary`、`backup1`、`backup2`、`backup3`、`backup4`；旧 `fallback` 仅作为 `backup1` 兼容别名。

## Prompt 资产

当前运行时 Prompt 资产共 8 类：

- 核心：`ecommerce-meta`、`aplus-meta`。
- 辅助：`product-vision`、`copywriting-assist`、`edit-rewrite`、`image-text-edit`、`content-safety-review`、`ecommerce-video-meta-15s`。
- `aplus-meta` 的源码资产为 `aplus_meta_prompt_0729.md`。
- `image-quality-review` 是旧数据库可能残留的历史记录，当前源码不再注册为运行链路依赖，也不再由 Workflow 调用。

## 本地数据路径

| 路径 | 内容 |
|---|---|
| `data/backups/listingo-*.sqlite3` | 迁移前冻结备份与迁移报告，仅审计保留，不再作为运行库 |
| `data/uploads/` | 上传商品图，不提交实际文件 |
| `data/results/` | 生成图片、A+、视频结果，不提交实际文件 |
| `data/exports/` | 临时 ZIP / 长图导出，不提交实际文件 |
| `data/.secret_key` | 本机 Fernet 密钥，不提交 |

## 环境变量

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `LISTINGO_ENV_FILE` | `.env.local` | 选择后端加载的环境文件；生产设为 `.env.production` |
| `LISTINGO_PORT` | `8000` | 后端监听端口，同时驱动 Compose、Vite 开发代理与 Nginx 反向代理 |
| `LISTINGO_DATABASE_URL` | 必填 | 外部 PostgreSQL URL，仅支持 `postgresql://` / `postgresql+psycopg2://` |
| `LISTINGO_DATABASE_POOL_SIZE` | `5` | PostgreSQL 常驻连接数 |
| `LISTINGO_DATABASE_MAX_OVERFLOW` | `10` | PostgreSQL 突发溢出连接数 |
| `LISTINGO_DATABASE_POOL_RECYCLE_SECONDS` | `1800` | PostgreSQL 空闲连接回收时间 |
| `LISTINGO_DATA_DIR` | `data/` | 上传、结果、导出和密钥目录 |
| `LISTINGO_TESTING` | `false` | 测试模式；生产必须关闭 |
| `LISTINGO_GLOBAL_DRY_RUN` | `true` | 全局默认 Dryrun |
| `LISTINGO_PUBLIC_ASSET_BASE_URL` | 空 | Live 参考图公网地址，不能是 localhost/127.0.0.1 |
| `LISTINGO_CORS_ORIGINS` | 本地 5173 白名单 | 后端 CORS 白名单，逗号分隔 |
| `LISTINGO_MAX_UPLOAD_BYTES` | `15728640` | 单文件上传上限 |
| `LISTINGO_SESSION_TTL_SECONDS` | `28800` | 会话有效期 |
| `LISTINGO_REFRESH_TTL_SECONDS` | `2592000` | 刷新会话有效期 |
| `LISTINGO_COOKIE_SECURE` | `false` | Cookie Secure 标志；生产 HTTPS 为 `true` |
| `LISTINGO_DEBUG_SMS_CODE` | 空 | 调试短信固定验证码；为空时生成随机码 |
| `LISTINGO_SMS_TIMEOUT_SECONDS` | `15` | 阿里云短信 HTTP 超时 |
| `LISTINGO_STORAGE_BACKEND` | `redis` | 临时状态存储后端；生产默认 Redis，`memory` 仅用于显式本地/测试兼容 |
| `LISTINGO_REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis 地址；Compose 后端使用 `redis://redis:6379/0`，独立部署时替换 |
| `LISTINGO_REDIS_KEY_PREFIX` | `listingo` | 多环境共用 Redis 时的 key 前缀 |
| `LISTINGO_REDIS_CONNECT_TIMEOUT_SECONDS` | `2` | Redis 连接超时 |
| `LISTINGO_REDIS_SOCKET_TIMEOUT_SECONDS` | `2` | Redis 命令超时 |
| `LISTINGO_REDIS_STARTUP_TIMEOUT_SECONDS` | `5` | 后端启动时等待 Redis `PING` 的总超时 |
| `LISTINGO_RATE_LIMIT_MAX_SIZE` | `10000` | 仅 memory 后端使用的记录硬上限 |
| `LISTINGO_RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | `30` | 仅 memory 后端使用的后台清理间隔 |
| `LISTINGO_MAX_JOB_CONCURRENCY` | `4` | 单任务图片并发，范围 1-8 |
| `LISTINGO_MAX_BATCH_TASKS` | `100` | 单批次 item 上限 |
| `LISTINGO_MAX_BATCH_ITEM_ASSETS` | `6` | 单个批量 item 图片上限 |
| `LISTINGO_MAX_ACTIVE_BATCH_ITEMS` | `1` | 批量调度活跃 item 上限 |
| `LISTINGO_MAX_PROVIDER_CONCURRENCY` | `4` | 全局 Provider 活跃调用上限 |
| `LISTINGO_OCR_ENGINE` | `rapidocr` | OCR engine，可选 `paddleocr`、`rapidocr`、`auto` |
| `LISTINGO_OCR_PRIMARY_MODEL` | `PP-OCRv5` | OCR 主模型 |
| `LISTINGO_OCR_FALLBACK_MODEL` | `PP-OCRv6` | OCR 备模型 |
| `LISTINGO_OCR_DEVICE` | `cpu` | OCR 设备 |
| `LISTINGO_OCR_TEXT_SCORE_THRESHOLD` | `0.62` | OCR 文本识别阈值 |
| `LISTINGO_OCR_BOX_SCORE_THRESHOLD` | `0.6` | OCR 文本框阈值 |
| `LISTINGO_OCR_SHORT_TEXT_SCORE_THRESHOLD` | `0.86` | OCR 短文本阈值 |
| `LISTINGO_OCR_MIN_BOX_WIDTH` | `5` | OCR 最小文本框宽度 |
| `LISTINGO_OCR_MIN_BOX_HEIGHT` | `5` | OCR 最小文本框高度 |
| `LISTINGO_OCR_MIN_BOX_AREA` | `40` | OCR 最小文本框面积 |
| `LISTINGO_OCR_FILTER_ISOLATED_CJK` | `true` | 是否过滤孤立 CJK 字符 |
| `LISTINGO_OCR_FILTER_WATERMARK_TEXT` | `true` | 是否过滤疑似水印文本 |
| `LISTINGO_OCR_USE_ENHANCED_VARIANTS` | `false` | 是否启用 OCR 增强变体 |

`.env.local` 与 `.env.production` 已逐项标注含义和使用位置；两者被 Git 忽略，需在每个部署环境保留。非 Docker 后端默认加载 `.env.local`，生产启动前设置 `LISTINGO_ENV_FILE=.env.production`。Compose 本地显式使用 `docker compose --env-file .env.local`，生产使用 `docker compose --env-file .env.production`。真实环境变量优先级高于 env 文件。`.env.production` 内的 `your-domain.com` 是必须替换的占位域名。

阿里云短信 `RegionId` 优先读取后台短信配置（PostgreSQL），未配置时由 `backend/app/services/sms.py` 使用 `cn-hangzhou` 兜底；Provider API Key 与 base URL 也继续由后台数据库配置管理，不进入 env 文件。

## Batch Runtime

- Batch hosting stays inside the existing FastAPI + PostgreSQL runtime. It uses a single-process `BatchScheduler` started from application lifespan outside test mode; tests drive it with explicit ticks.
- Redis is used only for temporary security state. No Celery, object storage, frontend Provider-key exposure, or public production auth gateway is introduced.
- `GET /api/v1/workspace-config` is the public source for upload and batch limits, including max batch tasks and max per-item assets.
- `ProviderConcurrencyLimiter` is process-level and shared by ordinary generation jobs, A+ generation jobs, child edits, OCR text edits, and batch jobs.
- Asynchronous Provider tasks are persisted through `provider_task_id` on suite, A+ and video items so restart recovery can poll/download existing Provider work before submitting new paid work.

## 部署更新

Docker Compose 镜像会在 `docker compose build` 时重新安装 `backend/requirements.txt`，因此 requirements 变化需要 rebuild 后端镜像。业务 PostgreSQL 不由 Compose 创建；容器内连接宿主机实例时使用 `host.docker.internal`（或对应云托管内网地址），非容器部署可使用 `localhost`。

首次从旧 SQLite 切换时，先停止写入并冻结旧库，再在空 PostgreSQL 目标库执行：

```bash
python -m pip install -r backend/requirements.txt
python -m alembic -c backend/alembic.ini upgrade head
python backend/scripts/migrate_sqlite_to_postgres.py
python backend/scripts/migrate_sqlite_to_postgres.py --verify-only
pg_dump --format=custom --file=data/backups/listingo-postgres-switch.dump <target-db>
```

迁移报告记录源库 SHA256、备份 SHA256、逐表行数与 digest、白名单修正和脱敏目标 URL。切换后 SQLite 永久弃用，不作为回滚目标；恢复只使用切换前 PostgreSQL `pg_dump` 快照。

常规部署更新执行：

```bash
python -m alembic -c backend/alembic.ini upgrade head
```

```bash
python -m pip install -r backend/requirements.txt
python -m alembic -c backend/alembic.ini upgrade head
```

前端依赖变化需要在服务器执行 `npm install` 后重新 `npm run build`，再 reload Nginx 或重建前端镜像。

生产首次部署前，先替换 `.env.production` 中的 `your-domain.com`，并确认 `LISTINGO_COOKIE_SECURE=true`、`LISTINGO_GLOBAL_DRY_RUN` 与短信配置符合目标环境，然后执行：

Docker Compose 会同时启动 Redis 7.4（AOF 持久化、健康检查和 `redis-data` 卷），后端通过 `LISTINGO_REDIS_URL` 连接；独立部署时替换该 URL 即可，不需要修改业务代码。Redis 后端允许多 Worker / 多实例共享限流和封禁状态；显式 memory 后端仍要求 `WEB_CONCURRENCY` 未设置或等于 1。前端 Nginx 会透传 `X-Forwarded-For`，用于按真实客户端 IP 隔离限流与封禁。

```bash
docker compose --env-file .env.production up -d --build
```
