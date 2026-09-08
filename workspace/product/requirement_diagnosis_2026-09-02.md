# 需求诊断报告 2026-09-02

## 背景

CEO 在 alpha.6 验收中报告两个新 bug（Hermes 广告图版本号改字场景）：

1. **Bug 1（字体一致）**：改字选中文字内容时字体就变了——在"文字内容"框删除一个数字，画布预览字体与原图不一致。要求：严格按照原字体保持一致。
2. **Bug 2（预览卡死）**：一直显示"预览尚未完成，请稍后片刻再确认"，点确认持续失败。

## 根因分析（对抗式审查）

### Bug 1：字体不一致（原图用 7 段点阵数字字体，资产不可得）

> ⚠️ 复核修正：之前误判为 Hermes 图。真实目标 = shuzi.jpg（vivo 支付截图）`-¥5.94`。

| 项 | 结论 |
|----|------|
| 现象 | 修改 `5.94` → 渲染出的数字字体、大小、比例均与原图不同（CEO：before.png vs after.png） |
| 代码路径 | 用户改字 → preview → `TextRenderer.render` 用 `style.font`（= FontMatcher 结果）渲染 → 预览 patch 覆盖原图 |
| 实测证据 | 全流水线实跑 shuzi.jpg：`-¥5.94` 块（421,422 · 227x67）→ **topScore 0.759 / APPROX / 匹配面 Thonburi（泰文）w=200 / fontSizePx 67.7**；Thonburi 渲染 inkWidth 226.6≈原块宽 227 ✓ 但 lineHeight 93.2 > 67 → 溢出竖直 |
| 视觉证据 | before.png 原数字为 **7 段/LED 点阵式**；after.png 渲染为 Thonburi 圆润无衬线 → 形状/比例全不同 |
| 根因 | **原图数字是 7 段点阵字体（设备/App 内置，非独立字体文件），本机 631 个 PostScript 面中无 LED/segment/digital 族可匹配** → FontMatcher 只能近似(Thonburi) → 视觉差异大。**资产来源限制，非代码缺陷** |
| 宽度 | FontMatcher+FitCalculator 宽度锚正确（227px 对上）→ 只有宽度还原对，字形与竖直比例还原不了 |

**结论**：要"逐像素/严格一致"，前提是拿到原 7 段点阵字体文件；否则任何代码只能近似。**这超出当前能改代码解决的范围，需 CEO 决策**（见报告）。

### Bug 2：预览确认卡死（代码缺陷，可确定）

| 项 | 结论 |
|----|------|
| 现象 | 持续显示"预览尚未完成，请稍后片刻再确认"，确认无法完成 |
| 文案来源 | `EditorState.swift:231-233` `confirmPreview`：`guard let pr = previewResult, pr.newText == trimmedDraft else { setOverlay(.exportFailure("预览尚未完成，请稍候片刻再确认")); return }` |
| 失败条件 | previewResult == nil，**或 previewResult.newText != trimmedDraft** |
| 根因（确凿） | `InspectorView.swift:100-104`：`onChange(of: textInput)` 中 `guard newVal != block.text else { state.draft = nil; return }` —— **只清 draft，不清 previewResult / pendingEdit / phase**。当用户把文本改回与原块文本相同时：draft=nil（→ trimmedDraft=""），但 previewResult 仍保留之前成功渲染的非空 newText，pendingEdit 也在 → 二者永不相等 → 每次点确认都命中 "预览尚未完成"。**这是悬空状态，与 D-038 同族（"幽灵会话"）但漏在 contentSection onChange 路径** |
| 次要问题 | 文案误导：draft 为 nil 时真正语义是"内容已恢复原样，无需确认"，却报"预览尚未完成" |
| 互补场景 | 预览 in-flight（previewEdit 正在跑，previewResult 为 nil）时点确认也会命中此文案——属正常"稍候"，但缺少 pending 指示 |

**修复方向**：
1. contentSection onChange 改回原值时：若 phase 为 preview → 走完整取消（`workflow.cancelPreview()` + `clearEditingSession`），与 D-038 select 同块重选路径对齐；
2. confirmPreview 对 draft==nil（无内容变更）分支给正确提示（"未修改文字"）或直接返回，不再误报"预览尚未完成"；
3. （体验增强）预览 in-flight 时确认按钮禁用或提示"预览生成中"。

## [第一性原理分析]

- Bug 1 本质：**换字 = 原字形 + 新文本渲染**。字体的唯一权威来源是原图，而匹配只能发生在"可枚举的已装字体"范围内。原图是 7 段点阵数字字体（格式每图片一体，非独立文件），本机无该族字体 → 匹配空间不含正确答案 → 结果必然近似。**产品"严格一致"承诺成立的前提是原字体在枚举空间内或可获取**——此处不成立，故该承诺对点阵设备字体不可实现。
- Bug 2 本质：**编辑会话（draft/previewResult/pendingEdit/phase）必须在生命周期终点被一致清理**。D-038 只修了 select 入口的清理，onChange 入口的"改回原值"分支制造了"draft 已死、preview 未死"的中间态。任何只清三件套之一的路径都是幽灵状态温床。

## [对抗审查记录]

- 自问 3 边界：
  1. 若 CEO 提供点阵字体文件，FontMatcher 能否命中？→ 需装后跑 match 验证分数 ≥0.86 exact；若分段字形仍难命中，则需调阈值或定向白名单。
  2. Bug 1 是否会随"换字体入口手动指定"缓解？→ 手动指定后预览用指定面渲染，能保证"你指定的字体"，但原图是点阵，仍非逐像素一致。
  3. 若用户改回原文本后接着再改第二次？→ 修复后 draft=nil 走取消 → 后续 onChange 以 block.text 为基准重新判定，行为一致。
- 最可能被挑战的假设：**"Bug 1 超出代码可解决范围"**。反方观点：可用任意相近字体"意会"。但 CEO 要求"严格按照原字体保持一致"，而原字体不可得 → 该假设成立，需 CEO 接受边界或提供资产。
- 外部依赖：7 段点阵字体文件（CEO 提供/设备提取）。依赖失效 → 只能近似，写入 PRD 边界。

## 任务分级

- Bug 1：L2 但 **依赖外部资产（点阵字体文件）**，且涉及产品承诺边界 → 先向 CEO 汇报根因 + 3 个决策选项
- Bug 2：L1（<10 行改动，单点状态清理）→ 已派 xiaoyou 修复并全链验收（75/75 pass）

## 流程

Bug 2：✅ 已闭环（xiaoyou → shouye → dana，75/75，Approve）。
Bug 1：等 CEO 在 3 个选项（A 提供字体 / B 指定近似 / C 接受近似）中决策后推进；alpha.7 先含 Bug 2 修复交付验证。

---

## 更新（D-041）：Bug 1 方案甲已由 CEO 拍板（无字体文件）

经历多轮澄清，CEO 明确：
1. **不要字体文件**，方案甲可行；"保存样式、改啥用它"架构已存在但存的是 Thonburi（泰文）→ 需换成`数字友好无衬线白名单`回退。
2. **字号保持**：文字变短不缩瘦、保持原字号居中。

**方案甲技术口径见决策日志 D-041**：`StyleAnalyzer.matchedFace` 对非 exact + 拉丁块回退到 HelveticaNeue 等干净字体；CJK/exact 零回归。验收：shuzi.jpg 改数字字号颜色位置一致、无 Thonburi 泰文感。
**状态**：已派单 zhenhai，流程进行中。
---

## 复核（2026-09-02 晚间）：CEO 实测 alpha.8 反馈 —— 三个真问题

### 1. "崩溃"（实际=冻结）
- 实测：`analyzeStyles`（打开后对全图逐块 font-match）在 shuzi.jpg（32 块、大量数字/CJK）上**串行极慢**——单块 match 需 2~7.5s，全块累计 100s+，期间 UI 冻结 → 用户以为崩。
- 证据：diag_one 逐块计时 block[0]=6.9s、block[5]=7.5s、block[2]/[4]/[10]≈2.5~3.8s；无 PxiuApp 崩溃 .ips，是**卡死非 crash**。
- 判定：**性能债，非 方案甲 引入**（方案甲只改 StyleAnalyzer.matchedFace，未动 FontMatcher）。属 L2 需优化。
- 修：font-match 加速（候选剪枝/掩码缓存/analyzeStyles 并行化），且 UI 不应因全块串行匹配而整体冻结。

### 2. 核心诉求未达成："0.00→0.10 字体完全不一样"
- 根因：改数字 = 用匹配近似字体（如 HelveticaNeue）**重新渲染**，原图数字是银行 App 特有字体 → 近似字形与原点阵字形**完全不同**，与"相似"无关。
- **唯一像素级一致路径 = 复用原图字形像素（字符复用**）：
  - 数据：OCR `perCharBoxes` 已有每字符 bbox；全图文本块含大量同字体数字（0.00、金额、卡号 6217/6222、时间 15:19、2026…）。
  - 方案：从全图收集数字字形像素池 → 新文本逐字符从池取像素贴到目标位置 → 0/./数字来自原图 → 与原点阵一致。
  - 边界：目标字符**全图不存在**时只能近似；来源字形尺寸不同需归一化。诚：0、. 等常用字符可完美；不保证所有字符逐像素完美。
- CEO 应确认是否采纳该方向（需较大改：字形池 + 抠图 + 拼贴管线，非"换字体"能解决）。

### 3. "预览被阻塞"
- 来源：EditorState.swift:162 切块时碰撞/文字过长/样式未就绪 → 拒绝切换提示。
- 诱因：#2 里 analyzeStyles 慢 → 部分块 style 未就绪 → 编辑大量触发阻塞；叠加 #1 冻结。
- 修：随 #1 性能修复 + 未就绪块更友好提示，不轻易阻塞。

### 结论（给 CEO 的决策点）
- A. 先修 #1（性能冻结）+ #3（阻塞误报）—— 可立即做，恢复可用。
- B. 核心需求 #2 需 CEO 采纳"字形像素复用"方向并接受其边界后，才值得实现（较大改动）。
- 若 CEO 只接受"逐像素完全一致且无条件"，在无字体文件前提下**做不到**——需明确承认，不假承诺。
