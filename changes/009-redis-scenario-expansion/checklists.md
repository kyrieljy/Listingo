# 验证清单 - REDIS_SCENARIO_EXPANSION

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] RuntimeStateService：FakeRedis 与 MemoryStorage 下 JSON 读写、TTL、锁互斥/安全释放、计数
- [x] Provider 快照缓存：capability/code 读取命中缓存；管理端 Provider/路由链/健康检查写回后版本失效
- [x] Prompt/Workflow 激活版本缓存：任务创建复用；版本激活后失效
- [x] 套餐/额度规则缓存：公开套餐与额度摘要复用；管理端套餐/规则/用户套餐更新后失效
- [x] 会话元数据缓存：命中缓存且用户状态仍读 DB；登出删除键
- [x] 批量状态缓存：详情重复读取命中；取消/重试/调度推进后失效
- [x] 分布式锁：批量认领、额度预留、订单创建、模拟支付键与互斥语义正确
- [x] 实时计数：分析事件计数入库到 Redis；ops-monitoring 返回 realtime_metrics；前端展示卡片
- [x] OCR 结果缓存：同图同设置第二次不跑引擎；设置/文件变化后键变化

## 测试
- [x] 新增运行时服务与缓存/锁/计数单元测试通过（test_redis_runtime_features.py，8 项全过）
- [x] 相关 API 回归（认证、套餐、批量、管理端、OCR）通过
- [x] `.venv/Scripts/python.exe -m pytest backend/tests` 通过（回归子集 117 用例全过；排除需 cv2/paddle/numpy 的 test_api_dryrun.py、test_execution.py）
- [x] 前端监控组件如被修改，`cd frontend && npm run test:run` 通过（前端仅消费 summary_cards 动态渲染，无新增组件逻辑需单独单测）

## 规范检查
- [x] 所有 Redis 键经 `core/storage/keys.py` 构造，无散落 f-string
- [x] 锁 fail-closed、缓存/计数 fail-open 语义在代码与文档一致（见 docs/REDIS_KEYS.md 降级语义章）
- [x] `docs/REDIS_KEYS.md`、`TECH_STACK.md`、`docs/CONTEXT_SUMMARY.md` 已同步
- [x] 符合 .coderules（注释说明 why、测试覆盖、无越界重构）
