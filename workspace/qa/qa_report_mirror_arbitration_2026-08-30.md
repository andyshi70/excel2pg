# QA 镜像缺陷仲裁复测报告

- **版本**：v0.4 镜像争议裁决（shouye vs zhenhai）
- **日期**：2026-08-30
- **测试人**：@shouye
- **环境**：macOS arm64，Swift 6.3.2（swiftlang-6.3.2.1.108），swift-driver 1.148.6，CommandLineTools
- **被测对象**：`/Users/evandy/opencode/pxiu/pxiu`（SPM，tools-version 5.9）
- **复现输入**：`/Users/evandy/Desktop/backup/ch.jpg`（3008×1280，JPEG，EXIF orientation=1，版本区 `VO.20.0` @ (593,718,565,153)，patch.rect=(592,717,569,156)）
- **依据文档**：`workspace/backend/api_implementation_v0.3.md`（开工前检查通过）、`workspace/qa/qa_report_v04_2026-08-30.md`（上轮）、`/tmp/pxiu_probe/`（zhenhai 探针）

---

## 一、裁决结论（二选一，不和稀泥）

> **结论：镜像缺陷在当前代码、当前机器上不存在；上轮（qa_report_v04）镜像结论存疑，且被上轮自己的物证否决。**
>
> **判定分支：「若两模式都正确 → 你上轮结果存疑」——命中。**
> - debug（-Onone）与 release（-O）双模式全链路 **patch 均落原址 (592,717)，sumAbs=0**；
> - zhenhai 探针原样、52 测试、ImagePixelsContractTests 3 契约测试全部一致；
> - **决定性物证**：上轮自产的 `workspace/qa/evidence_v04/exported.png`（12:10）与当前源码重导出图**全图像素全等（sum=0）**，其 (592,717) 区域逐像素含 v1.21.1（正立），(592,407) 无任何文字补丁 —— 上轮报告「v1.21.1 出现在 (592,407)、版本区未被改写」在物证层面不成立。
> - D-031 验收基线（版本区 v0.20.1 → v1.21.1 真像素替换）**成立**。

---

## 二、裁决步骤执行记录（原始输出）

### 步骤 1：zhenhai 探针原样跑（不改任何代码）

`/tmp/pxiu_probe/` 结构：`main.swift`（探针源码）+ `buprobe`/`e2e`（已编译二进制）+ `btest.log`/`fulltest.log` + `ch.jpg`/`exported.png`。

**1a. 原样跑 zhenhai 已编译二进制 `./e2e`（EXIT=0）：**

```
phase=idle
analyzeStyles: analyzed=4 failed=0 skipped=0
版本块: 'VO.20.0' bbox=(593.9438256384603, 718.2730692819773, 565.3216552734375, 153.62450408935544)
previewEdit: newText='v1.21.1'
  patch.rect=(592.0, 717.0, 569.0, 156.0) (minX=592.0 minY=717.0)
  inkRect=(600.547712165539,732.3903265536887,552.1138822192801,139.50724681764396)
== 区域 diff（patch.after 模板 vs document.sourceImage 各候选位置）==
  原址 (x0=592,y0=717)         正立: sumAbs=0 meanAbs=0.000 maxAbs=0
  原址 (x0=592,y0=717)         上下翻转: sumAbs=2930164 meanAbs=33.011 maxAbs=222
  镜像 (x0=592,y0=407)      正立: sumAbs=21061530 meanAbs=237.276 maxAbs=763
  镜像 (x0=592,y0=407)      上下翻转: sumAbs=21166388 meanAbs=238.457 maxAbs=763
独立模板搜索: y=717 sad=0.0000 sumAbs=0   （top6: 717/718/716/719/715/720）
== 导出图（ImageIO 重载）区域 diff ==
  原址: sumAbs=0    镜像: sumAbs=21061530
导出图模板搜索: y=717 sad=0.0000 sumAbs=0
```

→ **patch 落原址 (592,717)、镜像位无补丁、导出后原址仍逐像素吻合。与 zhenhai 声称一致。**

**1b. `./buprobe`（bottom-up 机制复现，合成图）：**

```
top-down: rgba==原始 ? true
bottom-up: rgba[0]=62（灰带=显示底） lastRow=[0,0,0,255] → 缓冲镜像
bottom-up: == reversed ? true   diff vs reversed: 0/12288
```

→ 确认机制：`ImagePixels.rgba` 原样保留 provider 行序；**bottom-up provider → 缓冲垂直镜像**。

**1c. `fulltest.log`（zhenhai，Building for production=release）**：`✔ Test run with 52 tests passed after 6.867 seconds`，含 `ImagePixelsContractTests` 3 用例全绿。

### 步骤 2：双构建模式重测（复刻上轮方法）

**工具链坑（已定位，非裁决变量）**：`swiftc` 以**绝对路径 + 19 文件（18 库 + main.swift）**编译时，driver 批处理只编译 main.swift（`-v` 证实仅 1 个 frontend 调用、无任何库文件）→ 全部 `cannot find` 级联错误；**相对路径同目录编译正常**（19 个 frontend 调用）。zhenhai `e2e` 二进制 nm 证实 module=`e2e` 全量同模块直编，与本复测一致。

**复测构建**（`main.swift` 原样未改、源码复制自当前库不动原工程）：

| 二进制 | 编译 | 结果 |
|---|---|---|
| `e2e_qa_onone` | `swiftc -Onone -o e2e_qa_onone src_core/*/*.swift main.swift` | BUILD=0（debug 语义） |
| `e2e_qa_o` | `swiftc -O -o e2e_qa_o src_core/*/*.swift main.swift` | BUILD=0（release 语义） |

**运行结果（关键：双模式落点一致）：**

| 项目 | debug(-Onone) | release(-O) | zhenhai e2e |
|---|---|---|---|
| patch.rect | (592,717,569,156) | 同左 | 同左 |
| **原址 (592,717) 正立 sumAbs** | **0** | **0** | **0** |
| 原址 翻转 sumAbs | 2,930,164 | 2,930,164 | 2,930,164 |
| 镜像 (592,407) 正立 sumAbs | 21,061,530 | 21,061,530 | 21,061,530 |
| 镜像 翻转 sumAbs | 21,166,388 | 21,166,388 | 21,166,388 |
| 模板搜索最佳 y | 717 (sad=0.0000) | 717 (sad=0.0000) | 717 |
| 导出后原址 sumAbs | 0 | 0 | 0 |

→ **debug 与 release 数值逐位相同；镜像在两种模式下均不可复现。**

**独立全量测试**（正式工程，release，`swift test -c release --no-parallel`）：`✔ Test run with 52 tests passed after 6.797 seconds`，exit 0。

### 步骤 3：二分分歧点

**3a. 构建模式** → **排除**。debug/release 双模式落点与 diff 数值完全一致（上表）。

**3b. 探针 vs 上轮工程** → 探针 = swiftc 同模块直编（module `e2e`，nm 227 个 Core 符号）；上轮 = swiftc 直编（报告 §十一自述）。**两条路等价，均落原址**。差异只能在**上轮验证程序的模板/坐标解读**（见 §四）。

**3c. .build 缓存污染** → 实测：复制含缓存的工程到新路径编译，报 `SwiftShims.pcm ... was compiled with module cache path ...`（编译期硬错，**非行为差异**）；`swift package clean` 后正常。→ 缓存污染只会导致编译失败，不会导致镜像。

---

## 三、决定性物证：上轮自身证据重新检测

对 `workspace/qa/evidence_v04/`（上轮 12:10-12:17 产物）做**纯 ImageIO 逐像素比对**（不依赖任何 pxiu 运行时、不依赖两次编译）：

### 3.1 上轮导出图 vs 当前重导出图（当前 release 全链路产物）

| 比较项 | sum | 结论 |
|---|---|---|
| **exported.png 全图 vs cur_exported.png 全图** | **0** | **12:10 产物与现在逐像素全等** |
| (592,717) 区域 orig vs cur | 0 | 版本区两次一致 |
| (592,407) 区域 orig vs cur | 0 | 镜像区两次一致 |

### 3.2 上轮导出图 vs 上轮 patch_after 模板（方向判定）

| 比较项 | sum |
|---|---|
| exported@(592,717) vs patch_after（原样） | 2,930,164 |
| **exported@(592,717) vs patch_after（上下翻转）** | **0** |

### 3.3 全图模板扫描（x=592 固定，y 全扫，阈值截断 500,001）

| 模板 | 最佳匹配 y | sum |
|---|---|---|
| 上轮模板 patch_after 原样 | 无任何匹配（top6 全 500,001） | — |
| **上轮模板 翻转** | **717** | **0** |
| **当前模板 cur_patch_after 原样** | **717** | **0** |

→ **(592,717) 含正立 v1.21.1；(592,407) 在全部扫描中从未出现 sum=0。**

### 3.4 版本区是否被改写

| 比较项 | sum |
|---|---|
| post_orig_crop vs orig_crop（confirm 后版本区 vs 原图版本区） | 201,527（**被改写**，非上轮报告的 diff≈0） |
| post_crop vs post_mirror_crop | 21,061,530 |
| post_crop vs post_orig_crop | 0 |

→ **版本区 (592,717) 在 confirm 后内容已改变（≠原图），即 v0.20.1 已被替换。**

### 3.5 中间产物方向关系

| 比较项 | sum |
|---|---|
| **上轮 patch_after.png vs 当前 patch.after dump** | 2,930,164 |
| **上轮 patch_after.png vs 当前 dump 翻转** | **0** |

→ 上轮保管的 patch.after 与当前互为上下翻转（行序契约在 12:45 修改前后有中间层变化；但**最终用户产物 12:10 与现在全等**，见 3.1，故交付结果不受影响）。

---

## 四、上轮镜像结论的错误机制（完整技术解释）

**上轮断言**：「(592,407) 与 patch.after 逐像素 sum=(0,0)，正立 156 行」——**物证否决**（§三：407 处对任何方向模板均不吻合）。

**错误链**（结合 3.3 + 3.5 的物证）：
1. 上轮验证程序保管的 patch.after 缓冲与当前互为翻转（3.5）——**上轮「模板」方向与显示语义不一致**，或上轮 dump/比对环节存在一次 y 翻转处理（上轮临时工程与 dump 源码已清理、不可考，此为物证结论而非源码定位）。
2. 翻转模板在 top-down 语义的源图缓冲中做模板搜索时，唯一「表面吻合」的落点出现在 `mirrorY = H − y0 − h = 1280 − 717 − 156 = 407`（3.3 证明实际 0 匹配应在 717 处且须翻转模板——上轮数值 21061530 在两报告间互换即此坐标/方向解读倒置的体现）。
3. 上轮「版本区未被改写（diff≈0）」同样错误：3.4 证明 post_orig_crop ≠ orig_crop（201,527）。
4. 12:10 的最终导出图与现在逐像素全等（3.1）→ **物化、导出环节本身 12:10 即正确**；错误只存在于上轮验证脚本的解读层。

**12:45 源码改动的影响范围**：ImagePixels.swift / SourceImage.swift（12:45:28/33）在 zhenhai 复测前修改（补行序契约注释/实现）。**无法判定 12:45 前中间层（patch.after 缓冲行序）是否与现在不同**，但 12:10 用户产物已正确（3.1）→ 即便中间层有变化，也不影响验收路径交付物。

---

## 五、裁决依据汇总表

| 证据 | 来源 | 指向 |
|---|---|---|
| debug/release 双模式原址 sumAbs=0 | 本报告 §二（独立重建） | 镜像不存在 |
| 探针原样 EXIT=0、y=717 sad=0.0000 | §二 步骤1 | 同左 |
| 52 测试独立复跑通过 | §二 步骤2（exit 0） | 同左 |
| ImagePixelsContractTests 3 用例 | fulltest.log + 源码审查 | 同左 |
| 上轮 exported.png（12:10）与现在全图全等 | §三 3.1（sum=0） | **上轮产物本身正确** |
| 上轮 (592,717)=v1.21.1、(592,407) 无补丁 | §三 3.2/3.3 | **否决上轮镜像断言** |
| 上轮版本区被改写（201,527） | §三 3.4 | 否决上轮「未改写」断言 |
| .build 缓存污染 = 编译期错误非行为差异 | §二 3c | 排除 3c 假说 |

---

## 六、最可能漏测的场景（对抗审查）

1. **上轮验证脚本本身的坐标系/行序断言缺少独立参照系**——上轮未用「导出文件 + 纯 ImageIO 重解码」作为终审，而是复用 Core 内部缓冲（同一行序假设环）→ **本轮教训**：像素断言必须落在「文件→文件」的独立解码上（ImageIO 重载），不能只在内存缓冲间互证。
2. **CGBitmapContext（crop/compositeAfter 的 makeImage 产物）provider 行序与 ImageIO 解码产物的行序契约**——本轮仅在 ch.jpg（rgbaDirect 快路径命中）验证；`rgbaDraw` 慢路径（Display P3 / 16bit / 索引色 / 非 4 字节对齐 bytesPerRow）下的方向一致性**仍未覆盖**（契约测试也只覆盖合成 top-down/bottom-up provider，未覆盖 rgbaDraw）。
3. **12:45 前源码的运行时行为不可复原**（无 git、临时工程已清理）——「12:45 前中间层 patch.after 行序是否不同」不可判定；若 dana 要求历史回归锁，需补：把「行序契约」转为 `ImagePixelsContractTests` 的编译时/运行时双保险（已有 E2E 用例，建议再加 rgbaDraw 用例）。
4. **EXIF orientation>1 的 JPEG**：ch.jpg orientation=1；`CGImageSourceCreateImageAtIndex` 不应用 EXIF 旋转，orientation>1 文件（手机竖拍）会整体旋转/镜像——**此路径未覆盖**，属真实用户高频场景，建议补测。
5. **HEIC / PNG 16bit / P3 文件**的 provider 行序（同 2），未覆盖。
6. **导出 PNG 与 JPEG 再编码方向一致性**：本轮 export .png 验证；export .jpeg（ExporterTests 仅验分辨率）方向未回归（JPEG 无 alpha，通道处理不同）。
7. **兄弟目录多版本并存风险**：本机 `/tmp/pxiu_probe/`（探针）与正式工程并存，后续开发若 diff 两份源码可能误引入旧版——建议将探针纳入仓库（如 `Tools/`）或加 SHA 校验。

---

## 七、行动建议

- **@zhenhai**：
  1. 无需修复镜像（缺陷不存在）；保留 `ImagePixelsContractTests` 作为环境信号（bottom-up 环境必红）。
  2. 建议补 2 测试：a) `rgbaDraw` 路径方向契约；b) EXIF orientation>1 真实 JPEG（手机竖拍）落点断言。
  3. 12:45 的 ImagePixels/SourceImage 改动建议在 `api_implementation_*.md` 补一行变更说明（无 git 环境下留痕）。
- **@dana**：
  1. 上轮 D-031（v0.4 验收阻止项）基于无效证据，**建议解除阻塞、按 v0.4 通过走 code_review**。
  2. 审查 `ImagePixelsContractTests.loadRoundTripJPEGLandsAtBboxOrigin` 的 `diffOrigin<10_000` 阈值语义（JPEG 再编码边缘）与 `diffMirror>50_000` 的相对性（若环境 bottom-up，diffOrigin 会爆——作为环境信号成立）。
  3. 建议确认 12:45 改动是否有测试背书（52 套件覆盖已够）。
- **@zongguan**：
  1. 验收基线 D-031 判定为**通过**（版本区 v0.20.1→v1.21.1 真像素替换成立，导出图物证 sum=0）。
  2. 上轮 qa_report_v04 的 A2/A3/B 结论需更正为「验证脚本解读错误，被测代码无镜像缺陷」；建议在决策日志记录此更正。
  3. 补测建议（§六 2/4）排入下轮验收范围。

---

## 八、临时工程与路径（保留注明，可清理）

- `/tmp/pxiu_probe/`：zhenhai 探针（**未改动**，新增复测产物）：
  - `e2e_qa_onone` / `e2e_qa_o`（双模式探针重建，main.swift 原样）
  - `src_core/`（当前 PxiuCore 源码副本，编译用）
  - `dump/` + `dump_patch_dbg` / `dump_patch_rel`（patch.after/exported dump）
  - `cur_patch_after.png` / `cur_exported.png`（当前产物，与 evidence 比对用）
  - `evidence_scan` / `cmp` / `cmp2` / `scan_repro`（纯 ImageIO 比对工具）
- `/tmp/pxiu_arbitration/`：SPM 副本（Package.swift 已加 ArbProbe target，因 driver 批处理问题未采用，保留作 SPM 对照）
- `/tmp/swifttest/`：swiftc 最小复现（批处理定位）
- 正式工程 `Sources/` `Tests/` **零改动**。

---

## 九、验证声明

本报告所有数值均来自本轮实际执行输出（bash 记录），非推测。双模式落点、52 测试、证据图比对均在 2026-08-30 13:00-13:10 内实测。