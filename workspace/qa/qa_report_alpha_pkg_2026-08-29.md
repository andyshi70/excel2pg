# QA 测试报告 — Pxiu DMG 安装镜像打包（alpha 发布）

| 项 | 值 |
|---|---|
| 报告编号 | qa_report_alpha_pkg_2026-08-29 |
| 测试角色 | @shouye（QA + SRE，发布流水线） |
| 测试日期 | 2026-08-29 |
| 测试对象 | pxiu macOS Swift 工程 → `Pxiu-1.0.0-alpha.dmg` 安装镜像 |
| 测试性质 | 构建 / 打包 / 签名 / 镜像校验 / 启动冒烟（**不修改任何产品代码**） |
| 版本 | 1.0.0-alpha（CFBundleShortVersionString=1.0.0, CFBundleVersion=1） |
| 结论 | ✅ **DOMMG 可安装**（详见结论章节，附 Gatekeeper 遗留风险） |

---

## 1. 环境与前置检查

| 项 | 实测结果 | 证据 |
|---|---|---|
| macOS | 26.6.2 (25G83) | `swift --version` / `sw_vers` 亲跑 |
| 架构 | arm64 | `uname -m` → arm64 |
| Swift | 6.3.2 (swiftlang-6.3.2.1.108)，Target: arm64-apple-macosx26.0 | `swift --version` |
| xcodebuild | 不可用（无完整 Xcode，仅 CommandLineTools） | 任务前置侦察；`swift build` 可编译 |
| 工具链 | codesign / hdiutil / plutil / file / lipo 均在 /usr/bin | `command -v` 逐一确认 |
| 开工前文档检查 | `workspace/backend/api_implementation_v0.1.md`、`v0.2.md` 均存在 | Glob 确认 |
| PUA 行为协议 | 已 Read `pua/SKILL.md`（backup/wukong 路径，本机无 `pua-skills/` 目录）；`references/display-protocol.md` 全机不存在，仅存在 `config-setup.md` | Read/Glob 亲查 |
| 工程入口 | `Sources/PxiuApp/PxiuApp.swift` 标准 `@main` SwiftUI App；`Sources/PxiuApp/` 无资源文件（无 Assets/图标）→ Resources/ 目录合法省略 | Read + ls 亲查 |
| Package.swift | `platforms: .macOS(.v14)`；executableTarget `PxiuApp`（依赖 PxiuCore） | Read 亲查 |

---

## 2. 执行记录（每步亲跑命令与输出）

### 2.1 Release 构建

命令（workdir=/Users/evandy/opencode/pxiu/pxiu）：
```
time swift build -c release --product PxiuApp
```
亲跑输出（摘录）：
```
Building for production...
[6/7] Linking PxiuApp
Build of product 'PxiuApp' complete! (39.16s)
swift build -c release --product PxiuApp  38.93s user 2.04s system 103% cpu 39.463 total
EXIT_CODE=0
```
- **产物路径**：`/Users/evandy/opencode/pxiu/pxiu/.build/arm64-apple-macosx/release/PxiuApp`
- **产物信息**（后续亲跑）：
  - `file` → Mach-O 64-bit executable arm64
  - `lipo -info` → Non-fat, arm64
  - `otool -l` → **minos 14.0**（与 Package.swift macOS 14 一致）
  - `otool -L` → 仅系统框架（AppKit/SwiftUI/Vision/ImageIO/CoreText 等），**无第三方动态库**，bundle 内无需嵌入 dylib
- 编译 warning 4 条（Sendable 可变属性 / var→let 建议 / 冗余 try），均为非阻塞提示，不影响产物。

### 2.2 构造 .app bundle

命令：
```
mkdir -p /Users/evandy/opencode/pxiu/dist/Pxiu.app/Contents/MacOS
cp .../.build/arm64-apple-macosx/release/PxiuApp /Users/evandy/opencode/pxiu/dist/Pxiu.app/Contents/MacOS/PxiuApp
```
Info.plist 用 plutil 创建（`plutil -create xml1` + 逐键 `-insert`），最终 `plutil -lint` → **OK**：

```
{
  "CFBundleDisplayName" => "Pxiu"
  "CFBundleExecutable" => "PxiuApp"
  "CFBundleIdentifier" => "com.pxiu.app"
  "CFBundleInfoDictionaryVersion" => "6.0"
  "CFBundleName" => "Pxiu"
  "CFBundlePackageType" => "APPL"
  "CFBundleShortVersionString" => "1.0.0"
  "CFBundleSignature" => "????"
  "CFBundleVersion" => "1"
  "LSMinimumSystemVersion" => "14.0"
  "NSHighResolutionCapable" => true
}
```
Bundle 结构：
```
Pxiu.app/Contents/
├── Info.plist
├── MacOS/PxiuApp
└── _CodeSignature/   （签名后生成）
```
Resources/ 按前置侦察省略（无资源文件）。

### 2.3 签名（ad-hoc）

```
codesign --force --deep --sign - Pxiu.app
  → "replacing existing signature"  SIGN_EXIT=0
codesign --verify --deep --strict Pxiu.app
  → 无输出  VERIFY_EXIT=0
codesign -dv --verbose=4 Pxiu.app
  → Identifier=com.pxiu.app
  → Format=app bundle with Mach-O thin (arm64)
  → flags=0x2(adhoc)  Hash type=sha256
  → VersionMin=917504 (=14.0)  VersionSDK=1705216
```
无 entitlements（未沙盒化，GUI 应用正常所需）。

### 2.4 制作 DMG

```
hdiutil create -volname Pxiu -srcfolder Pxiu.app -ov -format UDZO Pxiu-1.0.0-alpha.dmg
  → created: .../Pxiu-1.0.0-alpha.dmg  HDIUTIL_EXIT=0  （14.07s）
```

---

## 3. DMG 校验信息

| 项 | 值 |
|---|---|
| 文件 | `/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.dmg` |
| 大小 | **780,405 字节（762.11 KiB）** |
| SHA-256 | `a764bba203dd4ee261453c0ef879e2f23f9d64c25c63f53052826a2ad29b5a29` |
| SHA-1 | `a0b83290601a0bc81748c6d8a80391d8c6d63456` |
| 格式 | UDZO（`hdiutil imageinfo`：Class CUDFDiskImage / Format UDZO / Checksum CRC32） |
| `hdiutil verify` | **VALID**（所有分区 CRC32 verified，含 MBR/GPT/APFS） |
| 二次校验（detach 后） | SHA-256 一致（上值） |

## 4. 挂载验证（对抗式，非"文件存在"级）

挂载点 `/tmp/pxiu_mnt_ufgk`（`hdiutil attach -nobrowse`，ATTACH_EXIT=0）：

| 检查项 | 结果 |
|---|---|
| dmg 内内容 | 仅 `Pxiu.app`，**无 .DS_Store / 垃圾文件**（find 空） |
| `plutil -lint`（挂载副本） | OK |
| `file`（挂载副本二进制） | Mach-O 64-bit executable arm64 |
| `lipo -info` | Non-fat, arm64 |
| `codesign --verify --deep --strict --verbose=2` | **valid on disk** + **satisfies its Designated Requirement**，exit 0 |
| `defaults read … CFBundleIdentifier` | com.pxiu.app |

## 5. 最小启动冒烟（真实 GUI 启动）

| 步骤 | 输出 |
|---|---|
| `open <mount>/Pxiu.app` | OPEN_EXIT=0 |
| +6s `pgrep -fl PxiuApp` | `21897 /private/tmp/pxiu_mnt_ufgk/Pxiu.app/Contents/MacOS/PxiuApp` 存活 |
| +11s `pgrep -fl PxiuApp` | 仍存活（PID 21897，**11+ 秒无崩溃**） |
| `osascript -e 'tell application "Pxiu" to quit'` | 成功；之后 pgrep 无进程（1=已退出），等效 Cmd+Q |
| 崩溃日志检查 | `~/Library/Logs/DiagnosticReports/` 仅有 2026-08-28 的 `pxiu_verify-*.ips`（历史旧产物，非本次 PxiuApp）；本次启动**无崩溃记录** |

**启动冒烟：✅ 已执行且通过**（本会话有 GUI 权限，真实启动 + 存活 + 优雅退出全链路验证）。

## 6. 回归说明

- **未执行 `swift test`**，跳过原因（按任务授权声明）：本次为**打包纯构建动作**，未修改 Sources/ 任何产品代码或 Package.swift；已知 swift test 约 371s 耗时，与打包改动面（bundle 构造/签名/dmg 封装，不改变编译产物逻辑）无直接关联。交付面已由 dmg 完整性校验 + 挂载副本签名/架构校验 + 真实启动冒烟覆盖。
- 若需完整回归，随时可执行 `swift test`（预计约 371s）作为补充验证。

---

## 7. 最可能漏测的场景（对抗式审查）

1. **Gatekeeper 首次启动拦截（最高风险，无法在本机完全模拟）**：ad-hoc 签名 + 未公证 app，从网上下载/拖入 /Applications 后，默认 Gatekeeper 可能弹"无法验证开发者"。本报告启动冒烟是**本地已信任来源**启动，未模拟"下载隔离属性"路径。缓解：CEO 首次启动右键 → 打开，或 `xattr -dr com.apple.quarantine /Applications/Pxiu.app`。
2. **仅 arm64**：产物为 arm64 单架构（本机 Swift 工具链所致），**Intel Mac 无法安装运行**；需确认 CEO 机器为 Apple Silicon。
3. **未在真实安装路径（/Applications）验证**：启动冒烟在 dmg 挂载卷（只读）内执行，与 /Applications 安装后路径等价性高但非 100% 相同（运行目录、写权限等）。交付 CEO 后在 /Applications 启动若有异常需回传。
4. **最低系统版本边界未验证**：LSMinimumSystemVersion=14.0 声明正确（二进制 minos 14.0），但仅在 macOS 26.6.2 实测，未在 14.x/15.x 真机验证。
5. **功能级冒烟未执行**：本次仅启动冒烟（窗口应正常显示首页）；OCR/编辑/导出等核心链路未在打包产物上验证（属 v0.2 功能测试范畴，本次范围=可安装性）。
6. **签名在 gatekeeper 远程场景**：`hdiutil verify` 只保证镜像完整性，不替代 Apple 公证（notarization）。无 Developer ID 证书 → 无法公证，属已知限制，非本次可修复项。

## 8. 遗留风险与建议

| 风险 | 等级 | 建议 |
|---|---|---|
| Gatekeeper 拦截未公证 ad-hoc app | 中 | CEO 首次以右键→打开方式启动；或安装后执行 `xattr -dr com.apple.quarantine` |
| 仅 arm64 架构 | 中 | 安装前确认 CEO 机器为 Apple Silicon（本报告环境 arm64 无法产出 universal） |
| 未公证（notarization） | 低（内部分发场景） | 若需外部分发，需 Developer ID 证书 + 公证流程 |
| LSMinimumSystemVersion 14.0 仅按声明未实测 | 低 | 如 CEO 系统 ≥14 且 <26 出现异常，回传复测 |

## 9. 结论

✅ **DOMMG 可安装**（针对 arm64 Apple Silicon + macOS ≥14.0 环境，附第 8 节 Gatekeeper 风险提示）。

- **产物**：`/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.dmg`（780,405 字节，SHA-256 `a764bba2…b5a29`）
- **启动冒烟**：已执行并**通过**（真实 GUI 启动，进程存活 11+ 秒无崩溃，优雅退出正常，无崩溃日志）
- 中间物 `dist/Pxiu.app` 已保留（可留可删）

---
*本报告所有结论均附亲跑命令输出，无转述猜测。测试过程未修改 Sources/ 任何产品代码或 Package.swift（红线遵守）。*