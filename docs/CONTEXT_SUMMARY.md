# CONTEXT_SUMMARY — 语义索引

> 本文件是 Listingo 项目的**文档单一入口（语义索引）**，由 `.coderules` §1 规定为权威文档索引。
> 职责：把「模块 / 能力 → 职责 → 关键文件路径」映射出来，让任何变更都能快速定位应同步的源码与文档。
>
> **文档状态说明（2026-08-22）**
> - `SPEC.md` 与 `README.md` 已从工作树删除（仍保留在 `git HEAD`），按当前决策**保持删除**；业务事实以 `TASKS.md`、`TECH_STACK.md`、`开发计划.md` 与当前源码为准。
> - 本索引的**内容型文档**（`ARCHITECTURE.md` / `API_REFERENCE.md` / `DB_SCHEMA.md` / `BUSINESS_DOMAIN.md`）尚未建立；本文件先行补齐语义索引，内容型文档按需由 `doc-update` 后续填充。
> - ⚠️ 已知偏差：`.coderules` §1 仍引用 `SPEC.md` 为权威摘要，与「SPEC.md 已删除」的现状不符，待后续统一（见文末「待办」）。

---

## 1. 权威文档映射

| 文档 | 状态 | 角色 |
|---|---|---|
| `TASKS.md` | 现行 | 当前能力清单、已完成项、本轮同步任务、服务器更新提醒（事实主源之一） |
| `TECH_STACK.md` | 现行 | 技术栈版本、架构边界、Provider/路由、Prompt 资产、环境变量、Batch Runtime |
| `开发计划.md` | 现行 | 四期实施计划、已交付阶段、运行原则、验收范围 |
| `design-qa.md` | 现行 | 设计 QA 验收标准 |
| `docs/CONTEXT_SUMMARY.md` | **本文件** | 语义索引（模块 → 职责 → 路径） |
| `docs/REDIS_KEYS.md` | 现行 | Redis 键命名规范与清单（安全态临时键） |
| `SPEC.md` | 已删除 | 原业务逻辑规格书（保留于 HEAD，不再作为工作树事实） |
| `README.md` | 已删除 | 原项目说明（保留于 HEAD，不再作为工作树事实） |

---

## 2. 后端模块索引（Backend · FastAPI + PostgreSQL）

入口与核心：`backend/app/`

| 模块 | 职责 | 关键文件 |
|---|---|---|
| 应用装配 | FastAPI 实例、 lifespan、挂载 `auth`/`public`/`admin` 三个路由 | `main.py` |
| 配置 | 环境变量、运行时配置、并发/上传/OCR 参数；双环境文件（默认加载 `.env.local`，`LISTINGO_ENV_FILE` 切生产），CORS/会话 TTL/Cookie Secure/调试短信码/短信超时/端口均从环境读取 | `config.py`、`.env.local`、`.env.production` |
| 限流防刷与临时安全状态 | Redis/Memory 存储适配器、固定窗口限流、Nonce 防重放、登录失败 IP 封禁、短信验证码哈希/尝试/冷却/滚动日限额 | `core/storage/`、`core/rate_limit.py`、`middleware/ip_block.py`、`services/sms.py` |
| 运行时派生状态（RuntimeStateService） | 热点配置/激活版本/套餐规则缓存、会话元数据、批量状态快照、分布式锁与实时计数；包装 `RateLimitStorage` 提供 JSON 缓存/版本失效/锁/计数，应用级默认实例装配于 `app.state.runtime_state` | `core/runtime.py`、`services/runtime_cache.py`、`services/metrics.py` |
| 数据库 | 同步 SQLAlchemy + psycopg2 PostgreSQL 引擎、连接池、会话、Base | `database.py` |
| 数据模型 | 全部 ORM 表（见 §4） | `models.py` |
| 请求/响应契约 | Pydantic Schema | `schemas.py` |
| 安全 | 密码哈希、JWT、API Key 加密与掩码 | `security.py` |
| 种子 | Provider / Prompt / Workflow seed 与 active 版本导出 | `seed.py` |

### API 路由层 — `backend/app/api/`

| 路由 | 前缀/职责 | 文件 |
|---|---|---|
| 认证 | 统一短信登录/注册（未注册手机号 `purpose=login` 验证通过即自动创建 active/free 账号，保留 `mode=register` 旧兼容）、密码登录、短信二次验证、账号中心（含飞书 Webhook 配置）、会话 | `auth.py` |
| 公开 | 工作台任务、上传、批量/workspace 配置、公开资产 | `public.py` |
| 管理 | Provider、Workflow、Prompt、用户、套餐、订单、监控、短信、OCR、运行配置 | `admin.py` |

### 服务层 — `backend/app/services/`

| 服务 | 职责 | 文件 |
|---|---|---|
| 套图任务 | 商品套图 Dryrun/Live 状态机、重试、取消、二次编辑 | `jobs.py` |
| 任务创建 | 套图/A+ 任务工厂与参数归一 | `job_creation.py` |
| 执行引擎 | Provider 调用编排、并发、回退、脱敏 | `execution.py` |
| A+ 详情页 | `aplus-meta` 0729 链路、模块解析、Web/移动端 route | `aplus_jobs.py` |
| 视频 | `ecommerce-video-meta-15s` + Seedance 2.0 submit/poll/mp4 | `video_jobs.py` |
| OCR 改字 | 文本检测、文字替换版本、`image-text-edit`、RapidOCR 1.2.x/1.4.x 构造兼容 | `image_text_edit.py` |
| 内容安全 | 本地关键词 + LLM 审查 | `content_safety.py` |
| 敏感词检测 | 运营可配置敏感词清单、变体生成、Aho-Corasick 快照匹配、套图/A+/视频卖点与上传 OCR 文本预检、图片安全布尔字段阻断；OCR 全局单例与启动自动预热 | `sensitive_words.py`、`sensitive_preflight.py`、`image_text_edit.py`（OCR 单例） |
| 水印 | AI 水印下载权限规则 | `watermarking.py` |
| 批量托管 | `BatchJob`/`BatchItem`、入队、取消、重试、恢复、ZIP | `batch_jobs.py`、`batch_execution.py`、`generation_queue_service.py` |
| 工作区恢复 | 重启后按 `provider_task_id` 续传/下载；保留 `queued` 任务以供队列重建，仅 `running`/`cancelling` 判定为中断 | `workspace_recovery.py` |
| 生图 / 生视频缓冲队列 | `UnifiedGenerationQueueScheduler`：两条相互独立的 Redis FIFO 队列；生图队列同时保存普通生图 `job_id` 与批量 `batch_item:{item_id}` token，两条队列各一个顺序 worker，启动按 PostgreSQL 时间戳混合重建，终态写入站内信；入队失败 fail-closed 并补偿释放额度 | `generation_queue_service.py`、`generation_queues.py`、`core/storage/keys.py`（`queue_key`）；批量项执行与恢复：`batch_execution.py`（`BatchItemExecutor`） |
| Provider 目录 | 47 个源码预设、route roles、slot 映射 | `provider_catalog.py`、`provider_routing.py`、`providers.py` |
| 并发限制 | 进程级 `ProviderConcurrencyLimiter`（普通/A+/子编辑/OCR/批量共享） | `provider_limiter.py` |
| Prompt 资产 | 8 类 Prompt 版本化、契约校验、JSON 修复 | `prompt_contract.py`、`prompt_testing.py`、`workflow_registry.py` |
| 账号/套餐 | 订阅、额度台账、模拟支付订单 | `subscriptions.py`、`auth.py`（service） |
| 短信 | 管理员短信二次验证、短信配置（含任务完成 `notify_template_code`）；验证码与防刷临时状态在 Redis；任务完成通知短信走独立通道、不占验证码日限额 | `sms.py` |
| 通知 | 通知中心事件 + 任务终态三渠道分发（站内信 / 短信 / 飞书 Webhook），文案同源 `build_task_result_title`；外部通知 fail-silent（仅记日志、不重试、不进 reconcile） | `notifications.py` |
| 存储 | 上传校验、图片写盘、Dryrun 资产、结果落盘 | `storage.py` |
| 脱敏日志 | 日志敏感信息掩码 | `redaction.py` |
| 运营分析 | 业务指标、用户钻取、Provider 成本/错误摘要 | `analytics.py` |

### 资产与提示词

| 资产 | 路径 / 说明 |
|---|---|
| 源码 Provider 目录 | `backend/app/providers/`（共 47 个预设；5 个 legacy 仅存 DB，不计入源码事实） |
| Prompt 资产（8 类） | `backend/app/prompts/`：`ecommerce-meta`、`aplus-meta`(→`aplus_meta_prompt_0729.md`)、`product-vision`、`copywriting-assist`、`edit-rewrite`、`image-text-edit`、`content-safety-review`、`ecommerce-video-meta-15s` |
| 静态资源 | `backend/app/static/demo/`、`backend/app/static/watermarks/` |

---

## 3. 前端模块索引（Frontend · Vue 3 + Vite + TS + Ant Design Vue）

入口：`frontend/src/main.ts`、`frontend/src/router/index.ts`、`frontend/src/api/client.ts`

| 能力域 | 职责 | 关键文件（`frontend/src/features/`） |
|---|---|---|
| 工作台 `/app` | 四期统一工作台：套图、A+ 详情页、视频、Demo 面板、批量托管、OCR 改字、水印下载、结果网格、环境感知生成失败提示（统一顶部 `message`，生产仅兜底文案）、水印关闭「我已知悉」确认、视频重试 2 秒防误触冷却 | `workspace/WorkspaceView.vue`、`APlusPhasePanel.vue`、`VideoPhasePanel.vue`、`DemoPhasePanel.vue`、`BatchHostingModal.vue`、`BatchHistoryDrawer.vue`、`ImageTextEditPanel.vue`、`WatermarkDownloadMenu.vue`、`ResultGrid.vue`；状态 `workspace-model.ts`、`generation-errors.ts`、`batch-model.ts`、`analytics.ts` |
| 账号 `/auth` | 统一登录/注册弹窗（无显式注册模式，短信登录自动开户、密码登录）、账号中心（含飞书 Webhook 输入）、套餐弹窗、用户菜单、会话 store | `auth/AuthModal.vue`、`AccountModal.vue`、`PricingModal.vue`、`UserMenu.vue`、`auth-store.ts`、`auth-model.ts` |
| 运营后台 `/admin` | Provider 分组、Prompt 上传/版本比较/试跑、Workflow、日志、运行配置、短信/OCR/用户/套餐/订单、监控图表、敏感词检测（含批量导入） | `admin/AdminView.vue`、`SensitiveWordsPanel.vue`、`sensitive-words-model.ts`、`MonitoringDashboard.vue`、`MonitoringLineChart.vue`、`SharePieChart.vue`、`ComparisonMatrix.vue`、`MetricKpiStrip.vue`、`UserDrilldownPanel.vue`、`provider-display.ts`、`monitoring-data.ts` |
| 基础设施 | HTTP 客户端、路由、全局样式 | `api/client.ts`、`router/index.ts`、`styles/` |

---

## 4. 数据模型摘要（PostgreSQL · `backend/app/models.py`）

> 当前 Alembic head 为 `a7c4e9f21b68`（补齐 PostgreSQL schema 索引与外键）。业务数据只允许外部 PostgreSQL；旧 SQLite 备份仅审计保留。

| 分组 | 表 |
|---|---|
| 账号/安全 | `User`（含 `feishu_webhook` 明文列）、`UserSession`、`LoginEvent` |
| 分析/通知 | `AnalyticsEvent`、`Notification` |
| 短信配置 | `SmsConfig`（含任务完成 `notify_template_code`；验证码本体与计数在 Redis） |
| 敏感词检测 | `SensitiveWordConfig`（单例开关/上限）、`SensitiveWord`、`SensitiveWordSnapshot`（最近 20 版 JSON 回源，Redis 丢失时重建） |
| 订阅/计费 | `SubscriptionPlan`、`PlanPrice`、`PlanQuotaRule`、`UserSubscription`、`PaymentOrder`、`QuotaLedger` |
| Provider/Prompt | `Provider`、`Prompt`、`PromptVersion`、`PromptTestRun`、`Workflow`、`WorkflowVersion` |
| 资产/任务 | `Asset`、`GenerationJob`、`GenerationItem`、`GenerationVersion`、`VideoJob`、`VideoItem`、`VideoVersion`、`AplusJob`、`AplusItem`、`AplusVersion`、`BatchJob`、`BatchItem`、`ExecutionLog` |

---

## 5. 最近变更（索引保鲜行）

| 日期 | 变更 | 来源 |
|---|---|---|
| 2026-08-31 | `archive/016-task-completion-multi-channel-notify`：任务终态通知扩展为站内信 / 短信 / 飞书三渠道同源。`notifications.py` 新增 `build_task_result_title`（文案单一事实源）与 `notify_task_completion_external`（飞书 POST + 阿里云通知短信，失败仅记日志、不重试、不进 reconcile）；`sms.py` 新增 `send_sms_notification`（复用 `notify_template_code`，不占验证码日限额）；`User.feishu_webhook` + `SmsConfig.notify_template_code` 两列（迁移 `d1e2f3a4b5c6`），个人中心新增飞书 Webhook 输入 | archive |
| 2026-08-31 | `archive/013-batch-generation-queue`：批量套图 / A+ item 以 `batch_item:{item_id}` 并入统一生图 Redis FIFO，与普通生图共用唯一顺序 worker（新增 `UnifiedGenerationQueueScheduler`，移除生产 `BatchScheduler`，执行抽取为 `BatchItemExecutor`）；创建 / retry 只入队即返回，取消仅 queued 可成功、running 返回 409，部分入队失败 fail-closed 503；父任务终态一条幂等站内信 | archive |
| 2026-08-31 | `archive/012-unified-phone-login-registration`：短信登录与首次注册合并——未注册手机号 `purpose=login` 验证通过即自动创建 active/free 用户、通知、会话与登录事件，并发首次登录复用胜出用户；保留 `mode=register` / `/auth/register` 兼容；前端移除显式注册模式与注册两步表单 | archive |
| 2026-08-31 | `archive/011-video-retry-error-notices-watermark-confirm`：视频「重试失败」首点即提交 + 2 秒防误触冷却（期间隐藏取消入口）；套图 / A+ / 视频生成失败统一走顶部 `message`（开发保留明细、生产固定兜底文案，结果区不再渲染原始异常）；订阅用户关闭 AI 水印需勾选「我已知悉」确认弹窗 | archive |
| 2026-08-31 | `archive/009-redis-scenario-expansion`：落地六类 Redis 场景，约束改为「PostgreSQL 事实 + Redis 派生态」。新增 `core/runtime.py::RuntimeStateService`（缓存 / 版本 / 锁 / 计数，装配于 `app.state.runtime_state`）、`services/runtime_cache.py`、`services/metrics.py`；覆盖 Provider / Prompt / 套餐热点缓存、会话元数据、批量详情、分布式锁（认领 / 额度 / 订单 / 支付）、实时计数与 OCR 结果指纹缓存；缓存与计数 fail-open、锁 fail-closed 503 | archive |
| 2026-08-31 | `archive/003-environment-config-files`：新增逐项注释的 `.env.local` / `.env.production`，`Settings` 默认加载前者、`LISTINGO_ENV_FILE` 切后者；CORS / 会话 TTL / Cookie Secure / 调试短信码 / 短信超时 / 端口全部改为读配置，Compose 与 Uvicorn / Vite / Nginx 统一取 `LISTINGO_PORT`；新增 `test_config.py` | archive |
| 2026-08-30 | `archive/015-batch-import-sensitive-words`：运营后台「敏感词」新增「批量导入」卡片——多行文本框按换行或逗号（含中文逗号）切分，后端 `POST /admin/sensitive-words/bulk` 一次性建词（`terms/enabled/note`），按 `normalized_term` 去重、跳过已存在与空项、超长/无效计入 `errors`；为避免大批量超时，快照重建移交 `BackgroundTasks` 异步执行，请求立即返回 `rebuild_scheduled=true`，前端 `bulkCreateSensitiveWords` 单独设 `timeout:180_000`；返回 `created/skipped/total/errors/rebuild_scheduled/snapshot`。前端 `SensitiveWordsPanel.vue` 新增卡片与 `bulkCreateSensitiveWords`/`splitBulkTerms`（`sensitive-words-model.ts`），新增后端测试 `test_sensitive_word_bulk.py`（含 300 词大批量回归） | archive |
| 2026-08-30 | `archive/014-sensitive-information-detection`：运营后台新增「敏感词」栏目（全局开关、词 CRUD、人工别名、实时变体预览、快照状态与重建）；套图/A+/视频/批量创建在 quota 预留与入队前完成卖点文本 + 上传图片 OCR 敏感词检测，命中返回 422「包含敏感信息」且不留 quota/不入队；新增 `SensitiveWordConfig`/`SensitiveWord`/`SensitiveWordSnapshot` 三表与无 TTL 常驻 Redis 快照（`sensitive:words:meta`/`snapshot`），检测仅消费快照、Aho-Corasick 一次扫描多文本视图；套图/A+ 商品视觉事实新增 `is_pornography`/`is_violence`/`is_politics` 布尔字段阻断（默认 0 兼容旧 Prompt）；OCR 改为进程级单例并启动自动预热，OCR 配置变更清理旧实例并重预热；`docs/REDIS_KEYS.md` 新增常驻快照键段 | archive |
| 2026-08-30 | `archive/013-batch-generation-queue`：批量套图与批量 A+ item 以 `batch_item:{item_id}` 并入统一生图 Redis FIFO，与普通生图共用唯一顺序 worker；批量创建 / 重试只入队并立即返回，等待中可取消、生成中返回 409，父任务终态幂等通知；启动按 PostgreSQL 时间戳混合重建生图队列 | changes |
| 2026-08-29 | `archive/012-unified-phone-login-registration`：短信登录与首次注册合并。未注册手机号通过 `purpose=login` 验证后自动创建 active/free 用户、注册通知、会话与 `sms` 登录事件；前端移除显式注册模式，保留密码登录与旧注册 API 兼容 | changes |
| 2026-08-29 | `changes/010-generation-video-buffer-queues`：生图 / 生视频外部 API 调用改为两条独立 Redis FIFO 缓冲队列。创建与 retry-failed 入队后立即返回 `queued`（不再 `BackgroundTasks` 同步执行），worker 条件认领为 `running` 并顺序执行，终态写入站内信；取消语义收紧为「`queued` 可取消 / `running` 返回 409」，`workspace_recovery` 保留 `queued` 供队列重建；前端提交/重试后提示「任务已在后台运行」，取消入口仅 `queued` 可见。`docs/REDIS_KEYS.md` 新增「队列缓冲」键段与队列保护运维约定 | changes |
| 2026-08-22 | 建立 `docs/CONTEXT_SUMMARY.md` 语义索引（响应 `/doc-update`）；确认 `SPEC.md`/`README.md` 保持删除，权威文档收敛为 `TASKS.md`/`TECH_STACK.md`/`开发计划.md` | doc-update |
| 2026-08-23 | `archive/009-redis-scenario-expansion`：落地 `redis-analysis.md` 第二节六类 Redis 场景——热点缓存（Provider/Prompt/Workflow/套餐/规则）、任务状态缓存、会话缓存、分布式锁（批量认领/额度预留/订单创建/模拟支付）、实时计数与 OCR 结果缓存；新增 `core/runtime.py`（`RuntimeStateService`）、`services/runtime_cache.py`、`services/metrics.py`，`keys.py` 扩展 cache/session/batch/lock/metric 构造器，`config.py` 新增 7 项 TTL 配置，`main.py` 装配 `app.state.runtime_state`；约束演进为「PostgreSQL 事实 + Redis 派生态」，缓存/计数 fail-open、锁 fail-closed | changes |
| 2026-08-23 | `changes/006-redis-rate-limit-verification`：新增 Compose Redis、`LISTINGO_REDIS_URL`、Redis 存储适配器；限流/Nonce/封禁与短信验证码临时状态迁往 Redis，删除 SQLite `sms_verification_code` 表 | changes |
| 2026-08-23 | `changes/007-sqlite-to-postgresql-migration`：切换为外部 PostgreSQL-only 配置、Alembic schema 对齐、SQLite 数据迁移脚本、PostgreSQL 临时测试库与启动版本校验；SQLite 在迁移后弃用 | changes |
| 2026-08-23 | `archive/008-redis-usage-optimization`：安全态 Redis 使用优化——7 项 `LISTINGO_REDIS_*` 配置可配置化、集中键构造器 `keys.py`、显式连接池（`max_connections`/`health_check_interval`）、`docker-compose` 增 `volatile-lru`、新增 `docs/REDIS_KEYS.md`；维持 fail-closed 503，未引入新场景 | archive |
| 2026-08-22 | `archive/005-rapidocr-model-path-fix`：补充 RapidOCR `det_model_path=None` 兼容参数，管理端 OCR 预热与真实包回归恢复通过 | archive |
| 2026-08-22 | `archive/004-memory-rate-limit`：新增进程内存限流防刷适配器、套图/视频共享限流、Nonce 防重放、登录失败 IP 封禁与 Nginx 客户端 IP 透传 | archive |
| 2026-08-22 | `archive/001-report-driven-safe-optimizations`：后端目标链路补齐参数/返回类型，Workspace 请求错误收紧为 `unknown`，Provider 动态 JSON 具体类型化；拒绝 AsyncSession 全量迁移 | archive |
| 2026-08-22 | `archive/003-environment-config-files`：新增本地/生产 env 文件，CORS、会话安全、短信安全/超时与端口配置迁入环境变量和编排配置 | changes |
| 2026-08-19 | `ca0a374` Sync active prompts and deployment docs：8 类源码 Prompt 与 SQLite active 版本哈希对齐，部署文档同步 | git HEAD |
| 2026-08-22 | `archive/002-check-driven-dead-code-cleanup`：删除已确认无生产调用的组件/函数与未使用直接依赖，保留 Provider/OCR 运行路径与同步 SQLAlchemy 架构 | changes |

---

## 6. 待办 / 偏差

- [ ] **`.coderules` §1 偏差**：仍写「`SPEC.md` 为权威摘要」，与 SPEC.md 已删除现状冲突；建议将 §1 改为引用 `TASKS.md`/`TECH_STACK.md` 为权威，或显式标注 SPEC.md 已弃用。
- [ ] 内容型文档未建：`ARCHITECTURE.md`、`API_REFERENCE.md`、`DB_SCHEMA.md`、`BUSINESS_DOMAIN.md` 待后续 `doc-update` 从源码增量填充。
- [ ] `changes/` 仍滞留 3 个变更，均因质量门禁未过而**未归档**：
  - `006-redis-rate-limit-verification` — 3 项 `[FAIL]`，Docker Compose 运行时验证未执行。
  - `007-sqlite-to-postgresql-migration` — 1 项 `[FAIL]`（Compose 后端连接校验外部 PostgreSQL）。
  - `010-generation-video-buffer-queues` — 25 项全部 `[ ]` 未开始，且缺 `result.md`（注：其队列能力实际已随 `013` 落地并在 `013` 中回归验证，`changes/010` 目录本身未回填）。
- [ ] `archive/` 已收录 001–005、008、009、011–016。
