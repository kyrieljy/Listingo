# Listingo 技术栈

## 运行时与框架

| 层级 | 技术 | 锁定版本 | 用途 |
|---|---|---:|---|
| 前端运行时 | Node.js | 24.13.x | 本地构建与开发服务器 |
| 前端框架 | Vue | 3.5.40 | 单页应用与组合式 API |
| 构建工具 | Vite | 8.1.5 | 开发服务器、打包 |
| 类型系统 | TypeScript | 7.0.2 | 前端静态类型 |
| UI 库 | Ant Design Vue | 4.2.6 | 表单、弹窗、表格、反馈 |
| 工作流画布 | Vue Flow | 1.48.2 | 节点、连线、属性编辑 |
| 状态管理 | Pinia | 4.0.2 | 前台任务与后台状态 |
| 路由 | Vue Router | 5.2.0 | `/app` 与 `/admin` |
| 前端测试 | Vitest | 4.1.10 | 单元与组件测试 |
| 后端运行时 | Python | 3.10.9 | API 与任务执行器 |
| Web 框架 | FastAPI | 0.139.2 | REST API、OpenAPI |
| 数据校验 | Pydantic | 2.13.4 | 请求与 Meta Prompt 合约 |
| ORM | SQLAlchemy | 2.0.51 | SQLite 持久化 |
| 迁移 | Alembic | 1.18.5 | 数据库版本管理 |
| HTTP 客户端 | HTTPX | 0.28.1 | LLM、图片与视频模型调用 |
| 加密 | Cryptography | 49.0.0 | API Key 加密落盘 |
| 图片处理 | Pillow | 12.3.0 | 上传校验与 Dryrun 资产 |
| 后端测试 | Pytest | 9.1.1 | API、服务与状态机测试 |

## 架构边界

- 前后端独立开发，但以一个仓库和一个本机部署单元交付。
- 后端采用同步 SQLAlchemy 会话与进程内异步扇出；单任务并发上限默认 4，可通过环境变量 `LISTINGO_MAX_JOB_CONCURRENCY` 在 1–8 之间调整（见 `backend/app/config.py`）。
- 本期不引入 Redis、Celery、对象存储、鉴权、支付或生产数据库。
- SQLite 是当前唯一持久化源；历史任务固定引用创建时的核心 Prompt、辅助 Prompt 与 Workflow 版本。
- 外部模型通过 Provider 适配器隔离：`openai_chat`（LLM）、`gemini_generate_content`（Nano Banana Pro / Nano 2）、`openai_images_generation`（Image 2 文生图 / edits）、`shengsuanyun_tasks_generation`（Seedance 视频提交与轮询）。
- OpenAI-compatible Chat 适配器支持文本与商品图 data URL 多模态消息，用于商品事实提取、核心规划、AI 帮写、二次编辑转写、内容安全审查与视频分镜脚本生成。
- Live 视频任务要求 `LISTINGO_PUBLIC_ASSET_BASE_URL` 已配置为可被外部访问的 HTTPS/域名地址；`127.0.0.1` 或 `localhost` 会在提交前被拒绝，避免 Seedance 拉不到参考图。

## Provider 预置矩阵（一期即随 SQLite seed 落地）

| 编码 | 能力 | 适配器 | 默认/备用 | 说明 |
|---|---|---|---|---|
| `doubao-seed-2-0-mini` | LLM | `openai_chat` | 默认 | 通过 `router.shengsuanyun.com`，模型 `bytedance/doubao-seed-2-0-mini` |
| `qwen-3-6` | LLM | `openai_chat` | 备用 | 通过阿里通义千问 `qwen3.6-plus` |
| `gpt-5-4-mini` | LLM | `openai_chat` | 未启用 | 预置但默认关闭，供人工切换 |
| `yunwu-nano-pro` | 图片 | `gemini_generate_content` | 默认（商品保持） | `gemini-3-pro-image`，2K/PNG |
| `yunwu-nano` | 图片 | `gemini_generate_content` | 备用（商品保持） | `gemini-3.1-flash-image`，1K |
| `yunwu-image-2` | 图片 | `openai_images_generation` | 视觉排版路线 | `gpt-image-2`，默认 `follow_ratio` |
| `shengsuanyun-seedance-1-5-pro` | 视频 | `shengsuanyun_tasks_generation` | 默认 | `bytedance/doubao-seedance-1-5-pro`，1080p、15s、含音频 |

## Prompt 资产（六类，全部可版本化）

- 核心：`ecommerce-meta`（用户上传的电商 Meta Prompt 原文，运行时追加 JSON 契约与变量块）。
- 辅助：`product-vision`（商品视觉事实抽取）、`copywriting-assist`（AI 卖点帮写）、`edit-rewrite`（二次编辑转写）、`content-safety-review`（合规审查，LLM 输出 `ContentSafetyReview` JSON）、`ecommerce-video-meta-15s`（15 秒电商视频分镜规划）。
- 上传要求 UTF-8 的 MD/TXT（≤2MB），新版本上传后不自动启用；运营人员必须在版本历史中显式点击“启用此版本”。历史任务始终固定引用创建时的版本。

## 本地数据路径

| 路径 | 内容 |
|---|---|
| `data/listingo.sqlite3` | SQLite 数据库 |
| `data/uploads/` | 原始商品图片 |
| `data/results/` | 生成图片与视频版本文件 |
| `data/exports/` | 临时 ZIP / 长图导出 |
| `data/.secret_key` | 本机 Fernet 密钥（不提交） |
