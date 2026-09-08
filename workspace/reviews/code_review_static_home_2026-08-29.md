# 代码审查报告 — 首页静态化（static_home）

- **日期**: 2026-08-29
- **角色**: @dana（技术负责人）
- **项目**: pxiu macOS 应用（SPM）
- **改动级别**: L1（2 文件，微调级）
- **审查对象**:
  1. `pxiu/Sources/PxiuApp/EditorState.swift`（第 45 行 phase 初始值 `.loading → .idle`）
  2. `pxiu/Sources/PxiuApp/HomeView.swift`（body 去 phase 读取；静态图分支 + dropArea 回退；删 loadingIndicator；新增 homeImagePath）
- **基线文档**:
  - QA 报告: `workspace/qa/qa_report_static_home_2026-08-29.md`（shouye, PASS）
  - 需求意图（CEO）: 首页静态展示；不转圈；不显示"正在打开图片"；显示 `/Users/evandy/Desktop/backup/shy.jpg`；缺图回退
- **审查方式**: 只读审查，未修改任何源码。核查了 `phase` 全部 37 处引用、`ProgressView` 全部 4 处命中、`EditorDocument` 全部引用、`AppModel.open/openPanel/goHome` 全流程。

---

## 1. 需求一致性 —— PASS

四点逐一核对：

| 需求点 | 证据 | 结论 |
|---|---|---|
| 首页静态展示 | `RootView`（PxiuApp.swift:84-89）：`isShowingEditor=false` → `HomeView()`；`AppModel.isShowingEditor` 初始 `false`（:15），启动即首页 | ✅ |
| 不转圈 | grep `ProgressView` 全源码仅 2 处：InspectorView.swift:135（编辑器内样式分析）、OverlayViews.swift:122（选中块 ProcessingBadge）——均非首页路径。HomeView 无任何进度视图；旧 loadingIndicator 已删 | ✅ |
| 不显示"正在打开图片" | 全源码 grep `正在打开` = 0 命中 | ✅ |
| 显示 shy.jpg | `if let image = homeImage { homeImageView(image) }`（HomeView.swift:27）；`homeImage` 经 `fileExists` + `NSImage(contentsOfFile:)` 双检（:19-22）；文件实测存在（2,472,884 B，3264×1376 可解码） | ✅ |
| 缺图回退 | 任一检查失败 → `homeImage == nil` → `dropArea`（拖拽 + 打开按钮 + formatNote 完整保留，:84-98） | ✅ |

**无过度实现**。改动严格限定 2 文件（QA 时间戳双证据确认），Style / Core / 测试均未动。

**一处行为退化（非需求违反）**：静态图分支的 `homeImageView` 未挂 `dropDestination`——原 dropArea 的"拖文件到窗口打开"能力在静态图模式下失效（拖拽落点在图片上无反应）。打开路径仍可用：文件菜单 Cmd+O（PxiuApp.swift:51）。属便捷性退化，见问题 #3。

## 2. 根因修复正确性 —— PASS

`EditorState.swift:45` `var phase: EditorPhase = .idle`：

- **open() 流程不受影响**：`open(url:)` 第一行显式 `phase = .loading`（:373）→ 完成 `.idle`/`.noText`（:388）→ 失败 `.idle`（:394）。初始值只是首帧兜底，打开路径全程显式赋值。✅
- **全部 phase 消费者核查（37 处引用）**：

| 消费者 | 位置 | 初始 .idle 影响 |
|---|---|---|
| `selectedBlockID` | EditorState.swift:81-84 | `.loading` 与 `.idle` 均返回 nil，等效，无影响 |
| `select()` | :119-121 | idle 时无 textBlocks，`:118` guard 阻止空选，安全 |
| `deleteBlock` / `settleAfterMutation` 等转移 | :226-283 | 均从具体态 guard 进入，初始值无关 |
| InspectorView | InspectorView.swift:40,107 | 编辑器内才渲染，首页不可达 |
| CanvasView | 不引用 phase（grep 0 命中） | 无影响 |
| `EditorDocument.phase`（Core 层，仍初始 `.loading`，未改） | EditorDocument.swift:8 | 仅被 `Commands`（undo 命令）/ `EditingWorkflow:109` 读取，**UI 层零引用**，不会驱动任何转圈。Core/UI 初始值不一致在 open() 显式赋值下无回归 |

**结论：修复正确、无回归风险。** 首页不再读 phase（HomeView body 仅依赖 `homeImage`）+ 初始值兜底 `.idle`，双保险。

## 3. 回退健壮性 —— PASS（附条件）

- 文件被移动/删除 → `fileExists` false → 顺滑回退 dropArea ✅
- `NSImage(contentsOfFile:)` 解码失败 → nil → 回退 ✅（含损坏图场景，双检正确）
- **硬编码绝对路径依赖（条件项）**：`/Users/evandy/Desktop/backup/shy.jpg` 为 CEO 本机路径。**发布的 dmg 未内嵌该图**（QA 打包未将图放入 bundle），换机器/换用户运行 → 图不存在 → 回退拖拽区。行为安全（不崩、不转圈），但"首页显示 shy.jpg"在发布环境不成立。当前为 CEO 临时指定 + 注释已标明，**alpha 阶段可接受**；正式发布前必须换成 bundle 资源（见问题 #1，挂条件）。

## 4. 静态图实现质量 —— PASS（含性能建议）

- **scaledToFit 不变形**：3264×1376（宽高比 2.37:1），minWidth 900 窗口下以宽为限（900 − 2×xl padding）等比缩放高约 360pt，居中，无拉伸。QA 已核实。✅
- **主线程重复解码（建议项）**：`homeImage` 是**计算属性**，每次 body 求值（窗口 resize、model 任意变化、系统刷新）都重新执行 `fileExists` + `NSImage(contentsOfFile:)` 全量解码 2.4MB。SwiftUI body 求值频率远高于 QA 报告的"每次 appear"。resize 窗口时可能感知卡顿。参见问题 #2。
- 视图代码简洁，无多余修饰，`scaledToFit` + `frame(max…)` + padding 组合正确。✅

## 5. 风格一致性 —— PASS（轻微）

- `DS.Spacing / DS.Typeface / DS.Color / DS.ease` 统一使用，与 dropArea/formatNote 同级风格 ✅
- taste-skill：静态图全幅居中、无营销堆砌、克制 ✅；`formatNote` 保留在图下（tertiary 小字）为信息性 footer，可接受
- **minor**：HomeView.swift:5 头注释仍写 `（home_empty / home_loading）`，loading 态已不存在，注释过时（问题 #4）

## 6. 测试覆盖 —— PASS（含补漏）

QA 报告质量高：改动范围时间戳双证据、debug/release 构建、启动/存活/无崩溃/退出、回退代码级审查、打包 dmg 全套（签名/架构/挂载冒烟）。**QA 引用的行号与源码逐一核对一致，无虚报。**

- 已覆盖主要分支：静态图命中分支（代码级）、回退分支（代码级）、open() 流程（:372-394 核对）
- **已知阻塞**：GUI 截图受屏幕录制 TCC 权限环境限制（非产品缺陷），代码级证据已充分兜底，认可
- **补漏 1 项**：静态图分支下窗口拖拽无反应（dropDestination 仅存在于 dropArea 分支）——QA 的"dropDestination 保留"断言只验证了 dropArea 分支，未验证静态图命中时的窗口拖拽行为。属本次行为变化，需求层面不违反，已列问题 #3。

---

## 7. 发现问题清单

### 条件项（本次可验收，正式发布前必须处理）

**#1 硬编码绝对路径 → 发布环境回退** — `HomeView.swift:17`
- 影响：dmg 在其他机器运行时 `homeImage == nil` → 回退拖拽区，"首页显示 shy.jpg"只在 CEO 本机成立。
- 建议：正式发布（非 alpha）前将图移入 bundle 资源（`Resources/` + `Bundle.main.url`）或 SDK/用户可配置路径；届时 `homeImagePath` 改为资源路径，回退语义不变。
- 当前阶段判定：注释已声明"CEO 临时指定"，alpha 流程可接受。

### 建议项（不阻塞，下轮优化）

**#2 homeImage 每次 body 求值重解码主线程** — `HomeView.swift:19-22`
- 影响：窗口 resize / model 变化触发全量解码，2.4MB 本机约几十 ms，极端 resize 连续触发可感知卡顿；换大图后放大。
- 建议：结果缓存到 AppModel（bundle 资源化后的自然位置）或进程级缓存：
  ```swift
  // 示意：AppModel 缓存（与 #1 合并推进）
  private(set) var homeImage: NSImage?   // open 时一次性解码；文件删除时置 nil 触发回退
  ```
  若保留"文件删了立即回退"语义则每次检 fileExists（便宜），只缓存解码结果（贵）；若接受会话级固定图，则 static let 一次性解码即可。

**#3 静态图分支无 dropDestination，窗口拖拽打开失效** — `HomeView.swift:38-44`
- 影响：拖文件到静态图上无反应（原 dropArea 可拖）。打开路径仍有菜单 Cmd+O，非功能缺失，属便捷性退化。
- 建议：`homeImageView` 挂同一 `dropDestination` + `isTargeted`（视觉反馈可做 subtle 高亮或不做，保持克制）；或将整窗（RootView）挂 drop 统一处理。下轮随 #1 一起做。

### minor 项

**#4 头注释过时** — `HomeView.swift:5`
- `（home_empty / home_loading）` → loading 态已删，建议改 `（home_static / home_empty）`。

---

## 8. 结论

**Approve(conditional)**

- 核心需求四点（静态展示 / 不转圈 / 不显示"正在打开图片" / 显示 shy.jpg / 缺图回退）全部满足；
- 根因修复（`EditorState.swift:45` `.idle`）正确，open() 显式赋值不受影响，全部 phase 消费者无回归；
- 无阻塞级缺陷，QA 阻塞项（截图 TCC 权限）为环境限制且代码级证据充分；
- **条件**：`HomeView.swift:17` 硬编码绝对路径必须在**正式发布**（非 alpha）前替换为 bundle 资源，否则发布环境将回退拖拽区、不显示 shy.jpg；
- **Follow-up 建议**：重解码缓存（#2）、静态图挂拖拽（#3）、注释修正（#4）。

---

## 汇报要点（@zongguan）

- **结论**：Approve(conditional)——本次改动可验收，CEO 本机需求四点全满足。
- **关键发现**：根因修复无回归（37 处 phase 引用 + 2 处 ProgressView + Core EditorDocument 全核查）；QA 行号引用与实际源码一致，证据可信；唯一行为退化是静态图模式窗口拖拽无反应（菜单打开仍可用）。
- **条件项**：hardcode 桌面路径仅 alpha 可接受；出正式发布版前必须 bundle 资源化，否则换机器即回退拖拽区。建议排入下轮迭代。
- **阻塞项**：无（QA 截图阻塞为环境 TCC 权限，非代码缺陷）。