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
