# 进度报告 2026-09-01（alpha.6：多块编辑持久生效）

## 需求（CEO 报告）
图片上改两处数字，只有一处生效；"我只要点第 2 处，第一处改的部分就还原了"。
要求：无论改多少处都能生效。

## 根因（系统调试 Phase 1，代码证据链）
切块 `select()` 时**静默丢弃前一块预览**：
1. EditorState.select(B) 只清 UI 草稿/预览，不物化 A
2. document.select(B) 用 phase=.selected(B) 覆盖 A 的 .preview(A)（= "还原"）
3. workflow.pendingEdit 单槽，B 的 previewEdit 覆盖 A
4. confirmEdit 只认当前 pendingEdit → 只有 B 生效，A 从未入 undo 栈

## 修复（CEO 批准方案 A：auto-confirm）
- 切块时前一块预览合法 → **自动物化 A**（patch 回贴 + 入 undo 栈）→ 再切到 B
- 前一块阻塞（碰撞/过长/样式未就绪/预览未完成）→ **拒绝切换 + 明确提示**，不静默丢输入
- undo 逐块回退

## 执行链（门禁全过）
1. zhenhai：select 重写 + hasPendingEdit + 6 测试（RED→GREEN）→ 67 tests
2. shouye QA 首轮：验收成立，发现 **P1**（同块重选 ghost pendingEdit，OverlayViews「手动更换」入口命中）
3. zhenhai P1 补修：同块重选补 cancelPreview + undo 悬空两分支兜底 + 5 测试 → **72 tests**
4. shouye 复测：72/72，P1 根治，无阻塞
5. dana：**Approve**，AC-1~5 全部 Satisfied，覆盖率 ~85%

## 交付 alpha.6
- 二进制：__text 完整段（421,456 B）与构建产物逐字节一致；签名有效；GUI 启动存活
- **SHA256: `5626ab2c14b59f752ef543f80c95e1f75300a8d687ac839e6d0db94d0599523c`**
- 文档链：prd_pxiu_v1.2 / requirement_diagnosis / api_implementation_v06 / qa_report_v06 / code_review_v06 / decisions D-038

## 遗留（非阻塞，backlog）
1. confirm 后 select 失败脏会话（UI 不可达，低危）
2. undo 悬空文案可再优化
3. in-flight 拒绝时序测试（需注入替身）
4. 三块连续链断言
5. Hermes 字体实装后回归（D-035/037 遗留）