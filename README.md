# Listingo

Listingo 是一个本机/私有化运行的电商创意生产平台，使用 Vue 3 + FastAPI + SQLite 交付前台工作台 `/app` 和运营后台 `/admin`。当前源码支持商品套图、A+ 详情页、15 秒电商视频、批量托管、账号中心、套餐额度、短信登录、运营监控、OCR 改字和 AI 水印下载。全局默认 Dryrun；只有在后台启用 Provider、录入密钥并满足路由要求后才会发起外部模型调用。

## 目录

```text
listingo/
├─ frontend/                 Vue 3 单页应用
│  ├─ src/api/               后端 API 客户端
│  ├─ src/assets/            Listingo 品牌资产
│  ├─ src/components/        通用组件
│  └─ src/features/          工作台、账号、运营后台功能
├─ backend/
│  ├─ app/api/               FastAPI 公共、账号与后台 API
│  ├─ app/prompts/           seed 使用的源码 Prompt 资产
│  ├─ app/services/          任务、Provider、Prompt、账号、订阅、OCR、存储服务
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

## 当前生效 Prompt 资产

源码 seed 当前维护 8 类运行时 Prompt 资产，均可在后台版本化。历史任务继续引用创建时锁定的版本。

| Code | 文件 | 用途 |
|---|---|---|
| `ecommerce-meta` | `backend/app/prompts/ecommerce_meta_prompt_v1.md` | 商品套图核心 Meta Prompt，运行时追加变量块与 JSON 契约 |
| `aplus-meta` | `backend/app/prompts/aplus_meta_prompt_0729.md` | A+ 详情页 0729 核心 Meta Prompt |
| `product-vision` | `backend/app/prompts/product_vision_v1.md` | 商品图视觉事实抽取 |
| `copywriting-assist` | `backend/app/prompts/copywriting_assist_v1.md` | 套图/视频卖点帮写 |
| `edit-rewrite` | `backend/app/prompts/edit_rewrite_v1.md` | 单图二次编辑指令转写 |
| `image-text-edit` | `backend/app/prompts/image_text_edit_v1.md` | OCR 行文本与用户修改转写为图片文字替换 edit Prompt |
| `content-safety-review` | `backend/app/prompts/content_safety_review_v1.md` | LLM 内容安全审查 |
| `ecommerce-video-meta-15s` | `backend/app/prompts/ecommerce_video_meta_prompt_15s.md` | 15 秒电商视频分镜规划 |

本地 SQLite 可能仍保留历史 `image-quality-review` Prompt 记录；当前源码 Workflow 和任务执行链路不再调用它。

## Provider 与中转配置

源码 Provider 目录当前包含 47 个预设：3 个 LLM 加 44 个图片/视频中转模型。支持的中转站分组包括 HelloBabyGo、fal.ai、Runware、OpenRouter、Atlas Cloud、Replicate、WaveSpeedAI、Kie.ai、CometAPI、API Models。

默认 route slot 使用 `primary`、`backup1`、`backup2`、`backup3`、`backup4`。旧 `fallback` 值只作为兼容别名归一到 `backup1`。Live 选择 Provider 时按 route role 与能力过滤，不只看全局默认/备用字段。

| Route | 默认源码链路 |
|---|---|
| `llm` | `doubao-seed-2-0-mini` primary，`qwen-3-6` backup1 |
| `suite_fidelity` | API Models Nano Banana Pro primary，Kie/Atlas/API Models/Runware Nano 2 备线 |
| `suite_layout` | Atlas GPT Image 2 primary，CometAPI/Runware/fal.ai/OpenRouter 备线 |
| `aplus_detail` | Atlas GPT Image 2 primary，CometAPI/Runware/fal.ai/OpenRouter 备线 |
| `aplus_mobile` | Atlas GPT Image 2 Edit primary，CometAPI/Runware/fal.ai/OpenRouter 备线 |
| `image_edit` | Atlas GPT Image 2 Edit primary，CometAPI/Runware/fal.ai/OpenRouter 备线 |
| `video` | HelloBabyGo Seedance 2.0 primary，CometAPI/Kie.ai/Atlas/WaveSpeedAI 备线 |

本机数据库可额外保留 5 个 legacy Provider（旧云雾/声算云记录）。这些记录不作为新源码事实；API Key、启用状态、短信凭据和运行时路由调整属于服务器本地配置，不通过 Git 推送。

## 主要链路

商品套图：

`商品图与卖点 → 输入安全审查 → product-vision → ecommerce-meta → JSON 契约校验 → 语义校验/比例补齐/一次重规划 → 内容安全审查 → 图片 Provider 并发生成 → 单图安全审查 → 聚合、重试、版本、ZIP/长图下载`

A+ 详情页：

`商品图与商品信息 → product-vision → aplus-meta 0729 → 模块 JSON 契约 → 按 module_selections 展开模块 → 详情/A+ Web 生图 → 高级移动端按需独立生成或从 Web 成图派生 → 聚合、重试、下载`

视频：

`商品图与卖点 → 输入安全审查 → ecommerce-video-meta-15s → 分镜安全审查 → Seedance 任务提交 → Provider 配置轮询 → 下载 mp4 落盘 → 聚合、重试、下载`

Live 图生图、二次编辑、A+ 移动端派生、OCR 改字和 Live 视频都可能需要公开可访问的参考图 URL。正式 Live 必须配置 `LISTINGO_PUBLIC_ASSET_BASE_URL`，且不能是 `localhost` 或 `127.0.0.1`。

## 账号、订阅与下载

- 支持短信登录/注册、密码登录、管理员短信二次验证、账号资料、手机号换绑、密码修改和登录事件。
- 内置套餐：免费版、标准会员、高级会员、企业定制版和内部管理员套餐。
- 套餐额度覆盖商品套图、A+、视频、二次编辑、批量套图和批量 A+；任务创建时预留额度，成功确认，失败释放。
- 支持模拟支付订单和后台套餐/额度管理；当前不接入真实支付网关。
- 免费用户默认下载带 AI 水印，付费/企业/管理员可下载无水印版本。

## 批量托管

工作台支持商品套图和 A+ 详情页批量托管。入口从对应业务类型进入，批次只做编排、聚合、恢复、取消、失败重试和 ZIP 导出；实际生成结果仍落在 `GenerationJob/GenerationItem` 或 `AplusJob/AplusItem`。

`GET /api/v1/workspace-config` 返回公开上传与批量上限。默认值：

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `LISTINGO_MAX_BATCH_TASKS` | `100` | 单个批次最大商品任务数 |
| `LISTINGO_MAX_BATCH_ITEM_ASSETS` | `6` | 单个批次 item 最大商品图数 |
| `LISTINGO_MAX_ACTIVE_BATCH_ITEMS` | `1` | 单进程同时调度的批次 item 数 |
| `LISTINGO_MAX_PROVIDER_CONCURRENCY` | `4` | 全局图片 Provider 活跃调用上限 |

调度器是 SQLite-backed，FastAPI lifespan 在非测试模式启动。重启后会恢复 queued/running/cancelling 批次，并通过 `provider_task_id` 继续轮询已提交的异步 Provider 任务，避免重复提交已计费任务。

## 运营后台

- Provider：按中转站分组展示模型目录，配置 API Key、启用状态、模型参数、route chain、连通测试和分组健康检查。
- Prompts：查看版本、上传 UTF-8 `.md` / `.txt` 新版本、比较版本、手工启用版本。
- Prompt 测试：支持 LLM 输出试跑与完整链路生成试跑；完整链路测试任务会标记 `is_admin_test=true`，不会混入前台任务历史。
- Workflows：版本化保存画布 JSON 并校验节点和连线。
- 用户/套餐：管理用户状态、套餐、额度规则、订单和广播通知。
- 监控：查看运营指标、用户钻取、Provider 成本与错误摘要。
- 短信：配置阿里云 PNVS 或普通短信，支持 debug 验证码模式。
- OCR：配置 PaddleOCR/RapidOCR、模型版本、阈值、缓存预热和清理。
- Logs：查看脱敏后的请求摘要、响应摘要和错误。
- Runtime settings：读写 `public_asset_base_url`。后台保存只影响当前运行实例，正式部署建议使用环境变量。

## 依赖变化

后端 OCR、账号和图像处理依赖已纳入 `backend/requirements.txt`：`argon2-cffi`、`numpy`、`opencv-python`、`paddlepaddle`、`paddleocr`、`onnxruntime`、`rapidocr-onnxruntime`。安装时会使用 Paddle CPU extra index。

前端运营监控图表依赖已纳入 `frontend/package.json` 和 lockfile：`echarts`、`vue-echarts`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
Set-Location frontend
npm.cmd run test:run
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini heads
```

Live 冒烟测试不会默认运行。只有在后台录入有效密钥、启用 Provider、配置公开资源地址并显式创建 Live 任务后，才会发起外部调用。

## 服务器更新与重启

Docker Compose 部署：

```bash
cd /path/to/listingo
git pull origin main
docker compose stop backend frontend
docker compose build --no-cache backend frontend
docker compose run --rm backend alembic -c backend/alembic.ini upgrade head
docker compose up -d --force-recreate
docker compose ps
docker compose logs --tail=100 backend
```

非 Docker/systemd 部署：

```bash
cd /path/to/listingo
git pull origin main
python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m alembic -c backend/alembic.ini upgrade head
cd frontend
npm install
npm run build
sudo systemctl restart listingo-backend
sudo systemctl reload nginx
```

服务器继续保留自己的运行时 DB 和密钥。如果服务器缺少本机相同的 Provider Key、短信凭据或启用状态，需要在服务器 `/admin` 中配置；这些敏感内容不会进入 Git。
