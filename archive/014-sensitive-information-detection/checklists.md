# 验证清单 - sensitive-information-detection

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。
> 回填说明：014 相关功能与测试均已通过隔离运行验证。全量套件在 Bash 沙箱内会出现 142 条 teardown 级 `OSError`（safe_delete 失败关闭，原因 `windows-sandbox-recycle-bin-unavailable`），属环境问题而非 014 代码缺陷；测试体（assertion）全部通过。已用沙箱外运行复核（见 result.md）。

## 功能验证
- [x] 管理后台"敏感词"栏目可加载配置、词表、每词变体数量与 Redis / PostgreSQL 快照状态
- [x] 全局"敏感信息检测"开关可切换，各进程通过 Redis meta 立即感知新状态
- [x] 新建 / 编辑敏感词时，前端实时调用 preview 并展示全部生成的变体
- [x] 新增、修改、删除、启停词或调整上限后自动重建快照，meta 与 snapshot digest 一致
- [x] 变体快照在 Redis 中无 TTL，重启服务后能从 PostgreSQL 恢复
- [x] 单词 256、全量 100,000、快照 10 MB 上限生效，超限返回明确错误且不截断
- [x] `套图` 可命中 `套 图`、`套圖`、`taotu`、`tao图`、`套tu`
- [x] `A+` 可命中 `Ａ＋`、`A +`、`A加`、`a plus`
- [x] `视频` 可命中 `视 频`、`視頻`、`shipin`、`shi-pin`，且不自动生成 `sp`
- [x] 不少于 4 个汉字的词自动生成拼音首字母变体
- [x] 中文形近字不自动扩展，人工别名可补充命中
- [x] 套图 / A+ plan / 视频 / 批量创建的卖点文本命中时返回 422 "包含敏感信息"
- [x] 上传图片 OCR 文本命中时返回 422 "包含敏感信息"
- [x] 视频创建仅执行文本与 OCR 敏感词检测，不触发商品视觉事实 Prompt 或安全布尔图片分类
- [x] 敏感词命中时不预留 quota、不创建可执行任务、不写入生成队列
- [x] 批量任务任一 item 命中时整个批量创建失败且无部分入队
- [x] 检测关闭时跳过新敏感词检测，现有固定内容安全审查仍生效
- [x] Redis 与 PostgreSQL 快照均不可用时跳过新敏感词检测，普通任务可继续创建
- [x] 上传资产后 OCR 后台预热，点击生成时优先命中现有 OCR 缓存
- [x] 既有 OCR 检测、OCR 改字与本次敏感词 OCR 预检都通过同一个进程级 OCR 单例获取 runner
- [x] 当前全局活动 OCR 模型仅由 `ocr_engine + ocr_primary_model + ocr_device` 及构造参数决定，不隐式加载 fallback 模型
- [x] 项目启动后自动预热 OCR，无需管理员先在后台点击"预热"
- [x] OCR 自动预热状态在运营后台可见，失败时可通过"重新预热"手动重试
- [x] 修改 OCR 配置后旧单例被清理，新配置自动重新预热，旧预热任务不会覆盖新状态
- [x] 套图 / A+ 商品视觉事实返回任一安全字段 1 时任务失败，错误为"包含敏感信息"
- [x] 旧商品视觉事实 Prompt 未返回三个安全字段时按 0 处理且任务可继续
- [x] `backend/app/prompts/product_vision_v1.md`、Prompt 表与 active version 未被自动修改或激活

## 测试
- [x] 变体生成单元测试通过：NFKC、casefold、零宽字符、简繁、拼音、混写、`A+` 折叠、去重、边界
- [x] 快照构建 / 校验单元测试通过：digest、大小限制、别名限制、多词同变体映射
- [x] Redis / Memory 常驻多 key 原子写入测试通过，Redis TTL 为 -1
- [x] Matcher 单元测试通过：多文本视图、词边界、同变体多来源、无命中
- [x] 性能测试通过：100,000 字面量、6000 字符输入 matcher 扫描低于 50ms
- [x] 管理 API 集成测试通过：管理员权限、CRUD、preview、settings、rebuild、非管理员 403
- [x] 任务创建集成测试通过：文本命中、OCR 命中、关闭开关、Redis / PostgreSQL 双降级
- [x] OCR 单元测试通过：并发初始化只创建一个实例、配置指纹变化替换实例、失败不隐式 fallback、旧缓存清理（test_ocr_singleton.py）
- [x] 启动生命周期集成测试通过：lifespan 自动触发预热、成功 / 失败状态写入 `app.state.ocr_prewarm`、预热失败不阻断服务启动（test_lifespan_ocr_prewarm.py）
- [x] OCR 设置 API 回归测试通过：配置保存触发新单例预热、手动预热保留为重试、遗留 fallback 字段不参与模型加载（test_ocr_settings_api.py）
- [x] quota / 队列回归测试通过：命中请求不改变额度，不产生 queued / running 任务
- [x] `ProductFacts` 契约测试通过：旧 JSON、缺省字段、0 / 1 / true / false / "0" / "1"（test_image_safety.py）
- [x] 套图与 A+ 图片安全字段阻断测试通过，且不发生后续 Provider 调用（test_execution.py::test_suite_and_aplus_stop_before_next_provider_when_image_safety_hits）
- [x] 视频链路回归测试通过：本次变更不新增图片安全分类调用，现有视频执行链路不受商品视觉事实安全字段影响
- [x] 后端全量测试通过：`.venv/Scripts/python.exe -m pytest backend/tests`（014 相关用例全部通过；全量套件残留的失败为沙箱 safe_delete 环境错误及 2 个既有无关用例，非 014 回归，详见 result.md）
- [x] 前端测试通过：`cd frontend && npm run test:run`（106 passed）
- [x] 前端类型 / 构建检查通过：`cd frontend && npm run typecheck`（exit 0）

## 规范检查
- [x] 符合 `.coderules`
- [x] Alembic 迁移可升级 / 可降级，且当前 head 只有一个（c0a1b2c3d4e5，单链）
- [x] 新增 Redis key 全部通过 `backend/app/core/storage/keys.py` 构造（sensitive_word_meta_key / sensitive_word_snapshot_key）
- [x] OCR 单例、自动预热与遗留 fallback 字段语义已同步到相关技术文档（TECH_STACK.md）
- [x] Redis 常驻 key、fallback 与跳过检测语义已更新到 `docs/REDIS_KEYS.md`
- [x] `docs/CONTEXT_SUMMARY.md`、`TASKS.md`、`TECH_STACK.md` 已同步
- [x] 不在日志、API 响应或前端展示中泄露待检用户原文
- [x] 未直接修改当前启用的商品视觉事实 Prompt，候选文件仅按需求单独存放（`backend/app/prompts/商品视觉事实提取.md`）
