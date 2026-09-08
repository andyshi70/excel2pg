# 决策日志（pxiu）

## D-029 缩放交付 + ch.jpg FAIL 确认 + v0.4 排期建议（2026-08-30）

- **缩放改造验收通过**：xiaoyou 实现（CanvasView 删自动 fit + ScrollWheelCatcher 滚轮缩放；ToolbarView −/百分比/+/适应窗口；EditorState.fitRequestTick）；shouye A 线 6 项全 PASS（qa_report_zoom_ch_2026-08-30.md）；dana **Approve**（code_review_zoom_ch_2026-08-30.md，3 条关注项均非功能破坏：滚轮方向待人工实测/锚点漂移体验项/并发低概率）
- **ch.jpg 改字 E2E：FAIL（坐实 D-028）**：CLI 实测检出版本串区域（y≈718，'VO.20.0' conf 0.5 / 'vO.20.0' conf 0.3——OCR 有 0↔1 / V↔VO 歧义）；GUI 证据链：runPreviewPipeline 占位 + CanvasView 渲原图 + confirm 只改数据 + export 导原图 → **改数据不改像素**，CEO 验收标准"图上文字真的变"未达成
- **关键反转（dana 复核）**：Core 层能力齐全——EditingWorkflow(previewEdit/confirmEdit) / TextEraser / BlockPatchBuilder 均在，`testEndToEndEraseRenderPatchMaterialize` 证明像素级真变（patch.before != after、confirm 后 crop==patch.after）。**缺的只有 UI 接线**
- **UI 接线评估（dana）**：L2 级，零 Core 改动，改 UI 编排层（CanvasView 渲合成图 / confirm 走 Core confirmEdit / export 导合成图）；最大风险=EditorState 自管 textBlocks+undo 与 Core EditorDocument 数据权威统一；OCR 歧义不阻塞（patch 基于用户确认文本重绘）
- **CI 挂起（QA C2 + dana 复现）**：swift test 全 PASS 但进程 60s 不退出 → 阻断 CI，P1 待修（v0.4 前置）
- **裁决**：产品整体=Request Changes（CEO 验收项改字未达）；建议 v0.4 单迭代 = UI 接线 Core 重绘 + CI 挂起修复，收口改字验收
- **汇报决策**：缩放可验收先行交付；改字 FAIL 如实上报，携带完整根因与 v0.4 方案，请求 CEO 授权排期

## D-031 v0.4 开工：Core 补口完成 + CI 策略裁决（2026-08-30）

- **zhenhai 交付**：
  1. `EditingWorkflow.analyzeStyles() async throws -> StyleAnalysisSummary`（协议新方法；只分析 style==nil 块；单块失败不中断；幂等；open 不自动触发、UI 显式调用）；注入扩展（fontCatalogBuilder/fontMatcher/styleAnalyzer 带默认值）；TDD 5 新用例全绿（49/49）
  2. **swift test 挂起根因（P1）**：Swift 6.3.2 CommandLineTools（macOS 26 arm64）`-Onone` 工具链级故障——单测试确定性挂起、ASan 静默、exclusivity 无关、`-c release` 4.2s 通过；预存于任何改动前。代码侧加固保留（ImagePixels rgba 直读 + CoreFontGate CTFont 串行化）
- **裁决（CI 策略）**：accept 工具链诊断。CI/验收统一切 `swift test -c release`（49/49, 7.2s, exit 0 干净退出）。debug test 挂起为环境已知问题，记录不追杀
- **下一步**：xiaoyou UI 接线（EditorState 改 Core 权威 + CanvasView patch 叠加 + export 走 workflow），依赖 analyzeStyles 契约（已落）

## D-032 QA 揪出垂直镜像 P0：ImagePixels.rgba 行序双路径缺陷（2026-08-30）

- **现象（shouye 铁证）**：v0.4 改字物化真实发生（patch 569×156 完整正立、逐像素一致 sum diff=0），但落在 `(592,407)` = 版本区 `(592,717)` 的**垂直镜像**（407 = 1280−717−156）；版本区全链路从未被改写（v0.20.1 纹丝未动）。用户症状：预览显示 v1.21.1 → 确认后版本区没变、v1.21.1 出现在 Hermes 标题区
- **根因**：`ImagePixels.rgba` 双路径——ch.jpg 走 rgbaDirect（provider 直拷行序）未做 y 翻转，与 UI/画布坐标系（y-down）镜像；CG 系小图单测走另一路径且数值自洽 → 合成图单测全绿掩盖缺陷
- **影响**：CEO 验收项（ch.jpg 改字）FAIL；undo/redo 落点连带镜像（机制自洽但坐标错）
- **裁决**：P0 修复（zhenhai）→ 修毕 shouye 重跑 A2/A3/B → dana 审查（焦点：ImagePixels 行序语义统一 + crop/compositeAfter/replaceImageRegion 的 y 索引 + 补真实 JPEG UI 坐标系单测）→ 打包 → 汇报
- **范围纪律**：v0.4 其余全 PASS（构建 49/49 / 三拦截 / UI 审查 24 项 / 缩放回归 / GUI 冒烟），唯一阻塞 = 镜像坐标

## D-033 镜像争议仲裁：QA 环境 vs zhenhai 本机结论冲突（2026-08-30）

- **zhenhai 反证**：本机全链路正确（patch 落 (592,717) 版本区 sumAbs=0）；rgbaDirect==rgbaDraw 行为一致（top-down 正/bottom-up 镜像）；镜像机制=解码端 provider 行序（bottom-up→镜像，CGImage 无方向信号）；ch.jpg EXIF=1；本机 52 测试全绿（含 3 新契约测试 ImagePixelsContractTests：真实 JPEG E2E 镜像回归锁，bottom-up 环境必红）
- **冲突本质**：同一机器同一文件，shouye（debug 临时工程）镜像 vs zhenhai（探针重编）正确 → 疑构建模式/上下文差异（debug -Onone 已知挂起 bug 同源工具链？）或探针实现差异
- **zhenhai 已产出**：ImagePixelsContractTests（3 契约测试）+ ImagePixels/SourceImage 行序契约注释（零行为变更）；请求决策 A/B/C
- **裁决（仲裁计划）**：不采信单方结论。①派 shouye 用 zhenhai 探针（/tmp/pxiu_probe/）**原样**重跑 + debug/release 双模式复测镜像 ②二分分歧点（构建模式？探针实现？）③据实定修复空间（环境差异→CI 统一 release 验收 + bottom-up 契约测试为信号；代码缺陷→zhenhai 修）④dana 审查契约测试
- **纪律**：全链路验收路径已定 `swift test -c release --no-parallel`（D-031），仲裁结论须与之对齐

## D-034 仲裁结案：镜像不存在，qa_report_v04 的 A2/A3/B 结论更正（2026-08-30）

- **裁决证据（shouye 复测，qa_report_mirror_arbitration_2026-08-30.md）**：zhenhai 探针原样跑 sumAbs=0 落原址 (592,717)；debug/release 双模式数值逐位相同均正确；**上轮 12:10 exported.png 与当前重导出全图全等 sum=0**；上轮 (592,717) 区域 = 正立 v1.21.1（被改写），(592,407) 任何方向模板均不吻合——**镜像从未发生**
- **上轮错误机制**：QA 验证脚本保管的 patch.after 缓冲与正确缓冲互为上下翻转，翻转模板在 top-down 源图上"表面吻合"mirrorY=H−y−h → 误报镜像。**验证脚本坐标/方向解读错误，非运行时缺陷**
- **更正**：qa_report_v04 的 A2 改字物化 / A3 undo-redo / B CEO 验收 **FAIL → PASS**。CEO 验收项（ch.jpg v0.20.1→v1.21.1 真像素替换）**成立**
- **边界（如实）**：12:45 前（zhenhai 加注释时点）中间层行序是否曾有差异不可判定（无 git、临时工程已清理），但验收产物（12:10 与现在全等）不受影响；rgbaDraw 慢路径 / EXIF orientation>1 / HEIC/P3 provider 行序未覆盖 → 建议 zhenhai 补用例（v0.4.1 项）
- **行动**：zhenhai 无需修缺陷；保留 ImagePixelsContractTests（bottom-up 环境信号）；dana 按 v0.4 全量审查；打包 alpha.3；汇报 CEO

## D-030 待 CEO 授权 v0.4（UI 接线 Core 重绘 + CI 修复）

- 内容：① UI patch 合成接线（CanvasView + EditorState + export）② swift test 挂起修复 ③ ui_audit 补缩放节 ④ 回归 + 重打包
- 状态：**CEO 已批**（2026-08-30）；执行中（D-031 完成后进入 UI 接线）

---
*决策变更时追加新条目，不修改历史。*