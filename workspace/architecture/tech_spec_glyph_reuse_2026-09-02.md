# tech_spec — 字形像素复用（Glyph Reuse）D-042

- 项目: pxiu（macOS 屏幕文字无痕修改）
- 版本: v1.3 (D-042, 2026-09-02)
- 产出: zhanshen（架构师，L3）
- 状态: 待 zhenhai 实现（TDD）→ shouye qa_v09 → dana code_review_v09 → alpha.9
- 前置依赖: PRD v1.2（已读）、decision D-042（已读）、全链路源码已核对

---

## 0. TL;DR（一句话）与关键决策列表

**一句话**：新增独立的字形池 `GlyphAtlas` + 逐字符拼贴渲染器 `GlyphCompositor`（实现现有 `TextRendering` 协议），把原图 OCR 抠出的字符像素按基线/字号贴回，实现与原文同字体的逐像素级一致；仅在池存在且命中时才走字形拼贴，否则无缝回退现有 `TextRenderer`。

**关键设计决策**：
| # | 决策 | 理由 |
|---|------|------|
| D1 | 字形像素**自带原始背景**（crop 原图整块，含底色+AA），不再应用 `style.background` 背景模型 | 像素来自原图 → 天然含正确底色，避免双重背景；target 块同字符零失真=逐像素一致（CEO 硬要求） |
| D2 | GlyphEntry 存**独立紧凑 RGBA 拷贝**（非大图引用） | 渲染时逐字可独立归一化缩放/贴位，避免裁剪语义混乱；大图整 buffer 常驻只有一份（复用 ImagePixels buffer），glyph 拷贝但裁剪只取字符框+少量边距，内存可控 |
| D3 | 新增 `TextRendering` 另一实现 `GlyphCompositor`，**不替换** `TextRenderer`；`EditorWorkflow.process` 按规则选渲染器 | 零回归：普通/精确匹配文字与 CJK 仍走原渲染器 |
| D4 | 目标字号/基线 = **块分析出的 baselineY（bbox.maxY − descent）+ 目标块同字符的原始 bbox 高**；目标字号优先取 `style.fontSizePx` | 对齐现有 `BlockPatchBuilder.layout` 契约，复用基线锚定，不新增坐标系 |
| D5 | 缩放：同 char(目标块内) 零缩放；异源同 char 近距选（尺寸最接近目标）→ 最近邻缩放（保留点阵锐度） | 点阵字形最近邻不失真、不产生柔化伪影；Lancoz 更适合照片/连续灰阶，点阵字数字用近邻 |
| D6 | 空格/0x0 矩形 → 用池内同字号数字的平均 advance 或近似字体 advance 填补 | perCharBoxes 空格 rect 退化（宽 0），无法 crop，需 advance |
| D7 | 池外字符 → 逐字近似字体兜底（仅该字符），与字形拼贴混排；整文本都需兜底才整体退回 TextRenderer | 最小改动、不整体切换渲染器 |
| D8 | glyph 池在 `open()` 后、`analyzeStyles` 前增量构建（纯像素 crop，无 FontMatcher） | 消除"analyzeStyles 卡死"的渲染路径依赖：能拼贴的块不再需要 FontMatcher |

**必改 vs 可后置**：
- **必改**（D-042 核心，alpha.9）：GlyphAtlas、GlyphCompositor、process 选渲染器分支、空格/0x0、测试。
- **可后置**（后续 alpha）：analyzeStyles 卡死优化（D8 的完整收益）、多行、异源缩放质量上限。

---

## 1. 业务本质（第一性原理）

### 1.1 根因回顾（D-039/D-040/D-042）
原图数字为**设备内置 7 段点阵字体**（无独立字体文件，本机无相近面）。FontMatcher 只能近似匹配（Thonburi 等），近似字形 = 完全不同形状 → CEO 不接受。

D-042 核心诉求：**新数字的字形必须与原图数字完全一致**。由于原图**就是**该字体的二进制位图，直接复用原图字符像素 → 天然同字体、同颜色、同 AA，无需字体文件。这是唯一不依赖外部字体资产的重建路径。

### 1.2 本质拆解
"改数字 `0.00`→`0.10`：新字形与原一致" 可拆为四个原子事实：
1. 原图已有 `0`、`.`, `1` 的像素（数字集常见，OCR perCharBoxes 已证明存在）。
2. 每个字符 = 一个**矩形像素块**（char + rect），可以直接从原图裁剪。
3. 拼贴 = 把这些矩形按**新文本顺序 + 同一基线 + 同一字号**排成一行，组成新字形补丁。
4. "与原一致" = 字符形状/颜色/大小/位置都与原块内对应字符一致（target 块内同字符天然零失真）。

这四个事实决定了方案形态：**裁剪 → 归一化缩放 → 基线拼贴 → 贴回**，全部是确定性的像素搬移，不需要字体文件、不需要 FontMatcher。

### 1.3 候选方案对比（选 A 不选 B）
| 方案 | 逐像素一致 | 依赖字体文件 | 改动量 | 结论 |
|------|-----------|------------|--------|------|
| A. 字形像素复用 | ✅ 池内字符 | ❌ | 中（新渲染器+池） | **选定（D-042）** |
| B. 数字友好字体回退（D-041） | ❌ 只是更贴的近似 | ❌ | 小 | 已否决（CEO 不接受近似） |
| C. 找原字体文件 | 是 | ✅（拿不到） | - | 已否决（CEO 明确不要） |

A 的根本优势：不依赖任何外部资产，且对池内字符**绝对一致**——这是唯一能同时满足"逐像素一致"+"无字体文件"的路径。

---

## 2. 现状链路核对（有依据，勿臆断）

已读源码确认的关键约束：
- `TextRendering.render(text,style,fit) -> RenderedText{patch,inkWidthPx,fontSizeUsed,scaleFactor,trackingUsed,baselineY}`（TextRenderer.swift:30-32, 5-28）。
- `BlockPatchBuilder.layout(for:block:style:)`：`baselineY = block.bbox.maxY − descent`（BlockPatchBuilder.swift:41）、`inkX` 居中（:45）、`patchOrigin = (inkX−pad, baselineY−rendered.baselineY)`（:50）。**patch 缓冲 top-down、`ctx.draw(glyphPatch, in: dest)` 直接贴**（compositeAfter:121）。
- `process` 管线：Erase → `renderer.render(text,style,fit)` → `layout` → `CollisionDetector.collisions(inkRect)` → crop before → `compositeAfter`（EditingWorkflow.swift:203-246）。**碰撞用的是 layout 产出的 inkRect（几何），与 glyph 像素内容无关** → Collision 步可原样复用。
- `CharBox{char, rect}`，perCharBoxes 逐字框，左上原点 px（TextBlockDetector.swift:23-30, 106-125）。
- `ImagePixels.rgba(_:rect:)` 提供 `(rgb, width, height)` 子区域采样（ImagePixels.swift:160-176），`Buffer` 为整图 RGBA（top-down）。
- `TextStyle{font, fontSizePx, color, background, tracking, baselineOffset, matchStatus}`（StyleTypes.swift:142-165）。
- `EditorWorkflow` 通过依赖注入持有 `renderer: any TextRendering`（默认 `TextRenderer()`，:104），`process` 用它渲染；`analyzeStyles` 串行跑 FontMatcher（:147-162）——这是"卡死"来源之一。

关键语义矛盾点：
- **TextRenderer 的 glyph patch 是"背景填充 + 字形 α 叠加"**（fillBackground + CTLineDraw）。字形像素来自渲染字体，背景来自 style.background。
- **GlyphCompositor 的神字像素来自原图 crop**，已含原图底色。若仍套用 style.background 背景模型 → **双重背景**。必须：glyph patch 直接由裁剪像素构成（自带背景），**不**调 fillBackground。
- compositeAfter 将 glyphPatch 当**不透明** `ctx.draw` 贴入（BlockPatchBuilder.swift:121，dest 由 patchOrigin 定位）→ 只要 GlyphCompositor 产出**不透明、已含背景**的 patch，compositeAfter 无需改动，天然兼容。✅

---

## 3. 数据模型：GlyphAtlas

### 3.1 类型定义（新增 `Sources/PxiuCore/Render/GlyphAtlas.swift`）

```swift
/// 单个字符的字形条目：从原图裁剪的紧凑像素块 + 几何元数据
public struct GlyphEntry: Sendable {
    public let char: Character
    public let sourceBlockID: UUID
    public let crop: [UInt8]        // RGBA，top-down，含原图背景 + 字形 AA
    public let cropWidth: Int
    public let cropHeight: Int
    public let baselineOffset: CGFloat  // 该字符框内「基线」到框顶的距离（见 3.4）
    public let advance: CGFloat         // 该字符的水平推进（见 3.5）
    public init(...) { ... }
}

/// 字形池：char → 可候选的 glyph 条目（同字符可能来自多个块/多次出现）
public struct GlyphAtlas: Sendable {
    public var entries: [Character: [GlyphEntry]] = [:]
    public var imageSize: (w: Int, h: Int) = (0, 0)
    public var isBuilt = false

    /// 构建：遍历所有块 perCharBoxes，从原图 rgba 正常 crop 每字符
    public static func build(image: SourceImage, blocks: [TextBlock]) -> GlyphAtlas
    /// 目标块内同字符（1 级源）：来源 blockID == 目标块，且尺寸最接近目标
    public func sameBlock(char: Character, targetID: UUID, targetHeight: CGFloat) -> GlyphEntry?
    /// 全图池同字符（2 级源）：尺寸最接近目标
    public func nearest(char: Character, targetHeight: CGFloat) -> GlyphEntry?
    /// 池外判定
    public func contains(_ char: Character) -> Bool
}
```

### 3.2 构建时机（D8）
- 在 `EditorWorkflow.open()` 内、`ocr.detect(...)` 返回 blocks 之后、`document.setBlocks` 前/后均可——**必须在 `analyzeStyles` 之前**，与样式分析解耦。
- 纯像素操作：一次 `ImagePixels.rgba(image.cgImage)` 整图 buffer → 逐块遍历 perCharBoxes → 逐 char crop。**不触发 FontMatcher**。
- 增量特性（本版不做热增量）：`open()` 一次性构建即可。用户**新增/手动块**（userAdded，无 perCharBoxes）不会入池（可后置：addBlock 时若在最后一行追加池重建）。

### 3.3 内存 / Buffer 语义（D2：拷 vs 引用）
- **整图 buffer 只有一份**：`ImagePixels.rgba(...)` 返回 `Buffer`（Swift `[UInt8]` 值类型，大数组 COW 共享）。GlyphAtlas 构建时持有这份 buffer 引用，不复制整图。
- **每个 GlyphEntry 存紧凑拷贝**（`crop: [UInt8]`，只裁剪字符框 + 少量边距）：理由：
  1. 渲染时每个 glyph 要独立缩放/定位，需**独立的、可归一化的源**；
  2. 若存"大图 + char rect 引用"，每个字符都要带一份大图索引/偏移，语义复杂；
  3. 裁剪仅取框（数字字符框通常 ~30×60px，约 7KB/字符，池中常见字符几十个 → 共 <1MB），内存完全可控。
- 故选择：**整图 buffer 引用（一次）+ 每字符紧凑拷贝**。避免"每 glyph 一份大图"。
- 内存护栏：池构建后释放整图 buffer 局部引用，仅保留 crop 数组；池大小有上限保护（如 >8MB 触发 LRU / 或仅保留目标块所在区块——可后置）。

### 3.4 基线偏移（baselineOffset）——关键几何
每个 Croplat 内的字符框 rect 来自 OCR，**不直接给基线**。需要把每个 char 的像素块映射到"同一基线"。
- **原则**：同一块内的字符共享同一基线 Y。对目标块 `targetBlock`，其基线 = `targetBlock.bbox.maxY − targetBlock.style.descent(approx)`（复用 `BlockPatchBuilder.layout` 的基线锚定语义，BlockPatchBuilder.swift:41）。
- **每字符框内到基线的距离** = `charRect.maxY − targetBaseline`。理想情况：相邻同块字符的 `charRect.maxY` 应近似相等（同一条基线）→ `baselineOffset ≈ charRect.height − descentConsistent`。
- **简化实现（本版）**：假设 target 块内所有字符 `charRect.maxY` 对齐同一基线。取 **target 块内同字符 rect.maxY 的众数/中位数**作为该块基线 `blockBaseline`；`baselineOffset(entry) = entry.crop 顶到 blockBaseline 的垂直距离 = blockBaseline − charRect.minY`。
- **异块源（2 级）**：来自其他块的字符，其 `baselineOffset` 依**其来源块**基线计算，拼贴时**垂直锚定到 target 基线上**：即新字形内，该字符框顶 y = (targetBaseline − entry.baselineOffset)；这样不同来源的字符即使框高不同，也能对齐同一基线的视觉下缘。
- **回退**：若单字符块（perCharBoxes 缺失）或目标块无 perCharBoxes → 无基线锚 → 回退 TextRenderer 或池内估算（见 §5.2）。

### 3.5 advance（水平推进）
- **优先**：同一来源块内，字符 `ch_i` 的 advance = `charRect_i+1.minX − charRect_i.minX`（同一块相邻推进 = 视觉字距，最佳）。块内最后一个字符、或整块单字符 → 用该块内平均 advance。
- **池近距源**：用该源块的相邻 advance（源块的 perCharBoxes 里也有相邻信息，需在 GlyphEntry 里带上其所在块的 advance 表或平均 advance）。
- **失败回退**：目标块无 perCharBoxes → 用近似字体 `FontProbe.inkWidth(char)`（复用现有字体度量，不新增）。空格同理（见 §5.4）。

### 3.6 依赖与回退
- 依赖：`perCharBoxes` 非空（OCR macOS 14+ 逐字框）。若目标块 `perCharBoxes == nil` → GlyphCompositor **无法获知基线/advance** → 该块回退 TextRenderer（见 §5.2 决策规则）。
- 依赖失效回退：池 `isBuilt == false`（OCR 全程无逐字框）→ 全部走 TextRenderer，行为与现状一致（零回归）。

---

## 4. GlyphCompositor 渲染器（新增 `Sources/PxiuCore/Render/GlyphCompositor.swift`）

### 4.1 协议：直接实现现有 `TextRendering`

```swift
public struct GlyphCompositor: TextRendering, @unchecked Sendable {
    /// 池：由 Workflow 注入（构建于 open 后）
    public let atlas: GlyphAtlas
    /// 兜底渲染器：池外字符/整块回退
    public let fallback: any TextRendering

    public func render(text: String, style: TextStyle, fit: FitSpec)
        async throws -> RenderedText
}
```

**两个关键点**：
1. `TextRendering` 协议签名不变（`render(text,style,fit) -> RenderedText`）→ `EditorWorkflow.process` 对 `renderer` 的调用点**零改动**，只是注入的实例从 `TextRenderer()` 换成 `GlyphCompositor(atlas:fallback:)`。
2. 由于 `GlyphAtlas` 依赖原图（open 后才有），**GlyphCompositor 需按块/按 open 后创建**：推荐 `EditorWorkflow` 在 `open()` 构建 atlas 后，内部持有 `glyphCompositor`（不再在 init 固定注入单一 renderer），`process` 按 §5.2 决策规则动态选择。

> 架构调整：`EditorWorkflow` 从"单一注入 renderer"改为"持有 `baseRenderer`(TextRenderer 兜底) + 可选 `glyphCompositor`(open 后构建)"，`process` 内一个分支选渲染器。**这是对现有 init 契约的最小侵入**（测试替身注入仍有效：测试可直接注入 baseRenderer；glyph 路径用真实 atlas + 测试构造的 SourceImage）。

### 4.2 渲染流程（逐字符选源 + 归一化 + 基线拼贴）

```
text 去空白(与现 process 一致) → guard 非空
targetID = 当前编辑块
targetHeight = style.fontSizePx（denominator，目标字号；见 4.3）
targetBaseline = 由调用方 layout 语义给定？→ 否：GlyphCompositor 只产 patch 内基线，
                 垂直绝对锚定交给 BlockPatchBuilder.layout（复用现有契约）

for each ch in text:
    src  = atlas.sameBlock(ch, targetID, targetHeight)   // 1 级：target 块同字符，零失真
        ?? atlas.nearest(ch, targetHeight)               // 2 级：全图池同字符，最近尺寸
        ?? nil
    if src == nil:
        fallbackChar = render(ch 单独，fallback renderer)   // 3 级：池外，单独近似字体
        按 fallback 的 fontSizePx 缩放/定位
        push(fallbackChar, baselineAnchor=targetBaseline)
    else:
        push(src 像素, 缩放系数 = 需决定，见 4.4, baselineOffset=src.baselineOffset)
    x += advance(ch)（源 advance 或 fallback advance）

整体：把逐字像素按 x 累积 + y 基线对齐写入 glyph patch buffer → 包 RenderedText
```

### 4.3 目标字号 / 基线从哪来（D4）
- **目标字号（缩放分母）**：`style.fontSizePx`（analyzeStyles 已存的目标块字号，TextStyle.fontSizePx）。字形源的目标高 = 字形源来源块的字符框高 `√`，但**统一以 `style.fontSizePx` 为"标准目标尺寸"来缩放源字符框高**。
- 但注意：`analyzeStyles` 给的 `fontSizePx` 是**按字体度量反推**的（受近似字体 Thonburi 干扰、偏高 93px vs 块高 67px，见 D-039）。字形拼贴场景应**用块内真实字符框高**而非字体度量字号：
  - **更稳**：目标字符高 = target 块内同字符的字符框高（零失真时根本不缩放，天然正确）；异源字符目标高 = target 块同字符串框高的代表值（median）。
  - **最终口径**：GlyphCompositor 内部"有效目标高 `H_t`" = target 块内与目标字符同字符的字符框高（取中位数）；target 块无该字符 → 用 target 块任意字符框高 median 作为 H_t；仍无 → 用 `style.fontSizePx` 作 H_t（兜底）。**以 `RenderedText.fontSizeUsed` 对外报告 H_t**（语义：`fontSizeUsed` 此处=字形点阵目标高，供 layout/metrics 用）。
- **基线**：`RenderedText.baselineY` 语义沿用（patch 内基线自顶距离）。GlyphCompositor 内部：基线自顶 = (glyph 块高) − (H_t 的 descent 部分)。**descent 从 target 块字符框下缘与基线差推出**：同块字符框下缘 ≈ 基线（字符底对齐基线，无 descent 字形）→ `descent ≈ targetBaseline − charRect.maxY ≈ 0` 时按 0 处理。实际实现：取 target 块内所有字符 `charRect.maxY` 的 median 作为基线 Y，`baselineOffset = baselineY − charRect.minY`。
  - **一致性**：产出 `RenderedText.baselineY` 后，`BlockPatchBuilder.layout` 用同一公式 `patchOrigin.y = block.bbox.maxY − descent(style) − baselineY` 定位——**沿用现契约，不新增坐标系**。GlyphCompositor 只需保证 patch**内部**字符按自身 `baselineOffset` 对齐到 patch 内一条统一基线上。

### 4.4 缩放策略（D5）
- **1 级源（target 块同字符）**：`scale = 1`，**零缩放** → 逐像素与原文一致 ✅（CEO 硬要求满足路径）。
- **2 级源（池近距/异源）**：`scale = H_t / src.cropHeight`。若 `|scale − 1| < 0.01` → 视为 1（不缩放）。否则按 `fit.targetInkWidthPx / src.cropWidth` 也校核横向（保持长宽比 1:1，防止 OCR 框宽不准拉伸）。**用最近邻（NearestNeighbor）放大/缩小**：
  - 理由：7 段点阵数字为**硬边 + 单像素宽段**，最近邻保留二值锐度、不引入插值柔化/灰边；Lanczos 适合照片连续灰阶，对点阵字形会稀释笔画、产生 halo。
  - 最近邻在纯整数坐标源（逐像素）上是确定性且最快的；点阵同分辨率缩放视觉效果与原一致（只是整体大/小）。
  - **取舍**：若后续遇到连续灰阶字形（非点阵）且 2 级源缩放,可后置加 Lanczos 开关（YAGNI，本版不做）。
- 缩放实现：新建小 CGContext（目标 w×h），逐像素最近邻映射进 `crop` 数组。纯 CPU 像素级，无字体/无 CoreText 依赖。

### 4.5 颜色 / 背景（D1：自带背景，不做双重背景）
- **字形像素 = 原图 crop（含底色 + AA + 字形）**，`alpha` 保持原值。crop 是非透明的（原图是 JPEG/PNG 照片，背景不透明）。
- **GlyphCompositor 不调 `fillBackground`**（对比 TextRenderer 的 fillBackground，TextRenderer.swift:118-152）。新字形 patch 直接由逐字 crop 像素"拼画布"构成。
- **拼接背景逻辑**：patch 中**字符与字符之间、字符内部的空隙** = 用什么？
  - 方案：**逐字 crop 自带背景** → 字符间缝隙由相邻 crop 的透明/缺口补？不行：crop 是矩形不透明块，字符右缘与下一字符左缘之间的缝隙**不属于任何 crop**。
  - **解决**：gap 区域像素取**目标块背景**（`style.background` 采样，或直接用邻接 crop 的边界背景色扩展）。但为满足"逐像素一致 & 简单"，首选：**gap 直接用原图目标块区域的已有背景**——由于目标块被 Erase 抹除后回填 inpaint 背景，gap 像素实际会由 `compositeAfter` 底图（inpaint 后的背景）补齐，只要 glyph patch 在 gap 处**留透明/或画背景色**即可。
  - **最简正确方案**：GlyphCompositor 的 patch 是一个**全不透明、背景 = 目标块背景模型渲染**的画布，字符 crop 像素直接盖上。也就是：patch 背景固定画 `style.background` 模型（flat/gradient/texture，复用 TextRenderer 的 fillBackground 逻辑或直接复用该私有方法 → 抽公共函数），字符像素（自带原始背景）不透明覆盖其上。字符 crop 自带背景与 patch 背景几乎相同（同图同块）→ 肉眼无接缝。字符间的 gap 露出 patch 背景 = 目标块背景 ✓。
  - **边界风险**：若目标块背景是渐变/纹理，crop 自带背景与 patch 背景在字符边缘可能 1-2px 色差 → 可接受（CEO 主诉是字形形状不一致，背景 1px 差异不放大）。若后续要严格，可"扩展 crop 边界背景填满 advance 区间"（可后置）。
- 结论：**复用背景模型渲染（抽公共 `fillBackground`），字形像素不透明覆盖** → 不双重背景、同块零失真、gap 自然。

### 4.6 空格 / 0x0 占位（D6）
- 逐字框中空格/全角空格 rect 可能 `width==0`（或极窄），无法 crop（crop w=0 返回 nil）。
- **方案**：`advance(space)` = 池内同字号目标块内数字/字母的平均 advance × 空格的标称宽度比（或用近似字体 `FontProbe.inkWidth(" ")`）→ 在拼贴 x 偏移处**空出 advance 宽度**，不画像素（露出 patch 背景）。
- 目标块整个评估：若目标文本含空格且无法 fallback → 空格处留空即可，无需字体。
- **回退**：gap 逻辑天然支持——空格 = 一个 advance 的空 gap。

### 4.7 兜底渲染（3 级源：池外字符）
- **池外字符（全图池无）**：单独用 `fallback renderer`（TextRenderer）渲染**该单个字符**（以 target 字号 H_t 或 style.fontSizePx 渲染），得到单字符 patch，再按目标基线拼贴。
- **拼贴细节**：单字符 fallback patch 背景较透明（TextRenderer 是 bg + 字形），拼到整体 patch 上与会字形 crop（不透明）混合 → 需把 fallback patch 视为字形源，按 α 混合进整体 patch（整体 patch 已有背景），或 fallback 单字符也以相同背景模型渲染成不透明块再覆盖。**统一口径**：所有字符源（crop / fallback 单字符）都作为"不透明字形块"覆盖到统一背景 patch 上；fallback 单字符先以 `style.background` 背景渲染成不透明单字符 patch，再拼贴。
- **整块全池外**：所有字符都 fallback → 等价于原 TextRenderer，但逐字母拼 vs 整体渲染会有轻微字距差。**决策规则（§5.2）**：若目标文本中**池外字符占多数（>50%）或整块需 fallback** → **整体回退 TextRenderer**（保持现状一致，避免逐字拼贴的度量偏差）。

---

## 5. 与现有管线整合

### 5.1 渲染器选择（D3/D7）
`EditorWorkflow.process` 内第 3 步改为一处分支（EditingWorkflow.swift:223 附近）：

```
glyphMode = (atlas.isBuilt) 
            && (block.perCharBoxes != nil)
            && 目标文本池外字符占比 ≤ 50%      // 见决策规则
if glyphMode:
    rendered = try await glyphCompositor.render(text, style, fit)
else:
    rendered = try await baseRenderer.render(text, style, fit)   // 现状
```

- `atlas.isBuilt == false` → 全部走 baseRenderer（零回归，与现状完全一致）。
- **注入方式**：`EditorWorkflow` 保留 `baseRenderer: any TextRendering`（默认 `TextRenderer()`）与可选 `glyphFactory`（构造 atlas 的闭包）。`open()` 内构建 atlas；`process` 用上述分支。

### 5.2 "何时 GlyphCompositor、何时原 TextRenderer"决策规则（不回归约束）
| 条件 | 渲染器 | 理由 |
|------|--------|------|
| 目标块 `perCharBoxes == nil`（未提供逐字框） | 原 TextRenderer | 无基线/advance 依据 |
| `atlas.isBuilt == false` | 原 TextRenderer | 无池 |
| 目标文本**池外字符占多数**（>50%） | 原 TextRenderer | 逐字拼贴无收益且可能字距偏差 |
| 池外字符少量（≤50%，如 `0.10` 的 `0/.` 均在池、目标无 `1` 时） | GlyphCompositor（混合兜底） | 主体逐像素一致，少量近似可接受且 CEO 已认可边界（"全图都不存在 → 只能近似"） |
| **目标块为 CJK/中文** | 原 TextRenderer | D-041 约束：CJK 不触碰；CJK 字符池命中率低 + 字形结构复杂，拼贴风险高 |
| exact 匹配块（普通非数字文字，font 是真实系统字体） | 原 TextRenderer | 无必要改，避免回归已验收精确文字 |

> **CJK 判定**：复用现有 `script(for:)`/`FontCatalog.facesCovering(text, script:)` 的思路判断目标块脚本（StyleTypes.swift 已按中英分流）。**本版：凡含 CJK 字符的块一律走 TextRenderer**（保守、零回归）。纯拉丁/数字块才考虑 GlyphCompositor。

### 5.3 池构建放 analyzeStyles 前（D8）
- `open()`：`ocr.detect` → `document.setBlocks` → **构建 GlyphAtlas** → 返回。analyzeStyles 不依赖 atlas，纯后台增强。
- **analyzeStyles 卡死的实质缓解**：凡走 GlyphCompositor 的块，其 `style.fontSizePx`（若为 nil）可由池内字符框高直接推导（H_t），**无需 FontMatcher**。本版最小做法：process 内若 `block.style == nil` 但可走 glyph，用池推导临时 H_t 渲染（不写回 style，保持 analyzeStyles 职责单一）。完整收益（analyzeStyles 对池覆盖块跳过 FontMatcher）→ **可后置**。
- 效果：CEO 主要场景（改数字）在 preview 时**不再被 FontMatcher 卡死**（render 路径不触发 FontMatcher）。

### 5.4 复用现有步骤
- **Erase（TextEraser）**：原样复用（仍需抹掉旧笔画，glyph 覆盖新字形）。
- **Collision（CollisionDetector）**：原样复用（基于 layout 的 inkRect 几何）。
- **patch 物化（BlockPatchBuilder.crop/compositeAfter/confirmEdit/undo）**：原样复用。`RenderedText.patch` 依旧不透明 → `compositeAfter` 的 `ctx.draw` 直接贴，无需改。
- **唯一改动点**：`process` 选渲染器分支 + `EditorWorkflow` 注入方式（可选 atlas）+ 新增两个文件（GlyphAtlas, GlyphCompositor）+ 抽公共 `fillBackground`。

---

## 6. 边界与失败回退（攻击者视角加固）

| 边界 | 处理 | 回退 |
|------|------|------|
| 目标文本含池外字符（如 `0.10` 的 `1` 不在池） | 单字符 fallback 或整块回退 | ≤50% 混合拼贴；>50% 整体 TextRenderer |
| 空格/0x0 矩形 | advance 空 gap | gap 露出 patch 背景 |
| 目标块无 perCharBoxes | 无锚 | 整体 TextRenderer |
| 池为 0 字符（OCR 全程无逐字框） | isBuilt=false | 全走 TextRenderer（零回归） |
| 单字符块编辑 | 池内同字符(他块)拼贴 or fallback | TextRenderer |
| 异源字符缩放失真 | 2 级源最近邻，目标高对齐 | 若失真相 (scale 差值过大) 回退 TextRenderer 该块 |
| 池内存上限 | >8MB 触发降级 | 仅保留目标块同块 entry（1 级）或整池弃用回退 |
| 渐变/纹理背景 1-2px 色差 | 复用背景模型填 gap | 可后置严格化 |
| target 块自身就是要改的 `0.00`→`0.10`，但 `1` 在原块 | 1 级 `0/.`、2 级 `1`（若他处有 `1`） | 无 `1` 则 fallback |

---

## 7. 测试策略（PxiuCoreTests 新增 + 回归）

目标：覆盖池构建、逐字符选择优先级、拼贴像素一致、空格/0x0、池外兜底、零回归。复用现有 `TestSupport`（构造图像/渲染）与 `ImagePixels` 断言。

### 7.1 必改测试（对应必改交付）
1. **GlyphAtlas 构建**：构造含不同字号 `0.00` + 另一块 `1` 的原图（TestSupport 渲染相关字体作"原图"），OCR perCharBoxes 或手工构造 `CharBox`，断言 atlas.entries 分组、crop 尺寸、baselineOffset/advance 计算正确。
2. **1 级选择优先级**：target 块内 `0` 存在 → `sameBlock` 命中且 `scale=1`（零缩放）。
3. **2 级选择**：target 块无 `1`，池他块有 `1` → `nearest(1, H_t)` 命中并缩放，且选**尺寸最接近**的。
4. **池外兜底**：文本含池外字符 `X` → 该字符走 fallback，其余从池。
5. **整块池外多数 → 回退**：断言按决策规则整体选 TextRenderer（可通过渲染器返回内容/调用计数断言）。
6. **拼贴 pixel 一致**：`0.00`（全池内）→ `0.10`：合成 patch 中 `0`/`.` 像素与目标块原 crop 同字符逐像素一致（1 级零失真）；中间 `1` 来自池/fallback。对比 `ImagePixels.rgba` 断言。
7. **空格/0x0**：文本含空格 → advance 空 gap，不 crash、gap 露出背景。
8. **compositeAfter 集成**：GlyphCompositor 产出 RenderedText → 走 `BlockPatchBuilder.layout + compositeAfter`（复用现有 E2E 模式，TextRenderingSemanticsTests.testCompositedPatchOCRUpright 同构）→ OCR 读回新文本、方向正确。
9. **零回归**：exact 匹配块、CJK 块、池未构建 → 全部走 TextRenderer（现有测试保持绿）。

### 7.2 复用现有测试
- TextRendererTests、FitCalculatorTests、TextRenderingSemanticsTests、CollisionDetectorTests、EditingWorkflowTests 全部保持绿（新实现不破坏）。

### 7.3 回归命令
`swift test -c release --no-parallel`（与 v1.2 验收一致）。

---

## 8. 必改 / 可后置清单

### 必改（alpha.9，D-042 核心）
- [ ] 新增 `GlyphAtlas.swift`（数据模型 + build + sameBlock/nearest/contains）
- [ ] 新增 `GlyphCompositor.swift`（实现 TextRendering，逐字选源/缩放/基线拼贴/空格 gap/fallback 混排）
- [ ] 抽公共 `fillBackground`（TextRenderer → 共享，供 GlyphCompositor 画 patch 背景）
- [ ] `EditorWorkflow`：open 后构建 atlas；`process` 加渲染器选择分支（§5.1 决策规则）
- [ ] 必改测试（§7.1 全 9 项）
- [ ] 汇报 + 链路文档（qa_v09, code_review_v09）

### 可后置（后续 alpha，非 D-042 阻塞）
- [ ] analyzeStyles 对池覆盖块跳过 FontMatcher（D8 完整收益）
- [ ] 增量池重建（addBlock/手动块入池）
- [ ] 空白/多行渲染
- [ ] 2 级源缩放质量上限（Lanczos 开关，连续灰阶字形场景）
- [ ] 渐变/纹理背景 1px 接缝严格化
- [ ] 池内存 LRU（超 8MB 降级策略）

---

## 9. 前置依赖与回退汇总

| 决策 | 前置依赖 | 依赖不成立回退 |
|------|---------|---------------|
| 池构建（3.2） | OCR macOS 14+ 逐字框 perCharBoxes | `isBuilt=false` → 全走 TextRenderer（零回归） |
| 1 级零失真（4.4） | target 块含同字符 | 2 级池近距 + 缩放 |
| 基线锚定（3.4） | target 块 perCharBoxes 可推基线 | 该块回退 TextRenderer |
| 空格 gap（4.6） | advance 可估算（源块相邻/字体） | gap 露出 patch 背景（仍可用） |
| 池外兜底（4.7） | fallback renderer 可用（=现有 TextRenderer） | 整块回退 TextRenderer |
| 决策规则（5.2） | 脚本判定（中英分流） | 保守默认：含 CJK → TextRenderer |

---

## 10. 第一性原理分析

**从业务本质推导技术形态**：
- 业务本质：让新文字"看起来就是原图同款"。原图本身就是目标字体的位图样本。
- 从本质推导：既然原图有该字体像素 → 不需要"匹配字体"，直接**搬运像素**。字形=像素块，排新文字=按序排列像素块。这就是 GlyphCompositor（拼贴器）而非"字体渲染器"的必然形态。
- 选源优先级（1 级 target 同字符 → 2 级池近距 → 3 级池外兜底）从本质推导：一致性优先（零失真最重要），其次可用性（尺寸接近减少失真），最后兜底（能出字就行）。
- 不选"改造 TextRenderer 支持字形字模"：因为 TextRenderer 的单字是"背景+字体字形合成"，字形拼贴是"像素块搬移"，两者模型不同 → 独立新渲染器，通过协议复用 `RenderedText` 契约与 layout/compositeAfter 管线，最小侵入。
- 背景自带（D1）：像素来自原图 → 已含背景，套 style.background 反而不对（双重背景）→ 从本质推出"自带背景 + patch 统一背景填 gap"。

**技术选型候选对比**：
- 选源：同字符优先 vs 任意字符放大 → 同字符保留笔画密度，零失真，必选。
- 缩放：最近邻 vs Lanczos vs 双线性 → 点阵硬边用最近邻（保锐度），Lanczos 会柔化段边，本版近邻，连续灰阶可后置。
- 内存：紧凑拷贝 vs 大图引用 → 紧凑拷贝（独立缩放源），整图 buffer 仅一份。
- 集成：协议新实现 vs 改 TextRenderer → 新实现（不污染、零回归），协议签名不变。

---

## 11. 对抗审查记录（攻击者视角）

### 11.1 三个「如果…会怎样？」
**Q1：如果 OCR perCharBoxes 对该块不连续/缺失某字符框，会发生什么？**
→ 若目标文本需求字符的框缺失 → 该字符走 2 级/3 级兜底，其余池拼贴。若 target 块 perCharBoxes `nil` → 整块回退 TextRenderer。**防御**：sameBlock/nearest 均返回 optional，缺失即降级；决策规则已覆盖"无逐字框挡底"。风险低。

**Q2：如果 target 块内同字符的 `charRect.maxY` 不整齐（OCR 框下有 padding/偏差），基线会对不齐，拼出来歪？**
→ 用 median 而非单个框顶求基线，抗单框噪声。异源字符统一按 baselineOffset 挂到 target 基线，垂直一致。**残余风险**：不同来源块的视觉基线若与 target 块差 >2px，拼出来会有高低差。**回退**：2 级源也做"垂直微相对齐"（用字符框高比 scale 后对齐 target 基线，已含），最坏该字符单 fallback。可后置加垂直偏移检测。

**Q3：如果预算/内存下池构建很慢（大图 + 多块全 clip），或池占内存超限？**
→ 构建是纯像素裁剪，`ImagePixels.rgba` 一次整图 + 逐字符 crop，量级 = 全块字符数 (~几十 ~ 几百)，每 crop 7KB → 构建 < 几十 ms，内存 < 几 MB。**若超 8MB**：仅保留 target 块 1 级 entry 或弃用池回退（§6 回退表）。风险低。

### 11.2 最可能被推翻的假设 + 回退
**假设**：*"同一块内所有字符的 `charRect.maxY` 对齐同一基线（`baselineOffset` 可靠）"*——这是拼贴垂直一致性的根基。
- **为何可能错**：OCR 的逐字框 `boundingBox(for: Range)` 对带下伸(downstroke, 如 `g/y/p`)或标点(`.`/`¥`/`)的字符会给出更高/更低或含 descender 的框，导致各字符 `maxY` 不齐；且 `-`、`¥`、`.` 的框语义与数字不同。
- **失效后果**：拼出来的数字串基线参差、标点上下偏移 → 视觉破绽，恰是 CEO 主诉（"字形不一致"）未覆盖的新露馅点。
- **回退/降级**：①基线改取 target 块内**纯数字字符（0-9）**的 `maxY` median，忽略标点字符框（标点单独用其框内相对偏移对齐数字基线）；②2 级异源字符仅与数字基线对齐；③最坏：若连数字框都无 → 该块回退 TextRenderer。**本版实现按①处理（数字对齐基线），②③作兜底**。

### 11.3 最可能被挑战的业务假设
*"改数字时，用户只关心数字本身；目标块背景与原图一致，字形自带背景无需二次处理"*。
- 若背景是**强渐变/纹理**，crop 自带背景与 patch 统一背景（style.background 模型）在字符边缘会有 1-2px 色差 → 接缝可见。
- **回退**：可后置"边界扩展填充 gap"严格化（用邻接 crop 边界色填满 advance）。本版接受 1px 级接缝（CEO 主诉是字形形状，非背景梯度）。已在 §6 标注。

---

## 12. 交付验收口径（对齐 QA/Dana）

- shuzi.jpg 改 `5.94`→`5.10` 等：`5`/`.` 逐像素与原块一致（1 级零失真）；`1` 若非池内 → 最近邻缩放 to 目标高（2 级）或近似（3 级）——**凡原图出现过的字符，拼贴结果与原文逐像素一致**（D-042 边界）。
- 含 CJK 块、exact 匹配文字、池未构建场景：**零回归**（走原 TextRenderer，行为与 alpha.8 一致）。
- 目标块 `0.00`→`0.10`：`0/.` 零失真、`1` 按可用源，拼贴 patch OCR 读回 "0.10"、方向/位置正确。
- 决策规则触发：无逐字框/无池/CJK/池外多数 → 回退 TextRenderer，无 crash。

---

## 附：文件改动清单

| 文件 | 动作 |
|------|------|
| `Sources/PxiuCore/Render/GlyphAtlas.swift` | 新增（数据模型 + build + 查询） |
| `Sources/PxiuCore/Render/GlyphCompositor.swift` | 新增（TextRendering 实现） |
| `Sources/PxiuCore/Render/TextRenderer.swift` | 修改：fillBackground 抽公共（供复用），其余不动 |
| `Sources/PxiuCore/Workflow/EditingWorkflow.swift` | 修改：open 后建 atlas；init/注入；process 选渲染器分支 |
| `Tests/PxiuCoreTests/GlyphCompositorTests.swift` | 新增（§7.1） |
| `Tests/PxiuCoreTests/GlyphAtlasTests.swift` | 新增（池构建/选择） |
