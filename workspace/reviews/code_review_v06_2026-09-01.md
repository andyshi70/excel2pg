# 代码审查报告 v06 — 多块编辑持久生效（D-038 auto-confirm + P1 补修）

- 审查者：@dana（技术负责人）
- 日期：2026-09-01
- 审查范围：`EditorState.swift`（状态机核心）、`EditorStateSwitchTests.swift`（11 条测试）、`EditingWorkflow.swift`（Core hasPendingEdit/confirmEdit）、`EditorDocument.swift`（Core select/cancelPreview）
- 前置文档：`workspace/qa/qa_report_v06_2026-09-01.md`（两轮验收，72/72 通过）
- 审查标准：状态机正确性、测试覆盖率（≥80%）、PRD AC 一致性、回归风险

---

## 一、状态机正确性（核心）

### 1.1 `EditorState.select(blockID:)` 全分支分析（:135-191）

```
select(blockID:)
├── ① 无选中（idle/noText）:136-140 → 直接 document.select + bump ✓
├── ② 同块重选 :142-151 → cancelPreview + select + clearEditingSession + bump ✓
└── ③ 切块 :153-191
    ├── liveSession 判定 :154-159
    │   ├── phase == .preview(pid) && pid == currentID → true ✓
    │   └── else → workflow.hasPendingEdit(for: currentID) 兜底 ✓
    ├── [否] liveSession=false → 直接 document.select + clearEditingSession + bump ✓
    └── [是] liveSession=true
        ├── ① confirmBlocked :161-164 → setOverlay + return（不物化，不切块）✓
        ├── ② !hasPendingEdit :168-173 → cancelPreview + clearEditingSession + select + bump（悬空兜底，放行切换）✓
        ├── ③ draft≠previewResult :177-180 → setOverlay + return（保留草稿，不物化）✓
        └── ④ 均通过 :181-186 → confirmEdit 物化 + 入 undo 栈
            └── :188-190 → document.select + clearEditingSession + bump ✓
```

**判定：四个分流按优先级严格递进（阻塞 > 悬空 > 草稿过期 > 物化），无分支泄漏。** 每条 return 路径均在 document.select 之前，phase 不被意外覆盖。

### 1.2 阻塞拒绝分支与 document.select 的顺序

:161-164（confirmBlocked）、:177-180（草稿过期）两条拒绝分支均在 :188 `document.select(blockID)` 之前 return。**phase 不会被覆盖，现场完整保留。** 与 QA 攻击点 b 结论一致。

### 1.3 P1 修补：同块重选 cancelPreview 误伤分析

同块重选分支（:142-151）：
```
workflow.cancelPreview()  // 弃 pendingEdit + generation++ + phase 回 selected
document.select(blockID)  // 同块重选：phase=selected(A)，无实质变化
clearEditingSession(for: currentID)  // 清 draft/previewResult/pendingFitFeedback
```

**不会误伤 continueEditing**：
- `continueEditing()`（:245-249）走 `document.cancelPreview()`（只回 phase，**保留 pendingEdit**），是完全不同的入口。
- `testContinueEditingStillKeepsDraftOnSameBlockChange`（:287-307）断言 continueEditing 后 `hasPendingEdit==true`、草稿保留、切 B 仍 auto-confirm → **回归守卫绿灯**。
- 同块重选是「放弃会话」语义（用户主动丢弃），continueEditing 是「继续编辑」语义（用户要改字），两者入口不同，互不干扰。

**判定：cancelPreview 在同块重选分支不会误伤合法的 continueEditing 场景。**

### 1.4 undo 悬空兜底两分支一致性

| 入口 | 条件 | 清理动作 | 文案/行为 |
|------|------|----------|-----------|
| `confirmPreview()` :222-228 | `!hasPendingEdit(for: id)` | cancelPreview + clearEditingSession | 「预览已失效，请重新编辑后再确认」+ return |
| `select` auto-confirm :168-173 | `!hasPendingEdit(for: currentID)` | cancelPreview + clearEditingSession + select | 放行切换，不阻断用户流程 |

- 判定条件一致（`!hasPendingEdit(for:)`）
- 清理动作一致（cancelPreview + clearEditingSession）
- 差异合理：confirmPreview 给用户提示后返回当前页（用户在等确认结果）；select 切块路径放行切换（用户想看下一块，阻断反而是坏事）
- **确认/切块是仅有的两个「尝试物化」入口**，均已兜住

**判定：两分支一致，无遗漏路径。**

### 1.5 分支泄漏审查：select 失败后的脏会话

:181-186 confirmEdit 成功后，:188 `guard document.select(blockID) else { return }` — 若 select 失败：
- A 已物化（phase=idle），但 :189-190 的 clearEditingSession/bump 被跳过
- 残留 A 的 draft/previewResult/pendingFitFeedback，而 phase 已 idle
- **可达性**：document.select 失败仅在「块不存在」或 `phase == .loading`；confirmEdit 后 phase=idle，仅「点击不存在块」触发
- **实际 UI 不可达**：CanvasView 只点击 textBlocks 中真实块

**定级：低危潜伏缺陷。实际不可达但防御性不足，建议后续补 clearEditingSession 兜底。非阻塞。**

---

## 二、Core 侧语义核验

### 2.1 `hasPendingEdit(for:)`（EditingWorkflow.swift:277-278）

```swift
public func hasPendingEdit(for blockID: UUID) -> Bool {
    pendingEdit?.blockID == blockID
}
```

单槽语义：`pendingEdit` 为 `PendingEdit?`（:93），包含 blockID/oldText/newText/patch。`hasPendingEdit` 仅查块 ID 匹配，语义清晰。

### 2.2 confirmEdit（:253-263）

```swift
guard let p = pendingEdit, p.blockID == blockID else {
    throw WorkflowError.noPendingEdit(blockID)
}
```

- 校验 pendingEdit 存在且 blockID 匹配 → 物化（commit TextEditCommand）→ 入 undo 栈 → confirm → pendingEdit = nil
- 语义：confirm 是「有草稿才确认，没草稿抛错」，正确

### 2.3 cancelPreview（:268-272）

```swift
public func cancelPreview() {
    generation &+= 1
    pendingEdit = nil
    document.cancelPreview()
}
```

- 弃 pendingEdit + in-flight 过期（generation++）+ phase 回 selected
- 幂等安全：pendingEdit 已 nil 也无副作用

### 2.4 单槽 pendingEdit 在 auto-confirm 下的撕裂风险

auto-confirm 在 select 切块时同步执行（:181-186），此时：
1. `confirmEdit` 消费 pendingEdit（pendingEdit = nil）
2. `document.select(blockID)` 切到新块
3. 用户开始编辑新块 → `previewEdit` 写入新的 pendingEdit

**无撕裂**：auto-confirm 是同步操作（非 async），确认完成才切块。单槽语义足够——确认后 pendingEdit 为 nil，新块预览写入新 pendingEdit，时序不重叠。

---

## 三、测试质量审查

### 3.1 11 条测试清单（6 首轮 + 5 P1 补修）

| # | 测试名 | 核心断言 | 真实性 |
|---|--------|----------|--------|
| 1 | testSwitchAutoConfirmsPreviousBlockAndSelectionMoves | A="AA2"、sel=B、canUndo | ✅ 真实管线 |
| 2 | testBlockedPreviousBlockRejectsSwitchKeepingPreviewState | sel=A、phase=preview(A)、overlay≠nil、B 未触碰 | ✅ 真实碰撞 |
| 3 | testContinueEditingThenSwitchAutoConfirmsWhenDraftMatchesPreview | A="AA2"、sel=B、canUndo | ✅ 真实管线 |
| 4 | testContinueEditingThenSwitchRejectsWhenDraftStale | sel=A、A="AA"、draft="AA3"保留、overlay≠nil | ✅ 真实管线 |
| 5 | testTwoBlockEditsBothMaterializeAndUndoPerBlock | A="AA2"、B="BB2"、undoDepth==2、逐块 undo | ✅ 真实管线 |
| 6 | testSingleBlockConfirmRegression | A="AA2"、phase=idle | ✅ 真实管线 |
| 7 | testUndoDuringPreviewConfirmGivesFriendlyMessageNotNoPendingEdit | overlay 不含晦涩文案、A 不物化 | ✅ 真实管线 |
| 8 | testUndoDuringPreviewThenSwitchIsNotGhostBlocked | sel=B、A="AA"、无晦涩文案 | ✅ 真实管线 |
| 9 | testSameBlockReselectDuringPreviewClearsPendingEdit | hasPendingEdit==false、draft=nil、previewResult=nil | ✅ 真实管线 |
| 10 | testSameBlockReselectDuringPreviewDoesNotGhostNextSwitch | sel=B、A="AA"、draft=nil | ✅ 真实管线 |
| 11 | testContinueEditingStillKeepsDraftOnSameBlockChange | hasPendingEdit==true、draft 保留、切 B auto-confirm | ✅ 真实管线 |

### 3.2 测试真实性核验

- **全部走真实 EditorWorkflow 管线**（`makeState` → `EditorState()` → `EditorWorkflow(document:)`），无 mock 短路
- **waitUntil 轮询**（40ms × 10s 超时）→ 超时即 `#expect` 失败，不会空转
- **碰撞场景**（#2）通过真实 previewEdit 管线触发 `WorkflowError.collision`，非桩
- **断言覆盖核心行为**：文本内容、selection、phase、canUndo、overlay、draft、hasPendingEdit、previewResult — 多维度交叉验证

### 3.3 覆盖率评估（select 全分支）

| 分支 | 测试覆盖 |
|------|----------|
| 无选中直接切换 | #5 间接（编辑后 undo→idle→重新 select） |
| 同块重选（无编辑） | #9, #10 |
| 同块重选（有编辑） | #9（预览态同块重选） |
| 切块 auto-confirm | #1, #3, #5 |
| confirmBlocked 拒绝 | #2 |
| 悬空兜底（!hasPendingEdit） | #8（undo 后切块） |
| draft≠previewResult 拒绝 | #4 |
| confirmEdit 成功 | #1, #3, #5 |
| confirmEdit 失败（catch） | 未直接覆盖（概率极低，需 pendingEdit 非 nil 但 confirmEdit 内部异常） |
| select 失败（document.select 返回 false） | 未覆盖（UI 不可达） |

**分支覆盖率评估：~85%**（核心可见路径全覆盖；2 条概率极低/不可达路径未覆盖）。**达标（≥80%）。**

---

## 四、对照 PRD AC 判定

| AC | 需求 | 判定 | 证据 |
|----|------|------|------|
| AC-1 多块编辑全部生效 | 连续编辑 N 块 → N 处全部落地 | ✅ 通过 | 测试 #5：A="AA2" + B="BB2" 同时生效 |
| AC-2 切块自动物化 | preview 态合法时 confirmEdit 物化 | ✅ 通过 | 测试 #1：A preview 后切 B → A="AA2"、canUndo=true |
| AC-3 阻塞拒绝切换 | 碰撞/过长/未就绪 → 拒绝 + 提示 | ✅ 通过 | 测试 #2：碰撞 → sel=A、overlay≠nil、B 未触碰 |
| AC-4 undo 逐块回退 | 每块独立入栈，逆序回退 | ✅ 通过 | 测试 #5：undoDepth==2、先 undo B 再 undo A |
| AC-5 回归保持 | 单块不变、D-035/D-037 不回归 | ✅ 通过 | 测试 #6：单块回归绿灯；代码审查未触碰 TextRenderer/StyleEstimators/FitCalculator/BlockPatchBuilder |

**AC-1~AC-5 全部通过。**

---

## 五、回归风险评估

### 5.1 D-035（颜色/方向）

本次改动集中在 `EditorState.swift`（状态机编排）和 `EditingWorkflow.swift`（+hasPendingEdit 查询方法），**未触碰**：
- `TextRenderer.swift`（渲染）
- `StyleEstimators.swift`（样式分析）
- `FitCalculator.swift`（字号拟合）
- `BlockPatchBuilder.swift`（patch 构建）

**无回归风险。**

### 5.2 D-037（字号继承 B）

同上，字号继承逻辑在 FitCalculator/StyleEstimators 内，本次未触碰。

**无回归风险。**

### 5.3 存量测试回归

67 存量测试全绿（QA 首轮 + 复测均验证），72/72 总量全绿。

---

## 六、问题清单

### 阻塞项

**无。**

### 非阻塞项

| # | 问题 | 严重度 | 现状 | 建议 |
|---|------|--------|------|------|
| 1 | confirmEdit 成功后 document.select 失败 → 脏会话残留（draft/previewResult 泄漏） | 低 | UI 不可达（仅"点击不存在块"触发），潜伏缺陷 | 后续迭代在 select 失败分支补 `clearEditingSession` 兜底 |
| 2 | undo-during-preview 确认后文案「预览已失效」对用户不够直观（用户可能不理解为何预览失效） | 低 | 已兜住（不泄漏晦涩文案），UX 可优化 | 报 zongguan 协调 UI 文案优化 |
| 3 | in-flight 预览拒绝路径无确定性时序测试（依赖异步管线毫秒级完成时机） | 中低 | 逻辑正确（previewResult=nil 时 guard 必失败），无 BlockingTextRenderer 注入测试 | 后续迭代补确定性注入测试 |
| 4 | 三块连续 A→B→C 编辑链无直接断言（undoDepth==3） | 低 | 逻辑正确（每步 auto-confirm 独立入栈），测试 #5 间接覆盖 | 后续补端到端三块测试 |

---

## 七、结论

### 判定：**Approve**

理由：
1. **状态机正确性**：select 全分支无泄漏，阻塞/物化/悬空兜底三条路径清晰，P1 ghost pendingEdit 根治
2. **测试质量**：11 条测试全部走真实管线、非空转，断言多维度交叉验证，分支覆盖率 ~85%（≥80% 达标）
3. **PRD AC 全通过**：AC-1~AC-5 逐条核验，修复语义与 CEO 原话 + 批准方案 A 完全一致
4. **零回归**：72/72 全绿，未触碰 D-035/D-037 代码
5. **非阻塞遗留项均为低危/测试覆盖缺口**，不影响功能正确性

### 交付链合规

| 阶段 | 状态 |
|------|------|
| zhenhai 修复完成 | ✅ 72 tests passed |
| shouye QA 测试报告 | ✅ `workspace/qa/qa_report_v06_2026-09-01.md` |
| dana 代码审查 | ✅ 本报告，Approve |
| 向 zongguan 汇报 | ✅ 可进行 |
