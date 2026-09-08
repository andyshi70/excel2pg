# UI 审计报告 — pxiu v0.4 核心重构（UI 管线接入 Core EditorDocument/EditorWorkflow）

- 版本：v0.4
- 日期：2026-08-30
- 撰写：xiaoyou（前端工程师）
- 依据：tech_spec_pxiu_2026-08-28.md §3/§4/§5、page_states_pxiu_2026-08-28.md §5、dana 批准 v0.4 改造方案
- 消费者：shouye（QA 测试基准）、dana（代码审查）、zongguan（验收）

---

## 0. 改造目标（dana 方案原文摘要）

UI 编辑管线从「自管数据 + 占位预览」切换到「Core EditorDocument/EditorWorkflow 权威 + 真实像素 patch 合成」：

1. **数据权威统一**：UI 的 EditorState 不再自管 textBlocks / undo 栈 / 命令，全部转发 Core `EditorDocument`；编辑操作走 `EditorWorkflow`。
2. **改字像素化**：确认后 sourceImage 物化（patch 回贴），画布渲染源自动变新图；导出经 workflow 导出物化后图。
3. **撤销/重做像素级**：Core `TextEditCommand` 带 patch before/after，undo/redo 回贴裁剪。

---

## 1. 改动文件清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `Sources/PxiuApp/EditorState.swift` | **重写（441→~470 行）** | 核心重构主体，见 §2 |
| `Sources/PxiuApp/CanvasView.swift` | 局部（+~15 行） | ① 图片层加 `.id(state.revision)`；② 新增 `previewPatchLayer` 真实像素叠加 |
| `Sources/PxiuApp/Feedback.swift` | 局部（+10 行） | 新增 `FeedbackFactory.styleNotReady()`（style==nil 时预览被拒的提示） |
| `Sources/PxiuApp/UndoRedo.swift` | **删除（128 行）** | UI 命令族全部废弃（UIDocumentCommand/UITextEditCommand/UIBlockGeometryCommand/UIBlockStructuralCommand/UIStyleOverrideCommand），全改 Core Commands.swift |
| `Sources/PxiuApp/InspectorView.swift` | 微调（onChange 分支扩展，~7 行） | preview 态继续改字也调 beginPreview（就地重跑），防确认物化旧文本；详见 §2.4 |
| `Sources/PxiuApp/ToolbarView.swift` | **零改动** | undo/redo/canUndo/canRedo 转发已通；禁用态经 revision 桥接自动刷新 |
| `Sources/PxiuApp/PxiuApp.swift` | **零改动** | AppModel.open → editor.open（内部已改）；菜单 undo/redo/导出转发已通 |
| `Sources/PxiuCore/**` | **零改动** | Core 禁止修改约束遵守 |
| `Tests/**` | **零改动** | PxiuCoreTests 无 UI 命令引用（已确认） |

---

## 2. EditorState.swift 重构说明

### 2.1 新增持有（单根权威）

```swift
let document: EditorDocument
let workflow: EditorWorkflow

init() {
    let doc = EditorDocument()
    document = doc
    workflow = EditorWorkflow(document: doc)   // init 注入默认齐全依赖
}
```

- 用显式 `init` 而非 `lazy var`：规避 @Observable 宏对 lazy stored 属性的兼容性坑。
- workflow 的默认依赖（TextEraser/TextRenderer/CollisionDetector/ImageLoader/TextBlockDetector/Exporter/FontCatalogBuilder/FontMatcher/StyleAnalyzer）全部经 init 默认参数注入，UI 侧零配置。

### 2.2 转发性（对外 API 形状保持，Toolbar/Canvas/Inspector 现有引用少改/零改）

```swift
var sourceImage: SourceImage? { _ = revision; return document.sourceImage }
var textBlocks:  [TextBlock] { _ = revision; return document.textBlocks }
var phase:       EditorPhase  { _ = revision; return document.phase }
var selection:   UUID?        { _ = revision; return document.selection }
var canUndo:     Bool         { _ = revision; return document.canUndo }
var canRedo:     Bool         { _ = revision; return document.canRedo }
```

**刷新机制（关键坑，本次改造最核心的设计决策）**：

- `EditorDocument` 是 plain class（非 @Observable），document 内部变更后 SwiftUI **无法感知**。
- 解决：`private(set) var revision = 0`（@Observable stored）作为观察桥接。所有转发 computed 内部**先读 revision 再读 document**——Observation 运行时已追踪对 `revision` 的读取，因此引用这些 computed 的任何视图（CanvasView / InspectorView / ToolbarView / PxiuApp 菜单 disabled 态）都会在 revision 变化后重新求值。
- 任一触达 document 的入口在变更后 `bump()`（`revision &+= 1`）：open 成功/失败、analyzeStyles 完成、beginPreview、confirmPreview、continueEditing、cancelPreview、undo/redo、moveBlock、addBlock、deleteBlock、mergeBlocks、applyStyleOverride、runPreview 结束。
- 物化路径额外保险：CanvasView 图片层 `.id(state.revision)`——confirm/undo 回贴 patch 后 cgImage 变化，`.id` 强制重建像素层（SwiftUI Image 对同源 CGImage 的展示缓存问题一并规避）。

**为什么不给 InspectorView 加 `.id(state.revision)`**：InspectorView 持有 @State `textInput`（草稿框），`.id` 重建会**重置草稿**（打字中被异步 bump 打断 = 灾难）。poke pattern（computed 内读 revision）达成同样刷新效果且不重建视图身份。这是对 dana 方案「用 .id(state.revision) 或 onChange 桥接」的实现层面的优化选择。

### 2.3 各操作转发映射（内部行为改造表）

| UI 操作（对外不变） | 旧实现（UI 自管） | 新实现（Core 权威） |
|------|------|------|
| `select(blockID:)` | 自检 loading/存在 + 自设 phase/selection | `document.select(blockID)`（Core 内含 loading 禁选 + 存在校验）+ 清 draft/previewResult |
| `beginPreview(id:)` | 自置 .preview + 本地提交 text | `document.beginPreview(id)`（selected→preview）+ **preview 态就地重跑**（Inspector onChange 已扩分支）：每次改字重跑 `previewEdit` 覆盖 previewResult/pendingEdit；`runPreview` 后 `confirmBlocked` 派生保留（数据源换真实 WorkflowError） |
| `confirmPreview()` | 自建 UITextEditCommand + 自管栈 | `workflow.confirmEdit(id)`（物化 patch 回贴 + 入 Core undo 栈 + preview→idle）；**新增一致性校验**：`previewResult.newText == draft.trimmed` 不满足（预览中继续改字后立刻点确认）→ 拦「预览尚未完成」，防 pendingEdit 旧文本误物化 |
| `continueEditing()` | 自置 .selected | `document.cancelPreview()`（**保留** workflow.pendingEdit 与 draft——用户可继续调整；比 workflow.cancelPreview 更贴旧语义，见 §4 风险） |
| `cancelPreview()` | 回退本地文本 + 自置 .selected | `workflow.cancelPreview()`（弃草稿 + 弃 pendingEdit + 回 selected） |
| `undo()/redo()` | 自弹 UI 命令栈 | `workflow.undo()/redo()`（内含 generation++ 弃 in-flight 预览防幽灵编辑） |
| `moveBlock()` | UIBlockGeometryCommand | 尺寸不变→`workflow.moveBlock`（纯平移）；尺寸变→`workflow.resizeBlock`（角柄缩放），调用点零改 |
| `addBlock()` | UIBlockStructuralCommand(.add) | `document.commit(BlockStructuralCommand(add:true))` + `document.select` 补 selection（§5.4 直达 selected） |
| `deleteBlock()` | UIBlockStructuralCommand(.delete) | `document.commit(BlockStructuralCommand(add:false))` |
| `mergeBlocks()` | UIBlockStructuralCommand(.merge) | **三条 Core 命令**（删除被吸收块 + keep 文本 TextEditCommand(patch:nil) + keep 几何 BlockGeometryCommand），undo 逆序完整恢复 |
| `applyStyleOverride()` | UIStyleOverrideCommand | `document.commit(StyleOverrideCommand(...))` |
| `export()` | 直连 Exporter | `workflow.export(format:to:)`（导出物化后源图） |

### 2.4 预览管线：占位 → 真实

删除 `runPreviewPipeline` / `previewFit` / `PreviewFitResult` / `UIUICollisionDetector`（占位实现全部移除），替换为：

```swift
private func runPreview(blockID: UUID) async {
    ...
    let result = try await workflow.previewEdit(blockID: blockID, newText: draft.newText)
    previewResult = result                      // EditPreviewResult（含真实 BlockPatch）
    pendingFitFeedback[blockID] = []            // 成功清空拟合反馈
    // 错误映射（保留 UI 现有反馈语义，数据源换真实 WorkflowError）：
    //   collision(hits)     → FeedbackFactory.collision(overlapCount:)      blocksConfirm
    //   textTooLong         → FeedbackFactory.textTooLong(minFontReached:true)
    //   styleNotAnalyzed    → FeedbackFactory.styleNotReady()（新增）         blocksConfirm
    //   staleResult         → 静默丢弃（用户已取消/继续编辑/撤销）
    //   兜底                → overlay「预览处理失败：<中文文案>」
}
```

- `confirmBlocked` / `facesCollision` / `isTooLong` 派生保留（数据源 = pendingFitFeedback 真实错误映射 + style warnings）。
- `previewResult: EditPreviewResult?` 缓存 = 画布 patch 叠加层渲染 + confirm 物化数据源（confirmEdit 用 workflow 内部 pendingEdit，此缓存仅供画布展示）。

### 2.5 CanvasView patch 合成层

```
ZStack(alignment: .topLeading)
├─ Image(sourceImage.cgImage) .id(state.revision)   ← 物化后强制重建
├─ previewPatchLayer                                 ← 新增：真实像素替换
│    if let pr = state.previewResult:
│    Image(decorative: pr.patch.after.cgImage, scale:1)
│        .frame(rect.size).position(rect.midX, midY)
├─ BlockFrameLayer（虚线框）
├─ ForEach(BlockInteractor)（文字块框/选中/拖拽）
└─ 添加框选高亮
```

- `patch.rect` 是图像坐标（= 容器坐标），随外层 `scaleEffect`/`offset` 整体变换，坐标正确。
- `patch.after` = 抹除后背景 + 新字形复合（Core TextEraser+TextRenderer 产出），预览即所见像素。

---

## 3. 删除文件

- `Sources/PxiuApp/UndoRedo.swift`（128 行）：UI 命令族 + UI undo/redo 栈全部废弃。已确认 PxiuCoreTests 无引用；EditorState 内部引用已全部改写。`UndoRedo.swift` 头部注释中的「Core 补齐后桥接」协调项随本次改造闭环。

---

## 4. 残留 TODO / 风险点（向 zongguan 汇报项）

| # | 风险 | 现状 | 建议 |
|---|------|------|------|
| R1 | **undo/redo 删除选中块后 phase 残留** `selected(已删id)` | Core `EditorDocument` 无「取消选中」公开 API（selection/phase 均 private(set)），删除选中块后 phase 停留 selected(已删id)；UI 已容错（selectedBlock=nil → Inspector 显示空态、画布无框），但保存语义不干净 | 建议 zhenhai 补 `deselect()` 或 `removeBlock` 联动清选中，v0.4.1 |
| R2 | **重复打开文件时 loading 语义弱化** | `EditorDocument.phase` 无 loading 写入 API（open 前无法显式置 .loading）；首次打开正常（init 即 .loading），重复打开时画布短暂显示旧图直至 OCR 完成 | 建议 zhenhai 暴露 `setLoading()` 或在 open 内先置；v0.4.1 |
| R3 | **mergeBlocks 用 3 条 Core 命令**（结构+文本+几何） | 语义完整、undo 逆序恢复正确；但部分撤销（仅 undo 一次）会进入中间态（Core 逐命令弹栈的固有属性） | 如收窄需求可加复合命令，v1.1 |
| R4 | **residualMetric（抹除残留）未接入 UI** | tech_spec §5 要求「残影超阈值弱提示」，但阈值未定义（残留度无标定基准），旧 UI 同样未接；`FeedbackFactory.residualReminder()` 存在未使用 | 阈值待 zhenhai 标定后接入 feedback |
| R5 | **continueEditing 与 dana 方案细微差异** | dana 方案「continueEditing: 调 workflow.cancelPreview()」会弃 pendingEdit/draft；实现采用 `document.cancelPreview()`（保留草稿，用户可继续调整后重新预览），与旧 UI 语义一致 | 已记录，若产品要「放弃后重进预览」语义再调整 |
| R6 | **样式分析失败的块** | analyzeStyles 单块失败 → style=nil → Inspector 显示「样式分析中…」+ 手动选字体兜底；试图预览 → styleNotReady 黄条（确认禁用） | 待 zhenhai 确认「失败」与「未完成」的 UI 区分（建议 errored status 标记） |

---

## 5. 构建与测试证据

### 5.1 命令与结果

| 命令 | 结果 |
|------|------|
| `swift build`（debug） | ✅ Build complete!（1.88s；仅剩 PxiuCore StyleEstimators 一处 let 警告，属 zhenhai 代码，禁改） |
| `swift build -c release` | ✅ Build complete!（4.66s） |
| `swift test -c release --no-parallel` | ✅ **Test run with 49 tests passed after 6.349s**，进程正常退出 |

### 5.2 测试明细（49 = 全部 PxiuCoreTests）

| Suite | 用例数 | 结果 |
|-------|-------|------|
| EditorDocumentTests | 5 | ✅ |
| CollisionDetectorTests | 6 | ✅ |
| EstimationTests | 4 | ✅（U3 SizeRecovery 4.0s 渲染密集） |
| PixelMetricsTests | 3 | ✅ |
| ExporterTests | 2 | ✅（U10 PNG/JPEG 往返） |
| FitCalculatorTests | 4 | ✅（U7 过长/变短/不放大） |
| TextRendererTests | 1 | ✅ |
| InpainterTests | 4 | ✅（U6 平坦/渐变/噪声 SSIM） |
| EditingWorkflowTests | 14 | ✅（端到端 erase→render→patch 物化、undo/redo、碰撞/过长错误路径、stale 过期） |
| FontMatcherTests | 5 | ✅（U1 准确率/U2 抗 AA/全字体枚举） |

### 5.3 环境问题说明（重要，供 zongguan 决策）

- 默认 `swift test -c release`（不带参数）**整体挂起**（swiftpm-testing-helper 进程 0% CPU 不退出，已两次复现，最长等过 20 分钟）。
- 同一台机器上：`--filter` 单类 / `--no-parallel -v` 全量均**秒级通过且正常退出**。
- 复现时均确认**无残留测试进程**（kill 后重跑），排除陈旧进程占用。
- 结论：这是 swift-testing 默认 runner 在此环境的工具链问题（zhenhai 之前记录的 debug 挂起同源——debug 工具链挂起是环境问题，验收用 release；release 默认 runner 亦有该问题，**显式 `--no-parallel` 为可靠验收路径**）。与本次 UI 重构无关（PxiuCore/PxiuCoreTests 零改动，UI 目标不参与测试）。

---

## 6. page_states §5 状态转移约束核对（QA 基准）

| 约束 | 实现 | 验证 |
|------|------|------|
| §5.1 loading 禁选中 | `document.select` guard phase != .loading | ✓ 代码审查 |
| §5.2 idle→selected 仅经点击有效块 | select 校验块存在性（Core） | ✓ |
| §5.3 selected→preview 仅内容变更 | beginPreview guard draft.newText != block.text；样式调整走 applyStyleOverride 不触发；preview 态改字 → 就地重跑（重新预览，非换 phase） | ✓ |
| §5.4 noText 添加块直达 selected | document.addBlock（idle/noText→selected）+ select 补 selection | ✓ |
| §5.5 overlay 不阻断编辑主链路 | overlay 为 UI 自管存储，与 phase 正交；processing 不设 guard | ✓ |

---

*本文档为 xiaoyou v0.4 交付审计。后续测试：shouye 按 §5 表格 + EditingWorkflowTests 端到端验收；dana 审查 §1 改动文件。*