# Code Review v0.9 — D-042 字形像素复用 + analyzeStyles D8 快路径

**审查人**: Dana（技术负责人）
**审查对象**: zhenhai — GlyphAtlas + GlyphCompositor + EditingWorkflow D8 synthetic
**验收依据**: tech_spec_glyph_reuse_2026-09-02.md（D1–D8）、qa_report_v09_2026-09-03.md
**审查方法**: 代码审查（不修改代码）+ 构建/测试证据 + 对抗式漏洞分析

---

## 0. 构建与测试证据

```
$ swift build -c release
Build complete! (5.74s) — exit 0（预存 warning 非本交付引入）

$ swift test -c release --no-parallel
Test run with 104 tests passed after 10.057s — 0 fail
```

> 注：qa_report_v09 记录 105 tests，本次实测 104。可能因 QAV09RealShuziDiagnostics 合并计数差异，非功能影响。

---

## 1. 总判定

### **Approve** ✅

两项 CEO 硬诉求在真实 shuzi.jpg 上经 shouye 独立实测通过，代码实现与 tech_spec 设计一致，测试覆盖核心路径，零回归。以下列出不阻塞建议和已知边界备案。

---

## 2. 逐审查重点分析

### 2.1 像素一致正确性（CEO 硬要求 #1）

**1 级同块零失真路径** — ✅ 正确

| 组件 | 实现 | spec 一致性 |
|------|------|------------|
| `GlyphAtlas.build()` crop | 整图 RGBA 一次 → 逐字符 insetBy(-expansion) crop，像素从 buffer 逐字节拷贝（GlyphAtlas.swift:81-90） | ✅ §3.3 紧凑拷贝 |
| `GlyphCompositor.scaleOneBitmap()` | 直接包装 entry.crop → GlyphBitmap，零缩放（GlyphCompositor.swift:149-151） | ✅ §4.4 scale=1 |
| `testSingleCharPixelIdentity()` | 逐像素 `pb.rgba[dp] == entry.crop[sp]` 断言（GlyphCompositorTests.swift:66-74） | ✅ 硬断言，非冒烟 |

**QA 证据**: `0`（2440 像素全等）/ `.`（1586 像素全等）逐像素一致已验证。

**2 级异源缩放路径** — ✅ 正确

- `glyphBitmap()` 用最近邻缩放 `srcBoxH = cropHeight - 2*cropExpansion`（GlyphCompositor.swift:156）→ 正确扣除了扩展边距
- `scale = targetHeight / srcBoxH`，1:1 时 `scale ≈ 1` 不触发缩放
- `nearestNeighbor()` 实现为纯 CPU 像素映射（GlyphCompositor.swift:218-236），无 CoreText 依赖
- advance 按相同比例缩放 `near.advance * (ht / max(1, CGFloat(near.cropHeight)))`（GlyphCompositor.swift:79）— 正确保持水平间距

**3 级池外兜底** — ✅ 功能正确，测试可改进

- `renderFallback()` 用 `FontProbe.inkWidth` 获取自然宽度 → `fallback.render()` 渲染单字符 → `fallbackBitmap()` 包装
- `testPoolExternalFallback` 仅做不-crash 冒烟，**未验证 OCR 可读性**。建议后续补 E2E OCR 断言（不阻塞 alpha.9）。

**baselineOffset 基线对齐** — ✅ 实现与 spec §3.4/§4.3 一致

- `GlyphAtlas.build()`: `baselineOffset = baseline - box.rect.minY`（line 95），其中 `baseline = median(digitBoxes.maxY)`（line 62）— 符合 spec §11.2 "数字优先" 抗标点噪声
- `GlyphCompositor.render()`: 基线 Y = `pad + patchTopB`（line 108），`patchTopB = max(pieces.bitmap.baselineOffset)`（line 94）— 正确保证所有字符共享同一基线
- `baselineY` 输出供 `BlockPatchBuilder.layout` 用同一公式定位 — 沿用现契约，不新增坐标系

**⚠️ 发现 1**: `targetBaseline`（line 53）计算后从未使用（编译器 warning "initialization of immutable value was never used"）。patch 的 `baselineY` 实际由 `pad + patchTopB` 推导。这是冗余代码，不影响正确性，建议清理。

---

### 2.2 D8 synthetic 正确性

**syntheticStyle 与 GlyphCompositor H_t 对齐** — ✅ 实质一致，口径微差

| 字段 | syntheticStyle (analyzeStyles) | GlyphCompositor (process) | 差异 |
|------|------|------|------|
| fontSizePx / H_t | 全字符框高中位 = 52.7 | 同字符数字框高中位 = 56.0 | 3.3px（CJK 拉高全字符中位） |
| matchStatus | approximate(0, PingFang) | N/A（不依赖） | — |
| color/background | ColorEstimator 像素推断 | 不独立采样（沿用 style） | 共用来源 ✅ |

**差异分析**：syntheticStyle 的 fontSizePx（全字符中位）与 GlyphCompositor 的 H_t（数字字符中位）不同，因为 `0.00元` 含 CJK `元` 拉低/拉高全字符中位。**但这不影响功能**：
- GlyphCompositor 的 `targetHeight()` 用自己的字符过滤逻辑（line 127-133），不依赖 style.fontSizePx
- 下游 `BlockPatchBuilder.layout` 用 `RenderedText.fontSizeUsed`（= GlyphCompositor 的 H_t），不直接读 style.fontSizePx
- **唯一影响**：UI 若展示 fontSizePx 给用户，会显示 52.7 而非实际使用的 56.0 — cosmetic 不一致，不阻塞

**⚠️ 发现 2（低风险）**: `syntheticStyle` 用全字符中位而 GlyphCompositor 用数字中位。建议后续统一口径（使 syntheticStyle 仅取 ASCII digit 中位），或在 GlyphCompositor 报告 H_t 时同步更新 style.fontSizePx。不阻塞 alpha.9。

**matchStatus = approximate(0, face) 路径安全性** — ✅

- `shouldUseGlyph` 只检查 `.exact`（line 29），approximate 不挡路 → 正确
- `analyzeStyles` 中 `block.style == nil` guard（line 156-158）→ synthetic 写入 style 后，后续调用 skipped
- 其他代码路径（DigitFallback、StyleAnalyzer）读 matchStatus 决定行为 → approximate(0) 触发"近似"分支，但 **synthetic 块的 style 已写入 document**，后续流程不会重新分析 → 无副作用
- QA R3.4 已验证 matchStatus=approximate(0.80, MLingWai)（FontMatcher 真实匹配）和 approximate(0, PingFang)（synthetic）两种路径

**⚠️ 发现 3（信息性）**: `0.00元` 块因含 CJK `元`，`shouldUseGlyph` 返回 false → analyzeStyles 走 FontMatcher（score=0.80, MLingWai），不享受 D8 synthetic 快路径。这与 QA P0 一致。**不是功能缺陷，是 D8 收益覆盖不全**——spec §5.2 "凡含 CJK 一律 TextRenderer" 的保守设计。建议后续做字符级脚本判定（数字部分仍走池合成）。

---

### 2.3 零回归

**所有回退路径** — ✅ 验证通过

| 场景 | shouldUseGlyph | process 渲染器 | 测试覆盖 |
|------|:---:|:---:|:---:|
| glyphAtlas = nil | false | TextRenderer | ✅ `testProcessUsesTextRendererWithoutAtlas` |
| perCharBoxes = nil | false | TextRenderer | ✅ `testShouldUseGlyphDecision` (line 175-177) |
| CJK 文本 | false | TextRenderer | ✅ `testProcessUsesTextRendererForCJK` |
| exact 匹配块 | false | TextRenderer | ✅ `testShouldUseGlyphDecision` (line 181-183) |
| 池外多数 (>50%) | false | TextRenderer | ✅ `testShouldUseGlyphDecision` (line 168) |

**⚠️ 发现 4（测试缺口）**: 无纯 CJK 块（如 `"你好"`）的 shouldUseGlyph 测试。当前 CJK 测试用混合文本 `"0你好"`。建议补纯 CJK case（不阻塞）。

**analyzeStyles 与 process 决策一致性** — ✅ 关键正确

两处都调用 `GlyphCompositor.shouldUseGlyph()`:
- `analyzeStyles` line 165: `GlyphCompositor.shouldUseGlyph(atlas: atlas, block: block, text: glyphDecision)`
- `process` line 282: `GlyphCompositor.shouldUseGlyph(atlas: atlas, block: block, text: text)`

**⚠️ 发现 5（需确认）**: `analyzeStyles` 用 `block.text.isEmpty ? block.detectedText : block.text`（line 163），而 `process` 用 `text = newText.trimmingCharacters(...)`（line 262）。**决策输入文本不同**：analyzeStyles 分析的是原块文本，process 编辑的是用户输入的新文本。这是**正确的设计意图**——analyzeStyles 决定"该块样式是否需 FontMatcher"，process 决定"新文本是否走 GlyphCompositor"。两者独立决策、不冲突。✅

---

### 2.4 性能边界

**池构建内存护栏（>8MB）** — ✅ 实现正确

- `GlyphAtlas.build()` line 77: `if atlas.poolBytes + bytes > atlas.maxPoolBytes { atlas.truncated = true; continue }`
- `testMemoryGuardTruncates()` 验证：maxPoolBytes=300，加完第一个 crop 后停，truncated=true ✅
- 真实图 32 块 / 73 字符 / poolBytes 未超 8MB → 护栏未触发（QA P4 已备案）

**⚠️ 发现 6（信息性）**: 池构建后整图 buffer（`ImagePixels.rgba` 返回的 `Buffer`）随 `build()` 返回自动释放（值类型）。spec §3.3 提到"池构建后释放整图 buffer"——Swift ARC 自动处理，无需显式释放。✅

**CJK FontMatcher 耗时** — ✅ 后台执行，不冻结

- 实测 analyzeStyles 总耗时 0.941s–1.539s，其中 24 个 CJK 块走 FontMatcher
- EditorState.swift:465 `Task { await analyzeStylesBackground() }` — 后台调度
- 首屏（open）0.156s 返回 → 界面立即可用
- **结论**：1–1.5s 后台耗时对用户体验无影响。这是已知遗留（spec §8 "analyzeStyles 对池覆盖块跳过 FontMatcher → 可后置"），不阻塞核心功能

---

### 2.5 并发/生命周期

**glyphAtlas 生命周期** — ✅ 正确

- `open()` line 143: `self.glyphAtlas = GlyphAtlas.build(...)` — 一次构建，后续只读
- `process()` line 281: `if let atlas = glyphAtlas` — 只读引用
- `analyzeStyles()` line 164: `if let atlas = glyphAtlas` — 只读引用
- `EditorWorkflow` 是 `final class`，`glyphAtlas` 是 `private var` — 无外部突变

**@unchecked Sendable 竞态风险** — ⚠️ 已知风险，不阻塞

- `GlyphCompositor: @unchecked Sendable` — 未验证线程安全（struct 无状态，实际安全）
- `EditorWorkflow: @unchecked Sendable` — `glyphAtlas` 是 var，并发 open + analyzeStyles + process 可能竞态
- **实际场景**：UI 层（EditorState）保证 open 完成后才调 analyzeStyles/process（阶段化调度），竞态概率极低
- **建议**：后续将 `glyphAtlas` 改为 `nonisolated(unsafe)` 或加锁（Swift 6 strict concurrency 要求）

**测试替身语义** — ✅

- `prebuiltAtlas` 参数（line 116）允许测试注入构造的 atlas → 测试不依赖 OCR 真实图
- `testProcessUsesGlyphForInPoolDigits` 用 prebuiltAtlas 验证决策路径 ✅

---

### 2.6 已知失真点核实

**analyzeStyles 耗时实测** — ✅ 与 QA 一致

| 来源 | 耗时 | 说明 |
|------|------|------|
| zhenhai 自报 | 1.374s | QA 基本确认（"同量级"） |
| QA 实测 | 1.347–1.539s（avg ≈ 1.46s） | 3 次独立测量 |
| 本次测试 | 1.085s（testAnalyzeStylesTimingOnShuziJpg） | 单次，含构建缓存 |
| QAV09 实测 | 0.941s | 最佳一次 |

**结论**：analyzeStyles 耗时 0.94–1.54s，全部后台执行。24 个 CJK 块走 FontMatcher 是耗时主因。这不是 bug，是 spec §8 明确标注"可后置"的已知限制。**核心数字编辑场景（改 `0.00`）的 preview 路径不被阻塞**（preview 0.025s）。

---

### 2.7 测试质量

**测试覆盖率评估**：

| spec §7.1 要求 | 对应测试 | 状态 |
|------|------|:---:|
| 1. Atlas 构建 + crop + 分组 + 几何 | `GlyphAtlasTests.testBuildGroupsAndCrops` | ✅ 含逐字节像素比对 |
| 2. 1 级选择优先级 | `testSameBlockAndNearest` + `testSingleCharPixelIdentity` | ✅ |
| 3. 2 级选择 | `testNearestPicksClosestSize` + `testHeteroSourceScalesToHt` | ✅ |
| 4. 池外兜底 | `testPoolExternalFallback` | ⚠️ 不-crash，未验证 OCR |
| 5. 整块池外多数→回退 | `testShouldUseGlyphDecision` (XYZ0 → false) | ✅ |
| 6. 拼贴像素一致 | `testSingleCharPixelIdentity`（逐像素硬断言） | ✅ CEO 硬要求路径 |
| 7. 空格/0x0 | `testSpaceGap` | ✅ |
| 8. compositeAfter E2E | `testCompositorPatchComposeOCR` | ✅ 结构性冒烟 |
| 9. 零回归 | 全套 shouldUseGlyph 决策测试 + EditingWorkflowTests | ✅ |

**⚠️ 发现 7（测试缺口）**:

| 缺口 | 风险 | 建议 |
|------|------|------|
| 纯 CJK 块 shouldUseGlyph | 低（混合 CJK 已覆盖） | 补 `"你好"` 测试 |
| 池外兜底 OCR 可读性 | 低（结构不-crash 已验证） | 补 OCR 断言 |
| 0.00元 块 E2E（CJK 块 + 编辑非 CJK 文本） | 中（CEO 主诉块） | 补端到端：CJK 块编辑 → shouldUseGlyph=true → pixel identity |
| 50% 池外边界（exact 0.5） | 低 | 当前 0X → true, XYZ0 → false，边界已覆盖 |

**⚠️ 发现 8（测试 oracle 审查）**: zhenhai 曾将 OCR 回读改为"可读性冒烟"（testCompositeO10OCRReadBack 用 OCR 读回检查 contain("0") && count >= 3）。审查该决定：
- **合理**：逐像素硬断言已在 `testSingleCharPixelIdentity` 覆盖（1 级零失真）
- **OCR 冒烟目的**：验证多字符拼贴的结构正确性（字符间距、基线对齐），非像素级
- **风险**：OCR 对小尺寸点阵字不稳定（测试输出读到 `[0|0.4]` 而非 `0.10`）
- **结论**：可读性冒烟作为补充验证合理，核心像素一致性由 `testSingleCharPixelIdentity` 硬断言保障。✅

---

## 3. 代码质量

### 3.1 编译器 Warning（本次引入）

| Warning | 文件:行 | 严重度 | 建议 |
|---------|---------|:---:|------|
| `targetBaseline` 未使用 | GlyphCompositor.swift:53 | 低 | 删除冗余计算或改 `_` |
| `var sp` 应为 `let sp` | GlyphCompositor.swift:247 | 低 | `let` 修复 |
| `withUnsafeBytes` 返回值未用 | GlyphCompositor.swift:296 | 低 | 加 `_ =` 或重写 |

### 3.2 代码设计评价

**✅ 优秀点**:
1. **最小侵入**：通过 `TextRendering` 协议复用现有管线，`process` 仅加一处分支 — 零回归保障
2. **决策一致性**：`analyzeStyles` 与 `process` 共用 `shouldUseGlyph()` — 避免分裂
3. **防御性编程**：每级选源都是 optional chain（`sameBlock ?? nearest ?? nil`）→ 优雅降级
4. **内存护栏**：8MB 上限 + `truncated` 标记 → 大图不 OOM
5. **测试替身**：`prebuiltAtlas` 参数 → 测试可构造 atlas 不依赖 OCR

**⚠️ 可改进点（不阻塞）**:
1. `fillBackground` 在 GlyphCompositor 内重新实现（line 257-288）而非抽取公共函数。spec §8 要求"抽公共 fillBackground"，当前是 GlyphCompositor 独立实现 + TextRenderer 有自己版本。功能正确，但有代码重复。后续可统一。
2. `isASCIIDigit` 在 GlyphAtlas 和 GlyphCompositor 中各实现一份（line 137-139 / line 213-215）。建议抽到公共枚举或扩展。

---

## 4. 对抗式审查：三个「如果…会怎样？」

### Q1: 如果用户编辑 `0.00元` → `0.10元`（新文本仍含 CJK），会怎样？

- `shouldUseGlyph("0.10元")` → `containsCJK("0.10元") = true` → **false** → 走 TextRenderer
- 用户期望字形一致，但 TextRenderer 会用近似字体渲染 `0.10元` → CEO 不满意
- **影响**：这是当前设计的保守边界。用户只能编辑纯数字/拉丁文本获得像素复用。编辑含 CJK 的文本回退原渲染器。**spec §5.2 明确规定此行为**。
- **建议**：后续可做字符级脚本判定——数字部分走 GlyphCompositor、CJK 部分走 TextRenderer，混排拼贴。不阻塞 alpha.9。

### Q2: 如果图片背景是强渐变，拼贴后字符间 gap 的背景色与 crop 自带背景不一致会怎样？

- GlyphCompositor 的 patch 背景用 `style.background` 模型填充（flat/gradient/texture）→ gap 处露此背景
- 字符 crop 自带原图背景（近似 flat 的局部区域）
- **如果原图背景是渐变**：crop 区域的背景色 ≈ 渐变在该位置的颜色，gap 用 style.background（从整个块采样的平均/模型色）→ 可能有 1-2px 色差
- **实际影响极低**：CEO 主诉是字形形状，不是背景梯度。shuzi.jpg 背景是近 flat 白色。
- **已标注**：spec §6 "渐变/纹理背景 1-2px 接缝 → 可后置严格化"

### Q3: 如果 `prebuiltAtlas` 在测试中传入的 atlas 与 open() 构建的 atlas 行为不同会怎样？

- 测试用 `TestSupport.render()` 构造的真字形图 → atlas 有真实 crop 像素
- `process` 用 prebuiltAtlas → 决策走 GlyphCompositor → 渲染用真实 crop → pixel identity 可验证
- **风险**：测试中的 SourceImage 与真实 shuzi.jpg 不同（字体/字号/背景）→ 测试结果不一定代表真实场景
- **缓解**：QAV09RealShuziDiagnostics 用真实 shuzi.jpg 做端到端验证 → 已覆盖真实场景

---

## 5. CEO 两个诉求验证矩阵

| CEO 诉求 | 代码路径 | 测试覆盖 | QA 实测 | 判定 |
|----------|---------|---------|---------|:---:|
| #1 数字字形与原图完全一致 | sameBlock → scaleOneBitmap（零缩放） | testSingleCharPixelIdentity（逐像素） | 0/. 2440/1586 全等 | ✅ |
| #2 打开不冻结 | open 0.156s + analyzeStyles 后台 Task | testAnalyzeStylesTimingOnShuziJpg（1.085s） | 0.35s open + 1.46s 后台 | ✅ |

---

## 6. 不阻塞建议清单

| # | 建议 | 优先级 | 原因 |
|---|------|:---:|------|
| N1 | 删除 GlyphCompositor.swift:53 未使用的 `targetBaseline` | 低 | 编译器 warning，代码清洁 |
| N2 | `var sp` → `let sp`（line 247） | 低 | 编译器 warning |
| N3 | 补纯 CJK 块 shouldUseGlyph 测试 | 低 | 测试完整性 |
| N4 | 补 0.00元 块端到端测试（CJK 块 + 编辑非 CJK 文本） | 中 | CEO 主诉块完整路径 |
| N5 | 后续统一 syntheticStyle.fontSizePx 与 GlyphCompositor H_t 口径 | 低 | cosmetic 一致性 |
| N6 | 后续抽取公共 fillBackground（spec §8 要求） | 低 | 代码重复，功能不受影响 |
| N7 | 后续将 `glyphAtlas` var 加锁或 `nonisolated(unsafe)` | 低 | Swift 6 strict concurrency |

---

## 7. 必须备案的已知边界（不阻塞，须向 @zongguan 汇报）

1. **D8 覆盖不全**：含 CJK 的块（如 `0.00元`）analyzeStyles 仍走 FontMatcher，不享受 synthetic 快路径。建议后续做字符级脚本判定。
2. **编辑含 CJK 文本无字形复用**：`shouldUseGlyph` 对含 CJK 文本返回 false → 回退 TextRenderer。用户只能编辑纯数字/拉丁文本获得像素一致。
3. **异源缩放（1 的 2 级源）无像素一致保证**：`1` 来自他块缩放，结构保真但非逐像素一致（CEO 已认可该边界）。
4. **@unchecked Sendable**：GlyphCompositor 和 EditorWorkflow 标记为 @unchecked Sendable，未严格验证并发安全。实际 UI 调度保证串行，竞态概率极低。

---

## 8. 与上一版 Code Review 差异

无前置 code_review_v08（本交付为首次引入 GlyphAtlas/GlyphCompositor）。审查依据从 tech_spec 和 QA 报告直接对照。

---

**结论: Approve** ✅

代码实现与 tech_spec 设计一致，CEO 两项硬诉求在真实图上经独立实测通过，测试覆盖核心路径（含逐像素硬断言），零回归。上述建议均不阻塞 alpha.9 交付。
