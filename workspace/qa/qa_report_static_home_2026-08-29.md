# QA 测试报告 — 首页静态化（static_home）

- **日期**: 2026-08-29
- **角色**: @shouye（QA + SRE）
- **项目**: pxiu macOS 应用（SPM）
- **改动**: L1 — 首页静态化（phase 根因修复 + HomeView 静态图）
- **范围**: 功能测试 + 重新打包 dmg
- **改动涉及文件**: `Sources/PxiuApp/EditorState.swift`、`Sources/PxiuApp/HomeView.swift`

---

## 0. 前置检查

| 检查项 | 状态 | 证据 |
|---|---|---|
| `workspace/backend/api_implementation_*.md` 存在 | ✅ PASS | `api_implementation_v0.2.md`（Aug 28 17:23）存在，无阻塞 |
| 静态图文件存在 | ✅ PASS | `/Users/evandy/Desktop/backup/shy.jpg` 存在，2,472,884 字节（~2.4MB） |

---

## 1. 测试项逐步结果

### A. 改动范围审查

> 非 git 仓库，无法 `git diff`。采用 ①文件修改时间戳 ②逐文件读取 双重证据。

| 断言 | 状态 | 证据 |
|---|---|---|
| 仅改动 `EditorState.swift` + `HomeView.swift` 两个文件 | ✅ PASS | 源码目录各文件时间戳：仅这两个文件为 `Aug 29 22:06`，其余（CanvasView/Feedback/InspectorView/OverlayViews/PxiuApp/Style/SystemFonts/ToolbarView/UndoRedo）均为 `Aug 28`。**Style.swift 未改**、Core 层未改、测试目录 `PxiuCoreTests/`（Aug 28）未改 |
| HomeView 含 `homeImagePath` 常量 | ✅ PASS | `HomeView.swift:17` `private let homeImagePath = "/Users/evandy/Desktop/backup/shy.jpg"` |
| 回退逻辑正确（文件不存在 → dropArea） | ✅ PASS | `HomeView.swift:19-22` `homeImage` 计算属性：`FileManager.fileExists(atPath:)` → 通过才 `NSImage(contentsOfFile:)`；缺任一返回 `nil`。`:27` `if let image = homeImage { homeImageView } else { dropArea }` 正确回退 |
| 静态图 `scaledToFit` 不拉伸 | ✅ PASS | `HomeView.swift:38-44` `Image(nsImage:).resizable().scaledToFit()` + `.padding(.horizontal, DS.Spacing.xl)`，等比缩放不拉伸 |
| `dropDestination` 拖拽保留 | ✅ PASS | `HomeView.swift:84-90` `.dropDestination(for: URL.self)` + `isTargeted` 保留 |
| `formatNote` 保留 | ✅ PASS | `HomeView.swift:32` + `:93-98` 外层保留格式说明 |
| 根因修复：phase 初始值 `.loading → .idle` | ✅ PASS | `EditorState.swift:45` `var phase: EditorPhase = .idle` |
| 首页无 loadingIndicator / 无转圈残留 | ✅ PASS | `HomeView.swift` 全文无 `ProgressView`/loadingIndicator；`OverlayViews.swift` 的 `ProgressView` 在 `ProcessingBadge`（选中块微进度，非首页）且该文件未改动 |
| `isShowingEditor=false` 主视图即 HomeView | ✅ PASS | `PxiuApp.swift:15` `var isShowingEditor = false`；`:84-89` `if model.isShowingEditor { editorBody } else { HomeView() }` |
| 打开图片逻辑未被破坏 | ✅ PASS | `EditorState.swift:372-394` `open(url:)` 仍 `phase = .loading` → 加载完成后置 `.idle`/`.noText`（打开流程合理的处理中态保留） |

**A 部分结论: ✅ PASS** — 改动面严格限定，无多余改动（Style/Core/测试均未动），新代码逻辑符合需求。

### B. 构建

| 项 | 状态 | 证据 |
|---|---|---|
| `swift build`（debug 冒烟） | ✅ PASS | `.build/debug` 输出 `Build complete! (2.23s)`，`EXIT=0`，可执行名 `.build/debug/PxiuApp` |
| `swift build -c release` | ✅ PASS | `.build/release` 输出 `Build complete! (5.12s)`，可执行名 `.build/release/PxiuApp`（1,558,920 B） |

### C. GUI 功能冒烟

| 断言 | 状态 | 证据 |
|---|---|---|
| 启动后进程存活 | ✅ PASS | `open` 方式启动 debug app → PID 32341 存活，launchservices 已注册（`lsappinfo` 可查） |
| 运行期无崩溃 | ✅ PASS | 进程存活 ~15s 后手动终止；`~/Library/Logs/DiagnosticReports/` 无 `PxiuApp*` 新增崩溃记录 |
| 优雅退出 / 进程干净终止 | ✅ PASS | debug 裸可执行 `TERM` 后 `pgrep`=1（已退出）；打包 bundle app 用 `osascript 'tell application "Pxiu" to quit'` → `exit=0`，进程消失 |
| **截图可视化确认首页显示 shy.jpg / 无转圈 / 无"正在打开图片"** | ⚠️ **阻塞（环境限制）** | 见下「阻塞项」：`screencapture` 因 Terminal 无屏幕录制权限失败，无法产出截图文件 |

**C 部分结论: ⚠️ 部分通过** — 启动 / 存活 / 无崩溃 / 退出全链路通过；唯一未验证项为**像素级可视化确认**，受环境屏幕录制权限阻塞（详下）。代码级确定性（第 A 项）+ 构建成功已从根因上保证：`phase=.idle` 使首页不再读 loading 态，HomeView 命中 `if let image = homeImage` 分支展示静态图，主视图 `isShowingEditor=false` 即 HomeView，不会自跳编辑器。

### D. 回退逻辑（只读审查）

| 断言 | 状态 | 证据 |
|---|---|---|
| 回退路径存在（代码审查） | ✅ PASS | `homeImage` 计算属性：路径常量 → `fileExists` → `NSImage(contentsOfFile:)` 非 nil；**任一失败 → nil → dropArea**（含拖拽区 + 打开按钮 + formatNote）。判据与任务要求一致 |
| 缺失分支 GUI 实测 | ✅ **skip（经授权）** | 任务明确禁止动 CEO 桌面 shy.jpg，缺失分支以代码审查通过为准，不做缺失实测 |

### E. 打包新 dmg（SRE）

| 项 | 状态 | 证据 |
|---|---|---|
| release 构建 | ✅ PASS | `.build/release/PxiuApp`（1,558,920 B） |
| 组装 Pxiu.app bundle（临时目录，未覆盖旧 dist/Pxiu.app） | ✅ PASS | `Contents/MacOS/PxiuApp` + `Info.plist` + `PkgInfo(APPL????)`；临时路径 `/var/folders/.../opencode/Pxiu.app`；旧 `dist/Pxiu.app` 时间戳 19:31 未变 |
| ad-hoc 签名 + 校验 | ✅ PASS | `codesign --force --deep --sign -` exit=0；`codesign --verify --deep --strict` exit=0；`flags=0x2(adhoc)`，`Identifier=com.pxiu.app` |
| dmg 创建 | ✅ PASS | `hdiutil create -srcfolder -ov -format UDZO` exit=0 |
| **产物路径** | ✅ | `/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.2.dmg` |
| **SHA-256** | ✅ | `94389e2b5b76f1b4caddf6232e47b847696860a6875c829ca3d8bf76331465c4` |
| **文件大小** | ✅ | 781,360 字节 |
| arm64 架构 | ✅ PASS | `file`: `Mach-O 64-bit executable arm64`；`lipo -info`: `architecture: arm64` |
| macOS 版本 | ✅ PASS | `LC_BUILD_VERSION` `minos 14.0`（macOS 14+） |
| mounted 副本签名/架构复验 | ✅ PASS | 挂载 `Pxiu-1.0.0-alpha.2.dmg` 内 `Pxiu.app`：arm64 / adhoc / Identifier 正确 |
| 打包产物启动冒烟 | ✅ PASS | mount → `open <mnt>/Pxiu.app` → PID 32790 存活 → `osascript quit` exit=0 进程消失（无崩溃）→ `umount` 成功 |
| 打包产物截图验证 | ⚠️ 阻塞（同 C） | 屏幕录制权限限制 |

---

## 2. 发现的问题

- **（阻塞·环境限制）GUI 截图不可用**：`screencapture -x` 返回 `could not create image from display`。根因：调用进程宿主为 `Terminal.app`，其未获 macOS「屏幕录制」TCC 授权（TCC.db 中无 `kTCCServiceScreenCapture` 记录，且该库受系统保护无法 CLI 修改）。**这是测试环境能力阻塞，非产品缺陷。**
- 未发现产品的功能缺陷。改动的代码级验证（phase 根因 + 静态图分支 + 回退分支）全部通过，构建/打包/启动全链路通过。

---

## 3. 阻塞项（需 @zongguan 知情）

1. **GUI 像素级可视化确认缺失**：因「屏幕录制」权限被系统保护且无法命令行授予，无法通过截图人工确认首页渲染 shy.jpg。已用代码级证据（`phase=.idle` 根因 + HomeView `if let image = homeImage` 命中静态图分支 + `isShowingEditor=false` 主视图）兜底。
   - **建议**：若需最终可视化确认，需你在 System Settings → Privacy & Security → **Screen Recording** 中给 **Terminal** 勾选授权后重跑截图，或由具权限会话复核。
2. 打包产物未在真实安装路径 `/Applications` 验证（沿用既有报告体系，属常规遗留项）。

---

## 4. 最可能漏测的场景（QA 对抗式审查必写）

1. **静态图跨会话持久性**：CEOs 偏好是否在"文件被移动/删除后用系统默认图占位"——当前实现`文件不在 → 直接回退拖拽区`，不会展示 placeholder 图。若后续期望"图缺失也留占位"，需需求方确认。
2. **窗口缩放极窄**：`scaledToFit` 在极端宽高比窗口下图片可能居中留白过大，未做最小尺寸约束实测（当前 minWidth 900/minHeight 560 已设，风险低）。
3. **`NSImage(contentsOfFile:)` 大图内存**：shy.jpg 2.4MB 加载于主线程，首页每次 appear 会重新解码。极小概率在新图上出现首帧卡顿，本次未见（文件小）。
4. **Retina / 非 600% 缩放**：未在不同屏幕缩放比下实测图片清晰度（arm64 decodes 3x 由 AppKit 处理，风险低，仅标注）。
5. **多显示器扩展桌面**：screencapture 检测到仅 1 显示器，多屏布局下首页渲染未实测（环境仅单屏）。

---

## 5. 交付物汇总

| 交付物 | 路径 |
|---|---|
| QA 报告 | `/Users/evandy/opencode/pxiu/workspace/qa/qa_report_static_home_2026-08-29.md` |
| dmg 产物 | `/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.2.dmg`（781,360 B） |
| SHA-256 | `94389e2b5b76f1b4caddf6232e47b847696860a6875c829ca3d8bf76331465c4` |
| 参考产物（未改动） | `/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.dmg`、`dist/Pxiu.app` |

---

## 6. 结论

- 改动范围 ✅ 严格限定（仅 2 个文件），代码符合任务要求。
- 构建 ✅ debug / release 均通过。
- 功能核心 ✅ 根因（phase→idle）+ 静态图展示逻辑代码级验证通过，启动/存活/无崩溃/退出链路通过。
- 打包 ✅ 新 dmg 生成，SHA-256 / 大小 / arm64 / minOS 校验齐全，产物启动冒烟通过。
- **唯一未决项**：GUI 截图受屏幕录制权限环境阻塞，已在阻塞项向 @zongguan 反馈。
- 本报告未修改任何 `.swift` 源码。

**测试整体判定：PASS（除环境阻塞的截图可视化外，无功能缺陷）。可移交 @dana 代码审查。**
