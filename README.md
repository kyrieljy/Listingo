# Listingo

Listingo 是一个面向电商套图与视频生产的本机演示平台。当前版本采用 Vue 3 + FastAPI + SQLite 的模块化单体架构：一期（商品套图）与三期（视频与爆款复刻）均已接入真实模型链路，具备生成、二次编辑、历史与批量下载能力；二期（A+详情）和四期（Agent 与画布）继续提供交互演示入口，任何 Live 触发前都必须经过 Provider 与提示词校验。

## 目录说明

```text
listingo/
├─ frontend/                 Vue 3 单页应用（/app、/admin）
│  ├─ src/api/              后端 API 客户端
│  ├─ src/components/       通用 UI 与工作台组件
│  ├─ src/features/         四期工作台及后台功能模块
│  ├─ src/router/           路由入口
│  └─ src/styles/           DesignKit 风格设计令牌与响应式样式
├─ backend/
│  ├─ app/api/              FastAPI 公共与运营后台 API
│  ├─ app/services/         提示词、任务、Provider、存储服务
│  ├─ app/static/demo/      Dryrun 演示资产
│  ├─ migrations/           Alembic 迁移
│  └─ tests/                Pytest 自动化测试
├─ data/                    SQLite 与本地文件存储（运行时生成）
├─ README.md                项目入口与部署说明
├─ TECH_STACK.md            框架、SDK、UI 库及锁定版本
├─ SPEC.md                  唯一业务逻辑规格书
├─ 开发计划.md              完整开发计划
└─ TASKS.md                 持续更新的任务清单
```

## 本机启动

要求：Node.js 24.13.x、Python 3.10.9。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm install
Set-Location ..
```

启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

启动前端：

```powershell
Set-Location frontend
npm run dev
```

访问：
- 前台工作台：<http://127.0.0.1:5173/app>
- 运营后台：<http://127.0.0.1:5173/admin>
- API 文档：<http://127.0.0.1:8000/docs>

## 默认安全状态

- 全局默认为 Dryrun，不调用外部模型。
- 预置 7 个 Provider：三个语言模型（Doubao Seed 2.0 Mini 默认 / Qwen-3.6 备用 / GPT-5.4-Mini 待启用）、Nano Banana Pro、Nano Banana 2、Image 2 与 Seedance 1.5 Pro 视频；首次安装不含任何密钥，默认使用 Dryrun。
- API Key 只能在本机后台录入，加密保存，接口只返回掩码。
- 工作台不暴露模型名：选择“商品保持优先”时走 Nano Banana Pro → Nano Banana 2；选择“视觉排版优先”时走 Image 2；视频三期固定使用 Seedance 1.5 Pro。
- 后台提示词资产支持上传 UTF-8 的 `.md` / `.txt` 文件为新版本，只有手工点击“启用此版本”才会影响后续 Live 任务。
- Prompt 工程包含 6 类独立资产：核心套图规划（`ecommerce-meta`）、商品视觉事实（`product-vision`）、AI 卖点帮写（`copywriting-assist`）、二次编辑转写（`edit-rewrite`）、内容安全审查（`content-safety-review`）、15 秒电商视频分镜（`ecommerce-video-meta-15s`）；Live 任务会锁定本次使用的辅助资产版本。
- 内容安全走“本地关键词过滤 + LLM 安全审查”双层：生成计划、每张成图、AI 帮写输入/输出、视频卖点输入/输出、视频分镜脚本都会审查一次，任一未通过即以 `ContentSafetyBlocked` 拒绝。
- 服务默认只监听 `127.0.0.1`；本 Demo 未实现用户或管理员登录，不应直接暴露到公网。运行三期 Live 视频前需在后台 `/runtime-settings` 配置 `LISTINGO_PUBLIC_ASSET_BASE_URL`，用于 Seedance 拉取商品参考图（不能是 `localhost`）。

## 一期真实执行链路

`商品图与结构化信息 → 输入安全审查 → 商品视觉事实 → 核心 Meta Prompt → JSON 结构校验（一次修复）→ 语义校验/比例自动补齐/一次重规划 → 计划安全审查 → 并发生图（默认并发 4，1–8 可配）→ 单图安全审查 → 聚合、历史、版本与 ZIP/长图下载`。

前台支持生成前策略确认、智能 7–12 张，以及用一个“商品卖点与要求”文本框完成信息输入；填写结构作为浅色占位提示，结构化商品事实与品牌风格由后端结合文本和商品图解析。AI 帮写先展示候选内容，可重新生成，确认后才回填。失败图片只通过“重试失败项”重新执行，不覆盖已经成功的结果。

## 三期视频真实执行链路

`商品图 + 卖点 + video_types + 时长/分辨率 → 本地安全审查 → ecommerce-video-meta-15s 生成分镜（LLM，失败回退备用 LLM）→ 分镜安全审查 → Seedance submit_video_task → 每 5 秒轮询 get_video_task（最多 180 次）→ 下载 mp4 落盘 → 聚合、失败重试、下载`。

单条视频顺序执行；单项失败通过 `POST /video-jobs/{id}/retry-failed` 重跑。Dryrun 使用固定 15 秒分镜模板，不提交外部请求。

## Docker Compose

```powershell
docker compose up --build
```

Compose 同样只映射到本机回环地址。前端为 `http://127.0.0.1:5173`，后端为 `http://127.0.0.1:8000`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
Set-Location frontend
npm run test:run
npm run build
```

Live 冒烟测试不会默认运行。只有在后台录入有效密钥、显式启用 Provider 并将任务模式切换为 Live 后才会发起外部调用。
