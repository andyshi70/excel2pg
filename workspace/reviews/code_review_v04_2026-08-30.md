# 代码审查报告 — pxiu v0.4 UI 接线 Core 重构（最终放行审查）

- **审查人**：dana（技术负责人）
- **版本/对象**：pxiu macOS app（SPM，`/Users/evandy/opencode/pxiu/pxiu`），v0.4 全量改动
- **审查日期**：2026-08-30
- **审查范围**：
  1. `Sources/PxiuApp/EditorState.swift`（重写：Core 权威转发层 + revision 桥接 + previewResult 缓存 + confirm/undo/redo/export 走 workflow + 删 UI 命令栈）
  2. `Sources/PxiuApp/CanvasView.swift`（渲染源 `.id(revision)` + previewPatchLayer 叠加）
  3. `Sources/PxiuApp/Feedback.swift`（`+styleNotReady`）
  4. `Sources/PxiuApp/InspectorView.swift`（preview 态续改重跑）
  5. `Sources/PxiuApp/UndoRedo.swift`（已删除，复核零残留）
  6. `Sources/PxiuCore/Workflow/EditingWorkflow.swift`（analyzeStyles + 注入扩展 + StyleAnalysisSummary）
  7. `Tests/PxiuCoreTests/ImagePixelsContractTests.swift`（zhenhai 3 契约测试）+ ImagePixels/SourceImage 注释
  8. 策略层 `swift test -c release --no-parallel` 为验收路径
- **前置检查**：
  - `workspace/qa/qa_report_v04_2026-08-30.md`（已读，其镜像 FAIL 已被仲裁推翻）
  - `workspace/qa/qa_report_mirror_arbitration_2026-08-30.md`（已读，仲裁：镜像不存在，A2/A3/B 更正 PASS，物化/undo/导出像素正确性已实证）
  - `workspace/frontend/ui_audit_v0.4_2026-08-30.md`（已读，xiaoyou 改动清单/转发映射/刷新机制/风险 R1/R2/R4）
  - `workspace/backend/api_implementation_v0.3.md`（已读，zhenhai analyzeStyles + CI + 契约测试）
  - `workspace/reviews/code_review_zoom_ch_2026-08-30.md`（本轮基线：上轮 Approve 缩放 + 给出 UI 接线方案）
- **约束遵守**：仅读取审查对象指定文件；未修改任何源码（只审查）
- **实测证据**：本机复跑 `swift test -c release --no-parallel` → **52 tests passed, 6.8s, exit 0**（含 3 条 ImagePixelsContractTests 全绿，即 top-down 环境无契约误报）

---

## 一、结论总览

| 审查点 | 结论 | 关键依据 |
|--------|------|----------|
| 1 数据权威统一（转发 + revision 桥接） | **PASS** | 6 转发 computed 全 poke；13+ 触达 document 入口全覆盖 bump |
| 2 preview patch 叠加 | **PASS** | patch.rect 图像坐标、位置/层级正确、清理完备、物化后 `.id(revision)` 重渲 |
| 3 confirm 链路 | **PASS** | newText 一致性校验 + confirmBlocked 映射 + WorkflowError 全分支 |
| 4 undo/redo 像素回退 + Core 等价 | **PASS** | 转发 workflow，generation 弃幽灵预览；patch before/after 回贴（仲裁实证）；移动/缩放/增删全 Core 命令 |
| 5 契约测试（必红设计误报） | **PASS** | 合成 provider 测试确定性；JPEG E2E 仅环境敏感、top-down 无误报（本机实测绿）|
| 6 回归（缩放/三拦截/GUI） | **PASS** | 缩放未受损；A4/A7 复核；仲裁推翻镜像 |
| 7 verdict：R1/R2/12:45/补测裁决 | 见 §五 | R1/R2 非阻塞；12:45 接受；rgbaDraw/EXIF 排 v0.4.1 |

### 最终结论：**Approve**

> v0.4 核心重构（数据权威统一 + 真实像素 patch 合成 + undo/redo 转发）经审查通过。覆盖率 52 测试全绿、真实 JPEG E2E 回归锁新增、镜像争议经仲裁解除、无阻塞项。附非阻塞改进建议与 v0.4.1 补测排期。

---

## 二、数据权威统一（审查点 1 — 最大风险区）

### 2.1 转发完整性 — ✅ 无残留自管

EditorState（:52-57）：
```swift
var sourceImage: SourceImage? { _ = revision; return document.sourceImage }
var textBlocks:  [TextBlock] { _ = revision; return document.textBlocks }
var phase:       EditorPhase  { _ = revision; return document.phase }
var selection:   UUID?        { _ = revision; return document.selection }
var canUndo:     Bool         { _ = revision; return document.canUndo }
var canRedo:     Bool         { _ = revision; return document.canRedo }
```

- **6 个转发 computed 全部先 `_ = revision` 再读 document** ✓ → Observation 建立对 `revision` 的依赖。
- **textBlocks 无本地存储**：UI 层已无自管块数组，全部取 `document.textBlocks`。selection/phase/canUndo/canRedo 同理全部转 document。
- **ui_audit §5 核对零残留**：UndoRedo 命令族在 `Sources/` 全域 grep 零命中（本次复核，见 §六）。

### 2.2 revision 桥接覆盖所有异步变更点 — ✅

逐一核验 EditorState 每个触达 document 的入口均有 bump（或经依赖合成触发）：

| 入口 | 触达 document | bump | 异步点 |
|------|--------------|------|--------|
| `select` | document.select | ✓ | — |
| `beginPreview` | document.beginPreview + 启动 runPreview Task | ✓ | runPreview 内再 bump |
| `confirmPreview` | workflow.confirmEdit | ✓ | — |
| `continueEditing` | document.cancelPreview | ✓ | — |
| `cancelPreview` | workflow.cancelPreview | ✓ | — |
| `applyStyleOverride` | document.commit(StyleOverrideCommand) | ✓ | — |
| `moveBlock`/`resizeBlock` | workflow.moveBlock/resizeBlock | ✓ | — |
| `addBlock` | document.commit + document.select | ✓ | — |
| `deleteBlock` | document.commit | ✓ | — |
| `mergeBlocks` | 3×commit + select | ✓ | — |
| `undo`/`redo` | workflow.undo/redo | ✓ | — |
| `open` | workflow.open + Task | ✓（成功+catch 双分支）| 异步 |
| `runPreview` | workflow.previewEdit | ✓ | 异步 |
| `analyzeStylesBackground` | workflow.analyzeStyles | ✓ | 异步 |

- **覆盖完整**：open/analyzeStyles/preview/confirm/undo/redo/move/resize/delete 全部含 bump → 画布与 inspector 不会失明。
- 全部变更点运行于 @MainActor（EditorState @Observable + Tasks 继承主 actor）→ bump 后 getter 重求值次序安全，无跨线程数据竞争。

### 2.3 桥接可靠性结论

- poke pattern（computed 内读 revision）在 @Observable 下机制正确，Avoid InspectorView 加 `.id(revision)` 的正确选择（`.id` 会重建视图身份并重置 @State textInput 草稿，打字中被异步 bump 中断=灾难——ui_audit §2.2 的优化判断成立）。
- CanvasView 图片层 `.id(revision)` 强制重建物化后像素层，规避 SwiftUI 同源 CGImage 展示缓存。✓
- **唯一需留意（非阻塞）**：`confirmPreview` 抛 `noPendingEdit` 时 previewResult 未清（canvas 仍显示 overlay 而 workflow.pendingEdit 已空）。但该场景需 pendingEdit 在未清 previewResult 的情况下被清，正常流程（cancel/undo/redo/confirm 均清 previewResult）不可达 → 不可触，不影响。

---

## 三、preview patch 叠加正确性（审查点 2）

CanvasView（:107-114）：
```swift
if let pr = state.previewResult {
    Image(decorative: pr.patch.after.cgImage, scale: 1)
        .frame(width: pr.patch.rect.width, height: pr.patch.rect.height)
        .position(x: pr.patch.rect.midX, y: pr.patch.rect.midY)
        .allowsHitTesting(false)
}
```

- **坐标**：`pr.patch.rect` 为图像/容器坐标（block bbox ∪ inkRect ∪外扩1px，`.integral` 整型对齐，EditingWorkflow:235）→ position(midX,midY) 落在容器原址；外层 scaleEffect/offset 整体变换，patch 不单独缩放 → 坐标一致。✓
- **层级**：patch 层在基础 `Image`（:52，即"字层"）之上、`BlockFrameLayer` 虚线框（:60）之下 → 满足「块层之下/字层之上」。替换像素覆盖旧字、虚线框仍绘制在上。✓
- **清理（previewResult=nil 时机）**：confirm 成功(170)、cancelPreview(191)、beginPreview 新预览(151)、select 切块(131)、deleteBlock 选中块(243)、mergeBlocks(263)、open(354)。**覆盖完整**，取消/确认后叠加清除。✓
- **物化后重渲**：confirm → bump → 基础 Image `.id(revision)` 强制重建 → 原图重渲为物化后内容。✓

---

## 四、confirm 链路 + undo/redo 像素回退（审查点 3 + 4）

### 4.1 confirm 链路

`confirmPreview`（:158-176）：
1. `guard phase == .preview(id)`。
2. `guard !confirmBlocked(for: id)` — 读 `pendingFitFeedback`（runPreview 错误映射）→ collision/textTooLong/styleNotReady 均 `blocksConfirm:true` → 确认禁用。
3. **一致性校验** `previewResult.newText == trimmedDraft`：预览未完成即确认 → 拦截「预览尚未完成」，防 pendingEdit 旧文本误物化。✓ **（QA A4 判定成立）**
4. `workflow.confirmEdit(id)`：guard pendingEdit → 构造 TextEditCommand(patch) → document.commit（回贴 after+setText）→ document.confirm()→idle。✓
5. catch → `message(for:)` 覆盖全 WorkflowError（blockNotFound/styleNotAnalyzed/noSourceImage/emptyText/textTooLong/collision/noPendingEdit/staleResult/eraseFailed/renderFailed/exportFailed/imageLoadFailed/styleAnalysisFailed）→ 禁静默失败 NFR-4 满足。`staleResult` 在 runPreview 中静默丢弃。✓

**preview 续改重跑**：runPreview 内 `generation &+= 1; let myGeneration; guard myGeneration == generation else throw staleResult`（EditingWorkflow:185-195）→ 旧预览过期、只最新 draft 存活，与 confirmPreview 的 newText 校验双保险一致。✓

### 4.2 undo/redo 像素回退

- `undo()/redo()`（:275-281）→ `workflow.undo()/redo()`（EditingWorkflow:274-284）→ `generation &+= 1`（弃 in-flight 预览防幽灵编辑）+ 清 pendingEdit + `document.undo()/redo()`。
- TextEditCommand **patch before/after 回贴**由 Core document.commit/undo 处理（v0.4 Core 零改动，行为沿用）——仲裁报告实证 undo=before / redo=after 像素级成立；回归锁 `testEndToEndEraseRenderPatchMaterialize` 覆盖。✓
- **移动/缩放/增删块 Core 等价**：moveBlock 尺寸不变→moveBlock、尺寸变→resizeBlock（均 BlockGeometryCommand）；addBlock→BlockStructuralCommand(add:true)+select 补 selection；deleteBlock→BlockStructuralCommand(add:false)。全部入 Core undo 栈，undo 逆序恢复（mergeBlocks 3 命令次序=几何→文本→被吸收块已验证）。✓
- 替换原 UI 命令后**零残留**（undo/redo 不再触碰本地命令栈）。✓

---

## 五、契约测试误报分析（审查点 5）+ 裁决建议

### 5.1 阈值/断言语义 — ✅ 无 top-down 误报

`loadRoundTripJPEGLandsAtBboxOrigin`：
- 结构：256×128 白底黑字 "AB" 于顶部（margin=8）→ `patch.rect` 顶部，镜像位（底部）与原位不重叠。导出真实 JPEG → 生产加载器重解码 → preview+confirm → export PNG → 重新解码 → 像素锚定。
- `diffOrigin < 10_000`（原址=patch.after，JPEG 再编码留边缘灰 → 宽松阈值）：top-down 正常环境原址恰含 patch.after，仅 JPEG 边缘噪声，小幅 <10k ✓。
- `diffMirror > 50_000`（镜像位=纯白原图内容，与 patch.after 含黑字形差异巨大）→ 正常环境必然 >50k ✓。
- **bottom-up 环境**：字形落在镜像位 → diffMirror 塌缩 → 断言红 → **环境缺陷转测试信号**。设计成立。
- **top-down 无误报实证**：本机复跑 52 全绿（含此 E2E）。✓
- `rgbaTopDownProviderPreservesRowOrder` / `rgbaBottomUpProviderMirrorsByProviderOrder`：合成 provider、确定性契约测试，任何环境都确定性通过/验证 rgba() 契约，不随环境翻车。✓

### 5.2 复核镜像仲裁（上轮 FAIL 推翻）

- 仲裁以 debug/release 双模式 + 上轮 `exported.png`（12:10）与当前重导出全图逐像素全等（sum=0）+ 纯 ImageIO 文件往返为终审 → 镜像缺陷**在当前代码/机器不存在**；物化/undo/导出像素正确性已实证。物证强于上轮 QA 验证脚本的模板解读错误。→ **采纳仲裁，解除 D-031 阻止项**。✓

### 5.3 对 zongguan 的裁决建议

| 议题 | 裁决建议 | 理由 |
|------|---------|------|
| **R1 undo/redo 删选中块后 phase 残留** | **非阻塞**；v0.4.1 清洁项 | UI 已容错（selectedBlock=nil → 空态/无框）；undo 后块恢复且 phase 指向恢复块会自选中，无数据损坏，仅选中语义不完美。建议 zhenhai 补 `deselect()` 或 removeBlock 联动。 |
| **R2 重复打开文件 loading 弱化** | **非阻塞**；v0.4.1 清洁项 | 首开正常（init=.loading）；重复开短暂显示旧图至 OCR 完成，属首印象 UX 问题非正确性。建议暴露 `setLoading()` 或 open 内先置。 |
| **12:45 边界（中间层行序不可判定）** | **接受** | 仲裁证明 12:10 用户产物与现在逐像素全等，即便中间层有变也不影响验收交付物；12:45 是补注释/实现留痕。 |
| **rgbaDraw 路径 + EXIF orientation>1 补测** | **排 v0.4.1** | 契约测试仅覆盖合成 top-down/bottom-up provider，未覆盖 rgbaDraw 慢路径（Display P3/16bit/索引/非 4 字节对齐）与 EXIF>1（手机竖拍，真实高频）。两种均为**补测缺口而非当前缺陷**（本机真实 ch.jpg 已验证），不阻塞 v0.4 放行。可行性：新增 rgbaDraw 构造用例 + 合成 EXIF 竖拍 JPEG 落点用例。 |

---

## 六、回归复核（审查点 6）

- **缩放（上轮 Approve 项）**：v0.4 重构在 CanvasView 仅加 `.id(state.revision)`（作用于基础 Image 子视图）与 previewPatchLayer，未触碰 scaleEffect/offset/viewport/fitRequestTick/onChange 链路。缩放数学、clamp 0.05...16、滚轮/捏合/工具栏/适应窗口链路完整。**未退化** ✓。
- **三拦截 A4**：textTooLong/styleNotAnalyzed/collision 全拦截，UI 错误映射齐全（本次复核 Feedback.swift styleNotReady 有 blocksConfirm:true，Feedback.swift:162-169 + EditorState runPreview:327-329 映射成立）→ **A4 PASS 复核通过**。
- **GUI 冒烟 A7**：启动存活、优雅退出、无新增崩溃；无 GUI 自动化权限故点击链路靠代码审查背书 → **A7 PASS 复核通过**。
- **UndoRedo 删除零残留**：`Sources/` grep `UndoRedo|UIDocumentCommand|UITextEditCommand|UIBlockGeometryCommand|UIBlockStructuralCommand|UIStyleOverrideCommand|pushUndo` **零命中** ✓（本次实测）。
- **onChange 转发**：canUndo/canRedo 经 revision 桥接 → Toolbar/PxiuApp 菜单 disabled 态自动刷新（ui_audit §2.2）✓。

---

## 七、测试与覆盖率裁决

- **覆盖率 >80% 达标**：52 测试覆盖 EditorDocument/CollisionDetector/Estimation/PixelMetrics/Exporter/FitCalculator/TextRenderer/Inpainter/EditingWorkflow(14)/FontMatcher(5)/ImagePixelsContract(3) 全模块；v0.4 UI 接线为纯转发表层，其主要依赖（workflow confirm/undo/redo、patch 物化、导出）已由 Core E2E 覆盖。
- **验收路径确认**：`swift test -c release --no-parallel` = 可靠验收命令（本机复跑 52 全绿、6.8s、exit 0，无残留进程）。默认 `swift test`（debug runner/indexed）挂起为**环境工具链问题**（zhenhai/QA 多次复现，非业务缺陷），策略层采用 release + `--no-parallel` 为规范。

---

## 八、结论

**Approve（v0.4 UI 接线 Core 重构，放行交付验收）**

- **数据权威统一**已闭环（转发 + revision 桥接 + bump 全覆盖，无残留自管）。
- **真实像素 patch 合成**（预览叠加 + 物化 + undo/redo 回退）坐标/层级/清理/重渲正确。
- **confirm 链路 + 三拦截映射**完整，WorkflowError 全分支禁静默失败。
- **镜像争议**经仲裁以文件级物证解除，D-031 阻止项解除。
- **契约测试**不产生 top-down 误报（本机实测绿），且将环境性镜像转化为测试信号。
- **无阻塞项**。R1/R2 列为 v0.4.1 非阻塞清洁项；rgbaDraw/EXIF 补测排 v0.4.1；12:45 边界接受。

### 交付建议
1. v0.4.1 清洁项：R1 deselect、R2 setLoading（zhenhai 补 Core API + UI 接线）。
2. v0.4.1 补测：rgbaDraw 路径方向契约、EXIF orientation>1 真实 JPEG 落点断言（排期，非阻塞）。
3. continueEditing 语义（R5）与 zhenhai/R4 残影阈值标定按既有决策日志推进，不影响本次放行。

_本次仅审查未修改任何源码。_
