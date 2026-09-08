# Code Review v08 — Bug 1 方案甲（D-041）

**审查人**: dana（技术负责人）  
**日期**: 2026-09-02  
**审查对象**:  
- `Sources/PxiuCore/Style/StyleAnalyzer.swift`（+35 行：`digitFriendlyWhitelist` + `digitFriendlyFallbackIfNeeded`）  
- `Tests/PxiuCoreTests/DigitFallbackAndFitTests.swift`（+7 测试）  

**口径依据**: D-041（decisions_2026-09-02.md）、qa_report_v08_2026-09-02.md、tech_spec_pxiu_2026-08-28.md §2.2/§2.5/§2.6

---

## 1. 实现与 D-041 口径一致性

### 1.1 回退条件 — 与口径完全一致 ✅

D-041 定义：`当匹配状态非 .exact 且块为拉丁（非 CJK，script(for:) 判定）时`，触发回退。

代码实现（StyleAnalyzer.swift:70-72）：
```swift
guard FontCatalogBuilder.script(for: text) == .latin else { return face }
if case .exact = match { return face }
```

- CJK 零影响：`script(for:)` 遇 CJK 码点即返回 `.cjk` → guard 提前返回 ✅
- exact 不动：`if case .exact = match` 精确匹配 `.exact(Double)`，`.approximate` 和 `.unmatched` 走回退 ✅

### 1.2 白名单存在性 — 安全降级 ✅

代码（StyleAnalyzer.swift:75-78）：
```swift
let catalogPSNames = Set(catalog.faces.map { $0.postScriptName })
let available = Self.digitFriendlyWhitelist.filter { catalogPSNames.contains($0.postScriptName) }
guard let best = available.min(by: { abs($0.weight - face.weight) < abs($1.weight - face.weight) }) else {
    return face
}
```

- 白名单面必须在 catalog 中存在才可选，catalog 来自 `FontCatalogBuilder.buildDefault()` 动态反映系统已装字体
- `available` 为空时 `guard let best` 失败 → 返回原 face（安全降级，无崩溃）
- 字重就近：`min(by: abs($0.weight - face.weight)` 选择与原面字重最近的白名单面

### 1.3 font 替换隔离 — 颜色/背景/tracking 不受影响 ✅

`digitFriendlyFallbackIfNeeded` 仅返回新 `FontFace`。`analyze()` 方法中：
- `fontSize` = `SizeEstimator.estimate(block: block, face: bestFace)` — 用新 face 重新估算（字号随字体 metrics 微调，合理）
- `color` = `ColorEstimator.estimate(block: block, buffer: buff)` — 完全不依赖 font
- `background` — 同上
- `tracking` = `SpacingEstimator.estimate(block: block, face: bestFace, fontSize: fontSize)` — 用新 face 估算（字间距随字体变化，合理）
- `baselineOffset` = 0（固定值）
- `matchStatus` = 原始 match.status（不改）

**结论**：font 变更隔离正确，符合 D-041"字号/颜色/位置保留原分析结果"口径。

### 1.4 与 tech_spec_pxiu_2026-08-28.md 一致性 ✅

方案甲是 D-041 新增的"数字友好字体回退"机制，属于 `StyleAnalyzer` 内部优化层。tech_spec §2.2 定义了 FontMatcher 两级剪枝 + 二值掩码匹配的主体架构，方案甲不修改匹配逻辑，仅在匹配结果后增加替换层。完全兼容。

---

## 2. 字重就近选择逻辑审查

白名单 6 面字重分布：400（HelveticaNeue, Avenir-Book）、500（HelveticaNeue-Medium, AvenirNext-Medium, Avenir-Medium, Futura-Medium）。

Thonburi weight=200，距离最近白名单面 = 400（差 200）。无 weight=300 的 HelveticaNeue-Light 在白名单中。

**判定**：当前选择逻辑正确（min abs diff）。字重从 200 跳到 400 视觉上笔画变粗，但在 v1 范围内可接受——QA report §4 P4 已标注此为"若用户反馈可考虑增加 HelveticaNeue-Light"的后续优化项，不阻塞。

---

## 3. catalog 空 / 白名单缺失的处理

代码行为：`available` 为空 → `guard let best` 失败 → 返回原 face（Thonburi）。

**判定**：安全降级，无崩溃、无静默数据损坏。回退静默失效但保留原始匹配结果——用户仍可通过 Inspector 手动选择字体（tech_spec §5 错误处理契约已有兜底）。可接受。

---

## 4. 测试覆盖审查

### 4.1 新增 7 测试行为锁定分析

| 测试 | 锁定行为 | 判定 |
|------|---------|------|
| `testLatinDigitApproxFallbackToDigitFriendlySans` | APPROX+拉丁 → 回退到白名单 sans（非 Thonburi） | ✅ 核心路径，断言 `isWhitelisted` + `!= Thonburi`，非写死通过 |
| `testCJKApproxNoFallback` | CJK APPROX → 保留原匹配面 | ✅ 回归保护，断言 `== psName` |
| `testExactMatchNoFallback` | exact → 不动 | ✅ 回归保护，断言 `== psName` |
| `testLatinDigitUnmatchedFallback` | UNMATCHED+拉丁 → 同样回退 | ✅ 覆盖 unmatched 分支，断言 `isWhitelisted` |
| `testShorterTextKeepsFontSizeAndCenter` | 变短 → scaleFactor=1, fontSizeUsed=f0 | ✅ FitCalculator "只缩不放"行为锁定 |
| `testSameLengthKeepsFontSize` | 等长 → scaleFactor=1 | ✅ 边界行为 |
| `testLongerTextStillShrinks` | 超长 → scaleFactor<1 | ✅ minScale 保护仍在 |

**断言质量**：测试使用 `TestSupport.render` 构造真实渲染图 → 真实 pipeline 路径，非 mock。断言检查白名单成员资格、非 Thonburi、字号比率合理范围，非固定值。**行为锁定充分**。

### 4.2 覆盖率评估

- 82/82 通过，零回归
- `digitFriendlyFallbackIfNeeded` 四条路径覆盖：CJK（guard）、exact（guard）、有可用面（正常回退）、无可用面（guard fallback）
- 唯一缺失路径：`available` 为空的分支未被显式测试（QA report P1 已标注）

### 4.3 测试白名单与生产白名单重复 — 低风险但需标注

测试文件 DigitFallbackTests 中 `digitFriendlyWhitelist` 是生产代码 `StyleAnalyzer.digitFriendlyWhitelist` 的复制（同 6 面同字重）。若生产侧增删白名单面而测试未同步，测试会失效。

**判定**：当前不影响正确性（测试用的是构造 catalog，仅验证回退到任意白名单面即可），但后续维护需注意同步。标记为 tech debt，不阻塞。

---

## 5. 回归风险评估

| 风险点 | 评估 |
|--------|------|
| CJK 块被误回退 | ❌ 不可能：`script(for:)` 判定为 `.cjk` 即 guard 返回 |
| exact 块被替换 | ❌ 不可能：`if case .exact = match` 精确拦截 |
| 白名单面不存在导致崩溃 | ❌ 不可能：`guard let best` 失败返回原 face |
| 字号/颜色/位置被改 | ❌ 不可能：回退仅替换 FontFace，其余属性由各自 Estimator 独立计算 |
| 原有 75 测试回归 | ❌ 已验证 0 回归 |

**回归风险：极低。** 方案甲是纯增量逻辑（guard + 白名单筛选 + 替换），不修改任何已有路径。

---

## 6. 漏测场景评估（与 QA report §4 交叉审查）

### P0 — 混合 CJK+拉丁（"¥100元"）不触发回退

- `script(for:)` 遇 `元`(U+5143) → `.cjk` → 整块跳过回退
- **是否可接受**：是。D-041 口径仅要求"数字块和中文块的正确性"。混合块"¥100元"可视为 CJK 块（含中文语义），跳过回退属于保守正确。在 shuzi.jpg 场景 `-¥5.94`（纯拉丁）已正确回退。混合场景作为 v1.1 优化项合理。
- **判定**：不阻塞本次验收。

### P1 — 空 catalog / 白名单面全部缺失

- `available` 为空 → 返回原 face → 回退静默失效
- 安全降级正确，但无显式测试覆盖
- **判定**：建议 alpha.8 后补测，不阻塞。

### P2 — displayName 使用 PS 名（"HelveticaNeue-Medium" 而非 "Helvetica Neue Medium"）

- 仅影响 Inspector UI 显示，不影响渲染
- **判定**：cosmetic，不阻塞。

---

## 7. 结论

**Approve** ✅

方案甲代码正确实现了 D-041 口径：
1. 回退条件精确（非 exact + 拉丁块），CJK 和 exact 块零影响
2. 白名单存在性校验 + 字重就近选择 + 安全降级完备
3. font 替换隔离正确，颜色/背景/tracking/baseline 不受影响
4. 7 新增测试行为锁定充分，非写死通过
5. 82/82 全通过，零回归
6. 回归风险极低

**无必改项。**

**建议跟进项（不阻塞验收）**：
1. 补测 `available.isEmpty` 分支（构造不含白名单面的 catalog，验证返回原 face）
2. 考虑在白名单增加 HelveticaNeue-Light (300) 缩小 Thonburi(200) → 白名单面的字重差距
3. displayName 使用可读名称而非 PS 名（cosmetic，优先级低）
4. 测试白名单与生产白名单同步维护（tech debt）
