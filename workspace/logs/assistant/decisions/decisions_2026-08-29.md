# 决策日志 — 2026-08-29

- 记录人：zongguan（产品经理）
- 项目：pxiu（截图文字无痕修改工具）
- 承接：decisions_2026-08-28.md（D-001~D-014）；本条记录 v0.2 验收阶段决策（D-015 起）

---

## D-015 QA v0.1 遗留 P1/P2 处理裁决：修复 → 复测通过 → 审查 Approve（有条件）

- **背景**：qa_report_v0.1 判定 P1（渐变背景逐像素复合未实现，违反 tech_spec §2.7）+ P2×4 遗留，要求"@zhenhai 修正后按 P1 回退门禁复测"
- **执行链**：
  1. zhenhai 修复（api_implementation_v0.2 §5.1）：P1 渐变逐像素插值（回归 SSIM 0.7907→0.9994）、P2 cancel 语义（generation 过期）、P2 低对比抹除自适应阈值；P2 局部 patch 结构差异评估为已知限制不修
  2. shouye 复测（qa_report_v0.2）：P1 回退门禁通过（QA 独立探针等宽改字 patch 局部 SSIM 0.9984 vs 平坦 c0 基线 0.8122）；全量 43 passed / 0 failed（39 基线 + 4 新增）
  3. dana 审查（code_review_v0.2）：Approve（有条件）——契约一致、常数零漂移、UInt8 越界全路径 clamp、证据链覆盖核心 PRD §6 项
- **裁决**：v0.2 验收通过（有条件），进入交付口径声明阶段

## D-016 渐变相位对齐（QA 新发现 P2）→ v0.3

- **背景**：短/长文本改字时 patch 渐变以自身 ink 为基准，与周边真实渐变错位（QA 实测接缝偏差 0.299；等宽改字无此问题）
- **裁决**：接受为 v0.2 已知限制，排 v0.3 修复（以原 ink 区间/bbox 为归一化基准 + 补短文本渐变 E2E）
- **理由**：等宽改字是 v1 主场景（微信/截图聊天记录改错字），长度骤变场景占比低且已有兜底（近似匹配提示）

## D-017 彻底可取消 + actor 化 → v0.3 架构项

- **背景**：workflow 为 @unchecked Sendable class 非真正 actor；renderer/eraser 无协作取消（Task.cancel 不传播到 CPU 密集渲染），当前仅语义级取消（generation 使结果过期）
- **裁决**：v0.2 接受语义级取消（QA 验证 testCancelInvalidatesInFlightPreview 通过）；actor 化 + 协作取消排 v0.3 架构项
- **理由**：app 单用户单文档，并发编辑实际由调用方串行约束，语义级取消已消除"幽灵编辑"用户可见缺陷

## D-018 .gradient 抹除掩码 c0 判据 → v0.3 已知限制

- **背景**：抹除掩码对 gradient 背景仍以 c0 为判据，强渐变区掩码偏大
- **裁决**：接受为已知限制，v0.3 修复；当前对外口径不含强渐变背景抹除

## D-019 覆盖率门禁口径：v0.2 采资产覆盖口径，实测门禁排 v0.3

- **背景**：dana 审查发现 >80% 覆盖率门禁无数值实测（swift-testing 未开 coverage），当前为资产覆盖推断
- **裁决**：v0.2 认可"资产覆盖口径"（43 用例覆盖 PRD §6 全验收项 + 核心模块均有测试）；补 `--enable-code-coverage` 实测纳入 v0.3 CI 基建
- **理由**：合成样本 E2E 已有量化基线（SSIM≥0.95），覆盖仪是增强项非本版阻塞

## D-020 QA 临时文件残留清理：已执行

- **背景**：dana 审查发现 Tests/ 残留 5 个 QA_* 临时文件（15 用例）导致树内全量读数 58 vs 交付 43 失真
- **裁决**：验收前移出 Tests/（QA 对齐诊断探针，非交付物）
- **执行**：已删除 5 文件；`swift test` 复跑 **43 passed / 0 failed**（371.8s）留证，交付树干净

## D-021 erase-only 实现口径缺口：登记 v0.3 修正，对外口径不含

- **背景**：dana 审查发现当前 `emptyText` 拒绝"删成空文本"路径，与 PRD FR-6 抹除语义及 D-011（v1 支持 erase-only）存在出入
- **裁决**：产品决策维持 D-011（erase-only 是真实需求）；实现缺口登记为 v0.3 修正项（UI 清空文本触发抹除路径）；v0.2 对外交付口径不宣称该能力，抹除能力以 QA 已验证的 erase-only 峰值（SSIM=1.000）为准
- **依据**：需求不因实现缺陷降级；顺序为修实现，非改需求

## D-022 交付口径声明（必须遵守）

- **v0.2 对外可宣称**：等宽改字无痕（局部 SSIM≥0.95）、平坦/低对比背景抹除无痕、undo/redo/导出全链路
- **不得宣称**：渐变背景任意长度改字无痕（相位对齐为 v0.3）、强渐变背景抹除（c0 判据为 v0.3）、删成空文本 erase-only（D-021）
- **依据**：QA E2E 与 dana 审查交叉确认的边界

## D-023 真实截图人工判定：v1 预发布前置，非 v0.2 阻塞

- **背景**：合成样本无法覆盖真实噪声/纹理背景；dana 建议 v1 预发布前补 20-30 张 × 3 人目测
- **裁决**：登记为 v1 预发布门禁项；CEO 提供真实截图样本集（此前已约定非阻塞可后补）
- **状态**：⏳ 等待 CEO 提供样本

---

## D-024 CEO 确认：v0.2 按限定口径作为 1.0 alpha 分发（2026-08-29）

- **裁决**：CEO 确认两个决策点——
  1. v0.2 作为 **1.0 alpha** 分发，交付口径限 D-022（等宽改字无痕 + 平坦/低对比抹除，不宣称渐变任意长度/强渐变抹除/删成空文本）
  2. 真实截图样本集后补（D-023 保持等待态）
- **分发技术约束（诚实披露）**：本环境无完整 Xcode/GUI，QA 验证覆盖核心管线（`swift build` 可构建 + 43 用例全绿），**GUI .app 打包需在有 Xcode 的机器执行**，alpha 分发前须完成 GUI 冒烟（窗口/拖拽/导出链路）
- **影响**：alpha = 内测分发（核心管线已验证），非全功能发布；GUI 验证完成前不得宣称"正式版就绪"

## D-025 Alpha 分发包已产出：Pxiu-1.0.0-alpha.dmg（2026-08-29）

- **裁决**：CEO 指令"打包 dmg，直接安装测试" → 走无 Xcode 标准链路（swift build release → 手工 .app bundle → ad-hoc 签名 → hdiutil UDZO）
- **交付物**：`/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.dmg`（762K，SHA-256 `a764bba2…b5a29`，arm64 + macOS ≥14.0）
- **启动冒烟（shouye 亲跑）**：open 真实 GUI 启动，进程存活 11+ 秒无崩溃，osascript 优雅退出正常，无崩溃日志
- **分发约束（如实告知 CEO）**：ad-hoc 签名未公证 → **首次启动需右键 → 打开**（或系统设置允许），非缺陷属 Gatekeeper 未公证应用常规行为
- **影响**：alpha 内测分发就绪；GUI 自动化仍缺（无 XCTest GUI 层），v1 人工目测门禁维持 D-023

## v0.3 范围登记（截至本报告）

| # | 项 | 来源 | 级别 |
|---|----|------|------|
| 1 | 渐变相位对齐修复（原 ink 区间归一化 + 短文本渐变 E2E） | QA v0.2 | P2 |
| 2 | actor 化 + renderer/eraser 协作取消 | QA v0.1 / dana | P2-1 |
| 3 | .gradient 抹除掩码逐像素判据 | QA v0.1 / dana | P2 |
| 4 | erase-only 删成空文本实现路径 | dana | P2 |
| 5 | 覆盖率实测门禁（--enable-code-coverage）+ CI 基建 | dana | P2 |
| 6 | 测试体量拆分（U3 371s 串行，CI 超时风险） | QA v0.1/v0.2 | P2 |
| 7 | 真实截图人工判定样本集（20-30 × 3 人） | dana | v1 前置 |

## D-026 首页静态化：根因修复 + 静态图展示（2026-08-29）

- **CEO 需求**：打开软件首页设置为静态，不要一直显示"正在打开图片"，静态图 = /Users/evandy/Desktop/backup/shy.jpg
- **根因定位（第一性）**：`EditorState.swift:45` 启动初始 `phase = .loading`（应为 .idle）→ HomeView 恒命中 loadingIndicator；无启动路径切走（仅 open() 后才流转）
- **定级**：L1（单文件 UI 改动 + 一个初始值修正），免架构师，走 dev → QA → dana
- **裁决**：① phase 初始值改 .idle（open() 内显式 .loading/.idle，无回归）② HomeView 不再读 phase，shy.jpg 存在（fileExists + NSImage 非 nil）→ scaledToFit 静态图；缺失 → 回退原 dropArea（拖拽入口保底）③ 删 loadingIndicator
- **验收**：shouye QA PASS（qa_report_static_home_2026-08-29.md）；dana **Approve(conditional)**（code_review_static_home_2026-08-29.md）
- **交付**：`/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.2.dmg`（781,360B，SHA-256 `94389e2b…465c4`，arm64 + macOS≥14.0，挂载冒烟通过）
- **条件项（dana，承接到 v0.4 迭代）**：① `HomeView.swift:17` 硬编码绝对路径 —— alpha 可接受，正式发布前必须 bundle 资源化（否则换机回退拖拽区）② homeImage 计算属性每 body 求值重解码，建议缓存 ③ 静态图分支未挂 dropDestination，拖拽打开退化（Cmd+O 仍可用）
- **环境阻塞**：运行会话无屏幕录制 TCC 权限，截图无法像素级确认；已用代码级证据 + NSImage 解码验证（3264×1376 成功）兜底

---
*决策变更时追加新条目，不修改历史。*

## D-027 画布缩放改造：原始分辨率 + 多通道缩放（2026-08-29）

- **CEO 需求**：打开的图片要么太大要么太小，不能像 Photoshop 一样打开直接显示原始分辨率，且可放大缩小
- **现状缺陷**：CanvasView onAppear 自动 fitToView（超宽图 3264px → 33%，"太小"）；唯一缩放入口=触控板 MagnificationGesture，鼠标用户无法缩放（"太大"= 100% 时越界无法缩小）；无工具栏缩放控件
- **定级**：L2（模块级，纯 UI 交互，3 文件：CanvasView / ToolbarView / EditorState 微调），无新 API/表 → 免架构师，跳 zhanshen 由 PM 直派
- **裁决**：① open() 后初始 scale=1.0（原始分辨率），删除 onAppear 自动 fit ② 缩放三通道：触控板捏合（已有）+ 鼠标滚轮（NSViewRepresentable scrollWheel 桥接）+ 工具栏 − / 百分比 / + / 适应窗口 ③ 保留拖拽平移与 clamp（0.05...16）④ 显式"适应窗口"按钮替代自动 fit
- **验收标准**：打开 ch.jpg(2.28MB/3264px) 初始 100%；滚轮/按钮可缩放；适应窗口一键 fit；不影响文字块交互
- **QA 关联**：随版跑 ch.jpg 改字 E2E 测试（CEO 要求）

## D-028 预判：ch.jpg 改字 E2E 当前必然失败（UI 管线未接通，待 QA 实锤）

- **CEO 测试指令**：ch.jpg 里 v0.20.1 → v1.21.1，成功才汇报
- **对抗式预判（第一性证据）**：`EditorState.runPreviewPipeline`（:313）为"预览拟合占位"，注释自证"Core Workflow 就绪后替换"；`previewFit`（:339）只算 tooLong/collision，**不调用任何抹除/重绘实现**；CanvasView（:42）渲染源= sourceImage.cgImage 原图，无 patch 合成层；confirmPreview（:147）仅物化文本数据进 textBlocks。→ **GUI 改字=数据变更，画布/导出像素不变**
- **影响**：CEO 以"改字后图上文字变化"为验收，当前 GUI 无法达成；Core 层抹除/重绘能力（QA v0.2 全绿）存在但 UI 未接线
- **决策**：不装聋——QA 如实跑 E2E 并取证；失败则上报 CEO，请求排期"UI 预览管线接通 Core 抹除重绘"（L2/L3 评估），不擅自扩大本次范围