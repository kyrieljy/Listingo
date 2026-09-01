# CHANGELOG — 变更日志

> 本文件由 `archive` Skill 在每次变更归档时增量更新。此处为初始种子（来自 `git log`，仅作历史锚点）。
> 语义索引与模块映射见 `docs/CONTEXT_SUMMARY.md`。

## 文档骨架建立（2026-08-22 · init / doc-update）

- 建立 `docs/` 全套骨架：`CONTEXT_SUMMARY.md`（语义索引）、`ARCHITECTURE.md`、`API_REFERENCE.md`、`DB_SCHEMA.md`、`BUSINESS_DOMAIN.md`、`AGENTS.md`、`CHANGELOG.md`。
- 确认 `README.md` 已删除（`spec.md` 即 `SPEC.md`，Windows 大小写不敏感视为同一文件，为现行项目摘要）；权威事实源收敛为 `spec.md` / `TASKS.md` / `TECH_STACK.md` / `开发计划.md` 与当前源码。

## 近期 Git 历史锚点（节选）

| 提交 | 说明 |
|---|---|
| `b414823` | Fix auth modal layout |
| `ca0a374` | Sync active prompts and deployment docs（8 类源码 Prompt 与 SQLite active 版本哈希对齐） |
| `17e4f3d` | Update workspace UI entry states |
| `8c7dcf0` | Fix generation status refresh |
| `38fcd9b` | Harden A+ JSON delimiter repair |
| `cc1f4b9` | Fix A+ JSON parsing failures |
| `ec53649` | Add A+ detail workflow and slim demo assets |
| `4ec4e9d` | docs: sync project docs with current source-of-truth |
| `81a8c8b` | chore: sync latest listingo changes |

> 后续每次 `archive` 在此追加：`### <编号>-<slug> — <一句话>` + 变更要点。请勿手工大段重写。

## [Unreleased]

### 016-task-completion-multi-channel-notify — 2026-08-31
- 任务终态通知扩展为「站内信 + 短信 + 飞书 Webhook」三渠道同源。`notifications.py` 新增 `build_task_result_title`（单任务/批量 × 成功 / 部分完成 / 失败 文案单一事实源）与 `notify_task_completion_external`（飞书 POST + 阿里云通知短信，try/except 仅记日志，失败不抛出、不重试、无兜底）；`sms.py` 新增 `send_sms_notification`（复用 `SmsConfig.notify_template_code` + 参数 `{"content": text}`，**不占验证码每日限额**），`send_aliyun_sms` 模板参数泛化（默认仍 `{"code": code}`）。触发点仅实时 `tick`（`generation_queues.py` / `generation_queue_service.py` 以 `asyncio.create_task` fire-and-forget），`reconcile_notifications` 仍只写站内信，避免重启对历史终态任务重推外部渠道。`User.feishu_webhook`（明文 String 512）与 `SmsConfig.notify_template_code` 两列 + 迁移 `d1e2f3a4b5c6`；`PATCH /account/profile` 与 `GET /auth/me` 支持该字段，个人中心新增飞书 Webhook 输入，运营后台短信配置面板暴露通知模板。新增 `test_task_notify_016.py`（15 passed）。关联模块：通知、短信、队列 worker、账号配置。

### 013-batch-generation-queue — 2026-08-31
- 批量托管任务并入统一生图缓冲队列：新增 `generation_queue_service.py::UnifiedGenerationQueueScheduler`，普通生图与批量套图 / A+ item 共用唯一生图 worker（视频仍独立 worker）。`POST /batch-jobs` 与 retry-failed 只落库、推入 `batch_item:{item_id}` token 并立即返回，移除生产 `BatchScheduler` 旁路，执行逻辑抽取为 `BatchItemExecutor`；父任务聚合终态并只写一条幂等站内信。取消语义收紧为仅全部 queued 可取消（逐个删除 Redis token、释放额度），已 running 返回 409；Redis 部分入队失败 fail-closed 回滚已推 token 并返回 503。前端批量提交提示「任务已在后台运行」，五种语义状态映射与稳定占位，取消入口仅 queued 可见。实现偏差：`generation_queues.py` 被外部进程锁定未改，扩展隔离于新子类。测试 26 passed / 后端全量 248 passed / 前端 106 passed。关联模块：批量托管、生图 / 生视频缓冲队列、通知。

### 012-unified-phone-login-registration — 2026-08-31
- 短信登录与首次注册合并：`/api/v1/auth/sms/login` 在 `purpose=login` 验证通过后，未注册手机号自动创建 active/free 用户、注册通知、会话与 `sms` 登录事件；并发首次登录经手机号预检冲突或唯一键冲突均复用胜出用户，不再直接 409。保留 `mode=register` 与 `/auth/register` 旧客户端兼容。前端移除 `AuthMode` / `initialMode` / `switchMode`、密码注册两步表单与注册验证码计时器，短信验证码固定 `purpose=login`，顶层「登录 / 注册」入口打开同一弹窗。验证码一次性消费、错误 5 次锁定、发送冷却与滚动日限额行为不变。后端 `test_sms_phone.py` 13 passed、前端 106 passed。关联模块：认证、短信、账号。

### 011-video-retry-error-notices-watermark-confirm — 2026-08-31
- 视频「重试失败」首次点击即提交：乐观地把失败项置为运行、2 秒冷却内禁用重试并隐藏取消入口、请求失败回滚失败快照，冷却结束后仅在任务仍 active 时展示「取消任务」，规避误触取消。套图 / A+ / 视频生成失败统一收敛到 AntD 顶部 `message`（不再 `Modal.error`），开发 / 测试构建保留明细，生产固定为 `生成图片失败，请稍后重试`（套图 / A+）与 `生成视频失败，请稍后重试`（视频），并从结果区、失败卡片与脚本文本移除原始异常渲染（后端 payload 与日志仍保留诊断）。订阅用户关闭「包含 AI 水印」需先勾选「我已知悉」确认弹窗，红色「确定」按钮未勾选前禁用、取消 / 遮罩关闭不改变状态，未订阅用户仍锁定。新增 `generation-errors.test.ts`、`WatermarkDownloadMenu.test.ts`、`VideoPhasePanel.test.ts`；前端 105 passed，生产构建已核实两条兜底文案。关联模块：工作台、水印。

### 009-redis-scenario-expansion — 2026-08-31
- 落地 Redis 六类新场景，约束演进为「PostgreSQL 事实 + Redis 派生态」：新增 `core/runtime.py::RuntimeStateService`（JSON 缓存 / 域版本号 / token 锁 / 计数）与 `services/runtime_cache.py`、`services/metrics.py`，`main.py` 装配 `app.state.runtime_state`。覆盖 Provider 快照与路由解析缓存、Prompt/Workflow 激活版本与套餐规则缓存、会话元数据缓存（`session:{sha256(token)}`，值不含明文）、批量详情短 TTL 缓存、批量认领 / 额度预留 / 订单创建 / 模拟支付分布式锁、当日实时计数（`/admin/ops-monitoring` 返回 `realtime_metrics`，前端 KPI 条新增「今日实时事件」）、OCR 结果指纹缓存。降级分级：缓存 / 计数 fail-open，锁 fail-closed 503。`keys.py` 扩展 cache/session/batch/lock/metric 构造器，`config.py` 新增 7 项 TTL 配置；`docs/REDIS_KEYS.md` 重写边界、键清单与失效策略。`test_redis_runtime_features.py` 8 passed。关联模块：运行时派生状态、Provider 目录、账号、批量托管、运营分析。

### 003-environment-config-files — 2026-08-31
- 新增逐项注释的 `.env.local` 与 `.env.production`（含义 / 使用位置 / 变量配置 三行注释）。`Settings` 默认加载 `.env.local`，经 `LISTINGO_ENV_FILE` 切换生产文件，真实环境变量优先于 dotenv。CORS 白名单、会话 / 刷新 TTL、Cookie Secure、调试短信码（移除内置 `246810`，空值时随机生成）、短信 HTTP 超时、后端端口改为读取配置；Compose 以 `${LISTINGO_ENV_FILE:-.env.local}` 注入，Uvicorn、Vite 开发代理与前端 Nginx 模板统一读 `LISTINGO_PORT`。新增 `test_config.py`（配置解析、CORS、会话 Cookie、短信配置引用），后端全量 169 passed，前端 typecheck 与 build 通过。遗留：`docker compose config` 运行时校验因本机无 Docker CLI 未执行。关联模块：配置、应用装配、认证会话、短信、部署编排。

### 014-sensitive-information-detection — 2026-08-30
- 运营后台新增「敏感词」栏目：全局开关、词 CRUD、人工别名、实时变体预览、快照状态与重建；套图/A+/视频/批量创建在 quota 预留与入队前完成卖点文本 + 上传图片 OCR 敏感词检测，命中返回 422「包含敏感信息」且不留 quota/不入队。新增 `SensitiveWordConfig`/`SensitiveWord`/`SensitiveWordSnapshot` 三表与无 TTL 常驻 Redis 快照（`sensitive:words:meta`/`snapshot`）；Aho-Corasick 一次扫描多文本视图；套图/A+ 商品视觉事实新增 `is_pornography`/`is_violence`/`is_politics` 布尔字段阻断（默认 0 兼容旧 Prompt）。OCR 改为进程级单例并启动自动预热，配置变更清理旧实例并重预热。`docs/REDIS_KEYS.md` 新增常驻快照键段；迁移：`b9f4d2a6c7e8`（敏感词三表）/ `c0a1b2c3d4e5`（`ExecutionLog.aplus_job_id` 关联，同变更 014 的 A+ 子项）。

### 015-batch-import-sensitive-words — 2026-08-30
- 运营后台「敏感词」新增「批量导入」卡片：多行文本框按换行或逗号（含中文逗号）切分，后端 `POST /admin/sensitive-words/bulk` 一次性建词（`terms/enabled/note`），按 `normalized_term` 去重、跳过已存在与空项、超长/无效计入 `errors`；快照重建移交 `BackgroundTasks` 异步执行，请求立即返回 `rebuild_scheduled=true`，前端 `bulkCreateSensitiveWords` 单独设 `timeout:180_000`。后续 UI 迭代：状态开关改为纯状态药丸（无文字）、「变体」列直接列举全部变体、清单顶部新增实时搜索（按敏感词/别名/变体匹配）。新增 `test_sensitive_word_bulk.py`（含 300 词大批量回归）。

### 001-report-driven-safe-optimizations — 2026-08-22

- 基于审计批判性采纳低风险类型修复：后端目标入口/服务/路由补齐参数与返回类型，Workspace 请求错误从 `any` 收紧为 `unknown`，Provider 展示动态 JSON 使用具体类型。
- 保留同步 SQLAlchemy 会话 + 进程内异步任务架构；暂缓 AsyncSession 迁移、全量业务下沉、Admin DTO 类型化与工具链引入。
- 修复认证弹窗高度与 Workspace raw source 测试的过期/换行敏感断言；后端 163 项、前端 94 项测试及类型检查、生产构建均通过。

### 002-check-driven-dead-code-cleanup — 2026-08-22

- 删除已确认无生产调用的后端函数、测试专用兼容包装与未引用的 `SmokeyBackground.vue`。
- 移除应用直接依赖 `dayjs` 与未使用测试依赖 `pytest-asyncio`，保留 Ant Design Vue 必需的传递 `dayjs`。
- RapidOCR 仅使用 requirements 已声明的 `rapidocr_onnxruntime`；后端 162 项、前端 94 项测试及类型检查、生产构建均通过。

### 004-memory-rate-limit — 2026-08-22

- 新增进程内存限流防刷基础：固定窗口限流、一次性 Nonce、登录失败 IP 封禁、IP Block 中间件与有界存储适配器。
- 套图/视频创建共享 20 次/分钟限流；改密与模拟支付要求前端生成唯一 `X-Request-Nonce`，Nginx 透传真实客户端 IP。
- 显式暴露内存后端单进程约束，`WEB_CONCURRENCY > 1` 时拒绝启动；后端、前端测试与类型检查通过。

### 005-rapidocr-model-path-fix — 2026-08-22

- 为 RapidOCR 构造补充 `det_model_path=None`，兼容当前已安装 1.2.x 在传入 `det_*` 参数时必须存在 `model_path` 键的行为。
- 保留已配置的 `text_score` 与 `det_box_thresh`，新增构造参数单测和真实 RapidOCR 预热回归。
- 管理端 OCR 预热恢复成功；专项测试、全量后端测试与 `pip check` 均通过。

### 008-redis-usage-optimization — 2026-08-23

- 优化现有安全态 Redis 使用（不引入新场景，维持 fail-closed 503 降级）：`config.py` 新增 7 项 `LISTINGO_REDIS_*` 配置（nonce_ttl / login_fail_window / login_block / sms_daily_window / sms_max_attempts / max_connections / health_check_interval）。
- 新增 `core/storage/keys.py` 集中键构造器（rate/nonce/login_*/sms:*），消除散落 f-string 字面量；`rate_limit.py` 与 `sms.py` 的 TTL/阈值改读 Settings，DB `SmsConfig` 仍 per-phone 覆盖优先。
- `redis.py` 支持显式 `max_connections` / `health_check_interval` 连接池配置；`docker-compose.yml` redis 新增 `--maxmemory-policy volatile-lru`（AOF 沿用）。
- 新增 `docs/REDIS_KEYS.md` 键清单/命名规范并纳入 `CONTEXT_SUMMARY` 索引；新增 7 项单测 + 受影响既有 43 项全绿，无回归。
