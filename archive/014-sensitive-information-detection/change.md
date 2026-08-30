# Change: sensitive-information-detection

## 变更标题
新增运营可配置的敏感词清单与套图 / A+ / 视频生成前敏感信息检测

## 变更背景 / 上下文
- 来源需求：管理员可维护敏感词并开关“敏感信息检测”；用户端在任务进入生成缓冲队列前检测“商品卖点与要求”与上传图片 OCR 文本；商品视觉事实提取候选 Prompt 增加涉黄、暴力、政治敏感三个布尔输出；任一文本或图片检测命中均阻止生成并提示“包含敏感信息”。
- 已确认算法决策：
  - 变体在管理员维护时实时生成、预览并同步 Redis，检测阶段只消费快照，不临时生成。
  - 接受“字符串 + 匹配规则族”的快照形式。
  - 拼音首字母只对不少于 4 个汉字的词自动生成；2 字词不自动生成 `tt`、`sp`。
  - 单词最多 256 个变体、全量最多 100,000 个变体、快照序列化后最大 10 MB。
  - 检测开启但 Redis 与 PostgreSQL 快照均不可用时跳过本次敏感词检测。
  - 中文形近字自动替换默认关闭，误杀风险高的写法通过人工别名补充。
- 新增 OCR 约束：
  - 全局使用同一个 OCR 模型实例（进程级单例）；本次敏感词 OCR 预检、上传预热、既有 OCR 改字与 OCR 检测接口都必须复用该实例。
  - 不再按主模型 / fallback 模型 / RapidOCR 组合加载多个 OCR runner；当前全局活动模型由现有 `ocr_engine + ocr_primary_model + ocr_device` 决定。
  - 项目启动时自动预热该单例；运营后台手动“预热”保留为失败后的手动重试入口，不再是启用 OCR 的必要操作。
- 视频图片检测决策：本次不为视频新增图片安全检测，也不接入商品视觉事实安全布尔字段；视频仍参与创建前的卖点文本与图片 OCR 敏感词检测。
- 关联模块：
  - 内容安全：`backend/app/services/content_safety.py`
  - 任务创建：`backend/app/services/job_creation.py`、`backend/app/api/public.py`
  - 套图 / A+ 视觉事实：`backend/app/services/jobs.py`、`backend/app/services/aplus_jobs.py`
  - 视频任务：`backend/app/services/video_jobs.py`
  - OCR：`backend/app/services/image_text_edit.py`
  - Redis：`backend/app/core/runtime.py`、`backend/app/core/storage/`
  - 运营后台：`frontend/src/features/admin/AdminView.vue`
- 现状约束：
  - 套图与 A+ 任务记录创建阶段已有固定关键词本地拦截；视频创建接口也直接调用同一本地检测。
  - `ProductFacts` 当前只解析商品事实，不包含安全布尔字段。
  - `product_vision_v1.md` 是当前启用的 Prompt 资产；本次不得直接修改或自动激活新版本。
  - Redis 现有 `setex/get` 面向 TTL 值，队列已引入无 TTL 常驻 key；敏感词快照需要类似的无 TTL 语义。

## 目标
1. 运营后台新增“敏感词”栏目，支持全局检测开关、敏感词 CRUD、人工别名、实时变体预览、快照状态查看和手动重建。
2. 管理员每次新增、修改、删除、启停词或切换全局开关时，立即生成全量变体快照并原子同步 Redis；检测请求不再执行变体生成。
3. 套图、A+、视频与批量任务的“商品卖点与要求”在 quota 预留和入队前完成敏感词检测；检测命中返回统一的“包含敏感信息”。
4. 任务创建前对上传图片执行 OCR，并将 OCR 文本纳入同一套敏感词检测；利用上传时预提取与现有 OCR 缓存降低点击生成时的等待。
5. 套图与 A+ 的商品视觉事实提取新增候选 Prompt，要求输出 `is_pornography`、`is_violence`、`is_politics`；代码兼容缺省值 0，任一值为 1 时终止任务并统一提示“包含敏感信息”。
6. 匹配性能与词表规模解耦：规范化后以字面量变体为主，用 Aho-Corasick 一次扫描多个归一化文本视图，避免请求期逐词遍历和大量正则。
7. OCR 全局单例在项目启动后自动预热，敏感词检测与既有 OCR 能力共享同一模型实例与结果缓存。

## 方案设计

### 涉及文件
| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/models.py` | 修改 | 新增 `SensitiveWordConfig`、`SensitiveWord`、`SensitiveWordSnapshot` ORM 表 |
| `backend/migrations/versions/xxxx_add_sensitive_words.py` | 新增 | 新建三张表、索引与唯一约束；迁移文件名由 coding 阶段按项目命名惯例生成 |
| `backend/app/seed.py` | 修改 | 启动种子创建单例配置；不预置敏感词，不修改 Prompt 启用状态 |
| `backend/app/schemas.py` | 修改 | 新增管理端配置、词表、变体预览、快照状态 Pydantic Schema；收紧输入长度与别名数量 |
| `backend/app/services/sensitive_words.py` | 新增 | 变体生成、文本规范化、快照构建 / 校验 / 同步、Aho-Corasick Matcher、检测入口 |
| `backend/app/services/content_safety.py` | 修改 | 保留既有黄赌毒等固定本地审查；接入新敏感词检测结果与统一异常文案 |
| `backend/app/services/job_creation.py` | 修改 | 套图 / A+ 创建路径改为可等待敏感词预检，确保在任务落库、quota、入队前执行 |
| `backend/app/api/public.py` | 修改 | 套图、A+、视频、批量创建入口调用异步预检；上传接口增加 OCR 后台预热 |
| `backend/app/services/batch_jobs.py` | 修改 | 批量 item 复用统一预检；任一 item 命中则整个批量创建失败且不预留 quota |
| `backend/app/services/image_text_edit.py` | 修改 | 引入进程级 `OcrEngineManager` 单例；移除请求期多候选引擎包装，抽出可异步执行的 OCR 文本收集 helper；敏感词 OCR 与既有 OCR 复用同一实例 |
| `backend/app/services/prompt_contract.py` | 修改 | `ProductFacts` 增加三个默认 `False` 的安全布尔字段，并保持旧 Prompt JSON 可解析 |
| `backend/app/services/jobs.py` | 修改 | 套图解析视觉事实后按三个布尔字段阻断；记录脱敏执行日志 |
| `backend/app/services/aplus_jobs.py` | 修改 | A+ 视觉事实链路应用同一图片安全阻断 |
| `backend/app/services/video_jobs.py` | 修改 | 仅接入视频创建文本/OCR 敏感词预检；本次不新增图片安全布尔检测，不额外调用商品视觉事实 Prompt |
| `backend/app/core/storage/base.py` | 修改 | 存储抽象新增无 TTL 多 key 原子写入契约 |
| `backend/app/core/storage/redis.py` | 修改 | 用 Redis pipeline transaction 写入敏感词 meta 与 snapshot 两个常驻 key |
| `backend/app/core/storage/memory.py` | 修改 | 用进程锁实现同等语义；持久条目不参与 LRU 淘汰 |
| `backend/app/core/storage/keys.py` | 修改 | 新增 `sensitive_word_meta_key()`、`sensitive_word_snapshot_key()` |
| `backend/app/main.py` | 修改 | 启动时从 PostgreSQL 生成 / 校验并同步快照；注册默认 Matcher 缓存；启动后自动触发全局 OCR 单例预热并记录状态 |
| `backend/app/api/admin.py` | 修改 | 新增敏感词配置、CRUD、变体预览、快照重建 API；OCR 设置响应返回自动预热状态，手动预热保留为重试能力 |
| `backend/requirements.txt` | 修改 | 新增 `pypinyin`、`opencc-python-reimplemented`、`pyahocorasick` 运行依赖 |
| `frontend/src/features/admin/SensitiveWordsPanel.vue` | 新增 | 敏感词栏目 UI：开关、词表、别名、实时变体预览、快照状态、重建入口 |
| `frontend/src/features/admin/sensitive-words-model.ts` | 新增 | API 类型、变体预览格式化与状态展示逻辑 |
| `frontend/src/features/admin/AdminView.vue` | 修改 | 导航新增“敏感词”，挂载新面板；OCR 页展示启动自动预热状态，按钮文案改为“重新预热” |
| `changes/014-sensitive-information-detection/商品视觉事实提取.md` | 新增 | 仅人工确认的候选 Prompt；coding 阶段不得直接替换 `product_vision_v1.md` 或自动激活 |
| `backend/app/prompts/商品视觉事实提取.md` | 新增（coding 阶段） | 人工确认后放置的候选文件；不进入 seed、不上传版本、不激活 |
| `docs/REDIS_KEYS.md` | 修改 | 记录敏感词常驻 key、无 TTL / 不淘汰语义、PostgreSQL fallback 与跳过检测策略 |
| `docs/CONTEXT_SUMMARY.md` | 修改 | 同步内容安全、运营后台、Redis 与 Prompt 资产索引 |
| `TASKS.md`、`TECH_STACK.md` | 修改 | 按项目文档规则同步能力、依赖与接口说明 |
| `backend/tests/test_sensitive_words.py` | 新增 | 覆盖变体生成、规范化、上限、快照、Matcher 与降级 |
| `backend/tests/test_sensitive_word_integration.py` | 新增 | 覆盖管理 API、任务创建阻断、OCR 命中、quota / 队列不落地 |
| `backend/tests/test_prompt_contract.py` 或相邻既有测试 | 修改 | 覆盖三个安全字段默认 0、显式 1 与旧契约兼容 |

### 数据模型

1. `sensitive_word_config`：单例配置表。
   - `id`
   - `enabled: bool`，默认 `False`
   - `max_variants_per_word: int`，默认 `256`
   - `max_total_variants: int`，默认 `100000`
   - `max_snapshot_bytes: int`，默认 `10_485_760`
   - `updated_at`
2. `sensitive_word`：
   - `id`
   - `term: string(120)`，管理员原词
   - `normalized_term: string(120)`，唯一索引
   - `aliases_json: text`，默认 `[]`，最多 20 个，单个别名最多 120 字符
   - `enabled: bool`，默认 `True`
   - `note: text`
   - `created_at` / `updated_at`
3. `sensitive_word_snapshot`：
   - `id`
   - `source_digest: string(64)`，唯一索引，由启用配置、规范化词、别名与上限决定
   - `payload_json: text`，完整快照 JSON，用于 Redis 丢失时恢复
   - `word_count: int`
   - `variant_count: int`
   - `payload_bytes: int`
   - `created_at`
   - 保留最近 20 版，过旧版本在事务内清理；便于审计与快速回滚重建。

快照结构：

```json
{
  "schema_version": "1.0",
  "enabled": true,
  "source_digest": "<sha256>",
  "generated_at": "<iso8601>",
  "limits": {"per_word": 256, "total": 100000, "bytes": 10485760},
  "words": [
    {
      "id": "<uuid>",
      "term": "套图",
      "aliases": [],
      "boundary": "none|word",
      "variants": ["套图", "taotu"]
    }
  ]
}
```

Redis 保存两个常驻 key：

- `sensitive:words:meta`：小 JSON，仅含 `enabled`、`source_digest`、`word_count`、`variant_count`、`payload_bytes`。
- `sensitive:words:snapshot`：完整快照 JSON。

两个 key 无 TTL、不参与淘汰，并通过存储适配层的 pipeline / lock 原子替换。检测进程只在 digest 变化时读取完整快照并重新编译；常规请求只读取 meta key。

### 变体生成算法

1. 输入统一先做基础规范化：
   - Unicode NFKC
   - casefold
   - 去零宽字符与控制字符
   - 拉丁变音符号折叠
   - 常见 leet / confusable 字符折叠，例如 `4 -> a`、`0 -> o`、`3 -> e`、`$ -> s`
   - 简繁转换
   - `+` 语义折叠：`＋`、`加`、`plus` 归一为 `+`
2. 生成两个基础文本视图：
   - `normalized`：保留空格与换行
   - `compact`：删除空格、换行与常见干扰分隔符（`.`、`-`、`_`、`*`、`~`、`/`、`|`、`、`、`·` 等）
3. 对中文连续片段生成无声调拼音视图，中文与拼音混写也在同一转换中归并为连续拼音；因此 `套tu` 与 `tao图` 都会落到 `taotu` 视图。
4. 每个启用词 / 人工别名生成：
   - 原词 compact 字面量
   - 简繁 compact 字面量
   - 默认拼音 compact 字面量
   - 混写归一后的字面量
   - 多音词仅生成常见读音，非常见读音由人工别名补充，避免请求期组合爆炸
   - 不少于 4 个汉字的词生成拼音首字母字面量
5. 变体以 `(term, alias, variant, boundary)` 去重；不同词如果命中同一变体，Matcher 保留到多个 source word 的映射。
6. 拉丁 / 拼音变体使用词边界；中文与纯 CJK 词不强制词边界；`A+` 由 `+` 折叠规则约束。
7. 达到单词 / 全量 / 字节任一上限时保存失败并返回可操作错误，不静默截断。
8. 检测请求不做上述变体扩展，只对用户文本执行同一套规范化与拼音视图后交给已编译 Matcher。

### 检测时性能方案

1. **零正则优先**：空格、标点干扰、全半角、大小写、leet、简繁、`A加` 等在文本规范化阶段折叠，敏感词变体在快照中保持字面量。只有无法折叠的极少人工例外才允许进入受控 regex 白名单，目标是常规快照 regex 数为 0。
2. **Aho-Corasick**：用 `pyahocorasick` 构建一个自动机，一次扫描可同时匹配全部字面量变体；复杂度与待检文本长度线性相关，不再随词表规模逐词 `in`。
3. **多视图合并扫描**：`compact`、`pinyin compact` 等文本视图一次性送入同一自动机，命中后再做边界校验。
4. **进程内编译缓存**：以 `source_digest + schema_version` 为 key 缓存自动机；meta digest 不变时不反序列化 10 MB 快照。
5. **上传时 OCR 预热**：`POST /assets` 保存成功后用 BackgroundTasks 对图片执行 OCR，并写入现有 OCR 结果缓存。点击生成时优先读缓存；未命中才在线补算。
6. **在线 OCR 有界并发**：cache miss 时按配置并发 OCR，默认并发 `min(图片数, 3)`；任一图片命中即取消剩余任务。OCR warning / engine unavailable 只跳过该图 OCR 文本，不让普通任务失败。
7. **先词检后 OCR**：卖点文本先扫描；文本已命中时不再跑 OCR。
8. **性能指标**：记录 matcher 耗时、OCR cache hit / wait 耗时、snapshot reload 耗时，只记数值与 hit 分类，不落用户原文。验收目标：6000 字符 + 100,000 字面量词表的 matcher 扫描低于 50ms；OCR 全缓存时新增预检耗时低于 100ms。未缓存 OCR 的耗时由 OCR 引擎决定，必须通过上传预热降低暴露面。

### 全局 OCR 单例与启动预热

1. 在 `image_text_edit.py` 中新增进程级 `OcrEngineManager`：
   - 使用 `threading.RLock` 保护初始化、替换、清理和预热，避免上传预热与任务检测并发时创建重复实例。
   - 只持有一个活动 OCR runner，配置指纹为 `ocr_engine + ocr_primary_model + ocr_device + 影响构造的阈值参数`。
   - runner 调用也由同一把锁序列化；上传预热与任务检测可并发调度，但进入同一模型实例时逐个执行，避免 PaddleOCR / RapidOCR 客户端的线程安全性差异引入竞态。
   - `detect_text_lines_with_status`、既有图片 OCR 接口、OCR 改字链路和本次敏感词 OCR 预检都统一调用 manager 获取 runner。
   - 若配置指纹不变，直接返回现有实例；若变化，先清理旧实例再构造新实例。
2. 当前版本不再自动加载 `ocr_fallback_model` 或额外的 RapidOCR fallback：
   - `ocr_fallback_model` 字段暂时保留用于兼容既有环境和 API，但不再参与活动模型选择，也不会被隐式加载。
   - 管理端 OCR 设置不再引导配置 fallback 模型；文档标注其为遗留字段。
   - 活动模型初始化或运行失败时返回明确 OCR warning / error，不静默切换到另一个模型，确保“全局同一个 OCR 模型”可预期。
3. 项目启动流程：
   - `main.py` lifespan 在数据库校验、seed、敏感词快照同步后创建后台预热任务。
   - 预热任务通过 `asyncio.to_thread` 调用现有 `prewarm_ocr_engine` 的单例版本，避免 PaddleOCR / RapidOCR 初始化或模型下载阻塞服务可访问性。
   - 预热状态写入 `app.state.ocr_prewarm`：`pending / running / succeeded / failed`、开始与结束时间、活动模型、错误摘要、cache size。
   - 预热失败不终止应用启动，记录 exception 并在运营后台显示失败状态；手动“重新预热”可重试。
4. OCR 配置变更：
   - `PATCH /admin/ocr-settings` 保存后立即替换配置指纹，清理旧单例，并自动触发一次后台预热。
   - 预热进行中再次保存配置时，旧预热结果标记为 `superseded`，新配置重新排队，避免旧任务把旧实例写回全局状态。
   - `POST /admin/ocr-settings/prewarm` 保留，但语义改为按当前配置手动重试 / 强制重新预热。
5. 多实例部署说明：
   - 单例是进程内对象；如未来部署多个后端实例，每个实例会各自加载同一份配置的模型实例。
   - OCR 结果缓存仍按完整配置指纹写入 Redis，确保实例间不会混用不同 OCR 设置的结果。

### OCR 性能取舍

- 单例调用锁会让少量 cache miss 图片按队列执行，这是为了保证全局唯一模型实例的行为稳定。
- 首选优化仍是上传时预热与 Redis OCR 结果缓存，让生成点击阶段大多命中缓存，不重复进入模型。
- 如后续确认所选 OCR 引擎官方支持线程安全调用，再单独评估放开调用锁；本次不以“并发调用同一实例”换取不确定风险。

### 管理端 API

- `GET /admin/sensitive-words`：返回配置、词表、每词变体数量、Redis / PostgreSQL 快照状态。
- `POST /admin/sensitive-words/preview`：不落库，输入 term / aliases，实时返回全量变体、边界策略、数量与上限警告；前端输入防抖 300ms 调用。
- `POST /admin/sensitive-words`：校验、生成快照、同步 Redis、保存词；响应包含变体预览与 `redis_synced=true`。
- `PATCH /admin/sensitive-words/{id}`：修改原词、别名、启停、备注并实时重建快照。
- `DELETE /admin/sensitive-words/{id}`：删除并实时重建快照。
- `PATCH /admin/sensitive-words/settings`：切换全局检测开关或调整上限；即使关闭也写入 `enabled=false` 快照，保证各进程立即看到关闭状态。
- `POST /admin/sensitive-words/snapshot/rebuild`：从 PostgreSQL 强制重建并同步 Redis。

管理端保存流程：

1. `SELECT ... FOR UPDATE` 锁单例配置行，序列化并发修改。
2. 在当前事务中修改词表并生成候选快照，执行规模与字节校验。
3. 写入 `SensitiveWordSnapshot` 并通过 `set_persistent_many` 原子更新 Redis meta + snapshot。
4. Redis 写入失败时事务回滚，管理端返回 503，避免出现“页面显示保存成功但检测仍用旧清单”的模糊状态。
5. Redis 写入成功但数据库提交失败时，立即用数据库最后提交状态补偿重建 Redis；补偿失败则记录错误，后续请求按 PostgreSQL fallback 校正。

### 用户端文本与 OCR 敏感词检测

1. 检测范围只取用户自由文本：
   - 套图：`selling_points`
   - A+：`product_info` / 批量 item 拼出的卖点文本
   - 视频：`selling_points`
   - 上传图片 OCR 成功行的 `text`
2. 不把平台、市场、语言、比例等枚举字段纳入敏感词扫描，减少无意义误杀。
3. 套图、A+ plan、视频、批量创建都在 quota 预留、任务终态落库和 `scheduler.enqueue_*` 之前预检。
4. 命中返回 `HTTP 422`，`detail="包含敏感信息"`；不创建任务、不预留 quota、不入队。
5. 批量任务任一 item 命中则整个批量创建失败并返回同一文案。
6. 配置关闭时跳过新检测；既有固定黄赌毒 / 政治本地审查与 LLM 内容安全链路保持现状，不受该开关放宽。
7. 检测开启但 Redis meta / snapshot 均不可读时，读取 PostgreSQL 最新快照；两者均不可用或快照校验失败时跳过本次敏感词检测，记录 warning 指标，不阻断普通生成。
8. 现有任务重试不重复扫描历史自由文本；新创建任务必须经过预检。
9. OCR 敏感词检测属于文本检测的一部分；本节不等于视频图片安全分类。视频本次不做涉黄、暴力、政治敏感图片分类。

### 图片安全布尔检测

1. 候选 Prompt 在原 `ProductFacts` JSON 契约上新增：
   - `is_pornography: 0|1`
   - `is_violence: 0|1`
   - `is_politics: 0|1`
2. `ProductFacts` Pydantic 字段使用默认 `False`；旧 Prompt 未返回、返回 `0`、返回 `"0"` 均视为不涉及，返回 `1` / `"1"` / `true` 视为涉及。
3. 套图与 A+ 在 `parse_product_facts` 之后、Meta Prompt 与任何生图调用之前检查三个字段；视频不接入该检测。
4. 任一字段为真：
   - 任务置为 `failed`
   - `error="包含敏感信息"`
   - `ExecutionLog(node="sensitive_image", status="failed")` 只记录命中的分类枚举，不复述模型原文
   - 不继续外部生图调用
5. 全局敏感信息检测关闭或快照不可用时跳过三个字段阻断；候选 Prompt 人工激活前的现有任务也因字段缺省 0 而保持兼容。
6. 本变更不直接修改 `backend/app/prompts/product_vision_v1.md`、不上传 PromptVersion、不改变 active version。人工确认候选文件后，由管理员在后台按现有上传 / 版本激活流程手动启用。

### 候选 Prompt 处理

- 本变更包中的 `商品视觉事实提取.md` 是完整候选文案，包含原商品视觉事实输出与三个安全字段。
- coding 阶段只允许将人工确认后的文案放到 `backend/app/prompts/商品视觉事实提取.md` 作为候选资产；不得改名为并覆盖 `product_vision_v1.md`。
- seed、Prompt 表和 active version 均不自动变更。
- 后续人工操作路径：管理员在“提示词资产 / 商品视觉事实提取”中上传该 MD 为新版本，试跑确认后手动激活。

## 验收标准
- [ ] 管理员可打开 / 关闭敏感信息检测，可新增、编辑、删除、启停敏感词与人工别名。
- [ ] 新建 / 编辑词时，前端能实时展示该词生成的全部变体；保存后 Redis meta 与 snapshot 均无 TTL 且 digest 一致。
- [ ] 单词 256、全量 100,000、快照 10 MB 上限生效；超限保存失败且无静默截断。
- [ ] 套图、A+ plan、视频、批量创建在入队前完成文本与 OCR 敏感词检测；命中时不预留 quota、不创建可执行任务、不入队，并返回“包含敏感信息”。
- [ ] `套 图`、`套圖`、`taotu`、`套tu` 可命中 `套图`；`Ａ＋`、`A 加`、`a plus` 可命中 `A+`；2 字中文词不自动生成拼音首字母。
- [ ] Redis 与 PostgreSQL 快照均不可用时跳过新敏感词检测，普通任务不被 503 阻断。
- [ ] 上传图片后 OCR 缓存被预热；点击生成优先读缓存并记录性能指标。
- [ ] 项目启动后自动预热全局 OCR 单例；管理员无需手动点击“预热”即可使用 OCR 功能，后台可查看预热状态并手动重试。
- [ ] 既有 OCR 能力与本次敏感词 OCR 使用同一个活动模型实例，且不会隐式加载 fallback 模型。
- [ ] 旧商品视觉事实 Prompt 输出仍可解析；新增字段缺失时默认 0。
- [ ] 新 Prompt 输出任一安全字段 1 时，套图 / A+ 在生图前失败，错误为“包含敏感信息”。
- [ ] 现有 `product_vision_v1.md` 与数据库 active Prompt 未被自动修改或切换。
- [ ] 100,000 字面量、6000 字符输入的 Matcher 性能测试达到目标。

## Open Questions
> 以下为待人工确认的问题。AI 不得自行猜测；必须回答后方可继续 coding。
- [x] Q1: 视频链路本次是否接入图片安全检测？ - Decision: 暂不添加。视频仅保留创建前卖点文本与图片 OCR 敏感词检测；不接入商品视觉事实安全布尔字段，也不额外调用商品视觉事实 Prompt。
