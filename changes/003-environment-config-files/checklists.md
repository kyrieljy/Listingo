# 验证清单 - environment-config-files

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] `.env.local` 默认加载，所有配置项均有含义与使用位置注释
- [x] `.env.production` 可通过 `LISTINGO_ENV_FILE` 或 Compose `--env-file` 选择，所有配置项均有含义与使用位置注释
- [x] CORS 白名单来自 `LISTINGO_CORS_ORIGINS`
- [x] 会话/刷新 Cookie 的 TTL 与 Secure 标志来自 Settings
- [x] 调试短信码来自 `LISTINGO_DEBUG_SMS_CODE`，为空时生成随机码
- [x] 短信 HTTP 超时来自 `LISTINGO_SMS_TIMEOUT_SECONDS`
- [x] 后端容器端口来自 `LISTINGO_PORT`，前端开发代理端口同步

## 测试
- [x] `.venv/Scripts/python.exe -m pytest backend/tests`
- [x] `frontend/npm run typecheck`（在 `frontend` 目录执行 `npm run typecheck`）

## 规范检查
- [x] 符合 `.coderules`
- [x] `TECH_STACK.md` 环境变量与部署说明已同步
