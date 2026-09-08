# 项目汇报 2026-09-02

## 本轮交付：alpha.8（D-039 Bug2 + D-041 方案甲）

### 修复 1：Bug 2「预览尚未完成」卡死 ✅
- 根因：输入框改回原文本时只清 draft、残留 previewResult/pendingEdit → confirm 恒失败
- 修复：onChange 改回原值完整取消会话 + confirmPreview draft==nil 防御 + 确认按钮 in-flight 禁用
- 验收：xiaoyou TDD（+3 回归测试）→ shouye（75/75）→ dana（Approve）
- **CEO 实测确认已解决** ✅

### 修复 2：Bug 1 字体/字号（方案甲）✅
- 根因：数字块被 FontMatcher 匹配成 Thonburi（泰文）→ 改数字渲染观感差
- 方案甲（CEO 拍板，无字体文件）：非 exact + 拉丁数字块回退到数字友好无衬线（HelveticaNeue 系）；字号保持：变短/等长不缩瘦居中，变长受 minScale 保护
- 实测：`-¥5.94` 块 face 从 Thonburi → HelveticaNeue；`5.94`↔`5.95` 渲染 inkWidth/lineHeight 完全一致（152.6/93.5px）
- 验收：zhenhai TDD（+7 测试，82/82 全绿）→ shouye（82/82，1 P0 漏测=混合 CJK+拉丁块非本场景，记为边界）→ dana（Approve，4 不阻塞建议）

## 交付物
- **Pxiu-1.0.0-alpha.8.dmg**（803KB）
- 二进制 SHA256：`620e67ba…`
- 启动验证：✅ 签名 OK、挂载启动正常

## 已知边界（请 CEO 知悉）
- 混合 CJK+拉丁块（如"¥100元"）不触发字体回退——保守保留原匹配面。shuzi.jpg 纯数字块 `-¥5.94` 不受影响，已正确回退。
- 方案甲字形是"干净无衬线近似"，非逐像素同原图点阵（无字体文件前提下客观边界）。

---

## alpha.9（2026-09-03）— 字形像素复用（方案 A）+ analyzeStyles 卡死修复

**交付物**：dist/Pxiu-1.0.0-alpha.9.dmg（839KB）
- binary sha256 `9d5a24f0…`；dmg sha256 `23d75859…`
- 签名 OK（--deep --strict）、启动正常不秒退（PID 15424 稳定运行）

**本轮解决的 CEO 两个核心诉求**：
1. **改数字 `0.00→0.10` 字形与原图完全一致** ✅
   - 新增字形像素复用：从原图 OCR perCharBoxes 抠字符原始像素做字形池（GlyphAtlas），新文本逐字符取池中像素拼贴（GlyphCompositor）
   - 真实 shuzi.jpg 验证：`0`/`.` 像素与原图 crop **全等**（2440/2440、1586/1586），ASCII 像素图清晰显示 0.10 字形全来自原图；scale=1.0 零失真
   - 边界（已与 CEO 对齐）：全图存在该字符 → 逐像素一致；全图不存在只能近似（如 `1` 走池近距缩放）
2. **打开不再"崩溃/冻结"** ✅
   - analyzeStyles D8 快路径：池命中数字/符号块（8 个）跳过 FontMatcher，synthetic 毫秒级 ready；`0.00元` 块几秒内可编辑
   - UI 后台异步 Task 跑分析，主线程不阻塞 → 界面秒开
   - 真实图 open 0.35s 返回首屏，previewEdit 单次 25ms，无卡死

**流程门禁**：shouye qa_report_v09（像素硬证据通过）、dana code_review_v09（Approve，7 项不阻塞建议后置）

**诚实备案（不掩盖）**：
- analyzeStyles 总耗时存在两台测差：shouye/dana 实测 ~1.5s；zongguan 分块实测 24 CJK 块 FontMatcher ~55s（后台异步、不冻结 UI，不影响数字编辑）。差异源未深挖，但**两种测法都确认 UI 不冻结 + 数字块可编辑**。
- `0.00元` 因含 CJK `元` 未享 synthetic 快路径（仍 FontMatcher ~2s），编辑渲染不受影响。
- 含 CJK 的新文本（如改成含中文）无字形复用，回退 TextRenderer。
- 24 CJK 块后台 FontMatcher ~55s 高负载，可能发热/短暂变卡，属后置性能项，不影响核心验收。
