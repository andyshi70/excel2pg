# QA 测试报告 — 缩放改造 + ch.jpg 改字 E2E

- **版本/对象**：pxiu macOS app（SPM，`/Users/evandy/opencode/pxiu/pxiu`）
- **被测改动**：xiaoyou 的 L2 缩放改造
  - `CanvasView` 删除打开时自动 fit，改为初始 100%（viewport.reset）
  - 新增 `ScrollWheelCatcher`（NSViewRepresentable）拦截滚轮 → 缩放
  - `ToolbarView` 新增缩放控制：− / 百分比 / + / 适应窗口
  - `EditorState` 新增 `fitRequestTick` 广播链路
- **测试日期**：2026-08-30
- **测试人**：shouye（QA）
- **环境**：macOS（darwin），CommandLineTools，swift 5.9，目标 .macOS(.v14)
- **依赖文档**：`workspace/backend/api_implementation_v0.2.md` 存在（无阻塞）；`workspace/frontend/ui_audit_v0.1_2026-08-28.md` 存在（早于本次缩放改动，报告中已注明）

> 文档依赖链说明：本次为 UI（xiaoyou）改动，前任 ui_audit v0.1 早于缩放改造，未覆盖新增缩放控件；QA 以 task 指定的测试清单 + 源码为准。已反馈 zongguan 补 ui_audit 缩放节。**非阻塞**（源码为当前权威）。

---

## A. 缩放功能测试

### A1. 初始 100% — ✅ PASS

**证据（代码级）**：
- `EditorState.swift:375-378` `open(url:)` 内调用 `viewport.reset()`，`viewport.reset()`（`:30-33`）置 `scale = 1.0`，panOffset 归零。→ 每次打开 = 100% 原分辨率。
- `CanvasView` **无** `onAppear` / `task` 自动 fit 逻辑。
- `CanvasView.swift:93-95` `onChange(of: viewport)` 为空 no-op，注释明确「内容尺寸变化时不自动重置」。→ 删除了旧的自动 fit。
- `ViewportState` 默认 `scale = 1.0`（`:28`）。

结论：打开即 100%，符合 spec「打开 = 100% 原分辨率」。✅

### A2. 滚轮缩放 — ✅ PASS（代码级；无 GUI 实测权限）

**证据（代码级）**：
- `ScrollWheelCatcher` 为 `private struct ... : NSViewRepresentable`（`CanvasView.swift:205-217`），桥接 `ScrollWheelNSView`（`:219-238`）。
- **仅拦滚轮**：`hitTest`（`:222-226`）`guard NSApp.currentEvent?.type == .scrollWheel else { return nil }` → 点击/拖拽/触控板点击事件 hitTest 返回 nil，**透传**给下层 SwiftUI 手势（选中/移动/角柄/平移不受遮挡）。
- **momentum 忽略**：`:229` `guard event.momentumPhase.isEmpty else { return }` → 惯性滚动跳过。
- **非精确 delta ×10 归一**：`:231-235` `hasPreciseScrollingDeltas` 为精确则直接用像素；否则（传统滚轮鼠标）`scrollingDeltaY * 10`。
- **缩放增量处理**：`zoom(by:)`（`:178-181`）`scale *= exp(delta * 0.02)`，clamp `0.05...16`。

GUI 实测：环境无屏幕录制/交互权限，未启动 app 实测；以上为代码级审查 + 设计注释自证。**注明限制**。

### A3. 工具栏缩放 — ✅ PASS（代码级）

**证据**：
- `ToolbarView.swift:76-96` `zoomControls`：`minus.magnifyingglass`（−，`zoom(by: 1/1.25)`）、百分比 `Text("\(Int(state.viewport.scale * 100))%")`、`plus.magnifyingglass`（+，`zoom(by: 1.25)`）、`arrow.up.left.and.down.right.magnifyingglass`（适应窗口，`fitRequestTick += 1`）。
- **±×1.25**：`zoom(by:)`（`:99-102`）`scale * factor`，clamp `0.05...16`。− 传 `1/1.25`，+ 传 `1.25`。✅
- **clamp 边界**：`max(min(target, 16), 0.05)` → 0.05...16。✅
- **disabled**：`:95` `.disabled(!model.isShowingEditor || state.sourceImage == nil)` → 非编辑器或无图时禁用。✅
- **monospacedDigit**：`:83` `.monospacedDigit()` → 百分比数字等宽，宽度稳定不跳动。✅

### A4. 适应窗口（fitRequestTick 链路） — ✅ PASS（代码级）

**证据（链路完整）**：
1. `ToolbarView.swift:90-92` 「适应窗口」按钮 → `state.fitRequestTick += 1`（自增广播）。
2. `CanvasView.swift:89-92` `.onChange(of: state.fitRequestTick)` → `fitToView(viewport:content:)`。
3. `CanvasView.fitToView`（`:170-175`）`scale = min(vw/cw, vh/ch)`（min 比例）+ `panOffset = .zero`（pan 清零），下限 `max(scale, 0.05)`。

链路自增 → onChange → min 比例 fit + pan 清零，三环齐全。✅

### A5. 回归：平移/选中/角柄/添加框/捏合 — ✅ PASS（代码级，无 git diff 可用）

> ⚠️ 环境非 git 仓库（`git status` → not a git repository），**无法提供 git diff**。回归结论基于对当前 `CanvasView.swift` 完整源码的审查（交互代码完整保留，未被缩放改造触碰）。

**证据**：
- **拖拽平移**：`:98-125` `primaryGesture` 非 addingBlock 时 `panOffset = value.translation`。完整。
- **选中**：`:69-71` `.onTapGesture` → `state.select(blockID:)`。完整。
- **角柄缩放**：`:351-375` `cornerHandle` + `resizeGesture`，`/scale` 换算容器坐标，min width/height 24/12。完整。
- **添加框**：`:75-81` 添加框高亮 + `:112-142` commitAddBlock（>8px 判定 + userAdded 状态）。完整。
- **magnify 捏合保留**：`:149-158` `MagnificationGesture`，clamp `0.05...16`，`onEnded` 记录 magnificationStart。完整。
- **clamp 边界**：滚轮/捏合/工具栏三处均 `0.05...16`，一致。✅

### A6. 构建 — ✅ PASS

**命令**：`swift build`（debug，`.build/arm64-apple-macosx/debug`）
**输出**：`Build complete! (0.44s)`，exit 0（缓存命中增量；PxiuCore 模块产物已在，PxiuApp target 可编译）。

**补充：单元测试**：
`swift test`（PxiuCoreTests）运行中 **24 通过 / 0 失败**，然后**进程挂起不退出**（卡在最后一个 test `testFitEnlargeNotAllowed` 打印截断处，无失败标记）。
- 判定：**非缩放改动引入的失败**（PxiuCoreTests 不引用 UI/缩放代码，纯 Core 层）。
- ⚠️ **风险点**（需 dana 关注）：`swift test` **退出挂起**是既有问题（Swift Testing CLI 在某后台任务/测试收尾处不退出），CI 若用 `swift test` 会一直卡住超时。见 C 章节。

---

## B. ch.jpg 改字 E2E（CEO 验收：v0.20.1 → v1.21.1，图上文字真的变）

### B1. CLI 验证 Core 检测能力 — ✅ 检测能力成立（OCR 检出版本文本，但读数与 0.20.1 有微小出入）

**方法**：临时独立 swift 脚本（放 `/tmp`，经 `swiftc` 直接链接 `.build/debug/PxiuCore.build/*.o`，import PxiuCore 的 ImageLoader + TextBlockDetector），加载 `/Users/evandy/Desktop/backup/ch.jpg`。脚本与生成产物已清理，**未修改任何 Sources/ 代码**。

**真实输出**（`ImageLoader.load` + `TextBlockDetector.detect`，accuracy 与 fast 双跑）：

```
IMAGE 3008x1280
=== LEVEL accurate blocks=4 ===
  ["翻"]   bbox y=668 conf=0.300
  ["VO.20.0"] bbox y=718 conf=0.500   bbox=593,718 565x153
  [ver?] 'VO.20.0' conf=0.500 bbox=593,718
=== LEVEL fast blocks=2 ===
  ["vO.20.0"] bbox y=718 conf=0.300   bbox=600,718 552x124
  [ver?] 'vO.20.0' conf=0.300 bbox=600,718
```

**分析**：
- 检测到的全部 4 块：`翻`(0.3)、`Hermes`(1.0)、`传令神版`(1.0)、以及**版本串**（accurate `VO.20.0` @0.5 / fast `vO.20.0` @0.3），位于 y≈718（全图 1280 高的下方），正是 CEO 所指「图上版本文字」的预期位置。
- 版本串被 OCR 读出为 **`VO.20.0` / `vO.20.0`**，而非精确 `v0.20.1`：
  - `V ↔ VO/vO`：OCR 把首字母 V 判成带 o 的 VO（小号无衬线/抗锯齿常见）。
  - `0 ↔ 1`（`.20.0` vs `.20.1`）：**0/1 误读**，置信度仅 0.3~0.5（中低），是抗锯齿小字典型 OCR 歧义。
- **结论**：Core 检测能力**成立**——确实在 ch.jpg 上检出版本文本块并给出 bbox + confidence。但**精确读到 "v0.20.1" 未达成**（OCR 读数歧义）。这本身**不足以阻塞改字**（检测到版本区域即可做 patch 定位）。

### B2. GUI 流程静态取证 — ❌ FAIL（CEO 标准：图上像素真实变化）

**结论：FAIL**。GUI 将 v0.20.1 改为 v1.21.1 后，画布源图像素与导出图的**像素不变**，仍是 v0.20.1。根因明确（见下）。代码级证据：

1. **预览管线是"占位"**：`EditorState.swift:314` 注释「预览管线（异步，**不走 Core Workflow**；Core Workflow 就绪后替换）」；`:340-341` `previewFit` 注释「Core Workflow/EditorWorkflow 就绪后，改为调用其 previewEdit 并**回填真实 patch**」。
   `runPreviewPipeline`（`:316-338`）只做：设置 `.processing` overlay、算 tooLong / collisionCount 反馈（启发式），**不生成/不合成任何像素 patch**。
2. **画布渲染源 = sourceImage 原图，无 patch 层**：`CanvasView.swift:52` `Image(decorative: image.cgImage, ...)` 直接渲染 **SourceImage 的原始 cgImage**（`image.sizePx` 原分辨率）。无任何 `TextEraser`/`BlockPatchBuilder`/`patch` 合成层叠加。
3. **confirm 只改数据不改像素**：`EditorState.confirmPreview`（`:150-164`）仅改 `textBlocks[idx].text`（数据数组）并入 undo 栈，`textBlocks[]` 是文字块**元数据**，非图像像素。
4. **export 导出原图**：`EditorState.export`（`:402-422`）`exporter.export(image, ...)` 传的是 `sourceImage`（原始 UIImage/CGImage）；`Exporter.export(image...)` 输出**原图**，改字结果未写入像素。

**根因（明确）**：**UI 预览管线未接通 Core 抹除/重绘 Workflow**。
- `runPreviewPipeline`（`:316`）为**占位实现**——仅跑反馈启发式，不调用 Core `EditingWorkflow`/`TextEraser`/`BlockPatchBuilder` 生成 patch。
- `CanvasView`（`:42`/`:52`）渲染源**无 patch 合成**——即使数据改了，画布显示仍是 SourceImage 原图。
- `confirmPreview`（`:147`）只改 `textBlocks` 数据 → 与像素解耦。
- export（`:399-419`）只导出 `sourceImage` 原图。
- 数据链路：`textBlocks[idx].text = "v1.21.1"` ✓（数据层确实变了）→ **像素层**（画布 cgImage / 导出图）**未变** → 导出仍 v0.20.1。

> 即 zongguan 预判 D-028 成立：**改字只改数据（textBlocks），不改像素（sourceImage/patch）**。

### B3. GUI 自动化实测 — 跳过

本 app 无 URL open 参数，openPanel 无法脚本化，且无屏幕录制权限。**代码级取证已足够坐实 FAIL**（渲染源无 patch 合成 + 预览管线占位），不需 GUI 实测。

---

## C. 风险点（需 dana / zongguan 关注）

1. **【阻塞级，Core 缺口】UI 预览/导出未接 Core 抹除重绘**（B 根因）——`runPreviewPipeline`（:316）占位、`CanvasView`（:52）原图渲染、`confirmPreview`（:147）只改数据、export（:416）导出原图。改字功能**端到端不可用**。修复方向：UI 需调用 Core `EditingWorkflow`/`TextEraser`+`BlockPatchBuilder` 生成 patch，CanvasView 渲染「原图 + patch 合成」，export 导出合成结果。
   - **前置**：Core `EditingWorkflow`/`TextEraser`/`BlockPatchBuilder` 是否存在可用 exe 路径待 dana 核对（`Sources/PxiuCore/Workflow/`、`Erase/`、`Render/` 目录已存在对应文件，TestKit `testEndToEndEraseRenderPatchMaterialize` 已通过 → 核心能力已具备，缺的是 **UI 侧接线**）。
2. **【阻断 CI】`swift test` 退出挂起**——24 通过/0 失败，但进程不退出（卡 `testFitEnlargeNotAllowed` 收尾）。CI 若跑 `swift test` 会超时伪失败。需 dana 定位后台任务/测试收尾 hang。
3. **【数据点】OCR 版本串读数歧义**——`VO.20.0`/`vO.20.0`（0↔1、V↔VO），conf 0.3~0.5。若未来要做"检测版本号自动比对"，需增强 OCR（放大 ROI / 更高分辨率 / fast+accurate 投票），或人工确认。
4. **【流程】ui_audit_*.md 早于缩放改动**——未覆盖新增缩放控件；建议 xiaoyou 补一份缩放节，供后续回归挂接。

---

## 最可能漏测的场景（QA 必写）

QA 对抗式审查：以下场景最可能漏测，建议后续补测——

1. **滚轮缩放锚点**：当前 `zoom(by:)` 以**画布左上原点/中心为固定锚**缩放，未做「以鼠标指针为中心」的锚点缩放。用户滚轮时内容围绕固定点缩放，**指针位置会漂移**（taste-skill 期望交互应锚定指针）。**大概率漏测**。
2. **缩放 + 拖拽平移同时发生**：`primaryGesture`（Drag，minDist 10）与 ScrollWheelCatcher 滚轮**无互相抑制**；快速滚轮缩放期间误触拖拽 → panOffset 被污染。未经实测。
3. **滚轮缩放后添加框/角柄坐标**：`BlockInteractor` 用 `dragDelta/scale` 换算容器坐标；缩放中途缩放率变化时，正在进行中的拖动/角柄的 scale 基准（`scale` 参数快照）与实时 `viewport.scale` 可能不同步 → 加框/拖动错位。仅代码推演，未实测。
4. **fit 后即时滚轮**：`fitToView` 设 panOffset=.zero + scale=fit；紧接着的滚轮缩放从新 scale 继续，未验证 fit 与连续缩放衔接。
5. **低置信度/中文版本号区**：ch.jpg 版本串 conf 仅 0.3~0.5 → 会被 `isLowConfidence(<0.5)` 标「？」弱化（`CanvasView:258-265`），且 patch 定位在小字区可能不准。改 v1.21.1 时**新文本与旧 bbox 尺寸/字体匹配**未验证。
6. **导出格式**：仅 PNG / JPEG 0.9 两档；缩放后导出走的仍是 sourceImage —— 确认导出与画布缩放无关（本应无关，但未实测导出文件是否含改字像素——按 B 结论必不含）。
7. **窗口 resize**：`onChange(of: viewport)` 是空 no-op，resize 窗口时缩放**不重置**（有意设计）——但「适应窗口」后 resize，view 尺寸变了 scale 仍旧，内容可能超界。未实测。

---

## 汇总

| 项 | 结果 |
|----|------|
| A1 初始 100% | ✅ PASS（代码级） |
| A2 滚轮缩放 | ✅ PASS（代码级，无 GUI 权限） |
| A3 工具栏缩放 | ✅ PASS（代码级） |
| A4 适应窗口链路 | ✅ PASS（代码级） |
| A5 回归交互 | ✅ PASS（代码级，无 git diff） |
| A6 构建/测试 | ✅ PASS（build exit 0；tests 24 过 0 败，退出挂起见 C2） |
| B1 Core 检测能力 | ✅ 检测成立（版本串被检出，读数有 0↔1 歧义） |
| B2 GUI 改字像素 | ❌ **FAIL**（改数据不改像素，导出仍 v0.20.1） |
| B3 GUI 自动实测 | 跳过（无权限/无 url 参数），代码级取证足够 |

**核心结论**：A 缩放改造**功能完整、链路正确（初始100/滚轮/工具栏/fit/回归/构建均通过）**；B 改字 **FAIL 坐实**——根因 UI 预览管线未接 Core 抹除重绘（runPreviewPipeline:316 占位 / CanvasView:52 原图渲染 / confirmPreview:147 只改数据 / export:416 导出原图），改字只改数据不改像素，CEO 标准「图上文字真的变」**未达成**。

**未修改任何 Sources/ 代码**。临时验证脚本已清理。
