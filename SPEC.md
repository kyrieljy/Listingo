# Listingo 业务逻辑规格书

> 本文档是开发与验收的唯一业务真实依据。实现、测试和界面文案如与其他说明冲突，以本文档为准。

## 1. 产品范围

Listingo 提供四期统一入口：商品套图、A+详情、视频与爆款复刻、Agent与画布。

- 一期（商品套图）：已具备真实模型链路，含商品视觉事实、Meta Prompt 规划、内容安全审查、并发生图、二次编辑、失败重试、ZIP/长图导出。
- 三期（视频与爆款复刻）：已接入 Seedance 1.5 Pro（`shengsuanyun_tasks_generation` 适配器），支持 8 类模板、15 秒时长、1080p、可选音频与商品图参考；提交后由后端轮询 Provider 任务并把 mp4 落盘到 `data/results/`。
- 二期（A+详情）与四期（Agent与画布）：仍以本地演示为主，任何 Live 触发前必须走同一份 Provider 校验；未在后台启用则回退到 Dryrun。

平台默认全局 Dryrun。所有 Provider 预置但关闭且不包含 API Key。用户在本机后台手工配置、测试并启用后，才能创建 Live 任务。

Live 视频任务额外要求 `LISTINGO_PUBLIC_ASSET_BASE_URL` 已配置为公网可达的地址（`127.0.0.1` / `localhost` 会被拒绝），否则 Seedance 无法拉取商品参考图。此地址可在运营后台 `/runtime-settings` 修改。

## 2. 一期用户旅程

```mermaid
flowchart LR
  A["上传 1-3 张商品图"] --> B["设置平台/市场/语言/比例"]
  B --> C["在单一文本框填写商品卖点与要求，或使用 AI 帮写"]
  C --> D["智能匹配或自定义 7-12 张"]
  D --> E["确认生成策略并创建 Dryrun / Live 任务"]
  E --> F["逐图生成与实时状态"]
  F --> G["查看/重试/二次编辑"]
  G --> H["勾选并下载 ZIP 或长图"]
  F --> I["任务历史与版本历史"]
```

### 输入规则

- 单任务必须上传 1–3 张 JPG、PNG 或 WebP；每张最大 15MB。
- `count` 必须为 7–12。
- 比例按前台 DesignKit 风格选项收敛为 `1:1`、`3:4`、`9:16`、`16:9`；后端合法比例集合还包括 `2:3`、`3:2`、`4:3`、`4:5`、`5:4`、`21:9`，用于兼容后续扩展。
- 自定义结构固定为白底图、场景图、卖点图、其他四类；每类 0–4 张，总数必须为 7–12 张且与 `count` 一致。智能匹配固定生成 7 张，由 Meta Prompt 规划具体类型。
- 前台只提供一个“商品卖点与要求”文本框，以浅色占位内容提示填写商品名称、核心卖点、适用人群、期望场景和具体参数，不逐项暴露结构化字段；空内容不能创建生成任务。
- “AI 帮写”使用后台可版本化的 `copywriting-assist` 完整提示词，实际传入用户提供的 Role / Workflow / Constraints / Output Format / Output Reference 全文；该 Prompt 只控制卖点与场景候选回填节点，不替代核心 Meta Prompt、生图 Prompt 或二次编辑 Prompt。输出为“商品定位 / 适用场景 / 5大核心卖点”三段 Markdown 文本；先展示可编辑候选内容，允许重新生成，只有用户确认后才回填原文本框。禁止虚构价格、销量、认证、规格、功效与竞品结论。Dryrun 使用同结构确定性本地文案，Live 使用默认 LLM 并在失败时回退备用 LLM；此节点不强制 `response_format=json_object`。
- 后端结构化商品字段仍包括商品名称、品类、规格、SKU、配件、认证、目标人群和品牌风格，由单文本输入与商品图视觉事实共同解析；不可见或未提供内容必须标记不确定，不得编造。
- Live 模式必须存在已启用的默认 LLM、当前用户偏好对应的图片 Provider、可用密钥，并且 `product-vision`、`copywriting-assist`、`edit-rewrite`、`content-safety-review` 四个辅助 Prompt 都处于启用版本；任何一项缺失都会在创建阶段（HTTP 409）失败。

## 3. 提示词与执行链路

核心 Meta Prompt 的唯一内容源是用户上传的 `电商Meta图片提示词_完整修订版.md`。该文件按字节意义保存为首个版本，不回写原文。Live 运行时在原文前加入本次任务变量块，并在原文后追加 JSON 输出契约；变量块明确高于原文示例中的同名变量。禁止从 Artflo 或其他系统导入、拼接、覆盖任何提示词内容；Artflo 仅可作为后台 Workflow 画布的视觉交互参考。

```mermaid
flowchart TD
  V["输入校验 + 本地关键词与 LLM 内容安全审查"] --> O["商品视觉事实：LLM 读取原图"]
  O --> M["Meta Prompt + 原图 + 商品事实 + 比例 + JSON 契约"]
  M --> L["LLM 输出 JSON"]
  L --> P{"Pydantic 校验"}
  P -->|失败| R["一次 JSON 修复重试"]
  R --> P2{"再次校验"}
  P2 -->|失败| X["任务失败，停止图片调用"]
  P -->|成功| C1{"核心语义校验 + 比例补齐"}
  P2 -->|成功| C1
  C1 -->|失败| RP["整套重规划一次"]
  RP --> C2{"再次结构与语义校验"}
  C2 -->|失败| X
  C1 -->|成功| SF["对整套计划做一次 LLM 内容安全审查"]
  C2 -->|成功| SF
  SF -->|拒绝| X
  SF -->|通过| F["图片项扇出，并发上限默认 4（1–8 可配）"]
  F --> Q{"用户模型偏好"}
  Q -->|商品保持优先| N["Nano Banana Pro generateContent"]
  N -->|失败| N2["Nano Banana 2 generateContent"]
  Q -->|视觉排版优先| C{"Image 2 是否带参考图"}
  C -->|否| G["/v1/images/generations JSON"]
  C -->|是| I["/v1/images/edits multipart"]
  N -->|成功| SG["单图内容安全审查（LLM）"]
  N2 -->|成功| SG
  N2 -->|失败| E["记录单项失败"]
  G -->|成功| SG
  G -->|失败| E
  I -->|成功| SG
  I -->|失败| E
  SG -->|通过| S["立即持久化成功结果"]
  SG -->|拒绝| E
  S --> A["聚合任务状态"]
  E --> A
```

标准合约：

```json
{
  "schema_version": "1.0",
  "images": [
    {
      "route_symbol": "#@",
      "image_type": "主图",
      "picture_requirement": "画面要求",
      "copywriting_requirements": "文案要求"
    }
  ]
}
```

- 一期只接受 `#@`；未知符号在图片模型调用前失败。
- 缺字段、非法比例、数量不符同样在模型调用前失败。
- JSON 解析/校验失败只修复一次。
- 核心语义校验至少检查：每张图显式比例、商品锁定、无文字策略、Amazon 首图白底、自定义数量和重复图片职责；不合格只允许整套重规划一次。若某条 `picture_requirement` 只是缺失当前 `aspect_ratio`，会先由 `inject_runtime_aspect_ratio()` 自动补齐后再判定，不额外触发重规划。
- 规划 LLM 同时接收结构化 `product_facts` 与原始商品图，不再只依赖用户卖点文本。
- 自定义结构会形成 `白底图X张、场景图Y张、卖点图Z张、其他图W张` 的高优先级运行时数量指令，进入用户上传的核心 Meta Prompt；该 Prompt 按自身规则把四类继续映射到图片类型与 `#@` JSON 项，不存在四套额外 Prompt。
- 商品保持优先时单项按 Nano Banana Pro → Nano Banana 2 回退一次，不跨能力回退至 Image 2；视觉排版优先时直接选择 Image 2。Image 2 无参考图时走 `/images/generations`；带商品参考图时走 `/images/edits`，不得把 `image` JSON 字段错误发送到 generations。
- 结果一旦成功立即落盘，不因其他项失败而丢弃。
- 聚合状态只允许 `succeeded`、`partial_failed`、`failed`。

## 4. 内容安全审查

- 本地关键词过滤（`services/content_safety.py` 中 `TEXT_SAFETY_KEYWORDS`）覆盖涉黄、涉赌、涉毒、涉政等类别，会同步用于生成任务输入、AI 帮写输入/输出、视频帮写输入/输出、视频任务输入。
- LLM 审查通过 `content-safety-review` 提示词返回 `ContentSafetyReview` JSON：`{schema_version, passed, categories, issues}`。默认 LLM 失败会回退到备用 LLM；LLM 判定不通过或字段缺失时抛出 `ContentSafetyBlocked`，任务在创建/推进阶段直接失败并返回 4xx。
- 一期生成链路会在“规划完成后”和“每张图产出后”各审查一次；三期视频链路会在“输入卖点”“分镜脚本产出”两处审查。
- Dryrun 依然会执行本地关键词过滤，但不会向外调用 LLM 审查。

## 5. Dryrun

- Dryrun 不执行任何外部 HTTP 模型请求。
- 使用固定的确定性 JSON 计划模拟 Meta Prompt 输出；Dryrun 不执行、也不验证核心 Prompt 的语义效果。
- Dryrun 会确定性模拟商品视觉事实、语义审查、内容安全审查节点，验证完整状态机，但不证明真实模型的视觉理解或审查质量。
- 使用本地演示资产走完创建、排队、生成、聚合、日志、历史、版本与 ZIP/长图状态机。
- Dryrun 日志与 Live 使用同一结构，并明确标记 `dry_run=true`。
- 视频 Dryrun 使用固定 15 秒分镜（`dryrun_video_script`），不提交 Seedance 任务。

## 6. 二次编辑与版本

- 输入由当前版本图、原始商品图、修改要求构成。
- Live 时使用任务锁定的 `edit-rewrite` 提示词和 LLM 转写修改要求，再按原任务的模型偏好调用图片 Provider。Nano Banana Pro/Nano Banana 2 使用支持参考图的 `generateContent`；Image 2 使用 `/images/edits` multipart。
- 二次编辑结果同样执行比例校验和内容安全审查，通过后才能创建子版本。
- 新结果创建 `generation_version` 子版本，保存 `parent_version_id`，不覆盖原图。
- Dryrun 生成确定性的本地子版本，用于完整演示版本链路。

## 7. 视频与爆款复刻（三期真实链路）

- 输入：1–3 张商品图、平台、市场、国家、语言、比例、卖点、目标人群、`video_types`（1–8 类，来自 `痛点解决 / UGC 种草 / 达人口播 / 测评对比 / 短剧搞笑带货 / 视觉展示 / 反转剧情 / 清单榜单推荐`）、时长 5–15 秒（默认 15）、分辨率默认 `1080p`、`generate_audio`、`camera_fixed`、`watermark`。
- Live 链路：本地安全审查 → `ecommerce-video-meta-15s` 生成分镜脚本（LLM，失败回退备用 LLM）→ 分镜脚本再做一次内容安全审查 → `submit_video_task` 提交 Seedance 任务 → 每 5 秒轮询一次 `get_video_task`，最多 180 次（≈15 分钟）→ 成功后下载 mp4，写入 `data/results/`，并把远端 URL 与本地 URL 一起返回。
- Video 任务顺序执行每条 `video_type`（不复用图片并发上限），失败项支持 `POST /video-jobs/{id}/retry-failed` 单独重试。
- Dryrun 复用同一状态机，但脚本使用固定模板、任务不上抛外部请求。
- 视频卖点帮写走 `POST /video-copywriting-assist`，同样先做安全审查、然后调用 LLM；输出结构与套图帮写一致（三段 Markdown）。

## 8. Provider 规则

- LLM 默认：`doubao-seed-2-0-mini`（`bytedance/doubao-seed-2-0-mini`，经 `router.shengsuanyun.com`）；备用：`qwen-3-6`（`ali/qwen3.6-plus`）。`gpt-5-4-mini` 预置为可选切换项，默认不启用。
- 商品保持优先：Nano Banana Pro（`gemini-3-pro-image`）为默认，失败回退 Nano Banana 2（`gemini-3.1-flash-image`）。
- 视觉排版优先：直接使用 Image 2（`gpt-image-2`），不向前台暴露模型名。
- 视频：Seedance 1.5 Pro（`shengsuanyun-seedance-1-5-pro`，`bytedance/doubao-seedance-1-5-pro`，默认 1080p、15 秒、含音频）。
- Nano 2 固定为 `gemini-3.1-flash-image` 与 `/v1beta/models/gemini-3.1-flash-image:generateContent`；没有 OpenAI Images 的 `size` 字段，`resolution` 映射到 `generationConfig.responseFormat.image.imageSize` 档位 512/1K/2K/4K，画面比例映射到同一对象下的 `aspectRatio`。
- Image 2 的 `size` 是像素尺寸或“跟随任务比例”策略，与 Nano 的分辨率档位不是同一字段；固定尺寸与前台 `aspect_ratio` 不匹配时在模型调用前失败。
- 默认、备用关系按能力类型分别唯一。
- 密钥加密保存；读取接口只返回掩码和 `has_api_key`。
- 连通测试必须由运营人员显式点击，不因保存配置自动发起。
- 请求/响应日志排除 API Key、Authorization、Cookie 和完整 base64。
- Provider 只有同时满足“启用开关打开”和“API Key 已配置”才具备调用条件；Dryrun 即使 Provider 已生效也不会外调。后台模型页按“提示词理解与任务规划 / 商品保持优先 / 视觉排版优先 / 视频生成”分组，并显示单模型状态和整条业务链路是否完整生效。

## 9. Workflow 与版本

- 一期 Workflow 由 8 个节点、7 条边组成：`input`、`product_vision`、`meta_prompt`、`llm`、`contract`、`semantic_validator`、`image_generate`、`aggregate`；节点顺序即上述执行链路（内容安全审查作为 `semantic_validator` 与 `image_generate` 之间的运行时子步骤，不作为独立节点参与画布校验）。
- 启用前必须验证：8 个必需节点各出现一次，只能按 `input → product_vision → meta_prompt → llm → contract → semantic_validator → image_generate → aggregate` 方向连线，且边数量恰好为 7；已废弃的 `image_qa` 节点在启动 seed 时会自动被迁移移除。
- 已创建任务始终引用其创建时的 Workflow 与 Prompt 版本，不随后台启用版本变化。
- 后台 Dryrun 仅验证节点顺序与确定性输出，不调用模型。
- Workflow 画布是版本、连线校验和任务引用控制面；运行时节点顺序仍由后端固定执行器实现，修改画布布局或节点属性不会动态改写执行代码。
- Prompt 后台不是纯展示：启用版本会被后续 Live 任务锁定并传入 LLM；历史任务继续引用创建时版本。Dryrun 只记录版本与长度，不使用 Prompt 语义生成图片计划。
- 提示词资产允许上传 UTF-8 的 MD/TXT 文件（最大 2MB）创建不可变新版本；上传后不自动启用，运营人员必须在版本历史中明确选择生效版本。
- Prompt 工程固定包含 6 类资产：核心 `ecommerce-meta` 以及辅助 `product-vision`、`copywriting-assist`、`edit-rewrite`、`content-safety-review`、`ecommerce-video-meta-15s`；辅助类不修改用户上传的核心 Meta Prompt，分别控制对应系统节点。

## 10. 状态与异常

| 场景 | 行为 |
|---|---|
| 上传非法 | 422，不创建资产记录 |
| Meta Prompt 结构非法 | 一次修复，仍失败则任务 `failed` |
| 单图默认模型失败 | 回退备用模型一次 |
| 部分图片失败 | 保留成功项，任务 `partial_failed` |
| 全部图片失败 | 任务 `failed` |
| 内容安全审查未通过 | 任务/接口返回 4xx，`ContentSafetyBlocked` 消息带类别 |
| 重试失败项 | 只新执行失败项，不覆盖成功项 |
| ZIP/长图无有效选择 | 422 |
| Provider 无密钥/未启用 | Live 创建或测试明确失败（409） |
| 视频 `public_asset_base_url` 未配置或为 `localhost` | Live 视频任务在提交前失败 |
| Seedance 任务轮询超过 180 次（≈15 分钟） | 单项失败并可重试 |
| 二期 A+ 与四期 Agent | 目前仍走本地演示，Live 通道预留 |

## 11. API

公共接口位于 `/api/v1`，运营接口位于 `/api/v1/admin`。完整请求与响应模型由 FastAPI OpenAPI 文档生成。前端每秒轮询任务详情，直至进入终态。

- 一期：`POST /assets`、`POST /generation-jobs`、`GET /generation-jobs`、`GET /generation-jobs/{id}`、`POST /generation-jobs/{id}/retry-failed`、`GET /generation-jobs/{id}/download?format=zip|long_image`、`POST /generation-items/{id}/versions`、`POST /copywriting-assist`。
- 三期视频：`POST /video-jobs`、`GET /video-jobs`、`GET /video-jobs/{id}`、`POST /video-jobs/{id}/retry-failed`、`GET /video-jobs/{id}/download`、`POST /video-copywriting-assist`。
- 运营后台：`/providers`、`/providers/{id}/test`、`/prompts`、`/prompts/{id}/versions`（含上传）、`/prompts/{id}/compare`、`/prompts/{id}/versions/{vid}/activate`、`/workflows`、`/workflows/{wid}/versions`、`/workflows/{wid}/versions/{vid}/activate`、`/workflows/.../dryrun`、`/logs`、`/runtime-settings`（读写 `public_asset_base_url`）。

## 12. 非目标

不实现用户、支付、公网安全、Redis、Celery、对象存储或生产数据库。`/admin` 无登录，仅用于绑定 `127.0.0.1` 的本机 Demo。三期视频虽然会通过 `public_asset_base_url` 暴露一次 HTTPS 资源链接给 Seedance，但仍不构成生产级鉴权/授权链路。
