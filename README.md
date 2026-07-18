# Listingo

Listingo 是一个面向电商套图生产的本机演示平台。当前版本采用 Vue 3 + FastAPI + SQLite 的模块化单体架构：一期提供可运行的套图生成、二次编辑、历史与批量下载；二至四期提供完整的交互演示入口。

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
## 非 Docker 部署（推荐）

### 1) 代码部署
- git init（首次）
- git remote add origin https://github.com/kyrieljy/Listingo.git
- git checkout -B main
- git add backend frontend *.md docker-compose.yml .github（仅提交代码与配置，不提交运行时数据）
- git commit -m "chore: sync latest listingo changes"
- git push -u origin main

### 2) 本机数据备份（数据库与运行文件）

> 项目默认不提交 `data/*` 到 Git（.gitignore 已过滤）。请单独打包迁移。

- 备份数据：
  - mkdir backup
  - Copy-Item data\listingo.sqlite3 backup\listingo.sqlite3
  - Copy-Item data\uploads backup\uploads -Recurse -Force
  - Copy-Item data\results backup\results -Recurse -Force
  - Copy-Item data\exports backup\exports -Recurse -Force
- 打包传输文件：
  - Compress-Archive -Path backup\* -DestinationPath listingo-data-bundle.zip -Force

### 3) 服务器恢复与启动（不走 Docker）

```bash
# 服务器拉代码
git clone https://github.com/kyrieljy/Listingo.git
cd Listingo

# 解压并恢复数据
mkdir -p data/uploads data/results data/exports
# Linux
unzip /path/to/listingo-data-bundle.zip -d .
cp -r backup/uploads/* data/uploads/ 2>/dev/null || true
cp -r backup/results/* data/results/ 2>/dev/null || true
cp -r backup/exports/* data/exports/ 2>/dev/null || true
cp backup/listingo.sqlite3 data/listingo.sqlite3

# 启动后端
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# 启动前端
cd frontend
npm install
npm run build
npm run preview -- --host 0.0.0.0 --port 5173
```

### Windows 启动示例

```powershell
.\\.venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt
.\\.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
Set-Location frontend
npm install
npm run build
npm run preview -- --host 0.0.0.0 --port 5173
```

### 访问地址
- 前台：`http://<服务器IP>:5173/app`
- 后台：`http://<服务器IP>:5173/admin`
- API文档：`http://<服务器IP>:8000/docs`

Docker Compose 方案保留用于本地容器化开发，不作为主线部署方式。

## 默认安全状态

- 全局默认为 Dryrun，不调用外部模型。
- 五个模型配置均已预置：两个语言模型、Nano Banana Pro、Nano Banana 2 与 Image 2；首次安装不含任何密钥，默认使用 Dryrun。
- API Key 只能在本机后台录入，加密保存，接口只返回掩码。
- 工作台不暴露模型名：选择“商品保持优先”时走 Nano Banana Pro → Nano Banana 2；选择“视觉排版优先”时走 Image 2。
- 后台提示词资产支持上传 UTF-8 的 `.md` / `.txt` 文件为新版本，只有手工点击“启用此版本”才会影响后续 Live 任务。
- Prompt 工程包含五类独立资产：核心套图规划、商品视觉事实、AI 卖点帮写、二次编辑转写、生成图片质量审查；Live 任务会锁定本次使用的辅助资产版本。
- 服务默认只监听 `127.0.0.1`；本 Demo 未实现用户或管理员登录，不应直接暴露到公网。

## 一期真实执行链路

`商品图与结构化信息 → 商品视觉事实 → 核心 Meta Prompt → JSON 结构校验 → 语义审查/一次重规划 → 并发生图 → 比例与视觉 QA → 聚合、历史、版本与下载`。

前台支持生成前策略确认、智能 7–12 张，以及用一个“商品卖点与要求”文本框完成信息输入；填写结构作为浅色占位提示，结构化商品事实与品牌风格由后端结合文本和商品图解析。AI 帮写先展示候选内容，可重新生成，确认后才回填。失败图片只通过“重试失败项”重新执行，不覆盖已经成功的结果。

## Docker Compose（仅本地可选）

当前默认部署流程不走 Docker。若需要快速本机验证，可按上述本机启动流程；若要本地容器化运行，请单独执行。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
Set-Location frontend
npm run test:run
npm run build
```

Live 冒烟测试不会默认运行。只有在后台录入有效密钥、显式启用 Provider 并将任务模式切换为 Live 后才会发起外部调用。
