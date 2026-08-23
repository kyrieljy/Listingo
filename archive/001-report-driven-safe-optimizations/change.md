# Change: report-driven safe optimizations

## 变更标题
基于 report.md 的批判性审计结论执行低风险代码质量优化

## 变更背景 / 上下文
- 来源需求：用户要求分析 `report.md`，批判性处理其中的建议，并在保证全部功能正常的前提下优化代码。
- 关联模块：后端 API 类型标注、视频任务与会话工厂、运行恢复、短信服务、前端错误处理与 Provider 展示类型。
- 影响范围：`backend/app` 的目标类型标注；`frontend/src/features/workspace` 的请求错误处理；`frontend/src/features/admin/provider-display.ts`。
- 审计事实：`report.md` 引用的规范文件存在，但其 AsyncSession 建议与 `TECH_STACK.md` 和 `docs/ARCHITECTURE.md` 的既定架构决策冲突。

## 目标
- 采纳报告中低风险且与现状相符的类型质量优化。
- 将前端请求错误处理从 `any` 收紧为 `unknown`，保留现有错误文案与安全拦截弹窗行为。
- 为后端仍缺失的关键参数/返回类型补充具体标注，优先覆盖服务、恢复和基础设施入口。
- 批判性记录不采纳或暂缓项，避免大规模重构引入功能回归。

## 方案设计
### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/main.py` | 修改 | 为运行时 schema 修补入口标注 `Engine`。 |
| `backend/app/security.py` | 修改 | 为构造器标注 `None`。 |
| `backend/app/services/batch_scheduler.py` | 修改 | 为构造器标注 `None`。 |
| `backend/app/services/job_creation.py` | 修改 | 为构造器标注 `None`。 |
| `backend/app/services/providers.py` | 修改 | 为构造器标注 `None`。 |
| `backend/app/services/sms.py` | 修改 | 为短信发送链路标注 `ApiKeyCipher`，并移除一处不再需要的 `Any`。 |
| `backend/app/services/video_jobs.py` | 修改 | 统一标注 `sessionmaker[Session]`。 |
| `backend/app/services/workspace_recovery.py` | 修改 | 为恢复和监控修复 helper 标注模型类型与过滤条件。 |
| `backend/app/api/admin.py` | 修改 | 为 OCR 配置序列化标注 `Settings`，为路由补齐返回类型。 |
| `backend/app/api/auth.py` | 修改 | 为认证/账号路由补齐返回类型。 |
| `backend/app/api/public.py` | 修改 | 为公开 API helper 与路由补齐返回类型。 |
| `frontend/src/features/workspace/WorkspaceView.vue` | 修改 | 将请求错误 helper 入参收紧为 `unknown`。 |
| `frontend/src/features/workspace/APlusPhasePanel.vue` | 修改 | 将请求错误入参收紧为 `unknown`。 |
| `frontend/src/features/workspace/VideoPhasePanel.vue` | 修改 | 将请求错误入参收紧为 `unknown`。 |
| `frontend/src/features/workspace/BatchHistoryDrawer.vue` | 修改 | 将捕获错误收紧为 `unknown`。 |
| `frontend/src/features/workspace/BatchHostingModal.vue` | 修改 | 将捕获错误收紧为 `unknown`。 |
| `frontend/src/features/admin/provider-display.ts` | 修改 | 用递归 JSON 值类型替换 `any`。 |
| `frontend/src/api/client.ts` | 修改 | 新增 `unknown` 错误的 HTTP status 安全读取 helper。 |
| `frontend/src/features/auth/auth-model.test.ts` | 修改 | 将认证弹窗高度断言对齐当前 680px 设计事实。 |
| `frontend/src/features/workspace/workspace.test.ts` | 修改 | 统一 raw source 换行符，并将登录/清理逻辑断言改为排版不敏感。 |

### 实现要点
1. 保持 API 契约、数据库模型、任务状态机和 UI 行为不变。
2. 报告建议分类：
   - 采纳：目标类型标注、前端错误对象 `unknown`、Provider 记录动态 JSON 字段的具体递归类型。
   - 拒绝：全量迁移 AsyncSession，因为同步 SQLAlchemy 会话是当前架构的明确决策。
   - 暂缓：全量 API 业务逻辑下沉、全量前端 Admin DTO 类型化、工具链依赖安装与 lockfile 更新。这些是独立大型变更，收益低于回归风险，且当前报告未证明可直接安全落地。
2. 验证中发现的既有测试问题只修正断言：
   - `auth-model.test.ts` 期望的 620px 与当前 `auth.css` 的 680px 不一致，测试落后于设计事实。
   - `workspace.test.ts` 对源码换行和缩进做过精确匹配；本次统一 raw source 换行并用空白不敏感断言保留原行为校验。

## 验收标准
- [ ] 后端既有测试全部通过。
- [ ] 前端既有 Vitest 全部通过。
- [ ] 前端 TypeScript 严格类型检查通过。
- [ ] 前端生产构建通过。
- [ ] 目标文件不再存在未标注的 Python 参数，剩余问题必须能对应到已记录的暂缓项。
- [ ] 工作区请求错误链路中的 `catch (error: any)` 全部移除。

## Open Questions
None.
