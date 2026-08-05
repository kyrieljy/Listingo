# Listingo

Listingo 是一个本机运行的电商创意生产演示平台，使用 Vue 3 + FastAPI + SQLite 交付前台工作台 `/app` 和运营后台 `/admin`。当前源码支持商品套图、A+ 详情页、15 秒电商视频的 Dryrun 与 Live 链路；四期 Agent 与画布仍作为交互演示入口。全局默认 Dryrun，不会在未配置 Provider 与密钥时调用外部模型。

## 目录

```text
listingo/
├─ frontend/                 Vue 3 单页应用
│  ├─ src/api/               后端 API 客户端
│  ├─ src/assets/            Listingo 品牌资产
│  ├─ src/components/        通用组件
│  └─ src/features/          工作台与运营后台功能
├─ backend/
│  ├─ app/api/               FastAPI 公共与后台 API
│  ├─ app/prompts/           当前 seed 使用的提示词资产
│  ├─ app/services/          任务、Provider、Prompt、存储服务
│  ├─ migrations/            Alembic 迁移
│  └─ tests/                 Pytest 自动化测试
├─ data/                     SQLite 与本地运行时文件，不提交业务数据
├─ README.md
├─ TECH_STACK.md
├─ SPEC.md
├─ 开发计划.md
├─ TASKS.md
└─ design-qa.md
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

## 当前生效提示词资产

源码 seed 当前维护 7 类运行时提示词资产，均可在后台版本化。历史任务继续引用创建时锁定的版本。

| Code | 文件 | 用途 |
|---|---|---|
| `ecommerce-meta` | `backend/app/prompts/ecommerce_meta_prompt_v1.md` | 商品套图核心 Meta Prompt，运行时追加变量块与 JSON 契约 |
| `aplus-meta` | `backend/app/prompts/aplus_meta_prompt_0729.md` | A+ 详情页 0729 核心 Meta Prompt |
| `product-vision` | `backend/app/prompts/product_vision_v1.md` | 商品图视觉事实抽取 |
| `copywriting-assist` | `backend/app/prompts/copywriting_assist_v1.md` | 套图/视频卖点帮写 |
| `edit-rewrite` | `backend/app/prompts/edit_rewrite_v1.md` | 单图二次编辑指令转写 |
| `content-safety-review` | `backend/app/prompts/content_safety_review_v1.md` | LLM 内容安全审查 |
| `ecommerce-video-meta-15s` | `backend/app/prompts/ecommerce_video_meta_prompt_15s.md` | 15 秒电商视频分镜规划 |

本地 SQLite 可能仍保留历史 `image-quality-review` Prompt 记录；当前源码 Workflow 和任务执行链路不再调用它。

## Provider 预置

seed 当前创建 8 个 Provider。Provider 默认都不启用且不含 API Key；Live 只有在后台录入密钥、启用 Provider 并满足 route role 后才可执行。

| Code | 能力 | 默认角色 |
|---|---|---|
| `doubao-seed-2-0-mini` | LLM | `llm` primary |
| `qwen-3-6` | LLM | `llm` fallback |
| `gpt-5-4-mini` | LLM | 预置待启用 |
| `yunwu-nano-pro` | image | `suite_fidelity` primary，斑点蛙模型 `nano_banana_pro` |
| `yunwu-nano` | image | `suite_fidelity` fallback，斑点蛙模型 `nano_banana_2` |
| `yunwu-image-2` | image | `suite_layout` primary、`aplus_detail` primary，斑点蛙模型 `gpt-image-2` |
| `aplus-mobile-edit-low-cost` | image | `aplus_mobile` primary，斑点蛙模型 `gpt-image-2` |
| `shengsuanyun-doubao-seedance-2-0` | video | `video` primary，斑点蛙模型 `seedance-2.0` |

后台 Provider 页按业务链路展示 route role：LLM、套图保真、套图排版、A+ 详情、A+ 移动端、视频生成。保存 Provider 配置不会自动发起外部请求；连通测试必须由运营人员显式点击。

## 主要链路

商品套图：

`商品图与卖点 → 输入安全审查 → product-vision → ecommerce-meta → JSON 契约校验 → 语义校验/比例补齐/一次重规划 → 内容安全审查 → 图片 Provider 并发生成（默认 4，1-8 可配）→ 单图安全审查 → 聚合、重试、版本、ZIP/长图下载`

A+ 详情页：

`商品图与商品信息 → product-vision → aplus-meta 0729 → 模块 JSON 契约 → 按 module_selections 展开模块 → 详情/A+ Web 生图 → 高级移动端按需独立生成或从 Web 成图派生 → 聚合、重试、下载`

视频：

`商品图与卖点 → 输入安全审查 → ecommerce-video-meta-15s → 分镜安全审查 → hellobabygo_video_generation submit → 按 Provider 配置轮询 → 下载 mp4 落盘 → 聚合、重试、下载`

Live 图生图、二次编辑、A+ 移动端派生图和 Live 视频都必须配置 `LISTINGO_PUBLIC_ASSET_BASE_URL`，且不能是 `localhost` 或 `127.0.0.1`，否则斑点蛙接口无法拉取商品参考图。

## 运营后台

- Provider：配置 API Key、启用状态、模型参数、route role、连通测试。
- Prompts：查看版本、上传 UTF-8 `.md` / `.txt` 新版本、比较版本、手工启用版本。
- Prompt 测试：支持 LLM 输出试跑与完整链路生成试跑；完整链路测试任务会标记 `is_admin_test=true`，不会混入前台任务历史。
- Workflows：版本化保存画布 JSON 并校验节点和连线。
- Logs：查看脱敏后的请求摘要、响应摘要和错误。
- Runtime settings：读写 `public_asset_base_url`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
Set-Location frontend
npm.cmd run test:run
npm.cmd run build
```

Live 冒烟测试不会默认运行。只有在后台录入有效密钥、启用 Provider、配置公开资源地址并显式创建 Live 任务后，才会发起外部调用。
