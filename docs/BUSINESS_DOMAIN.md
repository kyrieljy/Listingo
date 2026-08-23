# BUSINESS_DOMAIN — 业务领域

> 本文件为骨架，业务事实以 `开发计划.md` / `TASKS.md` 为准。细节由后续 `doc-update` 补全。

## 领域模型（核心实体）

- **用户（User）**：注册/登录（短信或密码）、管理员短信二次验证、账号中心、套餐与额度。
- **订阅（Subscription）**：套餐（Plan）→ 价格（PlanPrice）→ 额度规则（PlanQuotaRule）→ 用户订阅（UserSubscription）→ 模拟订单（PaymentOrder）→ 额度台账（QuotaLedger）。
- **创意生产任务**：四期统一工作台入口 ——
  - **商品套图（Generation）**：上传 → 视觉事实抽取 → 核心规划 JSON → 语义校验 → 并发生图 → 结果/二次编辑/下载。
  - **A+ 详情页（Aplus）**：规划（aplus-meta 0729）→ 模块数量选择 → Web/移动端生成。
  - **视频（Video）**：分镜 Prompt → Seedance 2.0 submit/poll → mp4 落盘。
  - **Demo**：演示资产轻量生成。
- **批量托管（Batch）**：套图/A+ 批次创建 → 单进程 `BatchScheduler` 调度 → 取消/重试/恢复 → 整批 ZIP。
- **OCR 改字（ImageTextEdit）**：文本行检测 → `image-text-edit` 文字替换版本生成。
- **AI 水印（Watermark）**：免费用户默认带水印，付费/企业/管理员可下载无水印。
- **Provider / Prompt / Workflow**：外部模型适配器（47 预设）、8 类版本化 Prompt、Workflow 注册与版本；route chain 决定调用链路。

## 关键流程

1. **生产闭环**：上传 → 策略确认 → Dryrun/Live → Provider route chain → 结果 → 二次编辑/OCR 改字/水印下载/ZIP。
2. **内容安全**：本地关键词 + LLM 双重审查，不安全则拦截。
3. **版本固定**：每个任务创建时固定引用 Prompt/Workflow 版本，后台启用新版本不影响历史。
4. **批量调度**：进程内 `BatchScheduler`，`LISTINGO_MAX_ACTIVE_BATCH_ITEMS` 控制并发活跃 item；`provider_task_id` 支持重启续传。
5. **运营监控**：业务指标、用户钻取、Provider 成本与错误摘要（ECharts 图表）。

## 术语表

| 术语 | 含义 |
|---|---|
| Dryrun | 全局默认离线模式，不外调 Provider，仅生成本地资产 |
| Provider route chain | 按 route role（llm/suite_fidelity/...）与 slot（primary/backup1..4）组织的调用链 |
| route role | 调用角色：`llm`、`suite_fidelity`、`suite_layout`、`aplus_detail`、`aplus_mobile`、`image_edit`、`video` |
| Prompt 资产（8 类） | ecommerce-meta、aplus-meta、product-vision、copywriting-assist、edit-rewrite、image-text-edit、content-safety-review、ecommerce-video-meta-15s |
| 版本固定 | 历史任务引用创建时的 Prompt/Workflow 版本，不受后台启停影响 |
| 批量托管 | BatchJob/BatchItem 进程内调度，支持取消/重试/恢复/ZIP |
| OCR 改字 | 基于 PaddleOCR/RapidOCR 的文本检测与 `image-text-edit` 替换 |
| AI 水印 | 按用户等级控制是否带/去水印下载 |
| is_admin_test | 后台完整链路试跑标记，隔离于前台历史列表 |

> 更细流程与实体关系见 `docs/ARCHITECTURE.md` 与 `docs/DB_SCHEMA.md`。
