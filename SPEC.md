# Spec — Listingo

> 项目摘要（一键速览）。权威事实以 `TASKS.md`、`TECH_STACK.md`、`开发计划.md` 与当前源码为准；模块映射见 `docs/CONTEXT_SUMMARY.md`。
> ⚠️ 命名说明：本项目运行于 Windows（大小写不敏感），`spec.md` 与本曾删除的 `SPEC.md` 视为同一文件。本文档即项目摘要的现行载体。

## 简介

Listingo 是本机 / 私有化运行的**电商创意生产平台**：以 Vue 3 + FastAPI + SQLite 模块化单体交付，提供「商品套图 / A+ 详情页 / 视频 / Demo」四期统一工作台与运营后台，集成 LLM·图片·视频 Provider、批量托管、OCR 改字与 AI 水印下载能力。默认全局 Dryrun，未配置有效 Provider 与密钥不得外调。

## 技术栈

- 前端：Node.js 24 / Vue 3.5 / Vite 8 / TypeScript 7 / Ant Design Vue 4.2 / Pinia 4 / Vue Router 5 / ECharts 6 + Vue-ECharts 8 / Vue Flow 1.48
- 后端：Python 3.10 / FastAPI 0.139 / SQLAlchemy 2.0 / Alembic 1.18 / Pydantic 2.13 / HTTPX 0.28 / Redis-py 5.2 / Cryptography 49 / argon2-cffi 21 / Pillow 12 / NumPy·OpenCV·PaddleOCR·RapidOCR
- 数据库：SQLite（业务事实唯一持久化源）与 Redis 7.4（限流、防重放、封禁、短信验证码等临时安全状态）
- 测试：后端 Pytest 9，前端 Vitest 4

## 启动命令

- 后端（本地虚拟环境）：
  `.venv/Scripts/python.exe -m uvicorn backend.app.main:app --reload`
- 前端（开发）：
  `cd frontend && npm install && npm run dev`
- 前端（生产构建）：
  `cd frontend && npm run build`
- 后端测试：
  `.venv/Scripts/python.exe -m pytest backend/tests`
- 前端测试：
  `cd frontend && npm run test:run`
- 数据库迁移：
  `.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head`
- 容器部署：
  `docker compose up --build`（后端/前端镜像需 rebuild 以安装新增依赖）

## 架构边界（要点）

- 前后端独立开发、同仓作为私有化单体交付；业务事实只在 SQLite，Redis 仅保存带 TTL 的临时安全状态。
- 进程内异步任务执行 + 单进程 `BatchScheduler`；无 Celery / 对象存储 / 真实支付 / SSO。
- Provider（47 预设）、Prompt（8 类）、Workflow 全部版本化；历史任务固定引用创建时版本。
- 全局默认 Dryrun；图片单任务并发默认 4（`LISTINGO_MAX_JOB_CONCURRENCY` 1–8），全局 Provider 并发默认 4。

## 相关文档

- 语义索引：docs/CONTEXT_SUMMARY.md
- 架构：docs/ARCHITECTURE.md
- API 参考：docs/API_REFERENCE.md
- 数据库：docs/DB_SCHEMA.md
- 业务域：docs/BUSINESS_DOMAIN.md
- Agent 协作规范：docs/AGENTS.md
- 变更日志：docs/CHANGELOG.md
- 任务清单：TASKS.md
- 技术栈细则：TECH_STACK.md
- 实施计划：开发计划.md
- 设计 QA：design-qa.md
- 编码与协作规范：.coderules
