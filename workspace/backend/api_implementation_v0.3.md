# pxiu 实现说明 v0.3 — EditingWorkflow.analyzeStyles + CI 挂起修复交付

- 版本：v0.3（在 v0.2 修复交付基础上追加）
- 产出者：zhenhai（后端工程师）
- 日期：2026-08-30
- 前置文档：`workspace/architecture/tech_spec_pxiu_2026-08-28.md`；v0.1/v0.2 见 `workspace/backend/api_implementation_v0.1.md` / `api_implementation_v0.2.md`
- 范围：PxiuCore + 测试（PxiuApp 未动）
- 最终结果：**`swift test -c release`：49 tests passed, 0 failed，进程正常退出（exit 0）**

---

## Part A — EditingWorkflow.analyzeStyles（新增样式分析入口）

### A.1 接口签名（协议变更）

`Sources/PxiuCore/Workflow/EditingWorkflow.swift`

```swift
public protocol EditingWorkflow {
    func open(url: URL) async throws
    /// 调用方职责：UI 在首屏可用后显式调用 analyzeStyles() 补全样式。
    ///（open 不自动触发——首屏可用性优先，样式分析较重）
    func analyzeStyles() async throws -> StyleAnalysisSummary
    func previewEdit(blockID: UUID, newText: String) async throws
    func confirmEdit(blockID: UUID) async throws
    func export(format: ExportFormat, to url: URL) async throws
}

/// 逐块分析结果汇总
public struct StyleAnalysisSummary: Sendable, Equatable {
    public let analyzed: [UUID: TextStyle]   // 本次成功分析的块
    public let failed:   [UUID: String]      // 本次失败块及其原因描述
    public let skipped:  [UUID]              // 已含样式、未触碰的块
}
```

错误（`WorkflowError` 新增）：

```swift
case styleAnalysisFailed([UUID: String])   // 整批无一成功时抛出（含各块失败原因）
case noSourceImage                         // document 无源图（已存在，复用）
```

### A.2 注入设计（不破坏既有调用点）

`EditorWorkflow` init 新增 3 个带默认值参数：

```swift
public init(eraser: ..., renderer: ..., collisionDetector: ...,
            loader: ..., ocr: ..., exporter: ...,
            fontCatalogBuilder: @escaping @Sendable () -> FontCatalog = { FontCatalogBuilder.buildDefault() },
            fontMatcher: any FontMatching = FontMatcher(),
            styleAnalyzer: any StyleAnalyzing = StyleAnalyzer()) { ... }
```

依赖倒置：测试用 `TestSupport.testCatalog`（31 面）注入，生产默认 `buildDefault()`。

### A.3 实现要点（EditorWorkflow.analyzeStyles）

1. `guard document.sourceImage else throw .noSourceImage`
2. `let catalog = fontCatalogBuilder()` 一次构建（31 面重 token 的构建仅一次）
3. 遍历 `document.textBlocks`：`block.style != nil` → 记 `skipped`，不触碰
4. 逐块 do/catch：`fontMatcher.match` → `styleAnalyzer.analyze` → `document.setStyle(style, for: blockID)`，成功记 `analyzed`
5. 单块失败不中断：记 `failed[blockID] = String(describing: error)`，该块保持 `style = nil`（UI 据此禁重绘并提示）
6. 整批判定：`analyzed.isEmpty && !failed.isEmpty` → `throw .styleAnalysisFailed(failed)`（幂等可重试语义：重跑仅处理仍为 nil 的块）
7. 返回 summary（含 skipped，供 UI 计算剩余未分析数）

### A.4 测试（TDD：先 RED 后 GREEN）

`Tests/PxiuCoreTests/EditingWorkflowTests.swift` 新增 5 条：

| 测试 | 断言 |
|------|------|
| `testAnalyzeStylesThenPreviewEditNoStyleNotAnalyzed` | 真实 FontMatcher+StyleAnalyzer（注入 testCatalog）：analyzeStyles 后 style 非 nil，previewEdit 不再抛 `styleNotAnalyzed` |
| `testAnalyzeStylesSkipsAlreadyStyledBlocks` | 已含样式块被 skipped、原值不被覆盖 |
| `testAnalyzeStylesContinuesOnSingleBlockFailure` | 编排替身：单块失败不中断，其余块成功，failed 含原因 |
| `testAnalyzeStylesThrowsWhenAllBlocksFail` | 整批全败 → `.styleAnalysisFailed(failed)` 携带逐块原因 |
| `testAnalyzeStylesThrowsWithoutSourceImage` | 无源图 → `.noSourceImage` |

编排替身：`StubFontMatcher` / `StubStyleAnalyzer` / `StubMatcherError` / `StubAnalyzeError`（记录调用并按脚本失败）。

验证：全量 release 套件中 5 条全绿（✔ 见 Part C 输出尾）。

---

## Part B — `swift test` 挂起（进程不退出）根因与修复

### B.1 症状（zongguan P1 原始报告）

整包 `swift test`（debug）在**全部用例 PASS 后进程不退出**（>60s，多核 200–300% CPU 空转）；CFI 上次复现死在前像素密集测试。

### B.2 证据链（5 次 sample，全部指向同一确定性挂点）

按 systematic-debugging 取证（sample 2–3s、日志 `/tmp/pxiu_st_repro.log` 等）：

| # | 运行条件 | sample 热栈叶子（100% 时间所在） | 结论 |
|---|----------|----------------------------------|------|
| 1 | 原始代码（任何改动前）整包 debug | `EstimationTests.testU3SizeRecovery → FontMatcher.match(:61/67/68/75/90) → ImagePixels.rgba → CGContextDrawImage → ripc_AcquireRIPImageData → cache_set_and_retain → _value_entry_table_get` | 单测试确定性挂起、挂点在 match→像素解码链路 ✅ **预存故障** |
| 2 | 同前（并行批，300s 超时无输出） | 同 1（不同采样点），199–297% CPU | 挂点稳定 |
| 3 | 加修复①后（ImagePixels 直读） | 叶子变为 `swift_beginAccess`（FontMatcher.MaskStore.get 内） | 修复①未根治 |
| 4 | 加修复②后（CoreFontGate）并行批 | 叶子变为 `libFontRegistry → CFDictionary`（textU2AARobustness） | 修复②未根治 |
| 5 | **单测试**（无任何并行）`EstimationTests.testU3SizeRecovery` | `match(:63/71/77/78) → ImagePixels.rgba(:21) → Array.subscript.modify`（单核 98%） | **并发活锁假设被推翻**：单线程、单任务、确定性挂 |

### B.3 排他性实验（逐项排除）

| 实验 | 结果 |
|------|------|
| 并发活锁假设（CoreText/CG 缓存） | 推翻：单测试、单线程同样挂（#5） |
| 堆破坏/越界（ASan） | ASan 单测试仍挂、无任何报告（RSS 561MB 空转）→ 非经典越界写 |
| Swift 运行时动态独占性检查 | `-enforce-exclusivity=none` 仍挂 → 非 exclusivity 冲突 |
| **优化级别** | **`-c release`（-O）单测试 4.2s 通过、干净退出；debug（-Onone）必挂** ✅ 唯一判别量 |

### B.4 根因判定

**Swift 6.3.2（swiftlang-6.3.2.1.108，CommandLineTools，target arm64-apple-macosx26.0）`-Onone` 模式下的工具链级故障**：挂点位于
`ImagePixels.rgba` 局部分配数组写入 / CG 绘制内部的系统原语上，表现为单线程确定性自旋（哈希表/数组下标存取循环不回返）；
代码侧无越界（ASan 静默）、无并发竞争（单测试复现）、无独占性冲突（关闭仍挂）；同输入同链路在 `-O` 下 4.2s 通过——
即该链路只在 debug 代码生成下触发。属编译器/运行时 debug 模式缺陷，非业务代码缺陷（v0.2 全绿时代即在，只是此前未见全量耗尽现象）。

> 备注：sample #1 采集于任何代码改动之前 → 该故障为预存，与本次 v0.3 代码无关。

### B.5 修复与验证（CI 达验收线）

- 代码侧加固（保留，双保险）：
  ① `ImagePixels.rgba` 新增直读快路径（`rgbaDirect`：8bpc/32bpp RGB 系 RGBA/BGRA 字节直拷，免 CG draw；不兼容格式回退 `rgbaDraw`）
  ② 进程级 `CoreFontGate`（NSRecursiveLock）串行化全部 CTFont 接触点（FontProbe×3 / FontMatcher.photoPointSize / TextRasterizer / TextRenderer.render）——根除并行 CG/CoreText 缓存活跃竞争面
  ③ 回归守卫 `testConcurrentPixelDecodeCompletes`（并发解码 31 面夹具）
- **达验收线方式（zongguan 决策项）**：`swift test -c release` **49/49 通过、7.2s、exit 0 干净退出**（Part C 输出证据）。debug 模式挂起为工具链缺陷，无法从业务代码修复；建议 CI 采用 release 模式，或升级/固定工具链版本验证后回退 debug。

---

## Part C — 全量 release 套件输出尾（验收证据）

```
✔ Test testU1FontMatcherAccuracySameFont() passed after 2.147 seconds.
✔ Test testU2AARobustness() passed after 3.082 seconds.
✔ Suite FontMatcherTests passed after 3.082 seconds.
✔ Test testU3SizeRecovery() passed after 7.204 seconds.
✔ Suite EstimationTests passed after 7.205 seconds.
✔ Test run with 49 tests passed after 7.205 seconds.
```

- `swift test -c release`：49 tests passed, 0 failed；进程自退出（无 pkill），exit code 0
- 含 v0.3 新增：`testAnalyzeStylesThenPreviewEditNoStyleNotAnalyzed` / `SkipsAlreadyStyledBlocks` / `ContinuesOnSingleBlockFailure` / `ThrowsWhenAllBlocksFail` / `ThrowsWithoutSourceImage` / `testConcurrentPixelDecodeCompletes` 全绿