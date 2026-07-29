# Listingo 任务清单

最后更新：2026-07-29

## 当前状态

- [x] 商品套图 Dryrun 与 Live 链路已实现。
- [x] A+ 详情页 Dryrun 与 Live 链路已实现，当前核心 Prompt 为 `aplus_meta_prompt_0729.md`。
- [x] 视频 Dryrun 与 Live 链路已实现，当前视频 Provider 为 `shengsuanyun-doubao-seedance-2-0`。
- [x] 运营后台支持 Provider route role、Prompt 上传、版本比较、LLM 试跑和完整链路试跑。
- [x] 后台完整链路测试任务使用 `is_admin_test=true`，不会混入前台历史列表。
- [x] 当前运行 Prompt 资产共 7 类，源码文件与本地 SQLite active 版本需要在提交前再次哈希确认。
- [x] 本地数据库可保留历史 `image-quality-review` 记录；它不属于当前运行 Workflow。
- [ ] 使用有效密钥执行完整计费 Live 套图验收。
- [ ] 使用有效密钥执行完整计费 Live A+ 验收。
- [ ] 使用有效密钥和公开资源地址执行完整计费 Live 视频验收。

## 已完成能力

1. 前后端骨架、依赖锁定、本地启动、Docker Compose。
2. SQLite 模型、Alembic 迁移、API Key 加密和掩码。
3. 8 个 Provider seed：3 个 LLM、4 个 image、1 个 video。
4. Provider route role：`llm`、`suite_fidelity`、`suite_layout`、`aplus_detail`、`aplus_mobile`、`video`。
5. 7 类 Prompt 资产版本化：`ecommerce-meta`、`aplus-meta`、`product-vision`、`copywriting-assist`、`edit-rewrite`、`content-safety-review`、`ecommerce-video-meta-15s`。
6. 商品视觉事实抽取、核心规划 JSON 契约、语义校验、比例自动补齐、一次重规划。
7. 本地关键词 + LLM 内容安全审查。
8. 套图保真路线：Nano Banana Pro primary、Nano Banana 2 fallback。
9. 套图排版路线：Image 2 primary。
10. A+ 0729 Prompt、模块数量选择、输出目标、A+ Web/移动端生成路线。
11. 视频分镜 Prompt、Seedance 2.0 submit/poll、mp4 落盘。
12. 前台任务历史、失败重试、二次编辑、ZIP/长图下载。
13. 后台 Prompt 上传 UTF-8 `.md` / `.txt`、版本比较、手工启用。
14. 后台 Prompt 测试记录与产物预览。
15. Runtime settings 读写 `public_asset_base_url`。
16. 前端工作台与后台自动化测试。

## 本轮同步任务

- [x] 确认本地 SQLite active Prompt 与 7 个源码 Prompt 文件哈希一致。
- [x] 确认 Alembic 迁移链单头。
- [x] 更新全部项目文档，移除旧视频模型、旧 Prompt 数量和旧 Provider 数量等过期信息。
- [x] 删除未被源码引用的旧 A+ 0224 Prompt 文件，避免仓库继续携带过期提示词资产。
- [x] 重新运行后端 Pytest：`71 passed`，仅保留既有 Starlette TestClient 弃用警告。
- [x] 重新运行前端 Vitest：`53 passed`。
- [x] 重新运行前端生产构建：通过，仅保留既有 Vite 大 chunk 警告。
- [x] 检查 Alembic 迁移头：单头 `b7d2c6a9e8f1`。
- [x] 检查 `git diff` 和 `git status`，确认未纳入运行时数据或生成产物。
- [x] 本轮源码树已准备为 `Sync active prompt assets and docs` 提交内容；Git 提交与推送状态以仓库历史为准。

## 备注

- 当前源码事实以 `backend/app/seed.py`、`backend/app/services/provider_routing.py`、`backend/app/services/prompt_testing.py`、`backend/app/services/aplus_jobs.py`、`backend/app/services/video_jobs.py`、`backend/app/services/jobs.py`、`backend/app/api/public.py`、`backend/app/api/admin.py` 为准。
- 未完成的 Live 验收需要有效 API Key、明确启用 Provider，并在视频场景配置公网可访问的 `LISTINGO_PUBLIC_ASSET_BASE_URL`。
