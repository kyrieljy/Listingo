# Change: environment-config-files

## 变更标题
补齐本地与生产环境配置文件并移除环境相关硬编码

## 变更背景 / 上下文
- 来源需求：按 `env.md` 检视结论编写 `.env.local` 与 `.env.production`，并将环境相关硬编码改为环境变量读取。
- 关联模块：后端配置（`backend/app/config.py`）、应用装配（`backend/app/main.py`）、认证会话（`backend/app/services/auth.py`）、短信服务（`backend/app/services/sms.py`）、部署编排（`backend/Dockerfile`、`docker-compose.yml`）、前端开发代理（`frontend/vite.config.ts`）。
- 影响范围：环境配置、CORS、会话 Cookie、调试短信码、短信网关超时、端口编排、技术栈文档与针对性测试。
- 现状：`env.md` 已指出 CORS、端口、会话时效、固定调试验证码、Cookie Secure、短信超时等常量随环境变化但被硬编码；现有 `LISTINGO_*` 配置体系完整，Provider 运行态仍应保留在数据库中。

## 目标
- 提供逐项注释的 `.env.local`（本地测试默认加载）与 `.env.production`（生产通过 `LISTINGO_ENV_FILE` 或 Compose `--env-file` 选择）。
- 新增安全与部署相关 `LISTINGO_*` 配置，并让 CORS、会话时效、Cookie Secure、调试短信码、短信超时和端口从环境读取。
- 保持本地开发默认行为可用；生产默认启用 Secure Cookie、禁用固定调试验证码，并要求替换公网域名占位值。
- 为配置解析、CORS 行为、会话 Cookie 和短信配置引用补充可执行测试。

## 方案设计
### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `.env.local` | 新增 | 本地测试配置，默认被 `Settings` 加载；每个变量均有含义与使用位置注释 |
| `.env.production` | 新增 | 生产配置模板值；每个变量均有含义与使用位置注释，部署前替换域名占位值 |
| `backend/app/config.py` | 修改 | 选择环境文件，新增 CORS、会话、Cookie、短信安全与超时配置并解析逗号分隔白名单 |
| `backend/app/main.py` | 修改 | CORS 白名单改为读取 Settings |
| `backend/app/services/auth.py` | 修改 | 会话时效与 Cookie Secure 改为读取 Settings |
| `backend/app/services/sms.py` | 修改 | 调试验证码与短信 HTTP 超时改为读取 Settings，移除固定验证码 |
| `backend/Dockerfile` | 修改 | 后端监听端口支持 `LISTINGO_PORT` |
| `docker-compose.yml` | 修改 | 通过可配置 env 文件与端口注入本地/生产差异 |
| `frontend/Dockerfile` / `frontend/nginx.conf` | 修改 | Nginx 反向代理端口改为由 `LISTINGO_PORT` 模板渲染 |
| `frontend/vite.config.ts` | 修改 | 开发代理目标按所选环境文件的 `LISTINGO_PORT` 生成 |
| `TECH_STACK.md` | 修改 | 同步环境变量、启动方式和生产占位值说明 |
| `docs/CONTEXT_SUMMARY.md` | 修改 | 记录本次配置体系变更 |
| `backend/tests/test_config.py` | 新增 | 覆盖配置文件解析、CORS、会话 Cookie 与短信配置引用 |
| `backend/tests/test_sms_phone.py` | 修改 | 覆盖调试验证码来自 Settings |

### 实现要点
1. `Settings` 默认加载项目根目录 `.env.local`；设置 `LISTINGO_ENV_FILE=.env.production` 后加载生产文件。真实环境变量优先级高于 dotenv。
2. `.env.local` 与 `.env.production` 覆盖现有运行配置与本次新增配置；每项采用“含义 / 使用位置 / 变量配置”三行注释格式。
3. `LISTINGO_CORS_ORIGINS` 使用逗号分隔；`LISTINGO_COOKIE_SECURE=true` 时会话与刷新 Cookie 加 `Secure`；`LISTINGO_DEBUG_SMS_CODE` 为空时调试模式生成随机码，不再内置 `246810`。
4. Compose 使用 `${LISTINGO_ENV_FILE:-.env.local}` 选择注入文件；生产启动使用 `docker compose --env-file .env.production up -d --build`。后端 Uvicorn 与前端 Nginx 均读取 `LISTINGO_PORT`。
5. Provider API Key、base URL、路由等继续由数据库与后台管理，不迁移到环境变量。

## 验收标准
- [ ] `.env.local` 与 `.env.production` 每个非空配置项均有含义和使用位置注释。
- [ ] 本地默认启动读取 `.env.local`；生产通过 `LISTINGO_ENV_FILE` 或 Compose 生产 env-file 读取 `.env.production`。
- [ ] CORS、会话 TTL、Refresh TTL、Cookie Secure、调试短信码、短信 HTTP 超时和端口不再依赖对应源码/编排硬编码。
- [ ] 生产配置默认 `LISTINGO_COOKIE_SECURE=true`、`LISTINGO_DEBUG_SMS_CODE=`，并给出公网资产/CORS 域名替换提示。
- [ ] 后端针对性测试通过，现有后端测试回归通过；前端配置涉及类型检查时执行 `npm run typecheck`。

## Open Questions
None.
