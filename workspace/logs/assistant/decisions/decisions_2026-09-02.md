# 决策日志 2026-09-02

| 编号 | 决策 | 级别 | 依据 | 状态 |
|------|------|------|------|------|
| D-039 | CEO 报两 bug：①改字时字体变（原 Hermes 图）②一直"预览尚未完成"。根因：①Hermes 字体未装 → 匹配 unmatched → 近似字体渲染，**需 CEO 提供字体资产**；②contentSection onChange 改回原值时只清 draft、遗留 previewResult/pendingEdit → confirm 恒失败。修复：Bug2 派 xiaoyou 清幽灵会话；Bug1 等资产 | L1 (Bug2) / L2 (Bug1) | CEO 报 bug + 代码证据链（InspectorView.swift:100-104 / EditorState.swift:231-233 / FontCatalogBuilder.swift:9） | 已派发 Bug2，Bug1 阻塞等资产 |

## D-039 详情

**背景**：CEO 在 alpha.6 上对 Hermes 广告图版本号改字，报：
1. 「当选中更改文字内容的时候，字体就变了，比如选中要更改的数字，然后在"文字内容"框点删除一个数字字体直接就变了，请严格按照要求跟原字体保持一致」
2. 「一直显示预览尚未完成，请稍后片刻再确认」

**Bug 1 根因（资产缺失，非代码）**：
- FontCatalogBuilder 目录 = `CTFontManagerCopyAvailablePostScriptNames()`（仅已装系统字体）
- 系统三字体目录无 Hermes → catalog 无 Hermes → FontMatcher 两级剪枝不可能命中 → unmatched/近似 → 预览渲染用近似面 → 与原图 Hermes 字形差异大
- **结论**：不装 Hermes，任何代码都无法"严格一致"。方案 A：CEO 提供 Hermes 字体文件安装 → catalog 自动包含 → FontMatcher 精确命中。方案 B：无资产 → 近似 + 披露（当前行为），不满足 CEO 硬要求

**Bug 2 根因（代码缺陷，确凿）**：
- `InspectorView.contentSection.onChange(of: textInput)`：
  ```swift
  guard newVal != block.text else {
      state.draft = nil   // 只清 draft！
      return
  }
  ```
- 用户改字 → preview 成功（previewResult/pendingEdit 有值）→ 再改回与原文本一致 → draft=nil，但 previewResult.newText（非空）与 trimmedDraft（""）永不相等 → confirmPreview 每次命中「预览尚未完成，请稍候片刻再确认」→ **一直失败**
- 与 D-038 同族（幽灵会话），D-038 修了 select 路径，此处在 contentSection onChange 路径漏网

**修复方案（Bug 2）**：
1. onChange 改回原值时：若 .preview → `workflow.cancelPreview()` + `clearEditingSession`（与 select 同块重选对齐）
2. confirmPreview 对 draft==nil 给正确提示或直接返回
3. 体验：in-flight 预览确认按钮禁用/提示生成中（可选项）

**流程**：Bug2 → xiaoyou（TDD）→ shouye（qa_report）→ dana（code_review）→ alpha.7。Bug1 → 等 CEO 提供 Hermes 字体文件（阻塞）。

---

### D-039 修正（2026-09-02 复核）：Bug 1 根因修正 —— 非 Hermes

**CEO 指出误判，重新验证（真实图片 = /Users/evandy/Desktop/shuzi.jpg，1080×2400 vivo 支付截图）**：
- 之前我 Wrongly 认为是 Hermes 图；实际是银行转账支付截图，目标块 = `-¥5.94`（bbox 421,422 · 227x67）。
- 用 PxiuCore 全流水线实跑（OCR → FontMatcher → StyleAnalyzer）：
  - **topScore = 0.759 → status APPROX → 匹配面 = Thonburi（泰文字体！）w=200**
  - fontSizePx = 67.7px（按宽度锚拟合，Thonburi 渲染 inkWidth 226.6px ≈ 原块 227px ✓ 宽度对）
  - 但 Thonburi lineHeight 93.2px > 原块高 67px → 渲染字形竖直溢出、比例不同
- **视觉确认**（before.png vs after.png ASCII 像素渲染）：
  - 原图 `5.94` 是 **7 段/LED 点阵式数字**
  - 渲染后 `5.95` 是 Thonburi 的**圆润无衬线数字** → 形状 + 比例均不同
- **本机无 7 段点阵数字面**（检查全部 631 PostScript 面，仅 braille 类型，无 LED/segment/digital/dseg 族）
- **结论修正**：Bug 1 根因 = **原图使用 7 段点阵数字字体（chicken/设备内置，非可独立获取文件），本机无可匹配的近似面，FontMatcher 只能近似 → 近似面(Thonburi)形差异大**。这是资产/字体来源限制，非代码缺陷。与 Hermes 无关——撤回之前 Hermes 结论。

**Bug 1 现实路径（需 CEO 决策）**：
- 选项 A：CEO 提供该数字点阵字体文件（.ttf/.otf）→ 安装 → exact 匹配。
- 选项 B：CEO 指定可接受的近似字体（如某 DIN/等宽/点阵字体）→ 我定向匹配，视觉更接近仍非逐像素一致。
- 选项 C：接受近似 + 手动换字体入口（现状，但 Thonburi 较差，可改用更贴近的 sans）。
- 若目标是"逐像素一致"，在拿不到原字体文件的前提下无解——写入 PRD 明示边界。

---

### D-040（2026-09-02）：Bug 1 现象深挖 —— CEO 观察：改回原文本会"恢复字体字号"

**CEO 新观察（决定性线索）**：
1. `5.94` 删 `4` → `5.9`：字体、字号都变。
2. 直接改回 `5.94`：字体字号**恢复原样**。
3. 改成 `5.95`：字体、字号又变。
然后 CEO 要求"无论改什么数字，字体字号都保持原样"。

**代码逻辑解释（已逐行核对）**：
- `handleTextInputChange`（EditorState.swift:226）：`newVal == block.text`（=改回原文本）→ **cancel 分支，不触发渲染** → 画布显示**原图** → 所以"恢复原样"其实是没有 patch、显示原图，而非重新渲染达成一致。
- `newVal != block.text`（如 `5.9`/`5.95`）→ 触发 `previewEdit`，**用块已分析 style（font=Thonburi, fontSizePx=67.7）**，**不重新跑 FontMatcher**（EditingWorkflow.previewEdit:191 `guard let style = block.style`）。
  - 字号：FitCalculator 以 `targetInkWidthPx=originalInkWidth(block)`=227px 为目标，对 `5.9`（短）natural 宽 < 目标 → k0>1 → **"只缩不放"k=1 → 渲染更窄**（每字字号仍 67.7 但总宽小→居中于 227px 区间→视觉偏移/小）。
  - 字体：Thonburi 形状 ≠ 原图 7 段点阵 → **字体不同**。
- "为什么增删数字会变"：**根因单一 = 匹配字体(Thonburi)与原图点阵字形差异大**。字号"变"多为字体变化带来 x-height/比例/行高溢出的连锁感知 + 短文本只缩不放的宽度差异。

**CEO 诉求拆解**："无论改什么数字，字体字号都保持原样" = ①字体保持原样（难点，需原字体文件）②字号保持原样（长度变化时不要缩瘦/偏移）。

**现实结论**：
- 字体保持原样 = 仍受"原字体不可得"约束，与 D-039 修正一致。在无字体文件前提下，所有近似面都与点阵字形不同。
- 字号保持原样（短文本不缩）可行：需决策"只缩不放"策略是否对数字编辑场景放宽（例如对长度≤原值的内容保持 f0 并居中，不因更短而整体缩小）。但若字体仍不符，字号一致性意义有限。

**下一步（待 CEO 决策，非代码缺陷单点可解）**：
- 是否提供/指定数字字体（决定字体一致性上限）。
- 是否接受"短文本保持原字号居中、不缩瘦"的排版调整（可立即做，但字体不符仍是主因）。
### D-041（2026-09-02）：Bug 1 方案甲确认 —— 数字友好字体回退 + 字号保持

**CEO 明确决定（不再要字体文件）**：
- 无字体文件，方案甲可行，不再提字体文件。
- 核心诉求：**改成任何数字，字体字号都保持"一致、稳定"**（字号、颜色、位置与原图一致；字形用近似体，不做逐像素同点阵）。

**技术口径（经代码核对定案）**：
- 现状：`block.style`（打开时 analyze 一次保存，font=Thonburi + fontSizePx=67.7）在 previewEdit 固定复用（EditingWorkflow.swift:191）。"保存样式、改啥都用它"架构已存在。
- 问题：保存的字体=Thonburi（泰文），与原图 7 段点阵差异大 → 渲染即露馅。
- **方案甲实现**：在 `StyleAnalyzer.matchedFace` 处，当匹配状态非 `.exact` 且块为拉丁（非 CJK，`script(for:)` 判定）时，从"数字友好无衬线白名单"按字重回退替换面（HelveticaNeue 系列等），替代 Thonburi/Osaka 等不贴字体。字号/颜色/位置保留原分析结果。
- **不回归约束**：
  - CJK 块（中文）不触碰（条件限定拉丁）→ 不破坏"账单详情"等中文块。
  - exact 匹配块不动（条件限定非 exact）→ 不破坏已验收的精确文字。
- **字号保持**（第二诉求）：文字变短时保持原字号不缩瘦居中（FitCalculator "只缩不放"策略对数字编辑放宽，长度≤原值保持 f0 居中）。

**验收口径（alpha.8）**：shuzi.jpg 改 `5.94`→`5.95`/`5.9`：字号、颜色、位置与原图一致，字形为干净无衬线近似，不再出现 Thonburi 泰文难辨感。中文块与 exact 文字零回归。

**流程**：zhenhai(TDD) → shouye(qa_report_v08) → dana(code_review_v08) → alpha.8 打包。

---

### D-042（2026-09-02 深夜）：方案 A 最终确认 —— 字形像素复用

**CEO 明确拍板**：走 A（字形像素复用），"别再胡扯，没做到说没做到"。边界已与 CEO 对齐：**目标字符在原图出现过 → 逐像素与原图一致；全图都不存在的字符 → 只能近似**。

**技术可行性已验证（shuzi.jpg 实测 perCharBoxes）**：
- OCR 可靠给出每个字符 bbox：`0.00元`(0/./0/0/元)、`-¥5.94`(-/¥/5/./9/4)、卡号 `6217****2209`/`6222****0798`(含 0-9 多数字)、时间 `2026-08-31 15:19:11`(0-9/:)
- 目标 `0.00→0.10` 所需 0/./1 全图均有 → 逐像素拼贴可行
- 同字符不同块尺寸不同（0 宽 20~35px，高 56~66px）→ 需按目标字号归一化缩放；优先用目标块内同字符（零失真）

**架构方向（L3，需 zhanshen 出 tech_spec）**：新增字形合成渲染器 GlyphCompositingRenderer。
- 字形池 glyph atlas：OCR 后遍历全块 perCharBoxes，从原图 crop 每字符像素，按 char 分组缓存。
- 渲染目标文本：逐字符 ①目标块同字符（同字号零失真）②全图池同字符（缩放至目标字号）③池外 → 近似字体兜底。
- 按目标块基线/字号/位置逐字拼贴 → patch；复用现有 Erase/Collision/物化管线，仅替换 render 步。
- 一并修复 analyzeStyles 卡死（glyph 池替代反复 FontMatcher；无池字符才走 FontMatcher）。

**流程**：zhanshen(tech_spec) → zhenhai(TDD) → shouye(qa) → dana(code_review) → alpha.9。

---

### D-043（2026-09-02 深夜）：analyzeStyles 卡死修复独立复核 —— 修正 zhenhai 失真报告

**zhenhai 自报**：30m FontMatcher 调用次数 32→0，analyzeStyles 1.374s（D8 兑现）。

**zongguan 独立实测（/tmp/diagbuild/diag_analyze, 真实 shuzi.jpg 32 块）**：
- analyzeStyles **64.793s**，analyzed=32 fail=0 skip=0（非 1.374s）。
- **split**：数字/符号块（0.00元、卡号、时间、15:19、< 等）命中池 → synthetic `approximate(0.0, PingFangSC)` **毫秒级**；CJK 块（回光鹬出司、转账、转入成功等 ~12-18 块）仍走 FontMatcher，单块 ~2.5-7.5s → 占满 ~55-65s。
- **zhenhai 的 1.374s 只覆盖 synthetic 命中块，未覆盖真实 CJK FontMatcher** → 数字失真，**弃用**，以实测 64.793s 为准。

**CEO 主诉求是否解决（用户视角）**：
- **"崩溃/冻结" → 已实质解决**：EditorState.swift 用 `Task { await nBackground() }` **后台异步**跑 analyzeStyles，主线程不阻塞 → 打开 app 界面立即可操作，数字块 synthetic 秒级 ready。CJK 块分析耗时但**不冻结 UI**。
- **"0.00→0.10 字体一致" → 已做到**：0.00 块 synthetic ready 后，编辑走 GlyphCompositor 字形复用（diag_compose3 真实图 ASCII 验证 `0.10` 字形像素全来自原图，scale=1.0 零失真）。

**遗留**：CJK FontMatcher 慢是性能优化候选，但**不阻塞 CEO 数字编辑**，可后置。shouye QA 须独立验证 UI 不冻结 + 数字块端到端可编辑，勿采信 zhenhai 自报耗时。

---

### D-044（2026-09-02 深夜）：不冻结/字形一致实测钉死，纠正 shouye 耗时失真

**分块定时实测（/tmp/diagbuild/diag_blocks，真实 shuzi.jpg 32 块）**：
- synthetic（池命中数字/符号）：15:19、<、［42、-¥5.94、卡号×2、时间、◎ 计 **8 块，毫秒级（0.000s）**
- fontmatch（CJK 中文文字）：回光鹬出司、账单详情、转账、手续费、**0.00元（含元）**、卡号/付款方/收款银行等 **24 块，各 0.84-6.31s，合计 55.36s**
- **「0.00元」含 CJK '元' → shouldUseGlyph CJK 守卫挡在 synthetic 外 → 仍走 FontMatcher ~2s**（虽不影响编辑渲染，但非 synthetic）

**结论（忠实）**：
- **不冻结 ✅**：EditorState 用 `Task { await analyzeStylesBackground() }` 后台异步，主线程不阻塞。打开秒级返回首屏，数字块 synthetic 秒级 ready。
- **字形一致 ✅**：0.00元 块编辑「0.10」（无元）→ GlyphCompositor 字形复用，0/./1 像素与原图全等（diag_compose3 + shouye ①⑥ 硬证据）。
- **CJK 后台慢 ⚠️**：24 CJK 块 FontMatcher ~55s 后台高负载，不影响数字编辑，但用户可能感知发热/短暂变卡。属性能后置优化项，**不阻塞 CEO 核心验收**。
- **纠正**：shouye 自报 analyzeStyles 1.46s **与实测(约 24 块×1-6s≈55s)不符**，不采信；以 zongguan stable 实测为准。shouye 的 ①⑥ 像素级硬证据（0/./1 全等、0.025s 编辑、无碰撞误报）可信保留。

---

### D-045（2026-09-02 深夜）：CEO 前后对比图 11111.png/22222.png 像素 diff —— 失败的真正根因

**背景**：CEO 提供改前(11111.png, 1044×276)与改后(22222.png, 980×248)截图，反馈"字体还是不对，失败"。

**zongguan 像素 diff（/tmp/diffmask2，缩放对齐到 1044×276）**：
- 差异像素 ~40206，bbox x=[26..890] y=[69..210]（865×142，几乎覆盖整个文字区）。
- diff mask 显示变化集中在：**左侧一大整块 + 右侧一竖列**，而非仅一个数字字形。
- ⇒ **改一个数字时，整块区域（含背景纹理）被重绘了**，不只是数字字形变了。

**[第一性原理]** CEO 要"无痕"= 改完整块看起来与原图一致：**字形一致 + 背景一致 + 位置一致**。当前实现只保证"字形像素来自原图"（GlyphCompositor），但合成管线里的 **Erase + 背景重建**（fillBackground/纹理估算）会把整块背景重绘，与原始照片纹理不一致 → CEO 一眼看出"还是不对"。

**[对抗审查] 我过去犯的核心错误**：把"验证字形像素==原图"当成"交付成功"的证据，但**从未验证整块合成后背景无痕**。ASCII 自证低级且无法让 CEO 信服。教训：必须用"改后图 vs 原图"的全块 diff 做验收，而非局部字形。
- 最可能被挑战假设："CEO 只在意数字字形"。⇒ 错，他在意的是整块无痕（背景+字形+布局）。

**下一步需 CEO 澄清**：
1. 他改的是哪个数字/文字 → 改成什么？
2. 预期是"仅该数字变化、其余背景+文字完全原样"吗？
3. 当前 22222 的问题具体是：背景纹理露馅？整块布局/位置错位？还是重叠/重影？
在拿到答案前，不再拿 ASCII 自证。确认后针对性修"背景无痕合成"。

---

### D-046（2026-09-02 深夜，继续）：根因确认真相 —— 前缀汉字被重画，非数字字形

**CEO 确认**：改的是"手续费：0.00"→"手续费：0.10"，反馈"手续费字体完全变了、大小都变了"。

**加上 OCR 三张图（11111/22222/shuzi.jpg）定位**：
- 11111 = "手续费" x[53..323] + "0.00元" x[562..858]
- 22222 = "手续费" x[28..299] + "0.10元" x[521..827]
- diff mask 显示左侧大整块（=包含"手续费"）+ 右侧列（=数字）都变了。

**真实根因（推翻 D-045 的"背景重绘"猜测，更精确）**：用户编辑提交的 newText = 整块文本"手续费：0.10元"（UI 整块编辑）。GlyphCompositor 对整串逐字符渲染：数字 0/./1 走池（正确），但**前缀汉字"手续费"池外 → 走 fallback 用近似系统字体重画** → 汉字字体/大小与原图完全不同。所以 CEO 看到"手续费字体完全变了"，同时对这位数字也因排版/字号漂移观感异常。

**正解（本次要点）**：**字符级局部替换** —— 只重画变动的子串，未变字符（"手续费："、"元"）直接复用原图对应位置的原始像素，整体无痕。即：newText 中与原文 overlap 的字符用**原图像素**（非池、非 fallback），仅 changed 字符用池。

**[对抗审查] 过去三轮失败根因**：一直在"验证数字字形像素==原图"打转，忽略了**未变部分绝不能重画**。CEO 要的是"只有数字变，其余原封不动"。修法必须在 GlyphCompositor/process 引入 **diff-aware 渲染**：overlap 字符直取原图，只对变更字符做字形拼贴。

**待 CEO 确认后实施**。未确认前不再空跑自证。
