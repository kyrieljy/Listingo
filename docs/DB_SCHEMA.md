# DB_SCHEMA — 数据库设计

> 本文件为骨架，权威 DDL 见 `backend/app/models.py`。完整字段由后续 `doc-update` 从模型抽取补全。
> 当前 Alembic head 为 `d1e2f3a4b5c6`（add_task_notify_channels）。

## 约定

- 数据库类型：PostgreSQL 17（本机/私有化唯一持久化源）。
- ORM：SQLAlchemy 2.0（同步会话）。
- 迁移：Alembic（`backend/alembic.ini`，script_location = `backend/migrations`，版本位于 `backend/migrations/versions/`）。
- 命名：`Base` + `TimestampMixin`（含 `created_at`/`updated_at`）；表名 snake_case。
- 不提交：`.secret_key` 不进入 Git；运行时 DB 为外部 PostgreSQL。`data/listingo.sqlite3` 为 SQLite→PostgreSQL 切换前的遗留库（已 gitignore、非运行时库、可删），审计备份仅 `data/backups/*.sqlite3` 不提交。

## 表结构（按业务分组）

> 下表为「表 → 主要职责」映射；逐字段定义见 `models.py`。分组与 `CONTEXT_SUMMARY.md` §4 对应。

### 账号 / 安全
| 表 | 职责 |
|---|---|
| `User` | 用户主表（密码哈希、角色、额度引用） |
| `UserSession` | 会话 |
| `LoginEvent` | 登录事件审计 |

### 分析 / 通知
| 表 | 职责 |
|---|---|
| `AnalyticsEvent` | 前端埋点事件 |
| `Notification` | 通知中心 |

### 短信
| 表 | 职责 |
|---|---|
| `SmsConfig` | 短信渠道配置（验证码本体与计数在 Redis，见 `docs/REDIS_KEYS.md`） |

### 订阅 / 计费
| 表 | 职责 |
|---|---|
| `SubscriptionPlan` | 套餐定义 |
| `PlanPrice` | 套餐价格档 |
| `PlanQuotaRule` | 套餐额度规则 |
| `UserSubscription` | 用户订阅实例 |
| `PaymentOrder` | 模拟支付订单 |
| `QuotaLedger` | 额度台账（消耗/恢复） |

### Provider / Prompt / Workflow
| 表 | 职责 |
|---|---|
| `Provider` | Provider 预设与启用状态（源码 47 预设；DB 可含 5 legacy） |
| `Prompt` | 8 类 Prompt 资产 |
| `PromptVersion` | Prompt 版本（active 引用） |
| `PromptTestRun` | Prompt 试跑记录 |
| `Workflow` | Workflow 注册 |
| `WorkflowVersion` | Workflow 版本 |

### 资产 / 任务
| 表 | 职责 |
|---|---|
| `Asset` | 上传商品图资产 |
| `GenerationJob` / `GenerationItem` / `GenerationVersion` | 商品套图任务/项/版本 |
| `VideoJob` / `VideoItem` / `VideoVersion` | 视频任务/项/版本 |
| `AplusJob` / `AplusItem` / `AplusVersion` | A+ 详情页任务/项/版本 |
| `BatchJob` / `BatchItem` | 批量托管任务/项 |
| `ExecutionLog` | 任务执行日志（脱敏） |

## 关系要点

- `User` 1—N `UserSubscription`、`PaymentOrder`、`QuotaLedger`、`AnalyticsEvent`、`LoginEvent`、`Notification`。
- 任务族（Generation/Video/Aplus/Batch）各自 `Job` 1—N `Item`；`Item` 1—N `Version`；`Version` 固定引用创建时的 `PromptVersion`/`WorkflowVersion`。
- `Provider` 经 route chain（`provider_routing.py`）被任务调用；异步任务通过 `provider_task_id` 支持重启恢复。
- `Prompt` 1—N `PromptVersion`（active 指向当前启用版本）；`Workflow` 同理。

> 字段级 DDL、索引、约束待 `doc-update` 抽取补全。
