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
| HTTP 客户端 | HTTPX | 0.28.1 | LLM 与图片模型调用 |
| 加密 | Cryptography | 49.0.0 | API Key 加密落盘 |
| 图片处理 | Pillow | 12.3.0 | 上传校验与 Dryrun 资产 |
| 后端测试 | Pytest | 9.1.1 | API、服务与状态机测试 |

## 架构边界

- 前后端独立开发，但以一个仓库和一个本机部署单元交付。
- 后端采用同步 SQLAlchemy 会话与进程内异步扇出；单任务并发上限为 3。
- 本期不引入 Redis、Celery、对象存储、鉴权、支付或生产数据库。
- SQLite 是当前唯一持久化源；历史任务固定引用创建时的核心 Prompt、辅助 Prompt 与 Workflow 版本。
- 外部模型通过 Provider 适配器隔离：OpenAI-compatible Chat、Gemini `generateContent`、OpenAI-compatible Image Generation/Edit。
- OpenAI-compatible Chat 适配器支持文本与商品图 data URL 多模态消息，用于商品事实提取、核心规划、AI 帮写、二次编辑转写和生成后 QA。

## 本地数据路径

| 路径 | 内容 |
|---|---|
| `data/listingo.sqlite3` | SQLite 数据库 |
| `data/uploads/` | 原始商品图片 |
| `data/results/` | 生成结果与版本图片 |
| `data/exports/` | 临时 ZIP 导出 |
| `data/.secret_key` | 本机 Fernet 密钥（不提交） |
