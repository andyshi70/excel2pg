# 代码审查报告 — pxiu v0.2

- **版本**：pxiu v0.2
- **审查人**：@dana（技术负责人）
- **日期**：2026-08-29
- **前置消费**：`workspace/qa/qa_report_v0.2_2026-08-29.md`（APPROVE 有条件）、`workspace/qa/qa_report_v0.1_2026-08-28.md`（首测基线）、`workspace/backend/api_implementation_v0.2.md`、`workspace/architecture/tech_spec_pxiu_2026-08-28.md`、`workspace/product/prd_pxiu_v0.1_2026-08-28.md`
- **审查方式**：只审查不修改代码。逐项核对契约常数、编译级源码核对、边界/安全路径核查、QA 遗留项裁决。
- **结论**：**APPROVE（有条件）** —— P1 回退门禁确认通过，P2 各项为已知限制/架构遗留，不构成 v0.2 阻塞；附审计建议与 zongguan 决策项。

---

## 0. 审查对象与证据范围

已亲读源码（审查范围内，非全树遍历）：

| 文件 | 定位 |
|---|---|
| `Sources/PxiuCore/Render/TextRenderer.swift` | §2.7 渐变逐像素复合（P1 修复实体） |
| `Sources/PxiuCore/Render/FitCalculator.swift` | §2.6 fit 规则 + §11 k_min=0.5 |
| `Sources/PxiuCore/Render/CollisionDetector.swift` | §11 碰撞阈值 2px |
| `Sources/PxiuCore/Style/FontMatcher.swift` | §11 匹配阈值 + 两级剪枝 |
| `Sources/PxiuCore/Style/PixelMetrics.swift` | #1 崩溃修复 clamp |
| `Sources/PxiuCore/Workflow/BlockPatchBuilder.swift` | 布局/补丁合成（无痕最后环节） |
| `Sources/PxiuCore/Workflow/EditingWorkflow.swift` | §2.8 异步/取消语义 |
| `Sources/PxiuCore/Erase/TextEraser.swift` | 抹除掩码判据 + inpaint |

QA 已独立亲跑（58/43 双口径全绿、P1 gateA~E、P2 三入口取消、低对比抹除），本报告采信其证据链（红线：无 QA 支撑的结论不入 verdict）。以下是编译级源码核对与裁决。

---

## 1. 审查结论表（位置 / 规格要求 / 实现现状 / 判定）

| 项 | 位置 | 规格要求（§） | 实现现状 | 判定 |
|---|---|---|---|---|
| 渐变背景逐像素复合 | `TextRenderer.swift:111-145` | §2.7「渐变=逐像素背景模型复合」 | `.gradient` 分支全像素嵌套循环 `lerp(c0,c1,t)` 逐像素写 RGB，笔画走同一混合方程（L98-100）；QA gateA 等宽改字 SSIM 0.9984、非平坦判据 0.8122、多对抗变体 ≤0.011 | ✅ **P1 已修复** |
| 复合范围「范围外不染指」 | `BlockPatchBuilder.swift:94-123` | §2.7-3 | `compositeAfter` 仅以抹除后背景为底 + 字形补丁贴入 `patchRect` 区域，区域外保持 inpaint 后背景 | ✅ |
| Fit 规则（只缩不放大） | `FitCalculator.swift:54-61` | §2.6-4 | `k0<1` 才缩 `fs=f0*k`，变长不放大；`topp` 语义正确 | ✅ |
| k_min / textTooLong | `FitCalculator.swift:62-65` + `TextRenderer.swift:55` + `EditingWorkflow.swift:167` | §11 k_min=0.5 / §5-3 | `tooLong = k<0.5` → `.textTooLong` → confirm 禁用，预览不渲染 | ✅ 一致 |
| 匹配阈值 | `FontMatcher.swift:8-10` | §11 0.86/0.70/0.03 | exactThreshold=0.86 / approxThreshold=0.70 / requireGap=0.03，与 §11 完全一致 | ✅ 无漂移 |
| 两级剪枝 | `FontMatcher.swift:70-99` | §2.2 两级 + topFamilyKeep=12 | 阶段1 family 粗筛取 top12 → 阶段2 精筛；两阶段同高 64（修复后） | ✅ |
| 碰撞阈值 | `CollisionDetector.swift:21-32` | §11 重载>2px | `threshold=2`，宽高均>2 计碰撞 | ✅ 一致 |
| LRU 掩码缓存 | `FontMatcher.swift:20-42,64` | §11 4000 条目 | MaskStore capacity=4000 | ✅ 一致 |
| 低对比抹除判据 | `TextEraser.swift:223-234` | P2 修复声明 | `maxDist∈(1e-3,0.25)` 按下探 `0.6·maxDist`；正常对比保持 0.25 不误伤 | ✅ 已修 |
| 抹除掩码梯度判据 | `TextEraser.swift:217` | — | `.gradient` 仍以 c0 作 bg 判据，强渐变掩码偏大 | ⚠️ 已知限制（见 §2.4） |
| 渐变相位对齐 | `TextRenderer.swift:131-136` | §2.7（理想的逐像素绝对坐标） | t 以**新字形自身 ink 区间**归一化，非源图绝对坐标/原 ink 区间 | ⚠️ 已知限制（见 §2.1） |
| 异步/取消 | `EditingWorkflow.swift:56,126-141,210-226` | §2.8 actor + generation | `@unchecked Sendable class`（非 actor）+ generation 语义取消；cancel/undo/redo 三入口 `generation &+= 1` | ⚠️ 偏差（P2-1，见 §2.2） |
| UInt8 越界防护（#1 修复） | `PixelMetrics.swift:94` | 系统性 clamp | 全包产品源码 8 处 `UInt8(` 转换**全部** `min(max(…,0),255)` 守卫（TextRenderer×3、Inpainter×3、PixelMetrics×1、ImagePixels×1） | ✅ 全路径覆盖 |

**契约常数整体判定：§11 全部可编程常数（0.86/0.70/0.03/0.5/2px/12/4000）实测零漂移。** 与 QA v0.1 §4 「契约常数无漂移」结论复核一致。

---

## 2. QA 遗留项逐条裁决

### 2.1 【P2·新发现】渐变相位对齐残余（gateE 接缝 0.299）— **Approve with comment（接受为 v0.2 已知限制）**

**技术判断（源码核实）**：`fillBackground` 归一化基准 = patch 自身 ink 区间（L131-136 `rel/inkW`，inkW=新字形 ink 宽），而不是源图像素平面上的绝对坐标/原 ink 区间。等宽改字时新字形 ink 宽 = 原 ink 宽，归一化后的相位与原图一致 → gateA 无接缝（0.9984）；一旦新文本长度骤变（gateE 200px→34px），patch 内渐变被**压缩/拉伸**到新 ink 区间，与周边真实渐变的相位错位，patch 边缘出现 RGB 0.30 量级接缝。

**为何接受为已知限制（不 Require fix）**：
1. **触发条件窄**：需「渐变背景 × 长度骤变」同时成立。等宽改字（无痕核心宣称）不受影响；平坦/纹理背景不受影响。
2. **非回归**：旧实现（平坦 c0 填充）在渐变场景整块 ~0.29 色差；新实现相位对齐是残余 ~0.30 仅在长度骤变边缘，净收益明确（QA 已论证）。
3. **修复属 v0.3 结构调整**：`BackgroundModel.gradient` 仅存 c0/c1/delta/axis，**未存源图上的归一化区间**；正确修法需把「原 ink 区间/bbox + patch 绝对坐标」穿进 renderer，属契约/数据模型改动，不宜在验收门禁内硬塞。
4. **口径**：QA 条件③已限定 P1 声明为「等宽改字渐变已修复」，长度骤变渐变复合不纳入「无痕」宣称——口径诚实。

**裁决：Approved-with-comment。登记为 v0.3 必修项（曲线：渐变归一化以原 ink 区间/bbox 为基准 + patch 绝对坐标对齐 + 补「短文本渐变 E2E」回归）。** 需 zongguan 在决策日志记录为 v0.3 范围并使 v0.2 交付口径含此披露。

### 2.2 【P2-1】彻底可取消（renderer/eraser 协作取消）+ actor 化 — **Approve with comment（明确排入 v0.3，不在 v0.2 追加）**

**技术判断**：
- **协作取消现状**：仅有 `Task.isCancelled` 检查点（FontMatcher stage2 循环 L89），CPU 密集渲染/抹除无检查点 → 非底层中断。QA 核实属实。
- **generation 语义**（三入口全覆盖 + `guard myGeneration==generation` 丢过期）在**单 UI 线程驱动**下已闭环「幽灵编辑」路径，v0.2 功能语义达标。
- **check-then-act 理论竞态**（L137 guard 通过→L138 赋值间另一线程 bump 可致幽灵挂起）：`@unchecked Sendable class` 无锁、单 UI 线程不可达，QA 已归入 P2-1。**不构成 v0.2 阻塞**，但这是「语义正确靠纪律、非类型保证」的确凿证据——actor 化正是要把它变为编译期不可构造。

**为何不追加到 v0.2**：actor 化是跨文件数据竞争模型重构（pendingEdit/generation/能力强隔离），影响面大、非本版功能缺陷；v0.2 以 generation 语义守住正确性红线。**列入 v0.3 架构项**。若 v0.2 之后出现多路并发调用方（非 UI 线程驱动），此条升级为 P1。

### 2.3 【P2】.gradient 抹除掩码 c0 判据偏大 — **Approve with comment（接受为已知限制）**

源码核实 `TextEraser.swift:217` gradient 分支取 c0 作 bg 判据；水平渐变下远离 c0 一侧的背景像素距 c0 远，会被误判为笔画 → 强渐变下掩码偏大、抹除范围过宽。触发条件 = 渐变背景（非平坦/低对比）。平坦/低对比场景已修（P2 自适应判据），渐变属遗留。**接受**，与 §2.1 同根（BackgroundModel 相位信息缺失），建议 v0.3 一并处理。

### 2.4 【P2】局部 patch 结构差异 — **Approve with comment（维持接受不修）**

复核 `BlockPatchBuilder.swift:94-123`：patch 为抹除后背景 + 不透明字形补丁，无跨边界滤镜路径；`compositeAfter` 无结构性泄漏。QA AlignDiag 峰值 0.53 属「局部口径 + 对齐搜索」类，非渲染缺陷。接受。**建议**：将「局部 patch 区 + 对齐 SSIM」设为永久回归口径（同时保留整图 SSIM），防止局部质量被整图稀释掩盖——这条是 v0.1 时就标注的「最可能漏测场景」。

### 2.5 【P2】测试体量 325s（U3 304s 串行）— **Approve（超出正确性范围，登记）**

非正确性阻塞。建议 v0.3 给 U3/U2 加并发/预渲染缓存，并评估 CI 超时护栏。若后续引入 CI 且超时导致流水线不可用，应升级处理。

### 2.6 【🟡】Tests/ 残留 5 个 QA_* 临时文件（15 用例 → 58 vs 43）— **建议 zongguan 决议清理**

源码级确认：`Tests/PxiuCoreTests/` 下确有 `QA_Reg_TempTests.swift`、`QA_AlignDiag{2,3,4,}Tests.swift` ×4，共 15 用例。影响：① CI/基线读数不可达（58 vs 交付 43），口径漂移风险；② 临时探针含 `[DIAG]`/`[QA]` print 污染测试日志；③ 临时文件夹带入交付物属工程卫生问题。

**技术判断：应在交付前清理**（红线内：清理动作由 zongguan 决策，本审查不代改）。清理后应重跑纯交付 43 全绿留证入库。若 zongguan 决定保留（如作开发诊断留存），需明确移出 `Tests/` 交付树并记录，避免基线混淆。**本条是唯一建议 Require 的清理动作，不改变代码 verdict。**

---

## 3. 测试覆盖评估（对照 PRD §6 验收）

| PRD §6 验收 | 交付用例覆盖 | 判定 |
|---|---|---|
| §6.1 打开图+OCR 显示块 | 状态机（EditorDocumentTests：loading/idle/noText→selected 转移）；OCR 探测经 E2E 管线 | ⚠️ 无独立 OCR 解析用例，靠状态机+E2E 间接覆盖 |
| §6.2 改字区域 SSIM≥0.95（ground-truth 口径） | 交付：`testEndToEndEraseRenderPatchMaterialize`；QA E2E：flat 0.953/0.987、dark 0.979、gradient 等宽 0.9984 | ✅ 证据链充分 |
| §6.3 抹除 | InpainterTests U6 flat/gradient/noise + `testLowContrastEraseAdaptiveThreshold` + E2E erase-only 1.000 | ✅ |
| §6.4 undo/redo | EditorDocumentTests（TextEdit/Geometry/Structural）+ EditingWorkflowTests（move/resize） | ✅ |
| §6.5 字体/字重保留 | FontMatcherTests U1（同字体识别≥90%）、U2（AA 鲁棒）、U3（字号回收） | ✅ |
| §6.6 导出分辨率一致 | ExporterTests（PNG/JPEG 分辨率+UTI） | ✅ |
| §6.x 无崩溃冒烟 | 全量 43 绿 + 9 套件；无 UI 100 次冒烟（环境无 GUI/XCTest，QA §9-7 环境约束） | ⚠️ 环境受限 |

**覆盖率口径说明（必须诚实披露）**：本交付**未运行行/分支覆盖率度量**（swift-testing 未启用 `--enable-code-coverage`，报告无覆盖百分比数值）。「>80%」标准在当前证据下为**由用例数量+9 套件模块全覆盖+E2E 端到端证据链支撑的推断，而非实测指标**。核心计算链路（抹除/渲染/匹配/fit/碰撞/导出/undo）均有对应用例，覆盖率推断成立，但**建议 zongguan 在验收记录中明确「覆盖率按测试资产覆盖而非数值门禁」**，或要求补一次 `swift test --enable-code-coverage` 实测后再定 v1 门禁值。这是本审查对「>80%」标准的唯一保留。

**QA 合成样本 E2E 是否构成充分证据链**：是。理由：ground-truth 按生产同路径（FitCalculator 适配字号 + 基线锚定 + 居中 + 同渲染后端）原生渲染，对照对象与 tech_spec §6.3 严格一致；float/渐变/深色/等宽渐变全覆盖；对齐搜索排除平移假象。**局限**：合成图无真实截图噪声/纹理样本（§6.4 真实样本人工判定未在本验收执行——无 GUI/样本集），这是持续环境约束，非本版修复引入，建议 v1 前补。

---

## 4. 发现缺陷清单（按严重级）

### P0 — 无

### P1 — 无（v0.1 的唯一 P1「渐变平坦 c0」经 QA gateA~E + 源码核对确认已修复，回退门禁通过）

### P2（全部为非阻塞已知限制/架构遗留，已在 QA §9 登记）
| # | 缺陷 | 位置 | 影响 | 建议 |
|---|---|---|---|---|
| 1 | 渐变相位对齐残余（长度骤变接缝） | `TextRenderer.swift:131-136` | 渐变背景×长度骤变时 patch 边缘 0.30 色差 | v0.3：原 ink 区间归一化 + 绝对坐标对齐 |
| 2 | 抹除掩码 gradient 用 c0 判据掩码偏大 | `TextEraser.swift:217` | 强渐变抹除范围过宽 | v0.3 随相位修复一并处理 |
| 3 | 非 actor + renderer/eraser 非协作可取消 | `EditingWorkflow.swift:56` + Render/Erase | 并发调用方非类型安全保证 | v0.3 actor 化 + 协作取消 |
| 4 | 局部 patch 区 SSIM（0.5~0.59）口径 | `BlockPatchBuilder.swift` | 局部质量度量易被整图稀释 | 设「局部+对齐 SSIM」为永久回归项 |
| 5 | 测试体量 325s（U3 304s 串行） | `FontMatcherTests`/`EstimationTests` | CI 超时风险 | v0.3 加并发/缓存；CI 护栏 |
| 6 | erase-only（删除成空文本）被 `emptyText` 拒绝 | `EditingWorkflow.swift:147-148` | 用户「整段删除」意图 v1 不支持 | 与 PRD FR-6 抹除语义存在口径缺口，需 zongguan 裁决（见 §5） |

### 🟡（工程卫生）
- `Tests/` 残留 5 个 QA_* 临时文件（15 用例）——建议交付前清理（§2.6）。

---

## 5. 需 zongguan 决策事项清单

1. **QA_* 残留清理**（§2.6）：是否交付前移出 `Tests/` + 重跑 43 全绿留证。**建议：是**。
2. **erase-only 支持与否**（缺陷 #6）：v1 是否允许「把文字删成空/删除」？当前 `emptyText` 拒绝整段删除。若无此需求则维持现状并在 PRD 明示「删除=改为空白不允许，需扩大块或接受残留」；若有需求则列入 v1.1。
3. **v0.3 范围登记**（§2.1/2.2/2.3）：渐变相位对齐 + 抹除掩码 c0 判据 + actor/协作取消一并排入 v0.3，决策日志记录。
4. **覆盖率门禁口径**（§3）：验收记录明确「覆盖率按测试资产覆盖（非数值门禁）」或补 `--enable-code-coverage` 实测后再定 v1 门禁。建议本次先以资产覆盖口径放行。
5. **真实截图人工判定（§6.4）缺失**：是否在 v1 前补 20-30 张真实样本人工目测（需样本集 + 至少 3 人）。建议列入 v1 预发布门禁。
6. **v0.2 交付口径声明**：确认对外宣称限于「等宽改字无痕（SSIM≥0.95）+ 平坦/低对比抹除」，不宣称「渐变任意长度改字无痕」（QA 条件③）。

---

## 6. 最终 Verdict

> **✓ Approve（有条件）** —— 代码与 tech_spec §2.7/§2.8/§11 契约一致，全部可编程常数零漂移；P1（渐变逐像素复合）回退门禁经 QA 独立亲跑 + 源码级核对确认修复；UInt8 越界类崩溃已全路径系统性 clamp；43 交付用例全绿并叠加 QA 合成 E2E 证据链，核心 PRD §6 验收项均有对应测试资产覆盖。P2 各项（渐变相位对齐、非 actor 取消、gradient 抹除 c0 判据）接受为 v0.2 已知限制并排入 v0.3，不阻塞本版验收。**条件**：① §5 六项 zongguan 决策完成（尤其 QA_* 残留清理 + v0.2 交付口径声明）；② v0.3 必须兑现 §2.1/2.2 架构遗留项。

---

## 7. 「最可能被挑战的假设」自审段

> 我判 **Approve** 的整条依据链，最可能被推翻的一环是：

**「QA 合成 E2E（SSIM≥0.95，ground-truth 同路径）足以构成 v0.2『无痕保真』的充分证据」这一前提。**

**为什么它可能错（攻击者视角）**：
1. **度量对象同源自证陷阱仍在**：QA 的 ground-truth 与**生产渲染共用同一 FitCalculator/TextRenderer 路径**。若渲染器存在**系统性偏差**（比如基线/字号/间距的固定错误），ground-truth 与结果图会**同错同偏**，SSIM 仍可能虚高——「自证」不能暴露「双方都对但都不对」的偏差。AOI SSIM 只能测「结果像 oracle」，测不出「oracle 本身是否代表真·原生渲染」。
2. **合成图无真实噪声/纹理/2x Retina 缩放插值噪声样本**：真实截图有压缩噪声、非整数缩放、subpixel 色边（深度模式），这些会让真实 SSIM 显著低于合成 0.95。正是 P2-3 局部 patch 0.5~0.59 与整图 0.95 的巨大反差所暗示的现象——局部质量可能被大面积未改背景稀释。我没有真实样本验证「局部无痕」在真实图上成立。
3. **覆盖率无数值证据**：>80% 是推断不是实测，若 zongguan 严格执「>80% 数值」口径，本 Approve 依据即打折。

**若此假设被推翻的降级**：Approved-with-comment 降为 Request Changes（需补真实样本局部 SSIM 或真实样本人工目测 + 独立 oracle 交叉验证）。**缓解**：本审查已把这条显式化（§3 诚实披露 + §5-5 建议补真实样本），使风险可见、由 zongguan 定夺，而非我单方面默认成立。

---

## 附录：审查手法自证

- 本次审查**零代码修改**（含 QA_* 残留文件——清理决策归 zongguan）；仅 Read 源码与文档。
- 契约常数核对为源码级（grep/Read 直读 `FontMatcher.swift:8-10`、`FitCalculator.swift:11`、`CollisionDetector.swift:21`），非转述。
- 所有 P1/P2 裁决均以 QA 独立亲跑输出（§0/§2 证据）为底，本报告只补源码级定位与质量判断。
