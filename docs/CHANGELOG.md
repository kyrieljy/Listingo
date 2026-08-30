# CHANGELOG — 变更日志

> 本文件由 `archive` Skill 在每次变更归档时增量更新。此处为初始种子（来自 `git log`，仅作历史锚点）。
> 语义索引与模块映射见 `docs/CONTEXT_SUMMARY.md`。

## 文档骨架建立（2026-08-22 · init / doc-update）

- 建立 `docs/` 全套骨架：`CONTEXT_SUMMARY.md`（语义索引）、`ARCHITECTURE.md`、`API_REFERENCE.md`、`DB_SCHEMA.md`、`BUSINESS_DOMAIN.md`、`AGENTS.md`、`CHANGELOG.md`。
- 确认 `SPEC.md`/`README.md` 保持删除；权威事实源收敛为 `TASKS.md` / `TECH_STACK.md` / `开发计划.md` 与当前源码。

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

### 014-sensitive-information-detection — 2026-08-30
- 运营后台新增「敏感词」栏目：全局开关、词 CRUD、人工别名、实时变体预览、快照状态与重建；套图/A+/视频/批量创建在 quota 预留与入队前完成卖点文本 + 上传图片 OCR 敏感词检测，命中返回 422「包含敏感信息」且不留 quota/不入队。新增 `SensitiveWordConfig`/`SensitiveWord`/`SensitiveWordSnapshot` 三表与无 TTL 常驻 Redis 快照（`sensitive:words:meta`/`snapshot`）；Aho-Corasick 一次扫描多文本视图；套图/A+ 商品视觉事实新增 `is_pornography`/`is_violence`/`is_politics` 布尔字段阻断（默认 0 兼容旧 Prompt）。OCR 改为进程级单例并启动自动预热，配置变更清理旧实例并重预热。`docs/REDIS_KEYS.md` 新增常驻快照键段；迁移 head：`c0a1b2c3d4e5`。

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
