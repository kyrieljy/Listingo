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
| 工作流画布 | Vue Flow | 1.48.2 | Workflow 节点、连线、视口 |
| 状态管理 | Pinia | 4.0.2 | 前台任务与后台状态 |
| 路由 | Vue Router | 5.2.0 | `/app` 与 `/admin` |
| 前端测试 | Vitest | 4.1.10 | 单元与组件测试 |
| 后端运行时 | Python | 3.10.9 | API 与任务执行器 |
| Web 框架 | FastAPI | 0.139.2 | REST API 与 OpenAPI |
| 数据校验 | Pydantic | 2.13.4 | 请求、Prompt、任务契约 |
| ORM | SQLAlchemy | 2.0.51 | SQLite 持久化 |
| 迁移 | Alembic | 1.18.5 | 数据库版本管理 |
| HTTP 客户端 | HTTPX | 0.28.1 | LLM、图片、视频模型调用 |
| 加密 | Cryptography | 49.0.0 | API Key 本机加密 |
| 图片处理 | Pillow | 12.3.0 | 上传校验、图片写盘、Dryrun 资产 |
| 后端测试 | Pytest | 9.1.1 | API、服务、状态机测试 |

## 架构边界

- 前端和后端独立开发，但作为一个本机演示单体交付。
- SQLite 是当前唯一持久化源；运行时数据库、密钥、上传、结果、导出文件不提交。
- 后端使用同步 SQLAlchemy 会话和进程内异步任务执行；单任务图片并发默认 4，可通过 `LISTINGO_MAX_JOB_CONCURRENCY` 在 1-8 间调整。
- 不引入 Redis、Celery、对象存储、鉴权、支付或生产数据库。
- Prompt、Workflow 和 Provider 都版本化/配置化；历史任务固定引用创建时的版本。

## Provider 与路由

外部模型通过 Provider 适配器隔离：

- `openai_chat`：Doubao Seed 2.0 Mini、Qwen-3.6、GPT-5.4-Mini，用于商品视觉事实、核心规划、帮写、编辑转写、内容安全和视频分镜。
- `hellobabygo_image_generation`：斑点蛙 `gpt-image-2`、`nano_banana_pro`、`nano_banana_2` 图片异步任务提交、轮询和结果下载，用于套图、A+ 详情和移动端派生。
- `hellobabygo_video_generation`：斑点蛙 `seedance-2.0` 视频异步任务提交、轮询和 mp4 下载。

Provider route roles 由 `backend/app/services/provider_routing.py` 定义。当前 route key 为 `llm`、`suite_fidelity`、`suite_layout`、`aplus_detail`、`aplus_mobile`、`video`。Live 创建时按 route role 选择可用 Provider，而不是仅按全局默认/备用字段。

## Prompt 资产

当前运行时 Prompt 资产共 7 类：

- 核心：`ecommerce-meta`、`aplus-meta`。
- 辅助：`product-vision`、`copywriting-assist`、`edit-rewrite`、`content-safety-review`、`ecommerce-video-meta-15s`。
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
