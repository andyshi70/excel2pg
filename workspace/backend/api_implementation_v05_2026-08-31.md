# pxiu 实现说明 v05 — 渲染三缺陷修复（白↔黑 / 镜像 / 字号虚大）

- 版本：v05（v0.3 基础上追加的语义修复交付）
- 产出者：zhenhai（后端工程师）
- 日期：2026-08-31
- 前置文档：`workspace/architecture/tech_spec_pxiu_2026-08-28.md`；v0.1–v0.3 见 `workspace/backend/api_implementation_v0.1.md` / `v0.2.md` / `v0.3.md`；根因定位见 `workspace/logs/assistant/decisions/decisions_2026-08-31.md`
- 范围：PxiuCore（TextRenderer + StyleEstimators + BlockPatchBuilder 注释契约）+ PxiuCoreTests
- 任务来源：CEO alpha.3 目测 Hermes 广告图（test.png，3008×1280）版本号改 `v1.21.1` 后 ①白字变黑 ②字镜像 ③字号与原因不匹配；PM zongguan 独立试验锁根因（证据链完整），L2 级直接开工
- 最终结果（初始交付）：**`swift test -c release --no-parallel`：57 tests passed, 0 failed（含 5 条新增语义测试，52 条存量零回归）**
- 最终结果（D-037 补充交付，2026-09-01）：**61 tests passed, 0 failed（+4 条选 B 语义测试，57 条零回归）**，详见 **Part F**

---

## Part A — Bug 1：白字渲染为黑（根因确凿）

### A.1 根因

`Sources/PxiuCore/Render/TextRenderer.swift` 原 `render()` 构造 CTLine 时 attrs **仅含字体（+可选 tracking）**：
`CTLineDraw` 以 attributed string 的 `kCTForegroundColorAttributeName` 属性渲染字形颜色，
**无视 `ctx.setFillColor(fg)`** → 白字永远按默认黑色绘制。

PM 独立验证（OCR 读回）：设颜色属性 → 白字读回；不设 → 全黑 OCR 空。

### A.2 修复（TextRenderer.swift:66-71）

```swift
let fgColor = CGColor(red: style.color.r, green: style.color.g, blue: style.color.b, alpha: 1)
var attrs: [NSAttributedString.Key: Any] = [
    NSAttributedString.Key(kCTFontAttributeName as String): font,
    NSAttributedString.Key(kCTForegroundColorAttributeName as String): fgColor,   // ← 新增
]
if tracking != 0 { attrs[.init(kCTTrackingAttributeName as String)] = tracking }
```

`ctx.setFillColor(fgColor)` 保留为兜底（TextRenderer.swift:102），字形实际颜色由 attrs 决定。

---

## Part B — Bug 2：字形镜像（根因确凿，坐标假设错误）

### B.1 根因

CGBitmapContext（`CGContext(data:)`）默认坐标系是 **Quartz 左下原点、y 向上**，与 CoreText 天然一致，
**无需翻转**。原实现执行 `ctx.translateBy(x:0, y:ph); ctx.scaleBy(x:1, y:-1)`（旧 TextRenderer.swift:92-94）
把坐标系翻成左上原点 → 字形上下颠倒（OCR 读 `1.13.1V`）。

PM 独立验证（5 变种 + Vision OCR）：不翻转且 textPosition=pad → OCR 精确读 `v1.21.1`；现序列 → 颠倒。

### B.2 修复（TextRenderer.swift:96-105）

```swift
// v05 Bug2 修复：删除翻转到左上原点的 CTM（CGBitmapContext 默认即 Quartz 左下原点，与 CoreText 一致）。
ctx.setFillColor(fgColor)
ctx.textPosition = CGPoint(x: pad, y: pad + descent)
CTLineDraw(line, ctx)
```

**基线偏移选择说明**（PM 指令为 `textPosition=pad`，实现取 `pad+descent`，理由如下）：
- PM 试验文本 `v1.21.1` 无下行部，`pad` 即可；但通用文本含 g/y/p 时，基线若仅置 `pad`，
  当 `descent > pad`（常见，如 Helvetica descent≈0.21em）下行部会被补丁盒下缘裁剪 —— 回归旧 P2-3 缺陷方向。
- 基线置 `pad+descent`：字形上缘 ≤ `pad+descent+ascent`（= ph−pad 当 leading=0）、下缘恰在 `pad`，
  ink 盒对称落于 `[pad, ph−pad]`，与旧翻转版几何**逐像素等价**（仅方向修正，位置不变）。
- 新增 `testDescenderInkNotClipped`（"gy" 96px 渲染 → 底缘 strip 须有字形像素）固化该选择。

### B.3 RenderedText.baselineY 新语义（TextRenderer.swift:107-110）

```swift
let baselineY = CGFloat(ph) - (pad + descent)
```

| | 旧（翻转版） | 新（no-flip） |
|---|---|---|
| 含义 | 基线距补丁**顶** = pad + ascent | 基线距补丁**顶** = ph − (pad + descent) |
| leading=0 时数值 | pad + ascent | ceil(ascent+descent)+pad−descent ≈ 同左 |
| 坐标系 | 翻转 CTM 后 top-down 行序 | 补丁缓冲行序（buffer row 0 = top） |

补丁缓冲行序与 `compositeAfter` 输出上下文一致（实验确认：`ctx.draw(image:in:)` 将 image row 0 绘至
dest 顶行），故 `BlockPatchBuilder.layout` 的 `patchOrigin.y = 图像基线 − rendered.baselineY`
（BlockPatchBuilder.swift:50）**公式不变**，两坐标系同为 top-down 行序。仅更新注释契约
（BlockPatchBuilder.swift:36，原注释「基线自顶 = pad + descent」本身已过期）。

---

## Part C — Bug 3：字号虚大（根因疑似，修复时验证）

### C.1 根因

`Sources/PxiuCore/Style/StyleEstimators.swift` SizeEstimator 原算法：
`fontSize0 = bbox.height / 1.15` 猜测 + 单向行高收敛（`fs = fs0 · H_obs / lineHeight(fs0)`）。
细窄字体（Hermes 版本号）detector bbox 高含行距/padding 而虚大（如 70px），
行高锚把字号推虚大 → 渲染字号虚大。**验证**：合成 bbox 高 ×1.4（细窄字场景）→ 旧算法给出 67.2px（真实 48px），+40% 偏差，测试 RED 复现。

### C.2 修复：行高 + ink 宽双约束（StyleEstimators.swift:59-87）

```swift
// —— 主锚：行高 ——（原算法保留）
let fsHeight = fontSize0 * (observedHeight / hr)
// —— 次锚：原 ink 宽（逐字框并集，无则 bbox 宽）——
let widthAnchor = BlockPatchBuilder.originalInkWidth(block)          // 紧贴字形的可靠信号
let wideProbe = FontProbe.inkWidth(text: text, face: face, fontSize: 100)  // 100px 探测避免 1px 亚像素舍入
let fsWidth = 100 * (widthAnchor / wideProbe)
// 两锚一致（±15%）：取高度锚（宽度锚含逐字框 union 的 kerning 欠估噪声）
if fsWidth >= fsHeight * 0.85 && fsWidth <= fsHeight * 1.15 { return fsHeight }
// 分歧：bbox 高虚大（detector padding/行距）→ 信宽度锚（宁小勿大 —— FitCalculator 只缩不放）
return max(fsWidth, 6)
```

- 与 FitCalculator 联动：FitCalculator 只有 `k0<1` 才缩放（`fs = f0·k`，k0≥1 时不缩 → `fs=f0`），
  故估算锚负责 `k0≥1`（新文本更宽时 k 由宽度锚独立决定，k<0.5 钳制路径仍受 f0 影响）。
  双约束把 `k0≥1` 路径的虚大根除，钳制路径的虚大也收敛。
- U3 回归验证：31 面 × 4 字号精确盒 bbox（height=行高、width=ink 宽）下两锚一致 → 走高度锚，
  维持 ±0.5px 回收率 ≥95%（全量绿，见 Part E）。

---

## Part D — 新增测试清单（TDD：先 RED 后 GREEN）

文件：`Tests/PxiuCoreTests/TextRenderingSemanticsTests.swift`（5 条，Vision OCR 依赖在 macOS 测试目标可用）

| 测试 | 语义 | 旧代码 RED 依据 | 修复后 |
|---|---|---|---|
| `testOrientationAndColorOCRReadsUprightWhiteText` | 方向语义：`v1.21.1` 白字黑底渲染 → Vision OCR（accurate, `usesLanguageCorrection=false`）读回含 `v1.21.1` | OCR 空（黑字）+ 镜像 | ✔ 读回 |
| `testColorSemanticsWhiteGlyphPixels` | 颜色语义：white 前景 → patch 字形核心像素接近白（maxLum ≥ 220），背景黑（minLum ≤ 20） | maxLum = 0.0（恒黑） | ✔ |
| `testDescenderInkNotClipped` | 基线偏移守卫：`gy` 96px → 底缘 strip 有字形像素（下行部不裁剪） | 黑字无像素 | ✔ |
| `testFontSizeNotInflatedByLooseBBoxHeight` | 字号语义：bbox 高 ×1.4 虚大（细窄字）→ 估得字号贴近真实 48px（≤30%误差）且渲染 ink 高（ascent+descent）/ bbox 高 ∈ [0.7, 1.3]（k0=1 自拟合隔离 FitCalculator） | est=67.2（+40%） | ✔ est=48, ratio≈1.0 |
| `testCompositedPatchOCRUpright` | 端到端：真实 Renderer + `BlockPatchBuilder.layout` + `compositeAfter` → OCR 合成区读回原文（防「patch 与模板同源自洽」盲区） | 镜像+黑字必败 | ✔ 读回 |

另同步修正 SSIM oracle（`TextRendererTests.drawTextOverlay`，原同为翻转+缺颜色属性缺陷）：
改为与生产同几何（no-flip、`kCTForegroundColorAttributeName`、基线 pad+descent），使
`testGradientPatchLocalSSIMAgainstOracle` 在巨头像方向修正后仍对齐（全绿）。

---

## Part E — 全量 release 套件输出尾（验收证据）

```
✔ Suite EstimationTests passed after 3.744 seconds.
✔ Suite FontMatcherTests passed after 2.584 seconds.
✔ Suite TextRendererTests passed after 0.001 seconds.
✔ Suite TextRenderingSemanticsTests passed after 0.131 seconds.
✔ Test run with 57 tests passed after 6.595 seconds.
```

- 命令：`swift test -c release --no-parallel`（release 必要：debug 模式 Swift 6.3.2 CLT `-Onone` 挂起，见 v0.3 Part B）
- 57 = 52 存量（零回归，含 U3 字号回收、SSIM 渐变 oracle）+ 5 新增语义
- 产出物：TextRenderer.swift（Bug1/Bug2/baselineY）、StyleEstimators.swift（Bug3 双约束）、
  BlockPatchBuilder.swift（注释契约）、TextRendererTests.swift（oracle 同步）、TextRenderingSemanticsTests.swift（新增）
- 风险项：OCR 语义断言依赖本机 Vision；Hermes 字体未安装，语义测试以 Helvetica 代理（镜像/颜色/字号缺陷均与字体无关，字号约束为算法级）

---

## Part F — 宽度策略选 B（D-037）语义确认与回归（2026-09-01 补充交付）

- 任务来源：CEO 明确选 B（宽度策略）：**只改内容，字号/颜色/风格继承原图**。
  ①正常场景（新文本 ink 宽 ≤ 原 ink 宽）：字号 100% 保持 `style.fontSizePx`（k=1，不缩放）
  ②超宽兜底（新文本 > 原 ink 宽）：等比缩小 k<1 直到 fit（minScale=0.5 下限）
  ③永不放大：新文本更窄时字号不变大。
- 结论先行：**`FitCalculator` 核心逻辑已天然满足选 B，本次零生产代码改动**（未改 FitCalculator，未动
  TextRenderer 翻转/颜色修复），交付物 = 链路审计结论 + 4 条新增语义测试 + 渲染层回归确认。

### F.1 链路审计：f0（fontSizePx）是否原值传递（结论：是，无副作用）

| 环节 | 文件 | 行为 | 审计结论 |
|---|---|---|---|
| 1. 产出 | `Style/StyleEstimators.swift`（SizeEstimator.estimate） | 行高 + ink 宽双约束估算，返回 fontSizePx；v05 起宁小勿大 | 与 FitCalculator「只缩不放」同向，无预缩放副作用 |
| 2. 赋值 | `Style/StyleAnalyzer.swift`（analyze） | `fontSizePx: fontSize` 原值写入 TextStyle，无任何 clamp/变换 | 原值传递 ✔ |
| 3. 消费 | `Render/TextRenderer.swift`（render） | `let f0 = style.fontSizePx` 原样传入 `FitCalculator.fit(baseFontSize: f0)`；渲染字号 `fs = fitResult.fontSizeUsed` | 原值传递 ✔ |
| 4. 规格 | `Workflow/EditingWorkflow.swift`（process） | `FitSpec(targetInkWidthPx: BlockPatchBuilder.originalInkWidth(block), minScale: minScale)`；目标宽 = 原 ink 宽（逐字框并集，无则 bbox 宽），`minScale` 初值 0.5（EditorWorkflow.minScale） | 目标/下限正确接入 ✔ |

**FitCalculator.fit（FitCalculator.swift:52-66）核心逻辑对照选 B：**
```
k0 = targetInkWidthPx / natural
k0 < 1 → k = k0, fs = f0·k（②超宽等比缩小）
k0 ≥ 1 → k = 1, fs = f0（①③正常/更窄，100% 继承，永不放大）
tooLong = k < minScale → fs 钳制 f0·minScale（超长兜底）
```
→ 三态 + 兜底全部对齐选 B 定义，**未改动**。

### F.2 新增测试清单（4 条，TextRenderingSemanticsTests.swift）

| 测试 | 对应选 B 语义 | 断言 |
|---|---|---|
| `testWidthFitsScaleDownWhenWider` | ②变宽（k<1） | 新文本 `v1.0.0-beta` vs 原文 `v1.0`（48px 探针验证更宽）→ `scaleFactor < 1` 且 `fontSizeUsed < 48` |
| `testWidthFitsNoScaleWhenEqualOrNarrower` | ①等宽/变窄（k=1） | 新文本 `v1.0` vs 原文 `v1.0.0-beta` → `scaleFactor == 1` 且 `fontSizeUsed == 48` |
| `testNeverScaleUpEvenForSingleChar` | ③永不放大 | 极端短文本 `V` vs 原文 `v1.21.1` → `scaleFactor == 1` 且 `fontSizeUsed == 48`（不许放大） |
| `testTooLongClampsToMinScale` | 超长兜底（k < minScale） | 超长串 vs 极小 target（10px）→ `tooLong == true` 且 `fontSizeUsed == 48 × 0.5 == 24`（钳制） |

- 风格对齐存量测试：`FontFace`（Helvetica）、`FontProbe.inkWidth` 探针前置 guard（探针失败 `Issue.record` 短路）、`#expect`（Swift Testing）。
- 构造为**算法级**（直接调 FitCalculator，不依赖 OCR/字体回归），跑秒级稳定。

### F.3 渲染层回归确认

- `TextRenderer.render`（TextRenderer.swift:58, 111-113）：`fs = fitResult.fontSizeUsed` 后
  CTFont 按 fs 创建字形、渲染 inkW 实测，`RenderedText(patch:, inkWidthPx:, fontSizeUsed: fs, scaleFactor: fitResult.scaleFactor, ...)`
  — **fontSizeUsed/scaleFactor 正确传回 RenderedText**，QA/上层（Workflow → EditPreviewResult.rendered →
  BlockPatchBuilder.layout/metrics）均消费该值，链路闭合 ✔。
- 未触碰：Bug1（kCTForegroundColorAttributeName 颜色修复，TextRenderer.swift:70）、Bug2（no-flip CTM，
  TextRenderer.swift:96-105）、baselineY 语义（:110）。零翻转/颜色回归。

### F.4 全量 release 套件输出尾（验收证据，2026-09-01）

```
✔ Suite EstimationTests passed after ~3.8 seconds.
✔ Suite FontMatcherTests passed after ~2.5 seconds.
✔ Suite TextRendererTests passed after 0.001 seconds.
✔ Suite TextRenderingSemanticsTests passed after 0.138 seconds.
✔ Test run with 61 tests passed after 6.598 seconds.
```

- 命令：`swift test -c release --no-parallel`（61 = 57 存量零回归 + 4 新增，0 failed）
- 产出物变更：`TextRenderingSemanticsTests.swift`（+4 条）；生产代码零改动