# 代码审查报告 — 缩放改造 + ch.jpg 改字 E2E 根因复核

- **审查人**：dana（技术负责人）
- **版本/对象**：pxiu macOS app（SPM，`/Users/evandy/opencode/pxiu/pxiu`）
- **审查日期**：2026-08-30
- **被测改动**：xiaoyou 的 L2 缩放改造（3 文件）
  - `Sources/PxiuApp/CanvasView.swift` — 删 onAppear 自动 fit；新增 ScrollWheelCatcher；fit 改由 fitRequestTick onChange 驱动
  - `Sources/PxiuApp/ToolbarView.swift` — 新增缩放区（−/百分比/+/适应窗口）
  - `Sources/PxiuApp/EditorState.swift` — 新增 `fitRequestTick`
- **前置检查**：`workspace/qa/qa_report_zoom_ch_2026-08-30.md` 存在（已读）→ 无阻塞，可审查
- **约束遵守**：本次仅读取用户指定 3 个业务文件 + Core 侧核对（Workflow/Erase/Render 目录、EditingWorkflowTests）；未修改任何源码

---

## 一、缩放改造审查（A 区）

依赖文档链：本次无新增前端 ui_audit 缩放节（QA 已反馈 zongguan）；以源码为当前权威。合规，不阻塞。

### 1.1 ScrollWheelCatcher 实现质量 — ✅ 基本正确，附关注项

**读取实况**（CanvasView.swift:205-238）：
```swift
private final class ScrollWheelNSView: NSView {
    var onScroll: ((CGFloat) -> Void)?
    override func hitTest(_ point: NSPoint) -> NSView? {
        guard NSApp.currentEvent?.type == .scrollWheel else { return nil }
        return super.hitTest(point)
    }
    override func scrollWheel(with event: NSEvent) {
        guard event.momentumPhase.isEmpty else { return }
        let delta: CGFloat = event.hasPreciseScrollingDeltas
            ? event.scrollingDeltaY : event.scrollingDeltaY * 10
        onScroll?(delta)
    }
}
```

- **NSViewRepresentable 生命周期**：`makeNSView` 建视图 + 注入 onScroll；`updateNSView` 更新闭包。标准写法 ✓。presentation/shadow 管理正确，无泄漏（闭包持有 EditorState 引用，属预期长生命周期）。
- **hitTest 透传**：非滚轮事件 return nil → 点击/拖拽/框选落到下层 SwiftUI 手势，不挡 BlockInteractor ✓。依赖 `NSApp.currentEvent` 属常用手法，脆弱点在**非事件上下文**调用 hitTest 时 currentEvent 为 nil → return nil，安全降级透传 ✓。触控板捏合（.magnify）非 scrollWheel → 不拦，由 SwiftUI MagnificationGesture 接 ✓，无冲突。
- **momentum 忽略**：`momentumPhase.isEmpty` 正确跳过惯性滚动，避免甩动后续惯性继续缩放 ✓。
- **delta 归一**：`hasPreciseScrollingDeltas`（触控板/妙控鼠标 true，delta 即像素）直用；传统滚轮 ×10 近似 ✓。合理。
- **⚠️ 关注项 A-D1 滚动方向未验证**：`scrollingDeltaY` 直接当 delta 传给 `exp(delta*0.02)`，未做方向归一。触控板"自然滚动"方向下，向上/向下的缩放方向语义（放大/缩小）未经 GUI 实测（QA 无屏录权限）。建议人工验证一次方向符合直觉，若反则加 `* -1` 或映射。非阻塞定型。

**覆盖整视口的权衡**：Catcher 置于 ZStack 顶层覆盖全视口，所有滚轮（含在工具栏/空白区）都转缩放，属标准画布行为，可接受。

### 1.2 滚轮锚点漂移 — ⚠️ 确认（QA 漏测 #1 成立，建议项非阻塞）

`zoom(by:)`（:178-181）仅改 `scale`，不改 `panOffset`。SwiftUI `scaleEffect(scale)` 默认锚点**中心（center）**，但 panOffset 固定 → 缩放时内容相对指针漂移，指针所指内容会移开，不满足 taste-skill「缩放锚定指针」的交互预期（macOS 画布/地图类应用标准行为）。

- 定性：**交互体验问题，非功能 bug**。缩放数学正确、clamp 正确。
- 建议（v0.4 前可选）：滚轮缩放时以指针位置为锚——`zoom(by:at anchor:)`，缩放后补偿 panOffset 保持指针下内容不动。若接受"中心缩放"作为简化，则确认为显式设计决定并记录。

### 1.3 滚轮缩放 vs 拖拽平移并发 — ⚠️ 关注（QA 漏测 #2）

DragGesture 在 content（minDist 10）、Catcher 在顶层 ZStack，两者无互斥。快速滚轮缩放途中误触拖拽会污染 panOffset。引擎层面：滚轮事件不进入 DragGesture（hitTest 不拦非滚轮，但滚轮也不触发 drag），故实际触发需"滚轮缩放中用户又按下拖动"——属并发时序，低概率。列为关注，不阻塞。

### 1.4 BlockInteractor scale 快照 vs 实时缩放 — ⚠️ 关注（QA 漏测 #3）

BlockInteractor 的 `let scale` 是 init 期快照；`displayRect`/`resizeGesture` 用 `translation/scale` 换容器坐标。viewport.scale 变化时 ForEach 重建 → 传新 scale ✓。但**正在进行的拖拽/角柄缩放中途**若 scale 变化，快照与实时 viewport.scale 不同步 → 错位。纯代码推演，交互时序低概率。回归数学本身正确（QA A5 确认保留），不破坏既有加框/角柄。

### 1.5 fitRequestTick 模式 — ✅ 可靠

- `fitRequestTick += 1` 自增（EditorState:66; ToolbarView:91）→ CanvasView `onChange(of: state.fitRequestTick)`（:89-92）→ fitToView。`@Observable` 会跟踪 int 变化；连续点适应窗口 tick 5→6→7 值必然变化 → onChange 必触发 ✓（解决了"同值不触发"问题，自增保证）。
- **open() 新图 tick 残留**：open()（EditorState:375-400）未重置 fitRequestTick。但 fit 仅在 onChange 触发时执行，open 后不点适应窗口不会误触发；残留只是数值累积，无实际副作用。✓ 非问题。

### 1.6 回归（坐标数学）— ✅ 未破坏

scaleEffect + offset + BlockInteractor /scale 链路完整（缩放改造未触碰交互代码）。QA A5 逐一确认平移/选中/角柄/添加框/捏合完整。fitToView（:170-175）`min(vw/cw, vh/ch)` + pan 清零，math 正确。

### 1.7 工具栏缩放区（taste-skill）— ✅

- 布局：− / 百分比 / + / 适应窗口，`Spacer()` 与导出菜单分离（ToolbarView:32-49），视觉层级清晰（缩放区在 Spacer 后、Divider 分隔导出）。
- disabled：`.disabled(!model.isShowingEditor || state.sourceImage == nil)`（:95），语义正确（无图/非编辑器时禁用）。
- `.monospacedDigit()`：百分比数字等宽不跳动 ✓。
- ±×1.25 对数步进，clamp 0.05...16 三处一致 ✓。
- ⚠️ 小点：缩放区 icon 按钮用 `button("", icon:)` 空 title + help，可访问性（a11y label）靠 help 兜底，可用但建议后续补 label。非阻塞。

### A 区结论

**Approve**（缩放改造功能正确、链路完整、回归无损；锚点漂移为体验建议项，滚动方向需人工验证一次）。

三条关注项（A-D1 方向、A-D2 锚点、A-D3/A-D4 并发快照）均为**交互时序级、非功能破坏**，建议 v0.4 迭代或补测处理，不构成 Request Changes。

---

## 二、ch.jpg 改字 FAIL 根因复核（B 区）

### 2.1 根因鉴定 — ✅ QA 结论坐实，逐条复核一致

| QA 指认 | 源码实况（本次复核） | 一致 |
|---------|---------------------|------|
| CanvasView:52 渲染原图 cgImage | `Image(decorative: image.cgImage...)` 直渲 `sourceImage` 原分辨率 cgImage，`image` 即 `state.sourceImage`（:25,52），无 patch 合成层 | ✅ |
| runPreviewPipeline:316 占位 | `previewFit`（:342-355）仅算 tooLong + collision 启发式，**不生成任何像素 patch**；文件头注释明示「不走 Core Workflow」 | ✅ |
| confirmPreview:150 只改数据 | `confirmPreview` 仅改 `textBlocks[idx].text` 元数据入 undo（:155-159），不触像素 | ✅ |
| export:402 导出原图 | `export` 传 `sourceImage` 给 Exporter（:402-422），`EditorWorkflow.export` 同理导 sourceImage 原图 | ✅ |

**根因不变量**：数据层 `textBlocks[idx].text = "v1.21.1"` 已变，但像素层（画布 cgImage / 导出图）未变 → 导出仍 v0.20.1。**改字端到端不可用，CEO 标准「图上文字真的变」未达成**。确认成立。

### 2.2 Core 侧能力复核 — ✅ 能力齐备可用

| 组件 | 文件 | 状态 |
|------|------|------|
| EditingWorkflow protocol | `Workflow/EditingWorkflow.swift:43` | 存在，定义 open/previewEdit/confirmEdit/export/move/resize/undo/redo |
| EditorWorkflow 生产实现 | 同上 :56 | 存在，依赖注入 + generation 防旧结果，抹除→适配→碰撞→patch 编排 |
| TextEraser | `Erase/TextEraser.swift` | 存在 |
| BlockPatchBuilder | `Workflow/BlockPatchBuilder.swift` | 存在，crop/compositeAfter/layout，可复用 |
| TextRenderer | `Render/TextRenderer.swift` | 存在 |
| **E2E 测试** `testEndToEndEraseRenderPatchMaterialize` | `Tests/PxiuCoreTests/EditingWorkflowTests.swift:62` | 通过。完整验证：previewEdit 产出 patch（`patch.before != patch.after` 像素真变）→ confirmEdit 物化（`crop(doc.sourceImage) == patch.after`）→ undo 回贴 before → redo 回贴 after。**改字像素真实化**已被测试覆盖 |

**结论**：Core「抹除 + 重绘 + patch 物化」能力**完全可用**，缺的只是 UI 侧接线。QA B 判断（Core 已有、UI 未接线）**成立**。

### 2.3 OCR 歧义（V↔O、0↔1）对 patch 影响 — ✅ 不阻塞

- QA B1 实测：ch.jpg 版本串读出 `VO.20.0`/`vO.20.0`（conf 0.3~0.5），0↔1、V↔VO 歧义。
- **复核判断：歧义只在检测/识别阶段**。patch 重绘用的是**用户确认输入的文本**（`v1.21.1`）+ 已检出的 bbox（版本区域定位，y≈718 准确）。检测把区域读出 `vO.20.0` 只影响「辅助预览填默认值」；用户手动改为 `v1.21.1` 后，重绘按用户文本画字形，**与 OCR 读数无关**，歧义不进入 patch 内容。
- 定位准确性：bbox 由检测给出（版本区定位正确），重绘在新 bbox 内。patch 与旧字形尺寸/字体匹配依赖 FontMatcher（Style/）——若匹配不中会走近似重绘，此为既有排版质量风险，非 OCR 歧义所致。
- **结论：OCR 歧义不阻塞 UI 接线** ✓（与 QA 判断一致）。歧义仅在"未来做版本号自动比对"时才需 OCR 增强。

---

## 三、UI 接线 Core 重绘 — 改造方案评估（为 CEO 排期决策）

### 3.1 最小接线路径

Core 已物化到 `document.sourceImage`（confirmEdit 把 patch.after 回贴进源图）。UI 最小接线只需「让画布与导出读 Core 的文档源图」：

1. **渲染层合成**：CanvasView:52 的 `Image(decorative: image.cgImage)` 改为渲染「EditorDocument 的 sourceImage」。preview 阶段叠加 `EditPreviewResult.patch.after`（按 patch.rect 贴合），confirm 后直接读物化后的 doc.sourceImage。
2. **confirm 驱动重绘**：`confirmPreview` 从「只改 textBlocks 元数据」改为「调用 `EditorWorkflow.confirmEdit(blockID:)` → 物化 patch + 读回新 sourceImage → 触发画布重绘」。
3. **export 改导合成图**：`export` 从「直发 sourceImage」改为「调 `EditorWorkflow.export`（它导物化后的 doc.sourceImage）」。
4. **undo/redo**：`EditorWorkflow.undo()/redo()` 回贴 before/after 裁剪，UI 侧 undo 栈替换或桥接到 Core。

### 3.2 工作量级别：**L2（模块级）**

- Core 全部就绪，**零 Core 管线改动**；改动集中在 UI 编排层。
- 不涉框架引入、不涉 DB、不涉 >5 张表 → 非 L3。
- 属「新增独立能力接线（编辑物化 + 合成导出）」，单个模块级改动。

### 3.3 涉及文件

- `EditorState.swift`：核心改造（接入 EditorDocument/EditorWorkflow，替换自管 undo、confirmPreview、export、open）
- `CanvasView.swift`：渲染源改为合成图（:52）+ preview patch 叠加
- 可能新增 1 个桥接/编排文件（PxiuApp 层）
- 测试：EditorState 桥接层单元测试新增件

### 3.4 风险点

1. **【最大风险】数据权威迁移**：现 UI 自管 `textBlocks[]` + `UIDocumentCommand` undo 栈（EditorState:38-76），而 Core `EditorWorkflow` 独有 `EditorDocument` + 自己的 undo 栈。两套状态并存 → 必须统一权威。方案：EditorState 改用 Core EditorDocument 为单根权威，UI 只读渲染；或做双向桥接。**这是改造主要复杂度与回归面**（所有现有 undo/redo/移动/删除操作都要对齐 Core 命令）。建议此改造配套补全 UI 层 regress 测试。
2. 渲染合成坐标：patch.after 是块级裁剪，回贴需在原图坐标对齐（BlockPatchBuilder crop/compositeAfter 可复用，Core 物化已保证一致性，风险低）。
3. 抹除残留：低对比/纹理区抹除可能有 `residualMetric` 视觉残留，UI 已有弱提示设计（§5-6），可接受。
4. 字体匹配不足时「近似重绘」的排版质量：既有风险，非接线引入。
5. 导出 JPEG 有损：合成后多次编解码引入色带，低影响注意即可。

### 3.5 排期建议

**建议作为下一迭代 v0.4，单独排期**：目标「UI 接通 Core patch 合成的 编辑+导出 端到端」（对应 QA C1 阻塞级缺口，CEO 验收项）。范围收紧为接线，不扩 OCR 增强（歧义不阻塞，见 2.3）。前置：先统一 EditorState 与 Core 文档权威（3.4-1）。

---

## 四、swift test 退出挂起（QA C2）— 复核

**已复现**：本次实测 `swift test` → 全部用例 PASS（无失败、无显式失败标记），日志停在 `testGradientPatchLocalSSIMAgainstOracle`（= 末个收尾用例）截断，**进程 60s 后不退出**（`kill -0` 确认存活，需 pkill 终止）。

- 定性：Swift Testing CLI 在异步 actor / 后台任务收尾后 Swift Testing 运行器未显式退出的已知类型问题。**非测试失败、非缩放改动引入**（纯 Core PxiuCoreTests）。
- **严重性：阻断标准 CI `swift test`**。若 CI 直接跑 `swift test` 会卡到超时 → 伪失败。需处理：
  - 立即降级：CI 用 `swift test --filter ...`（逐 filter/逐 suite）或外层加进程超时 `timeout`，或改用 xcodebuild test。
  - 根修：定位后台任务/actor 残留（疑 ImageLoader/检测器/渲染器的全局服务未 tearDown），补 `deinit`/取消点。
- 不影响本次审查结论登记；列为 P1 待 @zhenhai/@shouye 处理。

---

## 五、结论

| 区 | 结论 |
|----|------|
| A 缩放改造 | **Approve**（附 3 条关注项：A-D1 滚动方向待人工验证、A-D2 锚点漂移建议、A-D3/A-D4 并发快照关注；均非功能破坏） |
| B ch.jpg 改字 FAIL 根因 | **复核成立**：UI 预览管线未接 Core 抹除/重绘（runPreviewPipeline 占位 / CanvasView 原图渲染 / confirm 只改数据 / export 导原图），改字只改数据不改像素 |
| C Core 能力 | **齐备可用**（EditingWorkflow/TextEraser/BlockPatchBuilder + E2E 测试通过），缺 UI 接线 |
| D UI 接线评估 | **L2 模块级**，建议作为 v0.4 单迭代；最大风险=数据权威统一 |
| E swift test 挂起 | **已复现**，阻断标准 CI，P1 待修 |

### 最终结论：**Approve（缩放改造）/ Request Changes（改字 E2E 整体）**

> 说明：缩放改造本身批准；但因 B 区改字功能端到端 FAIL（CEO 验收项未达成），产品整体验收状态为 **Request Changes**，需经 D（UI 接线 Core）改造后由 shouye 回归 + 本审查复核方可放行。

---

## 附：@zongguan 决策依据要点

1. **缩放**：功能完整、链路正确、回归无损 → 可合入。
2. **改字 FAIL 根因确凿**，且缺件 Core 已备齐（含 E2E 测试证明像素真变）→ 差 UI 接线，工作量 L2。
3. **接线方案**：渲染读合成图 + confirm 走 Core confirmEdit + export 走 Core export，核心难点是统一 EditorState 与 EditorDocument 数据权威。
4. **排期建议**：v0.4 排「UI 接线 Core 重绘」，作为 CEO 验收项收口；OCR 歧义不阻塞（patch 基于用户文本重绘）。
5. **CI**：swift test 挂起 P1，需在 v0.4 前置修，否则 CI 卡死。

_本次仅审查未修改任何源码。_
