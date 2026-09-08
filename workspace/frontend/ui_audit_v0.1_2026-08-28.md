# UI 审计报告 — 截图文字无痕修改工具（pxiu）

- 日期：2026-08-28
- 撰写：xiaoyou（前端工程师）
- 版本：v0.1
- 关联：`page_states_pxiu_2026-08-28.md`（§3 编辑器状态 / §5 转移约束）、`tech_spec_pxiu_2026-08-28.md`（§1–§5）、`prd_pxiu_v0.1_2026-08-28.md`
- 消费者：shouye（QA，测试前必读）、dana（审查）
- 构建验证：`swift build --target PxiuApp` → **0 error / 0 warning**（PxiuCore 侧 warning 属 zhenhai 域）

---

## 1. 范围与目标

本报告为配合 zhenhai 的实际 `PxiuCore` 编译，对 UI 薄壳层（`Sources/PxiuApp/`）做契约对齐审计。UI 遵循指纪律：克制创作工具美学、无 AI 渐变、自适应浅/深色（NSColor 语义）、对比度优先、简体中文界面文案。

### UI 目标物（已随本次审计实现/对齐）
- `EditorState.swift` — 单根 @Observable 状态对象，五态 + 四叠加
- `CanvasView.swift` — 画布 + 文字块覆盖层 + 缩放平移 + 添加框选 + 碰撞/低置信度标记
- `InspectorView.swift` — 检查器（内容 / 样式 / 反馈条）
- `ToolbarView.swift` / `HomeView.swift` / `OverlayViews.swift` — 工具栏、主页、叠加层
- `UndoRedo.swift` — 撤销/重做命令族（UI 前缀，避 Core 符号冲突）
- `Style.swift` / `SystemFonts.swift` / `Feedback.swift` — 设计 token 与反馈映射
- `PxiuApp.swift` — App 入口 + 根布局 + CommandMenu

---

## 2. 状态覆盖率矩阵（对照 page_states §3）

| 状态（page_states） | Core 枚举（`EditorPhase`） | UI 实现 | 覆盖 |
|---|---|---|---|
| editor_loading | `.loading` | `open(url:)` 置 loading，Task 内解码/OCR | ✅ |
| editor_idle | `.idle` | OCR 完成、blocks 非空 → idle；selection=nil | ✅ |
| editor_selected | `.selected(UUID)` | `select(blockID:)` | ✅ |
| editor_preview | `.preview(UUID)` | `beginPreview(_:)`（仅内容变更进入） | ✅ |
| editor_notext | `.noText` | blocks 为空 → noText | ✅ |

### §5 转移约束逐条核对
1. **loading 禁选中** — `select(blockID:)` 显式 `switch phase { case .loading: return }` ✅
2. **idle→selected 仅经点击有效块** — 画布 `BlockInteractor` `.onTapGesture { state.select }`，`select` 校验块存在 ✅
3. **selected→preview 仅内容变更、样式变更不触发内容重绘** — `beginPreview` guard `draft.newText != block.text`；`applyStyleOverride` 不回退 phase、不触发重绘 ✅
4. **notext 下添加块成功直达 selected（无悬空）** — `addBlock(_:)` 设 `phase = .selected` ✅
5. **所有 overlay 不阻断编辑主链路** — 叠加态为独立属性传递，不拦截交互 ✅

### 四叠加态（Core `EditorOverlay`）
| 叠加 | Core 枚举 | UI 呈现 | 覆盖 |
|---|---|---|---|
| processing | `.processing(UUID, PipelineStage)` | `OverlayBar` 局部进度 | ✅ |
| font_mismatch | `.fontMismatch(UUID, FontMatchResult)` | 黄色近似匹配条 | ✅ |
| export_success | `.exportSuccess(URL)` | 成功条 + 路径 | ✅ |
| export_error | `.exportFailure(String)` | 错误条 + 重试 | ✅ |

---

## 3. 交互覆盖率

| 交互 | 载体 | 实现 | 覆盖 |
|---|---|---|---|
| 打开/拖拽图片 | HomeView + CanvasView onDrop | NSOpenPanel + 文件 URL | ✅ |
| 画布缩放 | magnifyGesture + scaleEffect | ✅ |
| 画布平移 | DragGesture（非添加模式） | ✅ |
| 点击选中 | BlockInteractor onTap | ✅ |
| 拖拽移动块 | BlockInteractor drag → `moveBlock` | ✅ |
| 角柄缩放 | BlockInteractor 角落拖拽（几何 undo） | ✅ |
| 添加文字块 | 添加框选模式 → `commitAddBlock` | ✅ |
| 删除/合并 | 工具栏/检查器 → `deleteBlock` / `mergeBlocks` | ✅ |
| 撤销/重做 | CommandMenu(⌘Z / ⇧⌘Z) → `undo()` / `redo()` | ✅ |
| 导出 PNG/JPEG | CommandMenu(⇧⌘E) → `export(format:)` | ✅ |

---

## 4. 视觉方向与设计系统

- 布局：单窗口（工具栏 48pt + 画布/检查器 300pt + 叠加条）
- 色板/字号/间距/圆角 token 统一收口在 `DS.*`（`DS.Color`=SwiftUI `Color`，`DS.NSColor`=AppKit 原始，双命名空间；`DS.Typeface`、`DS.Spacing`、`DS.Radius`、`DS.spring`）
- 交互常量（BlockInteractor 阈值、拖拽灵敏度）归 `DS.Gesture`
- 详细设计 token 另文：`design_system_v0.1.md`

---

## 5. 与 PxiuCore 契约一致性与偏差

本次审计针对 zhenhai 实际落地的 Core 逐项核对了签名：

| 项 | 结论 | 处理 |
|---|---|---|
| `EditorPhase` `.noText`（非 `.notext`） | Core 用 `.noText` | UI 已统一 `.noText` |
| `EditorOverlay` `.processing(UUID, PipelineStage)` 等 | 与 UI 一致 | 复用 Core 枚举 |
| `TextBlock.detectedText` 非 Optional | UI 原先 `if let` 错 | 已改非 Optional 判空 |
| `TextBlock` 初始化签名 | `TextBlock(text:detectedText:bbox:confidence:perCharBoxes:style:status:)` | 已对齐（含 status `.userAdded`） |
| `RGBColor` 分量 0…1 Double | 与 QD Quickdraw 同名类型有歧义 | 显式 `PxiuCore.RGBColor`；`rgb(from:)` 分量 0…1 |
| `SourceImage` / `ImageLoader.load(url:)` / `TextBlockDetector.detect(in:configuration:)` | 与调用一致 | 直连 Core 打开链路 |
| `Exporter.export(_:format:to:)` / `ExportFormat` | `.png` / `.jpeg(quality:)` 一致 | 直连 Core 导出链路 |
| `CollisionDetector.collisions(with:in:excluding:)` | 签名一致 | UI 薄封装调用 |
| `FontMatchResult` / `MatchStatus` / `StyleWarning` / `FontFace` / `TextStyle` | 与 UI 反馈映射一致 | ✅ |
| `StyleWarning` 非 Hashable | UI 原用 Dictionary 索引 | 改为 switch 分支取标签 |
| `any Gesture` 条件返回 | SwiftUI 需具体类型 | 重构为单 DragGesture 分支处理 |

### 5.1 命名规避（符号冲突）
Core 已导出 public `DocumentCommand`/`TextEditCommand`/`BlockStructuralCommand`/`StyleOverrideCommand`，UI 侧撤销命令族以 `UI` 前缀命名（`UIDocumentCommand` 等），避免 PxiuApp 内定义冲突。

---

## 6. 已知缺口与阻塞项（需 zhenhai / zongguan 协调）

### 🔴 阻塞（阻断完整流水线）
1. **`EditingWorkflow` / EditorWorkflow 不存在** — `Sources/PxiuCore/Workflow/` 为空。`open` 目前直连 `ImageLoader`+`TextBlockDetector` 可真实 OCR；但**抹除+重绘预览（editor_preview）与风格分析**尚未接入真实 patch 管线，`previewFit` 采用占位拟合（保守宽度启发式），待 Core Workflow 就绪后替换。
   - 影响：editor_preview 的可视"抹除+重绘"为占位，尚未端到端真素材。

### 🟡 需协调（不阻塞编译，影响语义/体验一致性）
2. **`EditorDocument.phase` 为 `private(set)`，且缺 confirm→idle 转移** — UI 侧 `confirmPreview` 需要把 preview→idle 的"物化+入栈"语义与 Core 对齐。当前 UI 用自身命令栈（UICommand）承载撤销，未耦合 Core `EditorDocument` 的栈，以保持 D-009（含 geometry undo）完整覆盖。建议 Core 补齐 `confirm()` 与 `BlockGeometryCommand` 后桥接（见 6.1）。
3. **D-009 geometry undo** — Core 无 geometry 命令，UI 侧 `UIBlockGeometryCommand` 自洽实现，覆盖拖拽/缩放撤销；Core 就绪后建议收敛。
4. **XCTest 环境缺失** — 本机仅 CommandLineTools，无 `XCTest` 模块，`swift test` 无法运行（`no such module 'XCTest'`）。属 shouye 测试环境前置问题，非代码错误。`swift build`（含 PxiuApp 链接）全绿。

### 6.1 Core 落地后建议的 UI 收敛点
- 移除 `UIBlockStructuralCommand` 的 `merge` 特化，改用 Core `BlockStructuralCommand(add:block:)` 语义（若 Core 补充 merge 命令）。
- 将 UI 撤销栈切换委托给 Core `EditorDocument.commit/undo/redo`（含内存预算复用），保留 UI 侧仅承载 Core 尚未覆盖的 geometry。

---

## 7. 验证

- `swift build --target PxiuApp` → **0 error / 0 warning**（本文件所有状态均经真实 Core 编译）
- `swift build`（全包）→ 仅 PxiuCore 侧 warning（zhenhai 域），PxiuApp 无 warning
- `swift test` → 环境阻塞（无 XCTest，见 §6-4）

## 8. 建议 QA 重点（供 shouye）
- §5 五条转移约束逐条实测
- noText 添加闭环
- selected→preview 仅内容变更触发；样式调整不触发内容重绘
- 撤销/重做跨命令族（内容/几何/结构/样式）行为
- overlay 不阻断编辑主链路
- 浅色/深色两套语义色对比度

---

*（xiaoyou 产出，文档链第 5 环；待 shouye qa_report 与 dana code_review 后交付）*
