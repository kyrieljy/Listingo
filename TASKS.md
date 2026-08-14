# Listingo 任务清单

最后更新：2026-08-14

本文档记录当前仓库状态与本轮同步任务，不再作为历史流水汇总。业务事实以 `SPEC.md`、`README.md` 和当前源码为准。

## 当前状态

- [x] 商品套图 Dryrun 与 Live 链路已实现，包含安全审查、语义校验、并发生图、失败重试、版本、下载和二次编辑。
- [x] A+ 详情页 Dryrun 与 Live 链路已实现，当前核心 Prompt 为 `aplus_meta_prompt_0729.md`。
- [x] 视频 Dryrun 与 Live 链路已实现，当前使用 Seedance 2.0 Provider route chain。
- [x] 登录/注册、账号中心、管理员短信二次验证、通知、套餐、额度和模拟订单已实现。
- [x] 商品套图与 A+ 详情页批量托管已实现，包含批次记录、取消、失败重试、恢复和整批 ZIP 下载。
- [x] OCR 改字已实现，包含 PaddleOCR/RapidOCR 配置、文本检测、`image-text-edit` Prompt 和图片 edit 版本生成。
- [x] AI 水印下载规则已实现，免费用户默认带水印，付费/企业/管理员可下载无水印版本。
- [x] 运营后台支持 Provider 分组、route chain、Prompt 上传、版本比较、LLM 试跑、完整链路试跑、Workflow、日志、运行配置、短信、OCR、用户、套餐、订单和业务监控。
- [x] 后台完整链路测试任务使用 `is_admin_test=true`，不会混入前台历史列表。
- [x] 当前源码 Prompt 资产共 8 类；本地数据库可保留历史 `image-quality-review` 记录，它不属于当前运行 Workflow。
- [x] 源码 Provider 目录共 47 个预设；本地 DB 可保留 5 个 legacy Provider，不作为新源码事实。
- [ ] 使用有效密钥执行完整计费 Live 套图验收。
- [ ] 使用有效密钥执行完整计费 Live A+ 验收。
- [ ] 使用有效密钥和公开资源地址执行完整计费 Live 视频验收。

## 已完成能力

1. 前后端骨架、依赖锁定、本地启动、Docker Compose。
2. SQLite 模型、Alembic 迁移、API Key 加密和掩码。
3. 47 个源码 Provider 预设，覆盖 LLM、图片生成/edit 和视频中转站。
4. Provider route roles：`llm`、`suite_fidelity`、`suite_layout`、`aplus_detail`、`aplus_mobile`、`image_edit`、`video`。
5. 8 类 Prompt 资产版本化：`ecommerce-meta`、`aplus-meta`、`product-vision`、`copywriting-assist`、`edit-rewrite`、`image-text-edit`、`content-safety-review`、`ecommerce-video-meta-15s`。
6. 商品视觉事实抽取、核心规划 JSON 契约、语义校验、比例自动补齐、一次重规划。
7. 本地关键词 + LLM 内容安全审查。
8. A+ 0729 Prompt、模块数量选择、输出目标、A+ Web/移动端生成路线。
9. 视频分镜 Prompt、Seedance 2.0 submit/poll、mp4 落盘。
10. 前台任务历史、失败重试、取消、二次编辑、OCR 改字、ZIP/长图下载。
11. 账号、短信、套餐额度、模拟支付订单和通知中心。
12. 后台 Prompt 上传 UTF-8 `.md` / `.txt`、版本比较、手工启用。
13. 后台 Prompt 测试记录与产物预览。
14. Runtime settings 读写 `public_asset_base_url`。
15. 批量托管：`BatchJob/BatchItem`、SQLite 调度器、公开 workspace 配置、全局 Provider 并发限制、`provider_task_id` 恢复、套图/A+ 批量入口与记录抽屉。
16. 运营监控：业务指标、用户钻取、Provider 成本与错误摘要。
17. 前端工作台与后台自动化测试。

## 本轮同步任务

- [x] 确认提交策略：源码安全同步，直接推 `origin/main`，不提交 SQLite、密钥、`.env`、上传结果、日志、缓存或临时测试 DB。
- [x] 确认本机 active Prompt 状态：8 个源码 Prompt 中 `ecommerce-meta` 曾与源码文件不一致，已按本机 SQLite active 版本导出覆盖源码文件。
- [x] 更新 `README.md`、`SPEC.md`、`TECH_STACK.md`、`TASKS.md`、`开发计划.md`、`design-qa.md` 的过期信息。
- [x] 重新校验 8 个源码 Prompt 与本机 SQLite active 版本哈希一致，历史 `image-quality-review` 不参与源码同步。
- [x] 运行 `git diff --check`：通过，仅有 Windows 换行提示。
- [x] 运行后端 Pytest：`163 passed`，仅有既有 Starlette TestClient 弃用警告。
- [x] 运行前端 Vitest：`94 passed`。
- [x] 运行前端生产构建：通过，仅有 Vite 大 chunk 与 plugin timings 提示。
- [x] 检查 Alembic 迁移头：单头 `4d5e6f7a8b9c`。
- [ ] 检查 staged 文件，确认未纳入运行时数据或生成产物。
- [ ] 提交：`Sync active prompts and deployment docs`。
- [ ] Push：`git push origin main`。

## 服务器更新提醒

Docker Compose 部署需要重新 build 后端镜像，因为 `backend/requirements.txt` 新增 OCR/账号依赖；前端也需要重新安装依赖并构建，因为新增 `echarts` 与 `vue-echarts`。

推荐顺序：

```bash
cd /path/to/listingo
git pull origin main
docker compose stop backend frontend
docker compose build --no-cache backend frontend
docker compose run --rm backend alembic -c backend/alembic.ini upgrade head
docker compose up -d --force-recreate
docker compose logs --tail=100 backend
```

## 备注

- 当前源码事实以 `backend/app/seed.py`、`backend/app/services/provider_catalog.py`、`backend/app/services/provider_routing.py`、`backend/app/services/prompt_testing.py`、`backend/app/services/aplus_jobs.py`、`backend/app/services/video_jobs.py`、`backend/app/services/jobs.py`、`backend/app/services/image_text_edit.py`、`backend/app/api/public.py`、`backend/app/api/auth.py`、`backend/app/api/admin.py` 为准。
- 未完成的 Live 验收需要有效 API Key、明确启用 Provider，并配置公网可访问的 `LISTINGO_PUBLIC_ASSET_BASE_URL`。
