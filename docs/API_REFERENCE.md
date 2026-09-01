# API_REFERENCE — API 参考

> 本文件为骨架，端点路径提取自 `backend/app/api/{auth,public,admin}.py`（源码为权威）。深层请求/响应 Schema 由后续 `doc-update` 补全。
> 基础前缀：`/api/v1`；后台路由额外要求 `require_admin`。

## 约定

- 鉴权：Bearer JWT（`Authorization` 头）；后台端点额外依赖 `Depends(require_admin)`。
- 内容类型：`application/json`；上传走 `multipart/form-data`。
- 路由前缀：
  - 认证/账号：`/api/v1`（auth.py）
  - 公开/工作台：`/api/v1`（public.py，tag=generation）
  - 运营后台：`/api/v1/admin`（admin.py，tag=admin）

## 接口列表

### 认证与账号 — `auth.py`（`/api/v1`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/sms/send` | 发送短信验证码 |
| POST | `/auth/sms/login` | 短信验证码登录 |
| POST | `/auth/register` | 注册 |
| POST | `/auth/password/login` | 密码登录 |
| POST | `/auth/first-password` | 首次设置密码 |
| POST | `/auth/logout` | 登出 |
| GET  | `/auth/me` | 当前用户 |
| PATCH| `/account/profile` | 修改资料 |
| POST | `/account/change-phone/start` | 改绑手机-发起 |
| POST | `/account/change-phone/confirm` | 改绑手机-确认 |
| POST | `/account/password` | 修改密码 |
| GET  | `/account/login-events` | 登录事件 |
| GET  | `/subscription/plans` | 套餐列表 |
| GET  | `/subscription/me` | 我的订阅 |
| GET  | `/quota/me` | 我的额度 |
| POST | `/subscription/orders` | 创建模拟支付订单 |
| POST | `/subscription/orders/{order_id}/mock-pay` | 模拟支付 |
| GET  | `/notifications` | 通知列表 |
| POST | `/notifications/{notification_id}/read` | 标记已读 |
| POST | `/notifications/read-all` | 全部已读 |
| POST | `/account/feishu-webhook/test` | 飞书 Webhook 连通性测试 |

### 公开 / 工作台 — `public.py`（`/api/v1`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/workspace-config` | 上传/批量限制（公开） |
| POST | `/analytics/events` | 埋点事件 |
| POST | `/assets` | 上传商品图资产 |
| POST | `/batch-jobs` | 创建批量托管任务 |
| GET  | `/batch-jobs` | 批量任务列表 |
| POST | `/batch-jobs/validation-fixtures` | 批量校验 fixtures |
| GET  | `/batch-jobs/selection-download` | 批量选择下载 |
| GET  | `/batch-jobs/{batch_id}` | 批量任务详情 |
| POST | `/batch-jobs/{batch_id}/cancel` | 取消批量 |
| POST | `/batch-jobs/{batch_id}/retry-failed` | 重试失败项 |
| GET  | `/batch-jobs/{batch_id}/download` | 批量 ZIP 下载 |
| POST | `/generation-jobs` | 创建商品套图任务 |
| GET  | `/generation-jobs` | 套图任务列表 |
| GET  | `/generation-jobs/{job_id}` | 套图任务详情 |
| POST | `/generation-jobs/{job_id}/cancel` | 取消套图 |
| POST | `/generation-jobs/{job_id}/retry-failed` | 重试失败项 |
| GET  | `/generation-jobs/{job_id}/download` | 套图下载 |
| POST | `/generation-items/{item_id}/retry` | 单图重试 |
| POST | `/generation-items/{item_id}/text-ocr` | OCR 文本检测 |
| POST | `/generation-items/{item_id}/text-versions` | 文字替换版本 |
| POST | `/generation-items/{item_id}/versions` | 单图二次编辑版本 |
| POST | `/copywriting-assist` | 帮写辅助 |
| POST | `/aplus-plan-jobs` | A+ 规划任务 |
| GET  | `/aplus-plan-jobs` | A+ 规划列表 |
| GET  | `/aplus-plan-jobs/{job_id}` | A+ 规划详情 |
| POST | `/aplus-plan-jobs/{job_id}/cancel` | 取消 A+ 规划 |
| POST | `/aplus-generation-jobs` | A+ 生成任务 |
| GET  | `/aplus-generation-jobs` | A+ 生成列表 |
| GET  | `/aplus-generation-jobs/{job_id}` | A+ 生成详情 |
| POST | `/aplus-generation-jobs/{job_id}/cancel` | 取消 A+ 生成 |
| POST | `/aplus-generation-jobs/{job_id}/retry-failed` | 重试失败项 |
| GET  | `/aplus-generation-jobs/{job_id}/download` | A+ 下载 |
| POST | `/aplus-items/{item_id}/retry` | A+ 单 item 重试 |
| POST | `/aplus-items/{item_id}/text-ocr` | A+ OCR |
| POST | `/aplus-items/{item_id}/text-versions` | A+ 文字版本 |
| POST | `/aplus-items/{item_id}/versions` | A+ 派生版本 |
| POST | `/video-copywriting-assist` | 视频帮写 |
| POST | `/video-jobs` | 视频任务 |
| GET  | `/video-jobs` | 视频列表 |
| GET  | `/video-jobs/{job_id}` | 视频详情 |
| POST | `/video-jobs/{job_id}/cancel` | 取消视频 |
| POST | `/video-jobs/{job_id}/retry-failed` | 重试失败项 |
| GET  | `/video-jobs/{job_id}/download` | 视频下载 |
| POST | `/video-items/{item_id}/versions` | 视频派生版本 |

### 运营后台 — `admin.py`（`/api/v1/admin`，需 admin）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/ops-monitoring` | 运营监控 |
| GET  | `/business-metrics` | 业务指标 |
| GET  | `/business-metrics/users` | 用户钻取 |
| GET  | `/business-metrics/users/{user_id}` | 单用户指标 |
| GET  | `/providers` | Provider 列表 |
| GET  | `/provider-groups` | Provider 分组 |
| PATCH| `/provider-routes/{route_key}/chain` | 设置 route chain |
| GET  | `/runtime-settings` | 运行时配置 |
| PATCH| `/runtime-settings` | 修改运行时配置 |
| GET  | `/ocr-settings` | OCR 配置 |
| PATCH| `/ocr-settings` | 修改 OCR 配置 |
| POST | `/ocr-settings/prewarm` | OCR 预热 |
| POST | `/ocr-settings/cache/clear` | OCR 清缓存 |
| PATCH| `/providers/{provider_id}` | 修改 Provider |
| POST | `/providers/{provider_id}/test` | Provider 试跑 |
| POST | `/provider-groups/{group_key}/health-check` | 分组健康检查 |
| GET  | `/users` | 用户列表 |
| PATCH| `/users/{user_id}` | 修改用户 |
| GET  | `/subscription-plans` | 套餐管理 |
| PATCH| `/subscription-plans/{plan_id}` | 修改套餐 |
| PATCH| `/quota-rules/{rule_id}` | 修改额度规则 |
| GET  | `/payment-orders` | 订单列表 |
| GET  | `/sms-settings` | 短信配置 |
| PATCH| `/sms-settings` | 修改短信配置 |
| POST | `/sms-settings/test-send` | 短信试发 |
| POST | `/notifications/broadcast` | 广播通知 |
| GET  | `/prompts` | Prompt 列表 |
| GET  | `/prompts/{prompt_id}` | Prompt 详情 |
| POST | `/prompts/{prompt_id}/versions` | 新建 Prompt 版本 |
| POST | `/prompts/{prompt_id}/versions/upload` | 上传 Prompt 版本（UTF-8） |
| GET  | `/prompts/{prompt_id}/compare` | 版本比较 |
| POST | `/prompts/{prompt_id}/versions/{version_id}/activate` | 启用版本 |
| POST | `/prompts/{prompt_id}/test-runs` | Prompt 试跑 |
| GET  | `/prompt-test-runs/{run_id}` | 试跑详情 |
| GET  | `/prompts/{prompt_id}/test-runs` | 试跑列表 |
| GET  | `/workflows` | Workflow 列表 |
| GET  | `/workflows/{workflow_id}` | Workflow 详情 |
| POST | `/workflows/{workflow_id}/versions` | 新建 Workflow 版本 |
| POST | `/workflows/{workflow_id}/versions/{version_id}/activate` | 启用版本 |
| POST | `/workflows/{workflow_id}/versions/{version_id}/dryrun` | Workflow 试跑 |
| GET  | `/logs` | 运行日志 |

#### 敏感词检测 — `admin.py`（`/api/v1/admin`，需 admin）

> 由 `changes/014-sensitive-information-detection` / `015-batch-import-sensitive-words` 引入（套图/A+/视频/批量创建在 quota 预留与入队前完成卖点文本 + 上传图片 OCR 敏感词检测）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/sensitive-words` | 敏感词列表 |
| POST | `/sensitive-words/preview` | 变体实时预览 |
| POST | `/sensitive-words` | 新建敏感词 |
| POST | `/sensitive-words/bulk` | 批量导入敏感词 |
| PATCH| `/sensitive-words/settings` | 全局开关 / 上限配置 |
| PATCH| `/sensitive-words/{word_id}` | 修改敏感词 |
| DELETE | `/sensitive-words/{word_id}` | 删除敏感词 |
| POST | `/sensitive-words/snapshot/rebuild` | 重建 Aho-Corasick 快照 |

> 响应模型定义在 `backend/app/schemas.py`；完整字段与错误码待 `doc-update` 补全。
