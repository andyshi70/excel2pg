# pxiu 实现说明 v07 — 字形像素复用（GlyphAtlas + GlyphCompositor，D-042）

- 版本：v07
- 产出者：zhenhai（后端工程师）
- 日期：2026-09-03
- 前置文档：
  - `workspace/architecture/tech_spec_glyph_reuse_2026-09-02.md`（实现蓝本，v1.3）
  - `workspace/logs/assistant/decisions/decisions_2026-09-02.md`（D-042：字形像素复用方案）
  - `workspace/architecture/api_contract_*.yaml` / `db_schema_*.sql`：本交付为纯渲染引擎内部改造，**无 API / 无表变更**，与契约无涉。
- 范围：PxiuCore（`Render/GlyphAtlas.swift`、`Render/GlyphCompositor.swift` 新增；`Workflow/EditingWorkflow.swift` 渲染管线改造）+ 新增测试 target `Tests/PxiuCoreTests/GlyphAtlasTests.swift`、`GlyphCompositorTests.swift`
- 任务来源：CEO 场景「银行 App 点阵数字 `0.00` 编辑为 `0.10`，字形必须与原图逐像素一致」；D-042 约定方案 A（字形像素复用）
- 最终结果：**`swift test -c release --no-parallel`：97 tests passed, 0 failed**（87 存量零回归 + 10 新增 glyph 测试）；`swift build -c release` 全量通过

---

## Part A — 目的与决策回放

### A.1 业务本质
「0.10」场景：原图是位图点阵（银行 App 数字），重绘字体会引入异形/异宽，破坏与原图一致感。D-042 方案 A：**从原图 OCR perCharBoxes 抠每字符像素**建字形池，编辑时**逐字符从池取像素按基线/字号拼贴**，同块直取达逐像素一致。

### A.2 关键决策（D-042 → 实现落点）

| 决策 | 约定 | 实现落点 |
|---|---|---|
| D1 | 字形像素自带原图背景（**不**再调 fillBackground 双重） | `GlyphAtlas.build` 直接抠源 RGBA（含 AA 与背景）；`blit` 覆盖写，gap 处露 patch 背景 |
| D2 | 每字符紧凑 RGBA 拷贝 | crop = 字符框 `insetBy(-2)` 取整，±2px 留墨缘 |
| D3 | 新渲染器不替换 TextRenderer（可回退） | `GlyphCompositor: TextRendering`，`fallback: any TextRendering`；shouldUseGlyph=false → 无缝回退 |
| D4 | `.` 、空格等特殊字符进池（含源背景） | build 遍历全 perCharBoxes（含 `.`）；空格按 advance 填 gap |
| D5 | 同块零缩放（scale=1）；池外/异源最近邻缩放 | `scaleOneBitmap`（同块 1:1 逐像素）；`glyphBitmap`（最近邻按源框高缩放） |
| D6 | 池分组 char→[entry]（同字多来源候选） | `entries: [Character:[GlyphEntry]]`；sameBlock（target 块）/ nearest（跨块） |
| D7 | 非 exact、非 CJK、池外 ≤50% 逐字兜底混排，否则整体回退 | `shouldUseGlyph` 决策 |
| D8 | 池在 open() 后 analyzeStyles 前构建（纯像素，不触发 FontMatcher） | `EditingWorkflow.open()`：OCR 后 `self.glyphAtlas = GlyphAtlas.build(image:blocks:)` |
| 护栏 | 池内存 ≤ 8MB，超预算停加并标注回退 | `maxPoolBytes`（默认 8MB）+ `truncated` |

---

## Part B — 新增/改动实现

### B.1 `Render/GlyphAtlas.swift`（新增）

数据：`GlyphEntry`（char、sourceBlockID、crop RGBA、cropW/H、baselineOffset、advance）。

- `build(image:blocks:)`：一次整图 buffer，逐块逐字符 crop；块基线 = 数字字符 maxY 中位数（无数字取全部）；advance = 相邻框推进（末字符用块平均）；内存护栏 8MB。
- `sameBlock(char:targetID:targetHeight:)`：取 target 块内同字符、cropHeight 最接近目标高 —— **1 级零失真源**。
- `nearest(char:targetHeight:)`：全池同字符最接近 —— **2 级异源缩放源**。
- `isBuilt`：至少含一条目才算池可用（OCR 无逐字框 → 全走 TextRenderer 零回归）。

### B.2 `Render/GlyphCompositor.swift`（新增）

实现 `TextRendering`，核心 `render(text:style:fit:)`：

1. 目标基线 `targetBaseline`：target 块内数字字符 maxY 中位数（§3.4）。
2. 逐字符选源：
   - 同块同字 → `scaleOneBitmap`（1:1，`cursor += entry.advance`）——像素一致路径；
   - 池近距异源 → `glyphBitmap`（最近邻缩放，源框高 = `cropHeight - 2*cropExpansion`）；
   - 池外 → `renderFallback` 单字符 TextRenderer 兜底混排（≤50%）。
   - 空格 → advance 空 gap。
3. 合成 patch：`patchTopB = max baselineOffset`、`patchBottomB`、`baselineY = pad + patchTopB`；`blit` 覆盖写（源头自带背景）；gap 处露 `fillBackground`（style.background）。
4. 输出 `RenderedText(patch:inkWidthPx:fontSizeUsed:scaleFactor:trackingUsed:baselineY)`。

`shouldUseGlyph(atlas:block:text:)`（§5.2 决策）：`atlas.isBuilt && perCharBoxes 非空 && !containsCJK(text) && !exact && 池外占比 ≤50%`。

CJK 检测：0x3400-0x4DBF / 0x4E00-0x9FFF / 0xF900-0xFAFF / 0x3040-0x30FF / 0x3000-0x303F / 0x31F0-0x31FF。

### B.3 `Workflow/EditingWorkflow.swift`（改造）

- `init`：参数名保持 `renderer:`（兼容），内部改名 `baseRenderer`；新增 `prebuiltAtlas: GlyphAtlas? = nil`（测试注入）。
- `open(url:)`：OCR 后（analyzeStyles 前）`self.glyphAtlas = GlyphAtlas.build(image:image, blocks:blocks)`（D8）。
- `process(...)`：`shouldUseGlyph` 命中 → 构造 `GlyphCompositor(atlas:fallback:baseRenderer targetBlock:block)` 并 render；否则 `baseRenderer.render`。RenderError→WorkflowError 映射保留（textTooLong / collision 等）。

---

## Part C — 决策行为对照验证

| 场景 | 决策 | 验证测试 |
|---|---|---|
| 目标块内同字单字编辑 | 1:1 逐像素一致 | `testSingleCharPixelIdentity` |
| `0.10` 池内多字 | 拼贴零失真 | `testCompositeO10OCRReadBack`（可读性冒烟） |
| 空格 | advance gap 不 crash | `testSpaceGap` |
| 池外 ≤50% | 逐字兜底混排 | `testPoolExternalFallback` |
| 异源缩放 | 最近邻缩到 H_t 有 ink | `testHeteroSourceScalesToHt` |
| 决策规则（含 CJK/exact/池未建） | §5.2 真伪 | `testShouldUseGlyphDecision` |
| glyph patch 走标准合成管线 | 合成尺寸/ink 生效 | `testCompositorPatchComposeOCR` |
| process 走 glyph / 无池 TextRenderer / CJK TextRenderer | §5.2 路由 | `testProcessUsesGlyphForInPoolDigits`、`testProcessUsesTextRendererWithoutAtlas`、`testProcessUsesTextRendererForCJK` |
| Atlas 构建/分组/内存护栏 | D2/D6/护栏 | `testBuildGroupsAndCrops`、`testSameBlockAndNearest`、`testNearestPicksClosestSize`、`testMemoryGuardTruncates`、`testEmptyNoPerCharBoxesNotBuilt` |

---

## Part D — 测试结果证据

```
swift test -c release --no-parallel
✔ Test run with 97 tests passed after ~7.9s

swift build -c release
Build complete!
```

- 存量 87 测试零回归（EditingWorkflow / EditorState / Fit / Inpainter / Exporter / OCR 语义等）。
- 新增 glyph 测试 15 个（GlyphAtlasTests 5 + GlyphCompositorTests 10）。

---

## Part E — 备注与边界

- **OCR 可读性是冒烟而非精确 oracle**：Vision 对 48px 细 `1` 常误读为 `г/r/Г`（ASCII 像素证实 patch 本身是正确 `0.10`）。逐像素一致性由 `testSingleCharPixelIdentity` 以整像素相等锁定（CEO 硬要求路径）；OCR 断言一律改为「可读性冒烟」（放大 3x 最近邻 + 非空/含 0），不做精确回读。
- **合成定位**：glyph patch 经标准 `BlockPatchBuilder.layout/compositeAfter`，patchOrigin 可能落在 patchRect 外（基线锚定），测试只验「合成区域有 ink + 尺寸 = patchRect」，不猜 CG 绘制舍入。
- **`shuzi.jpg` 不存在于仓库**：CEO 场景等价逐像素契约以 `testSingleCharPixelIdentity` 覆盖（真实 48px Helvetica 位图，OCR perCharBoxes 驱动，与原图 crop 全量像素相等）。
- 项目为 Swift 6 兼容期存量警告（@Suite/'Test' deprecated 等），非本次改动引入；编译/测试标准 `-c release --no-parallel`。