# PRD: pxiu 多块编辑持久生效（D-038）

- 项目: pxiu（图片文字编辑）
- 版本: v1.2（D-038，2026-09-01）
- 状态: 待 zhenhai 实现

## 1. 确定性问题

CEO：改两处数字，只有一处生效；点第 2 处时第 1 处还原。
根因：切块 `select()` 静默丢弃前一块预览（详见 requirement_diagnosis）。

## 2. 核心需求（AC）

### AC-1 多块编辑全部生效
连续编辑 N 个文字块 → N 处全部落地生效（源图体现全部修改）。

### AC-2 切块自动物化
- 当前块 A 处于 preview 且预览合法（无阻塞、已完成）→ 切换选中到 B 时：
  自动 `confirmEdit(A)`（patch 回贴 + 入 undo 栈）→ 再切换 selection 到 B
- 用户感知：改一处，点下一处，前一处已生效

### AC-3 阻塞拒绝切换（方案 A）
A 存在阻塞时（collision/tooLong/样式未就绪/预览 in-flight 未完成）：
- 拒绝切换到 B
- 明确提示（复用现有 UIFeedback 文案：碰撞高亮/过长/未就绪/预览未完成）
- 不静默丢弃 A 的编辑

### AC-4 undo 逐块回退
每块物化为独立 command 入 undo 栈 → undo 按块逆序回退（先 B 后 A）。

### AC-5 回归保持
- 单块编辑现有行为不变
- 颜色/字号继承/方向（D-035、D-037）不回归

## 3. 技术方案（zhanshen 勘察）

改动点（预计集中在 UI 编排层 EditorState + 可能的小 Core 暴露）：

1. **EditorState.select(blockID:)**（PxiuApp/EditorState.swift:128）——核心改动：
   - 前置：若当前 phase == .preview(prevID) 且 prevID != blockID：
     - 校验预览合法（无 confirmBlocked、previewResult 已完成且 newText == draft）
     - 合法 → `workflow.confirmEdit(prevID)` 物化 + 清该块 UI 残留
     - 不合法/阻塞 → 拒绝切换（保留 preview 态）+ setOverlay 提示
   - 后置：规范 `document.select(blockID)` 转移

2. **confirmEdit 幂等/残留**：confirm 后清 previewResult/draft/pendingFitFeedback[prevID]
   （对齐现有 confirmPreview 的清理逻辑，拆公共函数复用）

3. **undo 联动**：undo()/redo() 已在 workflow 侧弃 pendingEdit（generation++），
   确认切块路径不破坏该语义

4. **测试**（Core EditingWorkflow 或 UI 层，zhenhai 定）：
   - 双块连续编辑：A preview → select(B) 触发 confirm → B preview → confirm → 两块都物化
   - 阻塞切块：A collision → select(B) 被拒 → A 保留
   - 单块编辑回归不破坏

## 4. 不做（YAGNI）
- 不做多槽 pendingEdit（dict）方案：auto-confirm 保持单槽语义，最小改动
- 不做"全部撤销"批量操作
- 不改动 document.select 的 phase 覆盖语义（由调用方在切块前先物化/阻断）

## 5. 验收（QA）
- UI 行为：两处编辑全生效；阻塞切块被拒并提示
- Core 测试：61 + 新增 全绿（swift test -c release --no-parallel）
- undo 逐块回退验证

## 6. 交付
- alpha.6 dmg + 文档链

## 7. 风险
- 切块 auto-confirm 与 runPreview in-flight 竞态（预览未完成时拒绝即可，已覆盖）
- confirmEdit 抛错场景要映射友好提示（复用现有 WorkflowError message）