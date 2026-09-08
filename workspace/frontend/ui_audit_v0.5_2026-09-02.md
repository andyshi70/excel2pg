# UI 审计报告 v0.5 · 2026-09-02

## 范围

Pxiu Bug 2（预览确认卡死）修复 + 预览态体验补强。本报告审计改动后的交互态语义与用户可感知文案，焦点为 EditorState（UI 层状态权威）与 InspectorView（预览确认入口）。

## 根因回溯（需求诊断 2026-09-02 §Bug 2）

- 现象：删除数字后一直显示「预览尚未完成，请稍后片刻再确认」，确认按钮持续失败
- 根因：`InspectorView.contentSection` 的 onChange 改回原文本时仅 `state.draft = nil`，未清理 `previewResult` / `pendingEdit` / `phase`
- 结果：draft=nil → confirmPreview 中 `trimmedDraft=""` 与残留 `previewResult.newText` 永不相等 → 每点确认都命中误导文案「预览尚未完成」→ 卡死

## 改动清单

| 文件 | 位置 | 改动 |
|------|------|------|
| `InspectorView.swift` | contentSection onChange | 删除散落的 draft 处理 + beginPreview 分支，统一改调 `state.handleTextInputChange(newVal, for: block.id)` |
| `InspectorView.swift` | previewActionBar | 预览 in-flight 时确认按钮禁用并显示「预览生成中…」，防点确认命中误导文案 |
| `EditorState.swift` | 新增 `handleTextInputChange(_:for:)` | 收拢内容输入变更逻辑：内容变更→设草稿+beginPreview；改回原值→完整取消预览会话（对齐 D-038） |
| `EditorState.swift` | `confirmPreview()` | 新增 draft==nil（无内容变更）防御分支：不物化、不报「预览尚未完成」，安全返回 |

## 交互态语义审计

### 1. 改回原值（Bug 2 核心修复）

| 状态 | 变更前 | 变更后 |
|------|--------|--------|
| phase | 残留 preview（幽灵） | 回 selected |
| draft | nil | nil |
| previewResult | 残留（根因） | nil |
| pendingEdit | 残留（幽灵） | nil |
| 点确认 | 报「预览尚未完成」卡死 | preview 态已退出，确认按钮不显示；不会卡死 |

实现：`handleTextInputChange` 改回原值命中时若 `phase == .preview(id)` → `cancelPreview()`（= `workflow.cancelPreview` + `clearEditingSession` + phase 回 selected），与 `select` 同块重选（D-038 已验收路径）语义一致。

### 2. draft==nil 防御（confirmPreview 语义修正）

运行时序紧耦合（如 undo 后留 previewPhase + previewResult，draft 已被置 nil）下：confirmPreview 现于 guard phase/blocked 之后新增 `guard let draft, !draft.newText.trimmed.isEmpty`——无内容变更时不物化、不泄漏误导文案，安全返回。真正有内容变更的路径完全不受影响（trimmedDraft == previewResult.newText 判断保留）。

### 3. 预览 in-flight 体验（体验补强）

phase==preview 且 previewResult==nil（previewEdit 正在跑）→ 确认按钮 disabled + 文案「预览生成中…」。用户不再可能点到「确认」而命中「预览尚未完成」误导文案。

## 文案审计

| 场景 | 文案 | 审计 |
|------|------|------|
| 预览生成中 | 「预览生成中…」 | 新增；代替可点击的「确认」，语义清晰 |
| draft==nil 确认 | 无提示（安全返回） | 语义正确：未修改文字无需确认，不再误报「预览尚未完成」 |
| 预览碰撞/过长/样式未就绪 | 「…被阻塞…」 | 保留（confirmBlocked 分支，未改动） |
| 预览 in-flight 点确认 | 按钮已禁用，不可达 | 「预览尚未完成」仅剩真过期（previewResult 与最新草稿不一致）这一有意义的语义 |

## 无回归确认

- select 切块 auto-confirm / 阻塞拒切 / continueEditing 语义均未改动（回归测试通过）
- beginPreview 内容变更路径逻辑保持：`handleTextInputChange` 与旧 onChange 对内容变更分支行为一致

## 结论

Bug 2 根因（改动值只清 draft 不清 preview 会话 → 幽灵 pendingEdit → 确认卡死）已消除；confirmPreview 语义修正 + in-flight 按钮禁用补齐误导文案防线。全部 75 测试通过、build release 通过。
