# QA 复测报告 — pxiu v0.2（P1 回退门禁复测）

- **版本**：pxiu v0.2（zhenhai §5.1 修复交付）
- **被测对象**：`/Users/evandy/opencode/pxiu/pxiu`（macOS Swift 工程：PxiuCore + PxiuApp）
- **测试类型**：P1 回退门禁复测 + P2 修复复核 + 全量回归 + 契约一致性 + 对抗式边界
- **执行人**：@shouye（QA + SRE）
- **日期**：2026-08-29
- **前序报告**：`workspace/qa/qa_report_v0.1_2026-08-28.md`（结论 APPROVE 有条件，P1 列为必须修复项）
- **供给下游**：@dana（code_review）、@zongguan（验收）
- **结论**：**APPROVE（有条件）** —— **P1 回退门禁通过**，允许进入 @dana 审查（条件见 §8）

---

## 0. 执行环境与证据总表（红线：每条结论附亲跑命令输出）

| 项 | 值 |
|---|---|
| 平台 | macOS / arm64（darwin） |
| Swift | 6.3.2（CommandLineTools） |
| 测试框架 | swift-testing 0.99.0（无 XCTest、无 Xcode/GUI 自动化） |
| 构建 | `swift build` → **Build complete! (1.79s)**，exit 0 |
| 网络 | 离线（事件测试纯本地） |

| # | 亲跑命令 | 输出证据 | 结论 |
|---|---------|---------|------|
| 1 | `swift build` | `Build complete! (1.79s)` | ✅ |
| 2 | `swift test`（树原样，含 QA 残留） | **58 tests passed / 0 failed**（334.6s，exit 0） | ✅ |
| 3 | `swift test --filter TextRendererTests` | **2 passed**（0.114s） | ✅ P1 |
| 4 | `swift test --filter EditingWorkflowTests` | **10 passed**（0.120s，含 testCancelInvalidatesInFlightPreview） | ✅ P2 |
| 5 | `swift test --filter InpainterTests` | **4 passed**（1.374s，含 testLowContrastEraseAdaptiveThreshold） | ✅ P2 |
| 6 | QA 临时探针 `swift test --filter QA_Gate_TempTests` | **5 passed**（0.116s），关键数值见 §2 | ✅ P1 对抗 |
| 7 | 移出 QA_* 残留后的**纯交付物全量** | **43 tests passed / 0 failed**（324.9s，exit 0） | ✅ 回归 |
| 8 | 探针删除 + 树还原后最终复跑 | **58 tests passed / 0 failed**（436.8s，exit 0） | ✅ 零污染 |

> 计数口径：交付物 43 = 首测基线 39 + 新增 4（TextRendererTests×2 + testCancelInvalidatesInFlightPreview + testLowContrastEraseAdaptiveThreshold）。树内残留 5 个 QA_* 临时文件（15 用例）使原样全量为 58，两口径均全绿，见 §7。
> 测试活动零产品代码改动：QA 探针文件测毕删除；QA_* 遗留文件移出/恢复原位，树还原至到达时状态。

---

## 1. 前置检查（开工门禁）

- ✅ 必读文档齐全：`qa_report_v0.1`、`api_implementation_v0.2.md`、`tech_spec_pxiu_2026-08-28.md §2.7/§2.8` 均已读取，无阻塞。
- ✅ zhenhai 声明的 4 项修复在源码与测试中均定位到实体（见各节行号）。

---

## 2. P1 回退门禁复测（核心项）

### 2.1 实现核对（源码级）

`Sources/PxiuCore/Render/TextRenderer.swift:111-145` `fillBackground`，`.gradient(axis,c0,c1,_)` 分支：

- **全像素嵌套循环**（`for y in 0..<height { for x in 0..<width }`）逐像素写 RGB——**非端点两点插值**；
- t 归一化：水平轴 `t = clamp((x+0.5−pad)/inkW, 0, 1)`，垂直轴按 y；每像素 `lerp(c0,c1,t)` 后夹取 0-255；
- 笔画经 CTLineDraw 走同一混合方程 `pixel = bg + α·(fg−bg)`（TextRenderer.swift:98-100）。

**判定：P1 实体「平坦 c0 填充」已被「逐像素背景模型复合」替换，实现方式与 tech_spec §2.7 一致。**

### 2.2 亲跑复现 SSIM 声明（QA 探针 gateA，vs 提交测试的断言阈值 0.90/0.95）

```
[QA-Gate A] 水平渐变 patch vs 渐变oracle SSIM = 0.9984（zhenhai 声称 0.9994）
[QA-Gate A] 水平渐变 patch vs 平坦c0 oracle SSIM = 0.8122（zhenhai 声称旧实现 0.7907）
✔ Test run with 5 tests passed after 0.116 seconds
```

- 声称 0.9994 → 实测 **0.9984**：同属 ≥0.99 量级，差异来自 oracle 采样舍入口径（提交测试不打印数值，QA 独立重构 oracle 复测）。**「与渐变 oracle 高度一致」声明成立**；
- 声称 0.7907（旧平坦基线）→ 实测 **0.8122**：同量级。关键判别：若实现仍为平坦 c0，patch vs 平坦 oracle 的 SSIM 会≈1.0；0.81 证明**当前实现与平坦填充显著分离**。提交测试断言 `ssimFlat < 0.95` 达标。

### 2.3 对抗式变体（QA 探针 gateB/C/D，全部亲跑）

| 变体 | 方法 | 实测 | 判定 |
|---|---|---|---|
| 极端宽渐变（渐变区间 = 3×ink 宽） | 逐列比对 lerp(t) 期望值，133 列 | 最大偏差 **0.011**，偏差>0.02 列数 **0/133**；中列色 0.498 vs 期望 0.500 | ✅ 块内全 ink 区间逐像素，非端点插值 |
| 垂直轴渐变 | 逐行 × 3 列抽样 | 最大偏差 **0.0053** | ✅ |
| 深浅端反向（c0 亮 c1 暗） | 逐列比对 | 最大偏差 **0.0096** | ✅ 无方向符号缺陷 |

### 2.4 ⚠️ 对抗式新发现：渐变相位对齐残余（gateE，短文本场景）

**场景**：渐变背景 + 改字后文本明显变短（新 ink 宽 34px vs 原 ink 宽 200px，短文本不放大规则）。

```
[QA-Gate E] 新 ink 宽 = 34.0 px；原 ink 宽 = 200.0 px
[QA-Gate E] patch 左缘色 = (0.200,0.298,0.400)；源图同处真实渐变 = (0.439,0.459,0.478)；接缝偏差 = 0.2987
[QA-Gate E] 源图在 patch 左缘 x 处的渐变进度 t_src = 0.395
```

**机理**（源码+实测双重确认）：`fillBackground` 的 t 以 **patch 自身 ink 区间**为基准（t=0@左缘，t=1@右缘），而源图真实渐变在 patch 落点处已走到 39.5%。当新字 ink 宽 ≠ 原 ink 宽时，patch 内渐变被压缩/拉伸，与周边真实渐变**相位错位**，patch 边缘出现 RGB 域 **0.30 量级色差接缝**。等宽改字（gateA）无此问题（0.9984）。

**与旧缺陷的净对比**：旧平坦填充在渐变场景整块≈0.29 色差；新实现等宽改字 0 接缝、仅长度骤变时边缘错位。**净收益明确**，残余为相位对齐问题。

**判定**：不构成 P1 回退门禁不通过（P1 判定标准＝「逐像素 vs 平坦」，已达成）；列为**新增 P2 已知限制**，建议 v0.3：渐变归一化以「原 ink 区间/bbox」为基准 + patch 绝对坐标对齐，并补「短文本渐变 E2E」回归。

### 2.5 P1 门禁结论

```
┌──────────────────┬────────────────────────────────────┐
│ P1 回退门禁      │ ✅ 通过（有条件）                 │
├──────────────────┼────────────────────────────────────┤
│ 逐像素复合       │ 源码核对 + gateA 0.9984 亲跑确认   │
├──────────────────┼────────────────────────────────────┤
│ 非平坦 c0        │ gateA 0.8122（若平坦应≈1.0）亲跑  │
├──────────────────┼────────────────────────────────────┤
│ 全 ink 区间逐像素│ gateB/C/D 最大偏差 ≤0.011 亲跑    │
├──────────────────┼────────────────────────────────────┤
│ 条件             │ 相位对齐残余列为 P2 已知限制       │
└──────────────────┴────────────────────────────────────┘
```

---

## 3. P2 cancel 语义复测

### 3.1 实现核对

`Sources/PxiuCore/Workflow/EditingWorkflow.swift`：

- `previewEdit`（L126-141）：开头 `generation &+= 1`，`await process(...)` 后 `guard myGeneration == generation else throw staleResult`（L137）→ 过期结果**丢弃且不写 pendingEdit**；
- 三入口全覆盖：`cancelPreview`（L210-214）/ `undo`（L216-220）/ `redo`（L222-226）均 `generation &+= 1` + `pendingEdit = nil`。

**判定：cancelPreview/undo/redo 三路径的 in-flight 过期语义覆盖完整，「取消后 in-flight 返回重新挂起 pendingEdit 可 confirm」的幽灵编辑路径已封闭。** 测试 `testCancelInvalidatesInFlightPreview` 亲跑绿（EditingWorkflowTests 10/10）。

### 3.2 对抗式残余

| 残余 | 性质 | 判定 |
|---|---|---|
| check-then-act 非原子窗口（L137 guard 通过 → L138 赋值之间，另一线程 bump generation 可致幽灵挂起） | `@unchecked Sendable class` 无锁；单线程 UI 驱动下不可达，并发调用方存在时为理论竞态 | 归入 P2-1 已披露「语义级取消/非 actor」同类，不阻塞；建议后续 actor 化时以 `pendingEdit` 与 `generation` 同区隔离一并消除 |
| 底层 CPU 密集渲染非协作可取消（`Task.cancel()` 不传播） | renderer/eraser 无 `Task.isCancelled` 检查点 | zhenhai 已披露（§5.1 P2-1），核实属实；彻底可取消属后续架构项 |

**判定：语义级取消符合 tech_spec §2.8 generation 语义；不阻塞 v0.2。**

---

## 4. P2 低对比抹除复测

### 4.1 实现核对 + 亲跑

`Sources/PxiuCore/Erase/TextEraser.swift` `strokeMask`（L223-234）：块内实测最大对比 `maxDist ∈ (1e-3, 0.25)` 时 `threshold = max(0.6·maxDist, floor)` 下探；`maxDist ≥ 0.25`（正常对比）**保持固定 0.25**——正常场景不受影响的判据由构造保证（只下探不误伤）。

- `testLowContrastEraseAdaptiveThreshold`（InpainterTests，13% 灰字 on 17% 灰底，距 bg≈0.04）**亲跑绿**：断言笔画中心被抹除回 bg±0.02；
- 正常对比回归：InpainterTests U6 flat/gradient/smooth-noise 三场景 4/4 全绿 → **无对正常对比场景的误伤证据**。

### 4.2 残余

`.gradient` 背景的抹除掩码仍以 c0 为判据（`TextEraser.swift:217`），梯度横向对比可能令掩码偏大——zhenhai 已披露（§5.1 #4），QA 同意其「平坦/低对比优先」优先级论证，记为已知限制。

**判定：P2 低对比抹除修复确认，非阻塞。**

---

## 5. P2 局部 patch 结构差异（评估不修项）复核

zhenhai 论证：v1 纯色文字补丁盒无阴影/滤镜等跨补丁边界效果，`compositeAfter`（BlockPatchBuilder.swift:94-123）＝抹除后背景为底 + 不透明字形补丁贴入，不存在结构性泄漏；QA 侧旧测 0.59 属局部口径。

QA 复核：代码确认无跨边界效果路径；树内 QA 残留探针 `QA_AlignDiagTests`（±3px 对齐搜索）实测补丁区对齐 SSIM 峰值 **0.53**（亲跑输出 `best offset = (0, 3) SSIM = 0.5288`）——补充印证「非渲染缺陷、属局部口径/对齐差异类」。**接受不修，记为已知限制。**

---

## 6. 契约一致性核对（tech_spec §2.7 / §2.8）

| 契约项 | 规格要求 | v0.2 实现 | 结论 |
|---|---|---|---|
| §2.7 背景复合 | 平坦 = 精确复合；**渐变 = 逐像素背景模型复合** | `fillBackground` 全像素插值 + 单一混合方程 | ✅ **已修复**（v0.1 ❌ → v0.2 ✅） |
| §2.7 复合范围 | 新字形外接 +1px，范围外不染指 | `compositeAfter` 仅贴 patch 区域 | ✅ |
| §2.8 异步模型 | 后台串行 **actor** + 结构化取消 | `@unchecked Sendable class` + generation 语义取消（非底层中断） | ⚠️ 架构偏差持续（P2-1 披露） |
| §2.8 generation | 过期结果丢弃 | `guard myGeneration == generation` 三入口覆盖 | ✅ 语义达成 |

**§2.8 偏差判定（zhenhai 声明 P2-1 语义级取消为已知限制）**：功能语义由 generation 机制保证且亲跑验证；「彻底可取消 + actor 化」属架构级演进，**不影响 v0.2 验收放行**，但必须在 dana code_review 中作为架构遗留项记录。

---

## 7. 回归确认与现树状态发现

- ✅ **回归确认**：纯交付物全量 **43 passed / 0 failed** = 首测基线 39 + 新增 4，**零回归**。
- 🟡 **现树状态发现（非阻塞）**：`Tests/PxiuCoreTests/` 残留 5 个 QA 临时文件（`QA_Reg_TempTests.swift`(11 用例)、`QA_AlignDiag*Tests.swift`×4），使树内全量测试数为 58。**建议 zhenhai/QA 规范清理临时探针**——否则 CI 测试基线读数（58 vs 交付 43）会失真，且临时探针含 print 诊断输出（`[DIAG]`/`[QA]`）污染测试日志。本次复测已按「原样 58 / 纯交付 43」双口径记录，互不矛盾。

---

## 8. §6.2 风格「最可能漏测的场景」对抗式清单（针对 P1 渐变复合修复点）

> 用户会怎么误用渐变改字？新修复在什么情况下会失效？——逐条亲跑过的打 ✅，未亲跑的打 🔲（已定性分析）。

1. **渐变背景 + 改字变短/变长（长度骤变）** → patch 渐变相位错位、边缘接缝。**✅ 已实测（gateE 接缝 0.299）**。这是用户最可能肉眼抓住的场景：按钮字从「Grand Total」改成「OK」。
2. **渐变 + 大字号改动（patch ink 高 ≫ 原块高或反）** → 垂直轴相位同理错位。🔲 由 gateE 机理外推（t 均以 patch 自身 ink 为基准），建议 v0.3 同补。
3. **渐变背景上的抹除** → strokeMask 以 c0 判据，强渐变下掩码偏大、抹除范围过宽（残余残影）。✅ 源码确认（TextEraser.swift:217）+ zhenhai 披露，已列为已知限制。
4. **斜向渐变/非轴对齐渐变** → 实现仅支持纯水平/垂直轴插值，斜向渐变被轴对齐近似。🔲 BackgroundModel 只有 axis 枚举，斜渐变无建模通道；属模型能力边界。
5. **渐变端点色非常规（细颗粒纹理渐变）** → `delta` 纹理方差未参与插值，纹理渐变被退化为纯线性插值。🔲 v1 背景模型即此语义，非本修复引入。
6. **强渐变 + 深色字 + 极小字号** → 前景 α 混合边缘是否存在补丁底色泄漏。✅ 单混合方程保证（代码核对），且 gateA 字形区 SSIM 0.9984 含字形像素；仍列观察项。
7. **相位错位的临界视觉阈值**（改字宽度变化 ±5%~15% 时接缝多大会被看出）→ 无主观视觉评测通道（无 GUI）。🔲 建议 v0.3 主观比对样本。

---

## 9. 遗留风险清单（交 @dana / @zongguan）

| # | 级别 | 项 | 状态 |
|---|------|----|----|
| 1 | P2（新） | 渐变相位对齐：短/长文本改字场景 patch 边缘接缝 0.30 量级（gateE 实测） | 建议 v0.3：渐变以原 ink 区间/bbox 为归一化基准 + pat­ch 绝对坐标对齐；补短文本渐变 E2E |
| 2 | P2-1 | 彻底可取消（renderer/eraser 协作取消 + actor 化） | 架构项，不阻塞 v0.2 验收 |
| 3 | P2-1 | check-then-act 理论竞态窗口（非 actor 并发） | 依赖调用方串行；actor 化时同区隔离消除 |
| 4 | P2 | .gradient 抹除掩码 c0 判据偏大 | 已知限制（已披露） |
| 5 | P2 | 测试体量 325s（U3 304s 串行） | 非正确性阻塞；CI 超时风险建议评估 |
| 6 | 🟡 | `Tests/` 残留 5 个 QA_* 临时文件（15 用例） | 建议清理，防测试计数失真 |
| 7 | 环境 | GUI 交互未 UI 自动化（无 Xcode/GUI） | 持续环境约束，状态机静态核对替代 |

---

## 10. 总评与结论

```
┌──────────────────────┬────────────────────────────────┐
│ ✅ 构建              │ swift build exit 0 (1.79s)     │
├──────────────────────┼────────────────────────────────┤
│ ✅ 全量测试          │ 43 passed / 0 failed（交付物）  │
│                      │ 58 passed / 0 failed（含残留）  │
├──────────────────────┼────────────────────────────────┤
│ ✅ P1 回退门禁       │ 通过（逐像素复合亲跑确认 0.9984）│
├──────────────────────┼────────────────────────────────┤
│ ✅ P2 cancel 语义    │ 三入口 generation 覆盖 + 测试绿 │
├──────────────────────┼────────────────────────────────┤
│ ✅ P2 低对比抹除     │ 自适应判据 + 13%/17% 场景绿     │
├──────────────────────┼────────────────────────────────┤
│ ✅ 零污染            │ 探针已删，树还原，最终复跑绿    │
└──────────────────────┴────────────────────────────────┘
```

- **结论：APPROVE（有条件）**
- **P1 回退门禁：通过** ——「渐变背景逐像素复合」已实现并经 QA 独立探针亲跑确认（等宽改字 patch 局部 SSIM 0.9984；对抗变体全像素插值最大偏差 ≤0.011；非平坦判据 0.8122）。
- **允许进入 @dana 审查：是**。条件：① 相位对齐残余（§9-#1）录入 dana 审查范围的架构遗留项；② §9 遗留清单随报告流转（尤其 #6 QA_* 残留清理）；③ P1 声明口径限定为「等宽改字渐变复合已修复」，不等宽场景（长度骤变）的渐变复合为已知限制，不得列入「已完成无痕」宣称。

### QA 手法自证

- 测试活动**零改产品代码**：仅新增 QA 临时探针文件，测毕删除；QA_* 遗留文件移出/恢复原位；探针删除后最终复跑 58 passed / 0 failed（436.8s），交付树未污染。
- 所有结论附亲跑命令与输出证据（§0 证据总表 + 各节内联输出），无一转述 zhenhai 自证。

---

## 附：亲跑命令证据汇总

```bash
# 1) 构建
swift build                                        # Build complete! (1.79s), exit 0

# 2) 全量复跑（树原样，含 QA 残留 15 用例）
swift test                                         # 58 tests passed (334.590s), 0 failed

# 3) P1 套件
swift test --filter TextRendererTests              # 2 passed (0.114s)

# 4) P2 cancel 套件
swift test --filter EditingWorkflowTests           # 10 passed (0.120s)，含 testCancelInvalidatesInFlightPreview
# 5) P2 低对比套件
swift test --filter InpainterTests                 # 4 passed (1.374s)，含 testLowContrastEraseAdaptiveThreshold

# 6) QA 独立探针（临时文件，验收后已删）
swift test --filter QA_Gate_TempTests              # 5 passed (0.116s)
#   gateA: 0.9984 / 0.8122（声称 0.9994 / 0.7907，同量级复现）
#   gateB: 极端宽渐变逐列最大偏差 0.011，中列 0.498
#   gateC: 垂直轴 0.0053；gateD: 深浅反向 0.0096
#   gateE: 短文本接缝 0.2987（新发现 P2 相位对齐残余）

# 7) 纯交付物全量（移出 QA_* 残留后）
mv Tests/PxiuCoreTests/QA_*.swift <backup>/
swift test                                         # 43 tests passed (324.883s), 0 failed = 39+4 无回归
mv <backup>/QA_*.swift Tests/PxiuCoreTests/

# 8) 探针删除 + 树还原后最终复跑
rm Tests/PxiuCoreTests/QA_Gate_TempTests.swift
swift test                                         # 58 tests passed (436.814s), 0 failed
```