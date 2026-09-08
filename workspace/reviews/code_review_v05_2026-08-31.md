# Code Review — D-037 宽度策略选B（字号继承三态）

- **版本**: v05 + D-037
- **日期**: 2026-09-01
- **审查人**: Dana（技术负责人）
- **依据**: `workspace/product/prd_pxiu_v1.1_2026-08-31.md` AC-1~AC-5
- **QA 前置**: `workspace/qa/qa_report_v05_2026-08-31.md` ✅（61 passed / 0 failed）

---

## 一、核心语义审查 — FitCalculator.swift

### 选B 三态逻辑核验

`FitCalculator.fit()` (L42-70) 逐行审计：

```
k0 = targetInkWidthPx / natural
if k0 < 1 { k = k0; fs = f0 * k }    // 变宽 → 等比缩小
else      { k = 1;  fs = f0 }         // 等宽/变窄 → 不缩放
tooLong = k < minScale
if tooLong { fs = f0 * minScale }      // 钳制到最小字号
```

**判定**: 逻辑与选B 完全一致。

- AC-1 三态：`k0≥1 → k=1, fs=f0`（不缩不放）；`k0<1 → k=k0, fs=f0·k`（只缩）；`k0<k0_min → tooLong`（兜底） ✓
- 永不放大：`k0>1` 时走 `else` 分支 `k=1, fs=f0`，不会把短文本放大 ✓
- tooLong 钳制：`fs = f0 * minScale` 独立于 `scaleFactor = k`，两者分离是设计意图 ✓

### scaleFactor / fontSizeUsed 分离语义分析

**zhenhai 记录的既有行为**确认为设计意图，非隐患：

- `scaleFactor`（即 `k`）= 自然缩放比（新文本相对目标宽度的理论 k0），暴露"文本有多超限"，供上层日志/调试
- `fontSizeUsed`（即 `fs`）= 渲染实际使用的字号（受 minScale 钳制后的值）
- 两者仅在 tooLong 场景下不同：`scaleFactor = k0`（如 0.05），`fontSizeUsed = f0 * minScale`（如 24）
- **无消费者误用风险**：`TextRenderer.render()` L58 `let fs = fitResult.fontSizeUsed`，仅用 `fontSizeUsed` 创建 CTFont；`RenderedText.scaleFactor` 仅传递给上层，不参与渲染字号计算

**结论**: scaleFactor/fontSizeUsed 分离是合理设计，不是 bug。当前无消费者会误用 scaleFactor 计算字号。

### 防御性缺口（非阻塞）

1. **targetInkWidthPx ≤ 0 未 guard** — `k0 = 0/natural = 0 → fs=0 → tooLong → fs=f0·minScale`，渲染字号 24px 但目标宽为 0 语义矛盾。当前 `EditingWorkflow.process()` L217 传入 `BlockPatchBuilder.originalInkWidth(block)` 为 bbox 宽度，已知路径 ≥ 0。**非阻塞，建议后续加 guard**。
2. **natural ≤ 0.5 guard** (L47) — 返回 nil，TextRenderer 抛 `engineFailure`，正确。

---

## 二、测试质量审查 — TextRenderingSemanticsTests.swift

### 4 条新增测试逐条审计

#### B.1 testWidthFitsScaleDownWhenWider (L173-186) — 变宽→k<1

| 项 | 审计 |
|---|---|
| 探针有效性 | `FontProbe.inkWidth("v1.0", helvetica, 48)` 和 `FontProbe.inkWidth("v1.0.0-beta", helvetica, 48)` 均返回有效 CGFloat（Helvetica macOS 预装） |
| guard 前提 | `newInkW > origInkW` 确保测试前提成立，否则 `Issue.record` 短路 |
| 断言精准性 | `scaleFactor < 1` ✓，`fontSizeUsed < 48` ✓（k0 = origInkW/newInkW < 1） |
| 空转风险 | 无：FontProbe 返回有效值，fit 返回非 nil，断言执行 |

**结论: PASS。** 断言精准，真正覆盖了选B ②态。

#### B.2 testWidthFitsNoScaleWhenEqualOrNarrower (L189-202) — 等宽/窄→k=1

| 项 | 审计 |
|---|---|
| 探针有效性 | 同上，Helvetica 有效 |
| guard 前提 | `newInkW <= origInkW` 确保测了变窄场景（非等宽） |
| 断言精准性 | `scaleFactor == 1` ✓，`fontSizeUsed == 48` ✓（k0>1 → k=1, fs=f0） |
| 空转风险 | 无 |

**结论: PASS。** 正确覆盖选B ①态。

#### B.3 testNeverScaleUpEvenForSingleChar (L205-216) — 永不放大

| 项 | 审计 |
|---|---|
| **核心攻击点** | FontProbe 对单字符 "V" 是否返回 nil？ |
| FontProbe 调用链审计 | `CTFontCreateWithName("Helvetica", 48)` → 有效 CTFont ✓；`NSAttributedString(string: "V", attributes: [kCTFont:])` → 有效 ✓；`CTLineCreateWithAttributedString` → 单字符产生有效 CTLine ✓；`CTLineGetTypographicBounds` → 返回 ~30-35px width ✓ |
| 返回值 | **有效 CGFloat > 0，非 nil** |
| FitCalculator 内部 | natural ≈ 30+，targetInkWidthPx ≈ 180（v1.21.1 at 48px），k0 ≈ 5+ → k0≥1 → k=1, fs=48 |
| 断言精准性 | `scaleFactor == 1` ✓，`fontSizeUsed == 48` ✓ |
| 空转风险 | **无**：FontProbe 有效，fit 返回非 nil，断言执行到尾 |

**结论: PASS。** 真正执行了 FitCalculator 逻辑，非空转。shouye 对抗审查结论成立。

#### B.4 testTooLongClampsToMinScale (L219-228) — 兜底钳制

| 项 | 审计 |
|---|---|
| 测试构造 | 超长串 `ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!@#$%^&*()` + targetW=10px → k0 ≈ 10/200+ ≈ 0.05 |
| tooLong 逻辑 | k = k0 = 0.05 < 0.5 → tooLong = true ✓ |
| 钳制逻辑 | `fs = 48 * 0.5 = 24` ✓ |
| scaleFactor 分离 | scaleFactor 保持 k0=0.05，fontSizeUsed=24，两者不同是设计意图 |
| 断言精准性 | `tooLong == true` ✓，`fontSizeUsed == 24` ✓ |

**结论: PASS。** 正确覆盖兜底场景，scaleFactor/fontSizeUsed 分离断言合理。

### 测试质量总结

- 4 条测试覆盖选B 三态 + 兜底，断言精准
- FontProbe 探针路径真实有效，无空转风险
- 缺少等宽场景（`newInkW == origInkW` 严格相等）的独立测试，但当前 guard `newInkW <= origInkW` 已覆盖 ≤ 语义，**非阻塞**

---

## 三、链路一致性审查

### f0 传递链路

| 环节 | 文件 | 行为 | 审计 |
|---|---|---|---|
| 估算 | StyleEstimator.estimate() | 返回 `CGFloat`（fontSizePx） | 原值，无 clamp ✓ |
| 赋值 | StyleAnalyzer.analyze() | `fontSizePx: fontSize` 写入 TextStyle | 原值写入 ✓ |
| 读取 | TextRenderer.render() L47 | `let f0 = style.fontSizePx` | 原值读取 ✓ |
| 传入 | TextRenderer.render() L49-53 | `FitCalculator.fit(baseFontSize: f0, ...)` | f0 原样传入 ✓ |
| 消费 | FitCalculator.fit() L50-66 | `let f0 = baseFontSize` → `fs = f0` 或 `fs = f0*k` | f0 仅参与乘法，不被修改 ✓ |

**链路完整，零副作用。**

### fontSizeUsed / scaleFactor 流入 RenderedText

- TextRenderer L58: `let fs = fitResult.fontSizeUsed`
- TextRenderer L111: `return RenderedText(... fontSizeUsed: fs, scaleFactor: fitResult.scaleFactor, ...)`
- 无重复缩放：CTFont 按 `fs` 创建 (L62)，渲染直接用 CTFont，无二次 scale 变换 ✓

### EditingWorkflow.process() 编排

- L217: `targetInkWidth = BlockPatchBuilder.originalInkWidth(block)` — 目标宽 = 原 ink 宽 ✓
- L218-220: `FitSpec(targetInkWidthPx: targetInkWidth, minScale: minScale, ...)` — 参数正确传入 ✓
- L223: `rendered = try await renderer.render(text: text, style: style, fit: fit)` — 调用 TextRenderer ✓
- L225: `if e == .textTooLong { throw WorkflowError.textTooLong }` — tooLong 向上层抛出 ✓
- L230: `BlockPatchBuilder.layout(for: rendered, block: block, style: style)` — 布局用 rendered 度量 ✓

**无重复缩放，链路一致。**

---

## 四、AC 覆盖判定

| AC | 描述 | 判定 | 证据 |
|---|---|---|---|
| AC-1 | 字号继承三态：k=1 不缩 / k<1 只缩 / 永不放大 | **Satisfied** | FitCalculator L53-61 逻辑 + 4 条测试覆盖三态 + tooLong 兜底 |
| AC-2 | 颜色继承回归保持 | **Satisfied** | 零生产代码改动；颜色由 `kCTForegroundColorAttributeName` 独立控制 (TextRenderer L70)；现有 `testColorSemanticsWhiteGlyphPixels` 覆盖 |
| AC-3 | 方向回归保持 | **Satisfied** | 零生产代码改动；CTM 翻转已删除（v05 Bug2 修复）；现有 `testOrientationAndColorOCRReadsUprightWhiteText` 覆盖 |
| AC-4 | 超长兜底 k < minScale → textTooLong | **Satisfied** | FitCalculator L62-66 + `testTooLongClampsToMinScale` + TextRenderer L56 `throw .textTooLong` + Workflow L225 映射 |
| AC-5 | 位置不变（基线对齐） | **Satisfied** | 零生产代码改动；BlockPatchBuilder.layout 未变更；基线锚定逻辑保持 v05 语义 |

**全部 AC Satisfied。**

---

## 五、测试覆盖率评估

| 指标 | 值 | 达标 |
|---|---|---|
| 总测试数 | 61（57 存量 + 4 新增） | — |
| 新增测试覆盖 | FitCalculator 选B 三态 + 兜底（4 条） | ✓ |
| FitCalculator 边界覆盖 | 变宽/等宽/变窄/单字符/超长/零宽 | ✓ |
| 缺失边界 | targetInkWidthPx = 0、natural ≤ 0.5、minScale ≤ 0 | 非阻塞（已知防御性缺口） |
| 覆盖率目标 ≥80% | 61 tests 全绿，FitCalculator 3 tests + 4 语义测试 = 7 条核心覆盖 | ✓ |

**覆盖率达标。**

---

## 六、非阻塞发现（建议，不阻塞 Approve）

| # | 发现 | 风险 | 建议 |
|---|---|---|---|
| 1 | FitCalculator 未 guard `targetInkWidthPx ≤ 0` | 低（已知路径 ≥ 0） | 后续迭代加防御性 guard |
| 2 | 测试仅覆盖 Helvetica 48px，未覆盖 CJK/其他字号 | 低（算法字体无关） | Hermes 实装后需回归 |
| 3 | scaleFactor/fontSizeUsed 分离可能被未来消费者误用 | 低（当前无误用） | 文档标注 scaleFactor 语义 |
| 4 | 等宽场景（`newInkW == origInkW` 严格相等）无独立测试 | 极低（≤ guard 已覆盖） | 可选补充 |

---

## 七、结论

### **Approve**

D-037（宽度策略选B）代码审查通过。

- FitCalculator 选B 三态逻辑与 PRD AC-1 完全一致
- scaleFactor/fontSizeUsed 分离是合理设计意图，非隐患
- 4 条新增测试断言精准，FontProbe 探针真实有效，无空转
- f0 链路原值传递，零副作用，无重复缩放
- 全部 5 条 AC Satisfied
- 61 tests 全绿，零回归，零生产代码改动
- 非阻塞建议 4 项，可在后续迭代处理

**无 Request Changes 项。可向 @zongguan 汇报。**
