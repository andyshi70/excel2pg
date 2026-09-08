# pxiu 实现说明 v06 — 多块编辑丢失修复（auto-confirm 切块物化）

- 版本：v06（v05 渲染缺陷修复之后的状态机缺陷交付）
- 产出者：zhenhai（后端工程师）
- 日期：2026-09-01
- 前置文档：`workspace/architecture/api_contract_*.yaml` / `db_schema_*.sql` 与本交付无涉（纯状态机，无 API/表变更）；v0.1–v0.5 见 `workspace/backend/api_implementation_v0.1.md`~`v05_2026-08-31.md`；根因定位见 `workspace/logs/assistant/decisions/decisions_2026-08-31.md`（系统调试 Phase 1 证据链）
- 范围：PxiuApp（EditorState 状态机编排）+ PxiuCore（EditorWorkflow 最小查询 API）+ 新增测试 target `PxiuAppTests`
- 任务来源：CEO 报 bug「多块编辑只有一处生效（改 A → 点 B → A 还原）」；根因已定位（证据链完整），修复方案 **A（auto-confirm）** CEO 已批准
- 最终结果：**`swift test -c release --no-parallel`：67 tests passed, 0 failed（61 存量零回归 + 6 新增 UI 层测试）**

---

## Part A — 根因（系统调试 Phase 1 已确认，代码证据链）

| # | 根因 | 证据 |
|---|---|---|
| 1 | `EditorState.select(blockID:)` 切块时**只清 draft/previewResult，不物化前一区块** | EditorState.swift:128-133（`guard document.select(blockID) else { return }; draft = nil; previewResult = nil; bump()`）|
| 2 | `EditorDocument.select(_:)` `phase = .selected(B)` **直接覆盖 A 的 `.preview(A)` 态**，A 的预览态丢失 | EditorDocument.swift:33-39 |
| 3 | `EditorWorkflow.pendingEdit` **单槽**：B 的 previewEdit 覆盖 A 的 pendingEdit，A 的编辑失去物化来源 | EditingWorkflow.swift:93-100（`private var pendingEdit: PendingEdit?`，:196-197 成功即覆写）|

**用户路径**：改 A（preview 落定，pendingEdit=A）→ 点 B（select 清 UI 草稿 + document 覆写 phase + B 管线覆写 pendingEdit）→ A 的编辑在原地蒸发。undo 栈无 A 的记录（preview 不落栈），A 文字回到原值 = 「A 还原」。

---

## Part B — 修复实现（方案 A：auto-confirm，最小改动）

### B.1 `EditorState.select(blockID:)` 改造（EditorState.swift:135-177）

切块前检查当前块「活跃编辑会话」并分流，**合法预览先物化、被阻塞则拒绝**：

```
liveSession = phase == .preview(当前块)
           || workflow.hasPendingEdit(for: 当前块)     // continueEditing 后 phase 已回 selected 但 pendingEdit 仍在
liveSession 时：
  ① confirmBlocked(当前块)（碰撞/文字过长/样式未就绪）→ 拒绝切换
     setOverlay("当前文字块预览被阻塞…")；不调 document.select；phase/preview 态、反馈全部保留
  ② 草稿与已渲染预览不一致（与 confirmPreview 同判定：previewResult.newText == trim(草稿)）→ 拒绝切换
     setOverlay("预览尚未完成…")；保留草稿（防静默物化旧预览 / 防丢新输入）
  ③ 均通过 → workflow.confirmEdit(当前块) 物化入 undo 栈 → 再 document.select(新块)
```

- **同块重选 / 无选中**：保持旧语义（直接重选；同块丢弃未确认会话），不触发 auto-confirm（最小改动）
- 失败路径全部 `setOverlay` 提示（禁止静默失败 NFR-4）+ `return` 保持现场，不静默丢输入

### B.2 抽取 `clearEditingSession(for:)`（EditorState.swift: 内部区）

`draft=nil / previewResult=nil / pendingFitFeedback.removeValue` 三件套抽公共私有方法，
`select`（切块/同块重选）、`confirmPreview`、`cancelPreview`、`deleteBlock` 四处复用，消除重复。

### B.3 `EditorWorkflow.hasPendingEdit(for:)`（EditingWorkflow.swift，confirmEdit/cancelPreview 区）

单一最小查询（CEO 许可：「如有必要暴露 pendingEdit 状态查询供 UI 判断」）：

```swift
/// 是否存在该块未确认的预览草稿（UI 切块 auto-confirm 的前置判定）。
/// 注意：continueEditing 后 phase 已回 selected 但 pendingEdit 仍在，需此查询兜底；
/// 被阻塞（碰撞/过长/样式未就绪）或 in-flight 时 pendingEdit 缺失 → 判定为不可自动物化。
public func hasPendingEdit(for blockID: UUID) -> Bool {
    pendingEdit?.blockID == blockID
}
```

- 被阻塞（blocked）/ 预览 in-flight：pendingEdit 缺失 → `liveSession` 虽为 true（preview 态），
  ①/② 判定拦截，**无需多槽 pendingEdit dict**（CEO 约束：不引入大改）
- 未改动：`confirmEdit` 语义（非 preview 态 + pendingEdit 存在的 continueEditing 场景下照常可确认 → 无需额外行为变更）

### B.4 关键约束落实

| 约束 | 落实 |
|---|---|
| 不改变 fit/字号/颜色/方向（D-035/D-037 已交付） | 未触碰 TextRenderer/StyleEstimators/FitCalculator/BlockPatchBuilder 任何代码 |
| 不引入多槽 pendingEdit dict 大改 | 单槽不变，仅加只读查询 `hasPendingEdit(for:)` |
| undo 逐块回退语义保持 | auto-confirm 走 `confirmEdit` → 标准 `TextEditCommand` 独立入栈；新测试断言 `undoDepth == 2` 且逐块回退顺序正确 |
| 状态机逻辑属 zhenhai（UI 视觉层超范围报 zongguan 协调） | 本次改动为纯状态机编排 + Core 查询，无视觉层改动 |

---

## Part C — TDD 过程（先 RED 后 GREEN）

### C.1 测试基建：新增 `PxiuAppTests` target

- `EditorState` 属 UI 层（PxiuApp，@MainActor @Observable），存量 `PxiuCoreTests`（仅依赖 PxiuCore）无法触达。
- 方案：Package.swift 新增 `.testTarget(name: "PxiuAppTests", dependencies: ["PxiuApp", Testing…])`。
  SwiftPM 测试 target 依赖 executable target 可行性先以临时包验证（编译/链接通过；运行期仅需与
  PxiuCoreTests 相同的 `-F CommandLineTools/Frameworks` + swift-testing 包依赖 —— 工程已有缓存，离线可用）。
- Fixture 风格对齐 `EditingWorkflowTests`：合成 TextBlock + 白底 sourceImage + 注入 helvetica style，
  走**真实 previewEdit 管线**（TextEraser 掩码为像素距离判定，白底图上合成块可用）；异步预览经
  `waitUntil`（40ms 轮询 + 超时）等落定。

### C.2 新增测试清单（6 条，`Tests/PxiuAppTests/EditorStateSwitchTests.swift`）

| 测试 | 断言（核心） | 旧代码 RED 依据（逐条实测） |
|---|---|---|
| `testSwitchAutoConfirmsPreviousBlockAndSelectionMoves` | 改 A 预览后切 B → **A 文本保持 "AA2"（不还原）**、selection=B、phase=selected(B)、canUndo=true | A 还原为 "AA"、canUndo=false ✔ |
| `testBlockedPreviousBlockRejectsSwitchKeepingPreviewState` | 碰撞阻塞时切 B → **拒绝**：selection 仍=A、phase 保持 preview(A)、overlay 非空、B 未被触碰 | selection 被切到 B、无 overlay ✔ |
| `testContinueEditingThenSwitchAutoConfirmsWhenDraftMatchesPreview` | continueEditing 后草稿未改 → 切 B 仍 auto-confirm A（"AA2" 物化） | A 还原 ✔ |
| `testContinueEditingThenSwitchRejectsWhenDraftStale` | continueEditing 后改草稿（过期）→ 切 B **拒绝**：selection 仍=A、A 文本保持原值（不静默物化旧预览）、**草稿 "AA3" 保留**、overlay 非空 | selection 切走、草稿丢失 ✔ |
| `testTwoBlockEditsBothMaterializeAndUndoPerBlock` | CEO 场景端到端：A 编辑切 B + B 编辑 confirm → **两块均生效**（"AA2"/"BB2"）、undoDepth==2、逐块 undo（先 B 后 A）正确 | A 丢失、undoDepth==1 ✔ |
| `testSingleBlockConfirmRegression` | 单块编辑 confirmPreview 正常物化 → phase=idle | 存量行为，回归守卫（旧代码即通过） ✔ |

RED 实测摘录（修复前跑新套件）：5 条 bug 测试 13 issues 全部按预期失败
（如 `(text → "AA") == "AA2"`、`selection == a.id`、`overlay → nil) != nil`）；修复后 6/6 通过。

---

## Part D — 验收证据（全量 release 套件输出尾）

```
✔ Suite EditorStateSwitchTests passed after 0.352 seconds.
✔ Test run with 67 tests passed after 7.514 seconds.
```

- 命令：`swift test -c release --no-parallel`（release 必要：debug 模式 Swift 6.3.2 CLT `-Onone` 挂起，见 v0.3 Part B）
- 67 = 61 存量（零回归，含 v05 渲染三缺陷 + D-037 宽度选 B）+ 6 新增 UI 层状态机测试
- 产出物变更：
  - `Package.swift`（+`PxiuAppTests` test target）
  - `Sources/PxiuApp/EditorState.swift`（`select` 改造 + `clearEditingSession` 抽取 + confirmPreview/cancelPreview/deleteBlock 复用）
  - `Sources/PxiuCore/Workflow/EditingWorkflow.swift`（+`hasPendingEdit(for:)`）
  - `Tests/PxiuAppTests/EditorStateSwitchTests.swift`（新增，6 条）
- 错误码：**无新增 Core WorkflowError**（拒绝路径复用既有错误文案 + `setOverlay(.exportFailure(...))` 出口；
  新增 UI 文案两条：「当前文字块预览被阻塞（重叠/文字过长/样式未就绪），请先处理后切换」「预览尚未完成，请稍候片刻再切换」）

---

## Part E — 意外发现与边界记录

1. **undo 发生在 preview 态**（悬空 previewResult + pendingEdit 被清）→ 切块时 liveSession=true，
   ① confirmBlocked=false、② 预览比对通过、③ `confirmEdit` 抛 `noPendingEdit` → 拒绝 + overlay「切换失败：没有待确认的预览」。
   安全兜底（不静默丢输入亦不静默物化），未新增测试（存量 cancel/undo 语义已覆盖该路径到 noPendingEdit）。
2. **同块重选语义保留**：旧代码同块重选即丢弃未确认会话，本次保持一致（CanvasView 通常对当前块点击不触发 select，为兜底路径）。
3. **测试基建成本**：`PxiuAppTests` 编译全量 PxiuApp（含 SwiftUI 视图），单次 `swift test` 全量时长 7.5s（基线 6.5s + 建连开销），可接受。
4. **未竟项**：in-flight 预览「拒绝切换」路径（`previewResult == nil` 且 pendingEdit 未落）与「预览尚未完成」
   拒绝共享同一判定分支，未做确定性时序测试（管线毫秒级完成，需 BlockingTextRenderer 替身 + EditorState 注入点，超出本次最小改动范围）；
   逻辑覆盖由 ② 判定 + `testContinueEditingThenSwitchRejectsWhenDraftStale` 间接保证（同一拒绝分支）。
5. swift-testing 包依赖在 Swift 6.3 工具链下产生 deprecation 警告（Testing 已并入工具链），与存量 PxiuCoreTests 一致，未处理（去依赖属另一任务）。

---

## Part F — P1 修补记录（2026-09-01 追加，QA shouye 对抗审查发现）

### F.1 P1 缺陷（QA 报告原文要点）

**同块重选在预览态 → ghost pendingEdit**：
- CanvasView 对当前块点击不触发 `select`（跳过），但存在其他入口（如 OverlayViews 字体匹配条「手动更换」按钮，`OverlayViews.swift:57` → `state.select(blockID:)`，会对**当前块**做同块重选）。
- 旧 `select` 同块重选分支：`document.select(blockID)` + `clearEditingSession(for:)`（清 draft/previewResult/pendingFitFeedback 三件套），**但不清 `workflow.pendingEdit`** → `hasPendingEdit(for:)==true` 幽灵残留。
- 后果：下一切块时 `liveSession = workflow.hasPendingEdit(for:)` 误判为 true → 走 auto-confirm 分支 → `previewResult` 已 nil（三件套被清）→ 命中「预览尚未完成，请稍候片刻再切换」被阻断。**真实可复现**，原代码层无保护、测试零覆盖。

### F.2 修复（EditorState.swift `select(blockID:)` 同块重选分支）

语义与旧代码一致（**同块重选 = 放弃当前会话**），补上此前遗漏的 `workflow.pendingEdit` 清理：

```swift
guard currentID != blockID else {
    // 同块重选：保持旧语义，放弃未确认的编辑会话。
    // P1 修复（ghost pendingEdit）：除 UI 三件套外，须一并清 workflow.pendingEdit。
    workflow.cancelPreview()          // 弃 pendingEdit + 使 in-flight 预览过期 + phase 回 selected
    guard document.select(blockID) else { return }
    clearEditingSession(for: currentID)
    bump()
    return
}
```

- 用 `workflow.cancelPreview()`（幂等安全：pendingEdit 已 nil 也无副作用）+ generation++（in-flight 预览过期）。
- **不破坏 continueEditing 语义**：`continueEditing()` 走的是 `document.cancelPreview()`（保留 pendingEdit 的专用路径），与同块重选（放弃）是不同入口，互不影响。真实内容变更会话（continueEditing 后切块 auto-confirm、过期拒绝）全部保留。

### F.3 顺带处理 QA【中】项：undo-during-preview 悬空确认

`undo()` 在 preview 态清 `pendingEdit` 但 phase 仍 `.preview`、`previewResult` 残留 → 确认/切块会误入 auto-confirm → `confirmEdit` 抛 `noPendingEdit` → 泄漏晦涩文案「没有待确认的预览」。补 `hasPendingEdit` 兜底（成本低，落地）：

- `confirmPreview()`：`!hasPendingEdit(for:)` → `workflow.cancelPreview()` + `clearEditingSession` + 友好提示「预览已失效，请重新编辑后再确认」。
- `select` auto-confirm 分支：同样前置 `!hasPendingEdit(for:)` → 弃悬空会话后**放行切换**（不制造 ghost、不泄漏晦涩文案）。

### F.4 TDD 新增测试（5 条，`Tests/PxiuAppTests/EditorStateSwitchTests.swift`）

| 测试 | 断言（核心） | RED 依据 |
|---|---|---|
| `testSameBlockReselectDuringPreviewClearsPendingEdit` | 预览落定后在预览态同块重选 → `hasPendingEdit(for:)==false`、draft/previewResult 均 nil | 旧代码 pendingEdit 残留 true ✔ |
| `testSameBlockReselectDuringPreviewDoesNotGhostNextSwitch` | 同块重选后切 B → **selection==B**、A 保持 "AA"（不物化）、draft nil | 旧代码 selection 被 ghost 阻断留 A ✔ |
| `testContinueEditingStillKeepsDraftOnSameBlockChange` | continueEditing 保留 pendingEdit+草稿；草稿一致时切 B 仍 auto-confirm A | 回归守卫（防误伤 continueEditing）✔ |
| `testUndoDuringPreviewConfirmGivesFriendlyMessageNotNoPendingEdit` | undo 后确认 → 提示**不包含**「没有待确认的预览」、A 文本保持 "AA" | 旧代码泄漏晦涩文案 ✔ |
| `testUndoDuringPreviewThenSwitchIsNotGhostBlocked` | undo 后切 B → selection==B、A 不物化、无晦涩文案 | 旧代码被 noPendingEdit 阻断 ✔ |

### F.5 验收证据（全量 release 套件）

```
✔ Test run with 72 tests passed after 7.565 seconds.
```

- 命令：`swift test -c release --no-parallel`（release 必要，同上）。
- 72 = 67 存量（零回归，含 v06 六条 + 全部 PxiuCore）+ **5 新增 P1/中项测试**。
- 产出物变更：
  - `Sources/PxiuApp/EditorState.swift`（同块重选分支 + confirmPreview/select 的 hasPendingEdit 兜底）
  - `Tests/PxiuAppTests/EditorStateSwitchTests.swift`（+5 条）
- **P1 根治确认**：同块重选预览态不再残留 pendingEdit；后续切块不被 ghost 阻断；select 全部入口（CanvasView + OverlayViews）均走 `EditorState.select(blockID:)` 单点，全覆盖。
- 错误码：无新增 Core WorkflowError；新增/调整 UI 文案三条：「预览已失效，请重新编辑后再确认/切换」。
- 禁止项遵守：未改 fit/字号/颜色/方向逻辑；未破坏 auto-confirm 三态语义（continueEditing 回归测试守卫）；release 模式跑测试。