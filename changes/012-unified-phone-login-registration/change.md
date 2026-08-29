# Change: Unified Phone Login And Registration

Date: 2026-08-29

## 变更标题

将短信登录与首次注册合并为一个手机号验证流程，未注册手机号首次验证通过后自动创建账号并登录。

## 变更背景 / 上下文

- 来源需求：当前登录和注册是两个独立流程；若手机号在系统中不存在，第一次登录时应自动完成注册，无需先注册再登录。
- 语义索引定位：`docs/CONTEXT_SUMMARY.md` 将认证能力映射到 `backend/app/api/auth.py`、`backend/app/services/auth.py`、`frontend/src/features/auth/`。
- 后端现状：
  - `backend/app/api/auth.py` 的 `/auth/sms/login` 根据 `payload.mode` 选择验证码用途：`register` 模式使用 `purpose=register`，默认登录使用 `purpose=login`。
  - 默认登录模式在查不到 `User.phone` 时返回 `404 该手机号尚未注册，请先注册`；只有显式注册模式才调用 `_create_user()`。
  - `_create_user()` 已具备手机号归一化、默认用户名、免费套餐、注册通知等开户能力，无需新增数据库表或迁移。
  - `backend/app/services/sms.py` 的验证码哈希、尝试次数、冷却和日限额都按 `phone + purpose` 隔离；只改用户创建而不收敛发送/验证用途，会导致前端发送 `login` 验证码但后端无法完成自动注册流程。
- 前端现状：
  - `frontend/src/features/auth/AuthModal.vue` 维护 `login | register` 双模式；注册模式下短信和密码表单都会请求 `purpose=register`。
  - 密码注册是独立两步流程，收集用户名、密码、手机号和验证码后调用 `/auth/register`。
  - 顶层入口文案已经是 `登录 / 注册`，实际上仍只有一个弹窗内的显式注册分支。
- 当前工作树存在大量与认证无关的未提交变更；本变更实现时不得回退或混入这些改动。

## 目标

- 用户只输入手机号和短信验证码即可完成登录或首次开户。
- 对系统不存在的手机号，首次通过 `purpose=login` 验证后自动创建 active/free 用户、注册通知、会话和登录事件。
- 已存在手机号继续按原短信登录语义签发会话，不重复创建用户。
- 前端认证弹窗只保留登录主流程：短信登录用于新老手机号，密码登录服务于已设置密码的既有账号。
- 保持验证码安全语义不变：一次性消费、错误次数、冷却、滚动日限额、手机号校验和会话签发逻辑不放松。

## 方案设计

### 涉及文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/api/auth.py` | 修改 | 将默认 `/auth/sms/login` 改为 `purpose=login` 验证并自动开户；兼容处理旧 `mode=register` 请求的验证码用途。 |
| `backend/app/schemas.py` | 修改 | 如需澄清兼容语义，为 `SmsLoginCreate.mode` 标注默认值与废弃说明；不新增必填字段。 |
| `frontend/src/features/auth/AuthModal.vue` | 修改 | 删除注册模式状态、注册表单、模式切换文案和注册验证码状态；短信验证码统一请求 `purpose=login`。 |
| `frontend/src/features/auth/auth-store.ts` | 修改 | 简化短信登录 payload 和成功提示，自动开户与老用户登录统一显示登录成功或可区分的首次登录提示。 |
| `frontend/src/api/client.ts` | 修改 | 收敛短信登录类型；仅在保留旧注册 API 兼容时保留对应函数。 |
| `frontend/src/features/workspace/WorkspaceView.vue` | 修改 | 移除认证弹窗的注册模式入口参数。 |
| `frontend/src/features/auth/auth-model.test.ts` | 修改 | 增加源码契约测试，防止注册模式回流。 |
| `backend/tests/test_sms_phone.py` | 修改 | 增加未注册手机号 `purpose=login` 自动开户测试，并更新受影响注册语义测试。 |
| `docs/CONTEXT_SUMMARY.md` | 修改 | 实现完成后同步账号能力描述：短信登录即首次注册，显式注册入口从主 UI 移除。 |
| `TASKS.md` | 修改 | 如能力清单需要表达认证流程变化，同步账号能力描述。 |

### 实现要点

1. **后端自动开户**
   - `/auth/sms/send` 主流程始终发送 `purpose=login` 验证码。
   - `/auth/sms/login` 先按请求模式确定旧验证码用途以兼容既有客户端：默认/`login` 使用 `login`，历史 `register` 请求继续使用 `register`。
   - 验证通过后归一化手机号并查询用户；不存在时调用 `_create_user(session, phone=phone)`，存在时复用原用户。
   - `_create_user()` 的唯一约束仍作为并发兜底；如捕获到手机号重复，应重新查询并复用用户，避免并发首次登录直接 409。
   - 创建后继续执行 active 校验、会话签发、`method=sms` 登录事件和提交事务，保持现有响应结构。
   - 不修改密码登录、管理员二次验证、换绑手机、账号中心和既有用户状态校验。

2. **前端流程收敛**
   - 移除 `AuthMode`、`initialMode`、`switchMode()`、注册验证码计时器和密码注册两步表单。
   - 弹窗标题固定为登录语义；短信标签文案可表述为「手机号登录 / 注册」，提交按钮为「登录」。
   - 短信验证码请求固定 `purpose='login'`，提交 `/auth/sms/login` 使用默认登录模式。
   - 保留密码登录 tab，用于已设置密码用户和管理员二次验证；未设置密码的新用户可在个人中心通过现有「设置登录密码」能力补设密码。
   - 顶层 `登录 / 注册` 入口打开同一个登录弹窗，不再携带注册模式。

3. **兼容与清理**
   - `/auth/register` 和密码注册 API 的去留见 Open Questions；实现阶段未确认前不得删除后端路由。
   - `SmsLoginCreate.mode` 未确认前也只作为兼容输入处理，不作为新 UI 的分支条件。
   - 保留 `purpose=register` 的后端短信能力以服务旧 API 兼容，避免已有验证码在发布窗口内失效。
   - 第三方登录占位、用户协议勾选、管理员首次密码提示和既有响应字段不变。

4. **测试**
   - 后端集成测试覆盖：未注册手机号请求 `login` 验证码，提交默认 `/auth/sms/login` 返回 200，用户、免费套餐、会话 cookie、注册通知和 `sms` 登录事件生成。
   - 覆盖同一验证码只能消费一次；重新发送 `login` 验证码后老用户再次登录成功。
   - 覆盖停用用户仍被拒绝，不能通过自动开户逻辑绕过状态控制。
   - 保留或新增旧 `mode=register` 兼容测试，确认历史客户端已发送的注册验证码仍可验证。
   - 前端测试断言认证弹窗不再包含注册模式、注册 API 调用和 `purpose=register` 主流程；短信请求固定 `login`。

## 验收标准

- [x] 全新手机号在登录弹窗输入验证码并提交后直接进入已登录状态，无需切换到注册。
- [x] 自动创建的用户为 active/free，手机号归一化存储，默认用户名沿用现有 `_create_user()` 行为。
- [x] 同一手机号第二次短信登录复用既有用户，不重复创建账号。
- [x] 已设置密码用户仍可通过密码登录；管理员短信二次验证不受影响。
- [x] 旧 `/auth/register` 路由和 `mode=register` 的处理策略符合 Open Questions 的决策。
- [x] 短信验证码仍为一次性消费，错误 5 次锁定、发送冷却和日限额行为不变。
- [x] 前端不再显示「立即注册 / 返回登录」模式和密码注册两步表单。
- [x] 后端认证相关测试和前端认证/工作台相关测试通过。

## Out of Scope

- 不新增手机号归属地、运营商校验或真实实名认证。
- 不改变短信 Provider、验证码 TTL、限流阈值、Redis 键结构或后台短信配置。
- 不改数据库 schema，不迁移既有用户。
- 不实现第三方登录、邮箱注册或账号合并。
- 不调整套餐、额度、通知中心和管理员账号创建逻辑。
- 不回退工作树中与本需求无关的既有改动。

## Open Questions

- [x] Q1: 合并后是否保留 `/auth/register` 后端路由和前端 `registerApi` 作为兼容/内部能力，还是在确认无旧客户端后彻底移除？ - Decision: 用户要求执行方案，采用推荐策略：保留 `/auth/register`、前端 `registerApi` 和 `mode=register` 兼容能力，但主认证 UI 不再暴露显式注册流程；待发布观察后再评估清理。
