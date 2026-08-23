# 验证清单 - check-driven dead code cleanup

> 由 coding 阶段回填状态：`[x]` 通过 / `[FAIL]` 失败。失败不可跳过，需修复或于 result.md 记录阻塞原因。

## 功能验证
- [x] 引用复查确认被删组件与函数无生产调用；Provider schema 与路由 API 走现行实现。
- [x] OCR 测试确认生产路径 `detect_text_lines_with_status` 输出保持排序与过滤行为。
- [x] 依赖树确认 `dayjs` 仅由 `ant-design-vue` 传递保留。
- [x] 后端仍只导入 requirements 声明的 `rapidocr_onnxruntime`。

## 测试
- [x] `.venv/Scripts/python.exe -m compileall -q backend/app backend/tests`
- [x] `.venv/Scripts/python.exe -m pytest backend/tests`
- [x] `cd frontend; npm run test:run`
- [x] `cd frontend; npm run typecheck`
- [x] `cd frontend; npm run build`
- [x] `git diff --check`

## 规范检查
- [x] 修改保持最小边界，未迁移架构或引入新工具链。
- [x] 相关依赖事实已同步到 `SPEC.md`、`TECH_STACK.md` 与 `docs/CONTEXT_SUMMARY.md`。
