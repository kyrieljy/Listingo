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
| ORM | SQLAlchemy | 2.0.51 | SQLite 持久化 |
| 迁移 | Alembic | 1.18.5 | 数据库版本管理 |
| HTTP 客户端 | HTTPX | 0.28.1 | LLM、图片、视频、短信模型调用 |
| 加密 | Cryptography | 49.0.0 | API Key 本机加密 |
| 密码哈希 | argon2-cffi | 21.3.0 | 用户密码哈希 |
| 图片处理 | Pillow | 12.3.0 | 上传校验、图片写盘、Dryrun 资产、水印 |
| OCR / CV | NumPy / OpenCV / PaddleOCR / RapidOCR | 1.26.4 / 4.10.0.84 / 3.7.0 / 1.4.4 | OCR 改字、文本框检测与图像预处理 |
| 后端测试 | Pytest / pytest-asyncio | 9.1.1 / 1.3.0 | API、服务、状态机测试 |

## 架构边界

- 前端和后端独立开发，但作为一个本机/私有化演示单体交付。
- SQLite 是当前唯一持久化源；运行时数据库、密钥、上传、结果、导出文件不提交。
- 后端使用同步 SQLAlchemy 会话和进程内异步任务执行；单任务图片并发默认 4，可通过 `LISTINGO_MAX_JOB_CONCURRENCY` 在 1-8 间调整。
- 批量与普通任务共享进程级 Provider 并发限制，默认 `LISTINGO_MAX_PROVIDER_CONCURRENCY=4`。
- 当前不引入 Redis、Celery、对象存储、真实支付网关、SSO 或生产数据库。
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
| `data/listingo.sqlite3` | SQLite 数据库，不提交 |
| `data/uploads/` | 上传商品图，不提交实际文件 |
| `data/results/` | 生成图片、A+、视频结果，不提交实际文件 |
| `data/exports/` | 临时 ZIP / 长图导出，不提交实际文件 |
| `data/.secret_key` | 本机 Fernet 密钥，不提交 |

## 环境变量

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `LISTINGO_DATABASE_URL` | SQLite 文件 | 数据库连接 |
| `LISTINGO_DATA_DIR` | `data/` | 上传、结果、导出和密钥目录 |
| `LISTINGO_GLOBAL_DRY_RUN` | `true` | 全局默认 Dryrun |
| `LISTINGO_PUBLIC_ASSET_BASE_URL` | 空 | Live 参考图公网地址，不能是 localhost/127.0.0.1 |
| `LISTINGO_MAX_UPLOAD_BYTES` | `15728640` | 单文件上传上限 |
| `LISTINGO_MAX_JOB_CONCURRENCY` | `4` | 单任务图片并发，范围 1-8 |
| `LISTINGO_MAX_BATCH_TASKS` | `100` | 单批次 item 上限 |
| `LISTINGO_MAX_BATCH_ITEM_ASSETS` | `6` | 单个批量 item 图片上限 |
| `LISTINGO_MAX_ACTIVE_BATCH_ITEMS` | `1` | 批量调度活跃 item 上限 |
| `LISTINGO_MAX_PROVIDER_CONCURRENCY` | `4` | 全局 Provider 活跃调用上限 |
| `LISTINGO_OCR_ENGINE` | `rapidocr` | OCR engine，可选 `paddleocr`、`rapidocr`、`auto` |
| `LISTINGO_OCR_PRIMARY_MODEL` | `PP-OCRv5` | OCR 主模型 |
| `LISTINGO_OCR_FALLBACK_MODEL` | `PP-OCRv6` | OCR 备模型 |
| `LISTINGO_OCR_DEVICE` | `cpu` | OCR 设备 |

## Batch Runtime

- Batch hosting stays inside the existing FastAPI + SQLite runtime. It uses a single-process `BatchScheduler` started from application lifespan outside test mode; tests drive it with explicit ticks.
- No Redis, Celery, object storage, frontend Provider-key exposure, or public production auth gateway is introduced.
- `GET /api/v1/workspace-config` is the public source for upload and batch limits, including max batch tasks and max per-item assets.
- `ProviderConcurrencyLimiter` is process-level and shared by ordinary generation jobs, A+ generation jobs, child edits, OCR text edits, and batch jobs.
- Asynchronous Provider tasks are persisted through `provider_task_id` on suite, A+ and video items so restart recovery can poll/download existing Provider work before submitting new paid work.

## 部署更新

Docker Compose 镜像会在 `docker compose build` 时重新安装 `backend/requirements.txt`，因此 requirements 变化需要 rebuild 后端镜像。非 Docker 部署必须重新执行：

```bash
python -m pip install -r backend/requirements.txt
python -m alembic -c backend/alembic.ini upgrade head
```

前端依赖变化需要在服务器执行 `npm install` 后重新 `npm run build`，再 reload Nginx 或重建前端镜像。
