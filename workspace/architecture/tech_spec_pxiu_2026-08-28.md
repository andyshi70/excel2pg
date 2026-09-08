# 技术方案 — 截图文字无痕修改工具（pxiu）

- 日期：2026-08-28
- 撰写：zhanshen（架构师）
- 版本：v0.1（L3 架构基线）
- 依赖上游：`prd_pxiu_v0.1_2026-08-28.md`、`requirement_diagnosis_2026-08-28.md`、`page_states_pxiu_2026-08-28.md`、`user_flow_pxiu_2026-08-28.md`
- 下游消费者：zhenhai（Core 流水线）、xiaoyou（UI/状态层）、shouye（QA 测试基准）、dana（审查）

---

## 0. 单机应用架构文档适配声明（必读）

AGENTS.md 文档依赖链要求架构师产出 `api_contract_*.yaml` 与 `db_schema_*.sql`。**本项目为纯离线 macOS 单窗口应用：无服务器、无网络协议、无数据库。** 按 zongguan 任务指令，本适配如下：

- `api_contract_*.yaml` → 由**进程内模块契约**替代：各模块的 Swift `protocol` / `struct` 定义 + 数据流（见 §4）。模块边界即"接口"。无 HTTP 语义，无需 YAML 表达。
- `db_schema_*.sql` → **不产出**。持久化仅有两种：导出的 PNG/JPEG 文件、可能的用户偏好（`UserDefaults`，与业务数据无关，不建表）。
- 全部架构决策（选型、契约、状态、错误、测试、风险）承载于本单文件 tech_spec。

适配理由：AGENTS.md 的阶段依赖是为 Client/Server 项目设计的；对单机应用强行产出 API 契约与建表语句是无意义形式主义。消费者（zhenhai/xiaoyou）以本文件为唯一架构依据。

---

## 1. 总览：核心数据流与模块拓扑

```
                        ┌─────────────────────────────────────────────┐
  PNG/JPEG/HEIC ──▶ ImageLoader ──▶ SourceImage (像素缓冲,不可变)         │ UI 侧
                        │                                               │
                        ▼                                               │
                 TextBlockDetector(Vision OCR)                          │
                        │ [TextBlock...]                                │
                        ▼                                               │
                 StyleAnalyzer (每块，可并行)              EditorState   │
                  ├─ FontMatcher ── 渲染比对(两级剪枝)      (@Observable)│
                  ├─ SizeEstimator ─ 渲染探针              ▲             │
                  ├─ ColorEstimator ─ fg/bg/α 模型         │ 预览/提交    │
                  └─ SpacingEstimator ─ 逐字框/聚合漂移     │             │
                        │ [TextStyle + warnings]           │             │
                        ▼                                  │             │
  用户编辑新文本 ──▶ EditorWorkflow (generation 计数) ──────┼─────────────┘
                        │ newText + TextStyle              │
                        ▼                                  ▼
                 TextEraser (inpaint 掩码=原笔画膨胀1px)  ──▶ 抹除后图像
                        │                                   │
                        ▼                                   ▼
                 TextRenderer (适配宽度→重绘→复合)      CanvasView 渲染
                        │ [patch]                          │
                        ▼                                  ▼
                 CollisionDetector ──▶ 通过?             画布叠加层
                        │                                   │
                        ▼                                   ▼
                 Exporter ──▶ PNG/JPEG 原分辨率          检查器面板
```

数据单向流动：`SourceImage`→`TextBlock`→`TextStyle`→`patch`。除 UI 层外，**任何模块不得反向依赖**（本文件 §4 契约强制）。

---

## 2. 技术选型论证（第一性原理）

> 总原则：截图是**已栅格化的像素网格**，没有文本层。所有"字体一致"问题都可转化为**确定性计算**（渲染后再比对），而不是深度模型猜测。先拆解"无痕"的数学定义：修改区域与其周边视觉连续 = ① 背景连续（抹除质量）② 同块文字样式连续（字体/字号/颜色/间距/基线还原）。

### 2.1 Vision OCR 使用方式

**候选方案：**
| 方案 | 取舍 |
|------|------|
| A. `VNRecognizeTextRequest`（`VNRecognizeTextRequest`） | 系统内置、离线、CJK+Latin 覆盖好，输出置信度与 bbox |
| B. 自研 OCR（CRNN 等） | 开发量巨大，离线模型嵌入重，v1 否决 |
| C. 第三方 OCR（Tesseract） | 中英文混排精度低于 Vision，SPM 集成繁琐，否决 |

**结论：A。** 关键配置与理由：

- `recognitionLevel = .accurate`：截图文字小（常见 12–28px），`.fast` 掉字明显；首轮全图只跑一次，≤3s 预算内（§2.8）。
- `recognitionLanguages = ["zh-Hans", "en-US"]`：优先级数组，截图场景 99% 覆盖。追加语言（zh-Hant/ja/ko）按需，每加一种增延迟；v1 不做语言设置 UI，固定这两项。
- `usesLanguageCorrection = true`：FontMatcher 要渲染 OCR 文本做比对，"读错了"会导致渲染错字、比对崩盘，语言纠正显著提升实词正确率；代价是对用户名/ID 类乱码可能"纠正错"，由置信度弱化标记兜底（§6）。
- **按词/短语返回（`automaticallyDetectsLanguage` 关闭）**：不按字符返回。Vision 原生无按字符识别模式；逐字符框用 macOS 14+ 的 `VNRecognizedTextObservation.boundingBox(for:)` 获取（按 Character 网格），用于字形宽距分析（§2.6），不作为识别粒度。
- **字号估算辅助**：`boundingBox` 为归一化坐标（原点左下），换算到图像 px（注意翻转）即得行高/逐字框，作为 SizeEstimator 初值（§2.5）。
- 坐标转换契约：Vision 归一化右下原点 → 图像左上原点 px，统一在 `TextBlockDetector` 内完成，下游只见图像坐标。

**前置依赖**：macOS 14+（`boundingBox(for:)` 逐字框）。**失效回退**：更低系统版本不提供逐字框 → `perCharBoxes = nil`，宽距分析降级为聚合漂移（§2.6 备选），功能不阻断。

### 2.2 字体匹配算法（核心命门）

**本质**：给定原图文字块，找系统字体集中"渲染同一文本后与原文结构最像"的字体。字形轮廓（glyph outline）定义字体身份；抗锯齿/次像素渲染是渲染器噪声，应被剔除。→ **两级剪枝 + 二值掩码重叠比对 + 逐字对齐**。

**候选集构建：**
1. 枚举：`CTFontManagerCopyAvailablePostScriptNames()`（macOS 约 300–600 个字体面）。启动时构建 `FontCatalog`，字体变更（第三方字体安装）监听 `kCTFontManagerRegisteredFontsChangedNotification` 增量刷新。
2. **去重字重变体**：按 family 分组，保留唯一 (weight, italic) 组合（`kCTFontWeightTrait` 归一化到 100–900；剔除同一 (family, weight, italic) 的别名 PostScript 面）。
3. **剧本分类剪枝**：文本含任一 CJK 码点 → CJK 块；否则 Latin 块。直接剔除不含该剧本字形的字体。
4. **字符覆盖剪枝**：`CTFontGetGlyphsForCharacters`，要求候选字体覆盖文本字符 ≥95%，缺失即淘汰（防 tofu 方块字）。纯 Latin 文本通常剩 100+ 面，CJK 文本通常剩 15–30 面（macOS 中文字体本就少）。

**渲染后端选择：CoreText(CTLine) + CGBitmapContext，非 TextKit、非纯 CoreGraphics 裸绘制。**
- TextKit（NSLayoutManager）为布局体系设计，控制粒度粗、按 NSAttributedString 排版路径长，无法保证逐像素 canvas 语义。否决。
- 裸 CoreGraphics（`CGContextShowGlyphsAtPositions`）需自行处理字体矩阵/翻转/字距，重复造轮子。否决。
- **CTLine 方案**：`CTLineCreateWithAttributedString`（设字体、字号、`kCTTrackingAttribute`）→ `CTLineDraw` 进 `CGBitmapContext`。一行代码拿全字形布局（含 kerning），坐标系翻转一次即可，可获得逐字 advance。**正选。**

**渲染参数（比对用）：**
- 画布：CGBitmapContext，Gray 8-bit，`premultipliedLast`，尺寸 = `CTLineGetTypographicBounds` 宽高 + 4px padding，上限 2048px 防爆。
- 抗锯齿：**开**（与屏幕截图同 profile），但**先二值化再比对**（见下），AA 开关差异被消弭。
- **尺度归一化**：字体匹配必须与字号无关（匹配先于估字号）。原文字块掩码与候选渲染掩码**均归一化到规范行高 H（阶段1取 32px，阶段2取 64px）**，双线性缩放后 Otsu 二值化。→ 匹配天然 scale-invariant，字号在 §2.5 单独闭环校准。
- 次像素渲染规避：离屏 CGContext 无 LCD 次像素，浏览器截图有；缩放+二值化后彩色副条纹坍缩为边缘像素，影响可忽略。这正是"二值化"而非"原样 SSIM"的第二重理由。

**相似度指标选择论证：**
| 指标 | 评析 |
|------|------|
| SSIM | 为全参考图像质量（亮度/对比度/结构在局部窗口）设计；对二值字形退化为加窗重叠统计，C1/C2 需针对近零亮度调参，计算重，阈值不直观（0.8? 0.9?）。且对 AA/纹理差异敏感——这恰是我们要**忽略**的渲染器噪声。**仅用于端到端验收**（§5），不用于匹配。 |
| 像素差 MSE/MAE | 对 1–2px 水平偏移极敏感，未对齐惩罚过大，需先对齐才可用（对齐后与 IoU 等价）。 |
| **二值掩码 Dice**（正选） | Dice = 2·\|A∩B\|/(\|A\|+\|B\|)，几何意义=笔画重合率，[0,1] 直观，阈值好定，SIMD 可压到亚毫秒。字重差异（该不该区分就区分）、轮廓差异都直接反映。 |
| 灰度 NCC（副选/决胜） | 对笔画灰度分布敏感，用于 top 候选得分接近时（差 < 0.03）区分"轮廓相似但字重/对比度不同"的面。 |

**初值阈值**（标定为可调旋钮，校准方法与 ≥90% 验收绑定，见 §7.2）：
- Dice ≥ 0.86 且与第二名差 ≥ 0.03 → `exact`；
- Dice ∈ [0.70, 0.86) → `approximate`（走视觉参数兜底 §2.2.2）；
- Dice < 0.70 → `unmatched`（几乎可断定 webfont/品牌字体）。

**对齐策略（防伪惩罚）：** 逐字比对。用 mac14+ 逐字框把原图按字符切窗；候选渲染同样按 `CTLineGetOffsetForStringIndex` 逐字切窗；每字窗质心对齐 + ±2px 平移搜索（9 邻域）取最大 Dice。整块得分 = 各字 Dice 加权平均（按字窗面积加权）。逐字比对同时**天然免疫字间距（tracking）差异**——两行文字 tracking 不同但字体相同，逐字掩码完全一致；这是"字距先被剥离、后单独估计"的关键设计（§2.6）。

**性能预算（单块 ≤300ms）达成手段：**
- **两级剪枝**：
  - 阶段1（粗筛）：family 级代表面（CJK family 用 Regular，无则最接近 400 的面）渲染于 H=32px 画布，Dice 粗算，取 top-12 family。成本 ≈ 候选面数 × (渲染 ~0.5ms + 比对 ~0.2ms) ≈ 100×0.7ms ≈ **70ms**。
  - 阶段2（精筛）：top-12 family 内全部去重 (weight, italic) 面（约 4–6 面/family，含 italic），渲染于 H=64px，逐字对齐 Dice；同分决胜用灰度 NCC。成本 ≈ 60 面 × (渲染 ~2ms + 比对 ~1ms) ≈ **180ms**。
  - 总预计 **≤250ms**，预留 50ms 缓冲进 300ms 预算。
- **字形掩码 LRU 缓存**：`(postScriptName, 字符UCS, 尺寸桶64px) → 掩码`，全局会话级 LRU（cap 4000 条目）。同一截图多文字块共享常用字掩码，首块付全价、后续块典型 **≤50ms**。
- 排序提前终止：阶段2按阶段1得分降序，比对中当前 best 已超剩余候选理论上限（Dice ≤ 1）不可能超越时截断。
- 计量：`os_signpost` 插桩 + Release 基准测试在参考机（Apple Silicon）断言单块 ≤300ms（§7.3）。

**2.2.2 视觉参数兜底（FontFallback）**：特征向量 {衬线度（笔画粗细方差/端点形态）、字重（平均笔画宽）、字宽（平均 advance/em）、x 高比、CJK/Latin}，从原图掩码提取，与各 family 预计算特征（会话内缓存，取自该 family Regular 渲染）做加权距离，最近 family 上位。命中目标：**同一字体族 top-3 内**。UI 明确"近似匹配"并给手动选择入口。

### 2.3 inpaint 抹除方案

**本质**：被文字笔画破坏的像素 = 原背景像素缺失，需按周围背景推断。截图背景多为**平坦色 / 线性渐变 / 轻噪声/细纹**（网页卡片、聊天气泡、列表底色）。
**掩码语义（关键）**：只 inpaint **原笔画掩码膨胀 1px** 的区域，而非整块 bbox——新文字笔画会覆盖 bbox 大部，真正需要补的就是"旧笔画下、新字形没盖住"的背景。区域小 → 快且保真。膨胀 1px 清掉旧文字 AA 残边。

**候选方案：**
| 方案 | 论证 |
|------|------|
| OpenCV `cv::inpaint`（Telea/NS）经 SPM 集成 | 可行性：OpenCV 无官方 macOS SPM 包，需第三方/自打包 XCFramework binaryTarget（约 200–300MB 体积、需 arm64+x86_64 双架构、版本滞后、CVE 跟随负担、构建链脆弱）。可用但对 v1 是**重型依赖换平庸收益**——Telea/NS 对平坦/渐变背景并无优势。 |
| CoreImage/Metal 自研 | CoreImage 无 inpaint 滤镜；Metal 多尺度扩散 = 真 R&D。v1 否决。 |
| **自研两级 inpaint**（正选） | 见下。 |

**自研两级 inpaint 算法思路**（核心 ~150 行，纯 vImage/Accelerate 可向量化）：
1. **Tier1 调和填充（harmonic fill）**：在掩码内求解 Laplace 方程 Δu=0，Dirichlet 边界 = 掩码外缘像素。数学性质：**平坦背景 → 恒值填充（正确）；线性渐变 → 精确还原斜坡（正确）**——这是截图 80% 场景的解析解。实现：Gauss–Seidel/共轭梯度松弛，典型文字块（<64×32）100 次迭代 ≈ 1–5ms。
2. **Tier2 纹理残留（annulus patch copy）**：掩码邻域局部方差高于阈值（判定非平坦）时，对每个掩码像素，在掩码外 8–24px 环形带内做小窗 SSD 匹配，拷贝最佳背景补丁。处理轻噪声/细纹/毛玻璃模糊（把高频搬进来）。
3. 复合：Tier1 打底 → Tier2 仅在不平区域以权重混合。输出与 Tier1 的差异作为**纹理残留度**指标（供 UI 披露"背景恢复可能不完美"，§6）。

**OpenCV 切换条件（写进契约，不在实现里）**：验收语料（含渐变+噪声+细纹背景样本）上，抹除区域独立 SSIM 均值 < 0.90 或可见残影命中率 > 15% 时，启动备选实现 `OpenCVInpainter`（Telea 主、NS 备）替换 `SelfInpainter`，**模块契约 `TextErasing` 不变**，零侵入切换。理由：先以零依赖方案拿第一性收益，用数据决定要不要背 300MB 依赖，而非恐惧先行。

**前置依赖**：Accelerate/vImage（macOS 内置）。**失效回退**：平坦/渐变场景 Tier1 已达标，Tier2 故障禁用于纹理场景并披露（不静默）。

### 2.4 颜色采样（前景/背景 + 抗锯齿边缘处理）

**本质**：纯色文字的每个像素 = `α·fg + (1-α)·bg` 的线性混合（AA 边缘）+ 抖动/噪声。fg 估计 = 找笔画核像素的稳定色簇。

**算法**：
1. 背景模型：块 bbox 外缘环形带（笔画掩码外 2–8px）像素 → 判定 `flat`(色方差 < τ) / `gradient`(沿主轴线性拟合) / `texture`(残差超限)。背景色/梯度模型存 `BackgroundModel`，供重绘合成（§2.7）。
2. 笔画核像素：块内与背景模型距离 > τ 的像素为候选前景集；**排除边缘环**（笔画掩码腐蚀 1px）剔除 AA 混合像素。
3. 前景色：候选集在 RGB 空间做小 k 聚类（k=2，取大簇），色 = 大簇中位数。**不假设"字是深色"**：用"距背景模型的距离"而非亮度方向分类，深色模式白字自动正确。
4. α 提取：`α_i = (c_i − bg_i)/(fg − bg_i)`（逐像素、梯度背景用逐像素 bg）→ 每像素覆盖率。此 α 是重绘合成的**无痕关键**：新字形覆盖率 × 前景色 + 背景模型 = 与原图同 AA profile 的复合（§2.7）。
5. 低对比度检测：fg 与 bg 相对亮度差 < 0.08 → 判定"低对比度"（疑似误检），置信度降级进 UI。

**候选对比**：均值/最暗像素法（对 AA 噪声与异常值脆弱）否决；直方图峰提取（无监督、不稳定）否决；**距离分类 + 大簇中位数**（鲁棒、O(n)、对渐变/纹理背景有模型支撑）正选。

### 2.5 字号估算

**初值**：`fontSize0 = 行bbox高度px / k`，k 为字体典型 ascent+descent 与 em 之比（Latin 约 1.15–1.25、CJK 约 1.0–1.16），取 1.15 起步。
**闭环校准（正选）**：字体匹配完成后，**用已匹配字体的真实 metrics 反查字号**：以 fontSize0 渲染原文，量渲染行高 H_r 与观测行高 H_o，`fontSize_final = fontSize0 · H_o/H_r`（行高对字号线性，一步收敛）。±0.5px 为达标精度。
**单位口径**：全部按**图像 px** 运算与渲染（截图常见 2x，源 14pt ≈ 28px；直接渲染像素级即所见即所得，无 pt/px 换算误差）。UI 显示 px，附 2x 折算 pt 参考（本节口径为待 zongguan 裁决项之一，§11）。

**候选对比**：纯几何推导（行高×常数）不依赖字体，误差大（±20%）；渲染探针闭环依赖"字体已匹配"，两级递进是唯一同时满足精度与解耦的方案。

### 2.6 宽度适配与字间距

**字间距估计**：
- 主路（mac14+ 逐字框）：逐字观测 advance `a_i^obs` vs 候选字体在估算字号下自然 advance `a_i^nat` → `tracking = mean(a_i^obs − a_i^nat)`（px）。逐字比对已剥离 tracking（§2.2 对齐），此处独立恢复，无耦合污染。
- 备路（无逐字框）：聚合漂移 `tracking = (W_obs − W_nat)/(n−1)`，n 为文本字数；多行块按行平均。
- `kCTTrackingAttribute` 值按 px 传入（CoreText 规定 tracking 单位为 point，字形按字号线性缩放后 px 即 pt 口径，一致）。

**新文字宽度适配公式**（重绘核心）：
1. 原文字 ink 宽 `W_orig`（逐字框并集宽度；无逐字框则 bbox 宽）。
2. 新文本以原字号 F0 渲染，测 ink 宽 `W'(F0)`（`CTLineGetTypographicBounds`）。
3. 缩放系数 `k = W_orig / W'(F0)`。字形宽度对字号**严格线性**（kerning、advance 同比例缩放），故 **`F_final = F0 · k`**，直接以最终字号渲染——**拒绝渲染后再位图缩放**（二次采样糊边）。
4. **缩放不对称为原则**：新文本**变长**时 k<1 缩小，下限 `k_min = 0.5`（保底最小字号 0.5·F0）；新文本**变短**时**不放大**（放大破坏字面设计的字距感知，短文本以原字号重绘并在原 ink 区间内水平居中）。k < k_min → 触发"文字过长"提示（§6），拒绝提交。
5. 基线对齐：基线 y = 原块逐字框下缘 − 下行 descent 估计；以 `CTLine` 基线锚定绘制，检查器提供 ±1px 基线微调步进。
6. 无逐字框时 W_orig 退化为 bbox 宽，适配容差放宽 ±2%。

**候选对比**：位图整体缩放（保宽毁底、最廉价的"伪适配"）否决；字体级线性缩放（保轮廓质量）正选；非对称规则（短不放大）是审美判断：风格一致性 > 占满宽度。

### 2.7 重绘合成（无痕的最后一环）

1. 以最终字号 + tracking + 基线渲染新字形 → 得**覆盖率掩码**（Gray 8bit，AA 开）。
2. 复合：`pixel = bg_model(x,y) + α_mask(x,y) · (fg − bg_model(x,y))`——**与原图文字同一混合方程、同一 AA profile**。平坦背景 = 精确复合；渐变背景 = 逐像素背景模型复合。这是"看不出衔接"的关键（硬贴 RGBA 会留亮边）。
3. 复合区域 = 新字形外接 +1px；覆盖范围外不染指（背景原样保留）。

### 2.8 异步模型：Swift Concurrency（正选）vs GCD

**场景约束**：OCR/抹除/重绘均 CPU 密集（毫秒–秒级），UI 绝不可阻塞；用户编辑会**取消并重算**（generation 语义）。

**论证**：
| 方案 | 评析 |
|------|------|
| GCD | 无编译期隔离；嵌套回调/信号量编排取消逻辑脆弱；"取消"需手工 flag。 |
| **Swift Concurrency** | 结构化并发：`Task` 级取消、`withTaskGroup` 并行、`@MainActor` 隔离状态、actor 封装串行管道。编译期保证数据竞争不成立。macOS 14+ 主力 API。**正选**。 |

**线程模型设计**：
- `EditorState`：`@MainActor @Observable`，唯一权威状态，UI 直读。
- `AnalyzeActor`（后台串行）：OCR 全图 + 每块样式分析；CPU 密集段（Vision perform、CoreText 渲染、掩码比对）在线程池（`Task.detached(priority:)` 或 `withTaskGroup`，并发上限 `processCount/2`）内执行——CTFont/CTLine 不可变对象线程安全，各自独立 CGBitmapContext 可并行；**CG/CT 对象不跨 actor 传递**，边界处只传值类型（`TextBlock`、掩码 `Data`）。
- `WorkflowActor`（后台串行）：抹除→重绘→碰撞的编排，输入为最新 `TextStyle` + 新文本，输出 patch。
- **Generation 计数**：每个文档变更 `generation += 1`；管道各阶段完成后比对 generation，过期结果丢弃（即使任务未被取消，先完成者作废）。保证"处理中继续编辑"（overlay_processing 不阻断）的一致语义。
- **取消**：新编辑触发旧任务 `cancel()` + generation 检双重保险。Vision 同步 `perform()` 无原生取消 → 放 `Task.detached` 内以 task 取消为信号，阶段间检查 `Task.isCancelled`。
- 进度：actor 通过主 actor 方法回报"正在分析 3/12 块"，UI 局部微进度。

---

## 3. 状态管理

### 3.1 五态 + 四叠加态 → SwiftUI 映射

**选型：`@Observable`（Observation 框架）而非 `ObservableObject/@StateObject`。** 理由：状态对象是**单一根对象**（单窗口应用），Observation 提供属性级失效（只刷新变了的视图，Canvas 大图重绘成本高，必须细粒度失效）；`ObservableObject`+Combine 是旧范式，`@State` 只适合叶子局部状态（如检查器输入框的未提交草稿），不用作文档权威源。

```swift
@MainActor
@Observable final class EditorState {
    // —— 文档模型（权威源）——
    var sourceImage: SourceImage?
    var textBlocks: [TextBlock] = []

    // —— 阶段态（互斥主态）——
    var phase: EditorPhase = .loading          // 五态之一

    // —— 叠加态（与 phase 正交，可叠加）——
    var overlay: EditorOverlay?                // 四叠加态之一（同一时刻至多一个展示，但语义独立于 phase）

    // —— 编辑会话（selected/preview 期间的非提交草稿）——
    var selection: UUID?                       // 选中块 id
    var draft: EditDraft?                      // 未提交内容/样式草稿

    // —— 导出 ——
    var exportURL: URL?                        // 最近成功导出路径
}
```

```swift
enum EditorPhase: Equatable {
    case loading            // 解码+OCR 中
    case idle               // 无选中
    case selected(UUID)     // 有选中、未改内容
    case preview(UUID)      // 内容已改、未确认（实时预览中）
    case noText             // OCR 无检出
}

enum EditorOverlay: Equatable {
    case processing(UUID, PipelineStage)      // 抹除/重绘执行中（不阻断）
    case fontMismatch(UUID, FontMatchResult)  // 近似匹配黄条
    case exportSuccess(URL)                   // 导出成功
    case exportFailure(String)                // 导出失败+重试
}
```

正交性设计理由（对应 page_states §4 约束）：`overlay` 独立于 `phase`，任意 phase 下可叠加 `processing`（哪怕 idle 时批量分析）与 `export*`——满足"overlay 不得阻断编辑主链路"。`fontMismatch` 仅在 preview 相关块上展示。

**状态转移约束（实现即测试，对齐 page_states §5）**：`loading` 禁选中；`idle→selected` 仅经点击有效块；`selected→preview` 仅内容变更时进入（样式调整不触发内容重绘，防抖动）；`notext` 下添加块成功必须直达 `selected`；`preview` 的"确认"/"继续调整"/"撤销"三出口。

### 3.2 Undo/Redo：Command 模式（正选）vs 快照

**论证**：
- 纯快照：整画布不可变拷贝每次提交一份。4K RGBA = 33MB/份，20 步 ≈ 660MB，且"仅改一个字"也拷贝整图，浪费且无下限保障。否决。
- 纯 Command（闭包式）：`apply/undo` 闭包捕获上下文，内存轻但是隐式图——难以序列化、难以测试、闭包生命周期易错。否决。
- **Command 带物化效果（正选）**：每个命令存**最小数据增量**（不存闭包、不重算）：

```swift
protocol DocumentCommand: AnyObject {
    var name: String { get }                 // 菜单/历史显示
    func apply(to state: inout EditorDocument)
    func undo(from state: inout EditorDocument)
    var memoryEstimate: Int { get }          // 冗余度预算
}
```

命令族（v1 全集，可枚举）：
- `TextEditCommand`：块 id、oldText/newText、**受影响 patch 前后裁剪**（块 bbox 级，典型 <300×80×4B ≈ 96KB）——抹除+重绘的效果物化在命令里，撤销=回贴旧裁剪，**不重算 inpaint**。
- `BlockGeometryCommand`：old/new bbox（移动/缩放）。
- `BlockStructuralCommand`：添加/删除/合并（删除带其 patch 裁剪以便还原）。
- `StyleOverrideCommand`：用户手动改样式 old/new 值。

撤销栈：`Array<DocumentCommand>` cap 50 步；`memoryEstimate` 累计 > 256MB 时淘汰最旧（UI 提示"较早历史已清理"）。**preview 阶段草稿不落栈**，仅"确认"产生一条命令——防打字/拖拽刷爆历史。

理由闭环：本应用所有变更都是**单块/单属性的可枚举操作**（无全文档级自由度），命令枚举完备、增量极小；物化效果避免 inpaint 重复执行（其成本是重计算的数百倍）。快照只有在"任意自由编辑（如笔刷）"场景才更有价值，本产品 v1 无此场景。

---

## 4. 模块划分与进程内模块契约

### 4.1 目标结构与依赖方向

```
PxiuCore (SPM target，无 AppKit/UI 导入，仅 Foundation/CoreGraphics/CoreText/Vision/ImageIO/Accelerate)
  ├─ ImageIO   : ImageLoader, SourceImage
  ├─ OCR       : TextBlockDetector, OCRConfiguration, TextBlock, CharBox
  ├─ Style     : FontCatalog, FontMatcher(+Fallback), StyleAnalyzer, StyleEstimators(Size/Color/Spacing), TextStyle, BackgroundModel
  ├─ Erase     : TextEraser, Inpainter(自研 Tier1/Tier2)
  ├─ Render    : TextRenderer, FitCalculator, CollisionDetector, RenderedText
  ├─ Export    : Exporter
  ├─ Model     : DocumentState(EditorDocument), Commands
  └─ Workflow  : EditorWorkflow(generation 编排), AnalyzeActor, WorkflowActor
App (薄壳：App 入口 + UI 目标)
  └─ UI        : EditorState(@Observable), CanvasView, InspectorView, ToolbarView, OverlayViews
Tests (PxiuCoreTests / PxiuIntegrationTests / PxiuPerformanceTests)
```

**可测性硬约束**：Core 无 `import AppKit/SwiftUI`；像素数据用 `CGImage`/`Data`（CF 类型，纯值语义）；所有 `protocol` 有生产实现 + 测试替身（内存注入的 `ImageLoading`、确定性时钟）。

### 4.2 契约定义（Swift）

```swift
// ============ ImageIO ============
struct SourceImage: Sendable, Equatable {
    let cgImage: CGImage          // 解码后 sRGB 像素图
    let sizePx: CGSize            // 原分辨率（导出必须一致）
    let format: ImageFormat       // .png/.jpeg/.heic
}

protocol ImageLoading: Sendable {
    func load(url: URL) throws -> SourceImage      // PNG/JPEG/HEIC，解码 →sRGB 像素缓冲
}

// ============ OCR ============
struct OCRConfiguration: Sendable {
    var languages: [String] = ["zh-Hans", "en-US"]
    var recognitionLevel: OCRLevel = .accurate     // .accurate / .fast
    var usesLanguageCorrection: Bool = true
}

protocol TextBlockDetecting: Sendable {
    func detect(in image: SourceImage,
                configuration: OCRConfiguration) async throws -> [TextBlock]
    // 内部：Vision 归一化左下原点 → 图像 px 左上原点；mac14+ 填 perCharBoxes
}

struct CharBox: Sendable, Equatable { let char: Character; let rect: CGRect } // 图像 px

enum BlockStatus: Sendable, Equatable { case detected(Float), userAdded, merged, errored(String) }

struct TextBlock: Identifiable, Sendable, Equatable {
    let id: UUID
    var text: String              // 当前（可编辑）文本
    let detectedText: String      // OCR 原文
    var bbox: CGRect              // 图像 px，左上原点
    var confidence: Float
    var perCharBoxes: [CharBox]?  // mac14+；nil 时下游走聚合路径
    var style: TextStyle?         // StyleAnalyzer 填充
    var status: BlockStatus
}

// ============ Style ============
struct FontFace: Hashable, Sendable {
    let postScriptName: String; let family: String
    let weight: Int               // 100–900（归一化）
    let italic: Bool
    let displayName: String
}

struct FontCatalog: Sendable {
    let faces: [FontFace]
    func facesCovering(_ text: String, script: ScriptKind) -> [FontFace]  // 覆盖≥95% + 剧本过滤
}

enum MatchStatus: Sendable, Equatable {
    case exact(Double)                    // 顶级 Dice
    case approximate(Double, FontFace)    // Dice 与兜底命中的面
    case unmatched(FontFace)              // 兜底强选，拟真度低
}

struct FontMatchResult: Sendable, Equatable {
    let status: MatchStatus
    let topScore: Double
    let runnerUps: [FontFace]             // 供 UI 手动选择展示 top-5
    let ambiguous: Bool                   // 1st/2nd 差 < 0.03
}

enum BackgroundModel: Sendable, Equatable {
    case flat(RGBColor)
    case gradient(axis: Axis, color0: RGBColor, color1: RGBColor, delta: CGPoint)
    case texture(mean: RGBColor, variance: Double)   // 纹理：均值+残余标记
}

enum StyleWarning: Sendable, Equatable, CaseIterable {
    case lowContrast          // fg/bg 相对亮度差 < 0.08
    case complexEffect(String) // 渐变/描边/发光 检出
    case textureBackground    // bg 纹理残留风险
}

struct TextStyle: Sendable, Equatable {
    var font: FontFace
    var fontSizePx: CGFloat
    var color: RGBColor                    // 笔画核 fg
    var background: BackgroundModel
    var tracking: CGFloat                  // px @ fontSizePx
    var baselineOffset: CGFloat            // 基线相对 bbox 下缘的偏移 px
    var matchStatus: MatchStatus
    var warnings: [StyleWarning]
}

protocol FontMatching: Sendable {
    func match(block: TextBlock, image: SourceImage,
               catalog: FontCatalog) async throws -> FontMatchResult
    // 内部契约：两级剪枝（family粗筛→weight精筛）+ 逐字对齐 Dice + NCC 决胜 + LRU 掩码缓存
}

protocol StyleAnalyzing: Sendable {
    func analyze(block: TextBlock, image: SourceImage, catalog: FontCatalog,
                 match: FontMatchResult) async throws -> TextStyle
    // 内部顺序：SizeEstimator(渲染探针) → ColorEstimator(fg/bg/α) → SpacingEstimator(逐字/聚合) → warnings
}

// ============ Erase ============
struct EraseResult: Sendable, Equatable {
    let image: SourceImage                  // 抹除后整图（不可变 COW 语义）
    let residualMetric: Double              // 纹理残留度（供 UI 披露）
}

protocol TextErasing: Sendable {
    func erase(_ image: SourceImage, block: TextBlock,
               style: TextStyle) async throws -> EraseResult
    // 掩码 = 原笔画掩码 膨胀 1px（新笔画覆盖区外才是真需要补的像素）
}

// ============ Render ============
struct FitSpec: Sendable, Equatable {
    var targetInkWidthPx: CGFloat           // W_orig
    var minScale: CGFloat = 0.5             // k_min
    var alignment: Alignment = .centerInInk // 短文本居中于原 ink 区间
}

struct RenderedText: Sendable, Equatable {
    let patch: CGImage                      // 新字形复合 patch（bg模型+α·fg）
    let inkWidthPx: CGFloat
    let fontSizeUsed: CGFloat               // F_final = F0·k（仅变长时 < F0）
    let scaleFactor: CGFloat                // 实际应用的 k
    let trackingUsed: CGFloat
    let baselineY: CGFloat                  // 图像坐标
}

protocol TextRendering: Sendable {
    func render(text: String, style: TextStyle,
                fit: FitSpec) async throws -> RenderedText
    // 内部：CTLine 测量 W'(F0) → k → 最终字号直渲染（禁止位图二次缩放）
}

struct Collision: Sendable, Equatable { let blockID: UUID; let overlapPx: CGFloat }

protocol CollisionDetecting: Sendable {
    func collisions(with candidate: CGRect, in blocks: [TextBlock],
                    excluding id: UUID) -> [Collision]   // 重叠 > 2px 计碰撞
}

// ============ Export ============
enum ExportFormat: Sendable { case png, jpeg(quality: Double) }

protocol Exporting: Sendable {
    @discardableResult
    func export(_ image: SourceImage, format: ExportFormat, to url: URL) throws -> URL
    // CGImageDestination；分辨率与原图一致；JPEG quality 默认 0.9
}

// ============ Workflow ============
enum PipelineStage: Sendable { case ocr, styleAnalysis, erase, render, export }

protocol EditingWorkflow: Sendable {
    /// 打开文件 → 解码+OCR → 返回块列表（阻塞至首屏可用，后续分析后台续跑）
    func open(url: URL) async throws -> EditorPhase
    /// 提交编辑：抹除+重绘+碰撞检查 → patch 落画布（不落 undo 栈）
    func previewEdit(blockID: UUID, newText: String) async throws -> EditPreviewResult
    /// 确认：preview 结果物化 + 入 undo 栈
    func confirmEdit(blockID: UUID) throws
    /// 导出
    func export(format: ExportFormat) async throws -> URL
}
```

### 4.3 TextBlock 字段设计理由

- `text`/`detectedText` 分离：OCR 原文与用户编辑中文本解耦——撤销/重算样式都以 detectedText 为锚，"用户改了又改"不污染样式基线。
- `perCharBoxes` 可选：macOS 版本差分在类型层面显式，下游 `StyleAnalyzer`/`FitCalculator` 按 nil 走聚合路径，无运行时崩溃面。
- `style` 可选：分析未完成时 nil，UI 显示"分析中"，与 overlay_processing 联动。
- `status` 承载 OCR/手动/合并/异常 四类来源，UI 据此决定弱化标记与可操作性。

---

## 5. 错误处理：PRD 已知限制 → 检测 → UI 反馈契约

| PRD 限制 | 技术检测方式 | UI 反馈契约（xiaoyou 按此实现） |
|----------|-------------|-------------------------------|
| 字体匹配失败（webfont/品牌字体） | `matchStatus`: `.approximate`（Dice 0.70–0.86）/ `.unmatched`（<0.70）；`ambiguous`（1st/2nd 差<0.03） | preview 黄条"近似匹配：XX 字体"，点击展开 top-5 手动选择；`.unmatched` 红级提示"无法精确匹配，已用 XX 近似"，仍可继续（不阻塞）但导出前再次确认 |
| 复杂效果（渐变/描边/发光） | ColorEstimator 检出笔画内多色簇（渐变）；笔画外缘色环（描边）；晕带（发光） | 检查器署名式提示"检测到渐变/描边效果，v1 仅尽力逼近"；渲染仍走纯色复合 + 最接近平均色 |
| 极端长度替换 | FitCalculator：`k < k_min(0.5)` | 预览不渲染 + 检查器红字"文字过长，已到最小字号仍超出文字块——请缩短文字或扩大文字块"；确认按钮禁用（阻止不合格提交） |
| 重绘碰撞相邻块 | CollisionDetector：新 ink 外接框与邻块 bbox 重叠 > 2px | 画布上碰撞块红色虚线高亮 + 提示"与 X 块重叠"；确认禁用直至解决 |
| OCR 低置信度 | `confidence < 0.5` | 块虚线边框 + "?" 角标；点击可对该块区域 `.fast` 重 OCR（手动 re-OCR 兜底） |
| 抹除残影（纹理背景） | Inpainter `residualMetric` 超阈值 | 检查器弱提示"背景恢复可能不完美"；不阻断（披露优先） |
| 无文字检出 | OCR 空结果 | `phase = .notext`，引导手动框选（用户拖框 → 区域内重 OCR 或直编辑） |

错误统一出口：`StyleWarning`/`MatchStatus`（Core 语义）→ `EditorState` 映射为 overlay/inspector 提示（UI 呈现）。**禁止静默失败**（NFR-4）：管道任何 throw 都进 overlay（exportFailure / 处理失败重试），不吞异常。

---

## 6. 测试策略

### 6.1 工程可测性支柱

- `PxiuCore` 纯净：无 AppKit/SwiftUI 导入；全部依赖经 protocol 注入；像素操作用 CF 类型，测试可无窗口跑。
- 确定性：视觉调度为可注入时钟；渲染后端固定参数（AA 开、Gray 桶）；测试禁网络。
- 快照基准：`XCTAssert` + 像素断言工具（掩码 Dice、区域 SSIM 现成实现，测试与生产共用 §2.2 指标代码）。

### 6.2 单元测试清单（对齐 PRD §6 验收）

| # | 测试 | 方法 | 验收线 |
|---|------|------|--------|
| U1 | FontMatcher 正确率 | **用 CoreText 渲染已知字体的测试图**（40 字体 × {Regular/Medium/Semibold/Bold} × {12/14/18/28px} × {1x/2x}，文本样本含中文/英文/数字），渲染结果直接喂回 matcher（生产同路径） | 同字体+字重识别率 ≥ 90%；同族不同重 > 60% 判对（其余重判为近似且手选可补救） |
| U2 | FontMatcher 抗 AA | 用不同 AA 开/关渲染同一字体，比对不串族 | 不串族率 ≥ 95% |
| U3 | SizeEstimator | U1 语料 + 已知字号 | 字号回收误差 ≤ ±0.5px 占比 ≥ 95% |
| U4 | ColorEstimator | 合成 fg/bg+AA 边缘复合图（平坦/渐变/噪声 bg，深色浅色各半） | 平坦 ΔE≤4；渐变 ΔE≤8（95 分位） |
| U5 | SpacingEstimator | 合成已知 tracking（−1/0/+2px） | 回收 ±0.5px |
| U6 | Inpainter | 掩码区域独立 SSIM（平坦/渐变/高斯噪声 bg） | 区域 SSIM ≥ 0.95（掩码外扩 2px 不参与） |
| U7 | FitCalculator | 新文本变长/变短/极端长 | 结果 ink 宽与目标差 ≤ 1%；k 越界触发"过长"警告；变短不放大 |
| U8 | 状态机 | 五态+四叠加全部转移（page_states §5 逐条） | 0 违反 |
| U9 | Undo/Redo | 全命令族 + 栈 cap + 内存淘汰 | 操作对称可逆；preview 不落栈 |
| U10 | Export | PNG/JPEG 往返解码比对 | 分辨率一致；PNG 像素全等；JPEG 用 PS 无参考指标 + 尺寸一致 |
| U11 | 碰撞检测 | 构造重叠/贴边/分离用例 | 阈值 2px 边界行为正确 |

### 6.3 集成测试：合成截图端到端 SSIM ≥ 0.95

- 构造：背景（平坦/渐变/噪声，含模拟聊天气泡卡片）+ CoreText 渲染原文 → **合成截图**。
- 流程：detect → analyze → 用户改新文本（脚本注入）→ erase → render → 得结果图。
- 基准：同一背景 + 渲染新文本（Ground truth，生产渲染同路径）。
- 断言：结果图 vs 基准整图 SSIM ≥ 0.95（PRD §6.2 严格线，合成样本可控）。含长/短文本各半、中日英文混排。
- 诚实边界（呼应 PRD 对抗审查）：**合成严格线与真实样本人工判定分轨**——SSIM ≥ 0.95 只承诺合成样本；真实截图走 §6.4 人工。

### 6.4 真实截图样本人工判定

- 语料：20–30 张真实截图（聊天/日志/网页价格页，用户自产或授权样本，不入 git，本地 fixtures）。
- 判定：≥3 人独立目测"该块是否看不出修改痕迹"，协商一致；通过率 ≥ 90% 块 为验收。
- 自动化辅助：人工判定同时记录 mask 级 SSIM 分布，作为"严格线不可达真实图"的量化旁证（供 v1.1 迭代输入）。

### 6.5 性能测试

- Release 配置 + Apple Silicon 参考机：单块字体匹配 ≤ 300ms（U1 语料抽样 50 块）；打开+OCR ≤ 3s（典型 1440×900/2x 截图，10 张均值）。
- 机器相关冒烟：断言放宽松档（×2），其余做趋势记录；`os_signpost` 可观测。

### 6.6 冒烟

- 打开→改字→导出 100 次无崩溃（PRD §6.6），在 UI 目标跑 XCTest UI 自动化。

---

## 7. 风险与回退（端到端依赖清单)

| 依赖 | 失效场景 | 回退方案 | 前置依赖 |
|------|---------|---------|---------|
| Vision OCR | 低清/艺术字/生僻字体识别率骤降 | 置信度标注 + 手动框选/添加/手动 re-OCR（.fast 区域级） | macOS 12+（实际按 14+ 编译） |
| 系统字体库（含苹方/SF） | 目标为 Windows/webfont/品牌字体 | `allowFallbackToApproximate` = 视觉参数兜底 + 黄条披露 + 手动选字体（离线，**不联网下载字体**） | 字体安装/移除事件监听增量刷新目录 |
| CoreText 渲染与源渲染器（Chromium Skia hinting）差异 | 同字体重排（hinting 差异致二值掩码漂移） | ① 渲染超采样 2–3× 后降采样归一（缓冲 hinting 差异）；② 切换"距离场 Chamfer"指标（掩码膨胀 1–2px 容忍亚像素漂移）；③ 终极：近似匹配+手动 | 匹配基准语料（U1） |
| mac14+ 逐字框 | 低版本/API 不可用 | `perCharBoxes = nil` 聚合路径（§2.6 备路），功能不阻断 | 部署目标 macOS 14+（文档明示） |
| 自研 inpaint（Tier1/2） | 纹理复杂致残影超标（区域 SSIM < 0.90 或命中率 > 15%） | 启 `OpenCVInpainter`（Telea/NS），契约 `TextErasing` 不变，零侵入切换 | 验收语料含纹理样本（U6 扩展组） |
| OCR 文本错误（纠正错/乱码） | 匹配渲染错字致比对崩 | 基于 detectedText 的匹配结果仅作建议；用户编辑后按**当前文本**重匹配（编辑即校正） | — |
| 性能预算（≤300ms） | 字体多/图大超预算 | LRU 掩码缓存 + family 粗筛 top-k 调参（12→6）+ 早停；基准测试把关（§6.5） | 参考机基准套件 |
| HEIC 解码 | 个别异常文件 | CGImageSource 失败 → 明确错误提示（不进 pipeline 假数据） | — |
| 导出（权限/磁盘） | 无写权限/磁盘满 | overlay_exportFailure + 重试；先写临时文件后原子 rename | — |

---

## 8. [第一性原理分析]（汇总）

**从业务本质推导：**
1. "无痕"的数学定义 = 背景连续 + 同块文字样式连续。背景连续 → inpaint 用调和方程（Δu=0）——因为截图背景主导是平坦/线性渐变，恰是拉普拉斯方程的解析解空间；不背 300MB OpenCV 也能拿 80% 正确解，数据说了算再升级。
2. "字体一致" = 字形轮廓一致，渲染器噪声（AA/次像素/hinting）不是字体身份 → 二值掩码 Dice 而非 SSIM；Dice 的几何语义（笔画重合率）直接对应"像不像"，阈值可解释。
3. 匹配必须先于估字号且与字号无关 → 掩码规范行高归一化，匹配 scale-invariant；字号用已匹配字体的真实 metrics 渲染探针闭环（一步收敛），而非猜常数。
4. 字间距必须从匹配中剥离再单独估计 → 逐字对齐比对天然免疫 tracking（免疫=不误判字体），随后用逐字框恢复 tracking；两个耦合变量解耦为两个独立阶段。
5. 重绘无痕的最后闭环是"同一混合方程"：像素 = bg 模型 + α·(fg − bg)——与原图 AA 边缘同构，而非硬贴 RGBA。宽度适配用"字号线性缩放"（k = W_orig/W'）数学上精确，并拒绝位图二次缩放。
6. 撤销/重做用"命令 + 物化效果"：所有变更是单块可枚举操作，命令增量以 KB 计，重算 inpaint 以百 ms 计——物化是 3 个数量级的差异。快照只有自由编辑场景才划算，v1 无此场景。
7. 异步用 Swift Concurrency：取消（generation + Task.cancel）与 UI 隔离（@MainActor）是并发正确性的编译期保障；GCD 靠纪律，Concurrency 靠类型。

**候选否决清单（杜绝"标准做法"）：** SSIM（匹配用）❌ / TextKit（渲染）❌ / 快照 undo ❌ / OpenCV 首发 ❌ / 深模型字体识别 ❌ / Tesseract ❌ / GCD 主力 ❌ / 位图缩放适配 ❌ / 纯几何常数估字号 ❌。每个否决在 §2 有根本原因（不是"业界不这么用"，是该路径与截图场景的数学/成本不匹配）。

---

## 9. [对抗审查记录]

### 9.1 三个边界场景自问

**① 如果 OCR 把一句话拆成多个块，且 bbox 高度不一（含上/下标）？**
- 后果：样式按块独立分析，上下标块的字号/基线估计错；合并操作把异高块并成一行，重绘破排版。
- 对策：合并启发式（同行 + 垂直重叠 > 60% + 高度差 < 60% 才建议合并，UI 提示而非自动）；**上/下标不纳入 v1 精确还原**（披露项），靠手动微调字号/基线步进兜底；`CharBox` 级基线差异（同一行内不同 char 框底部不一）由"基线取主簇"处理（排除离群 char 框）。
- 遗留风险：合并规则本身可能误并（两个相邻独立标签）——人工确认弹窗在前。

**② 如果截图是深色模式（白字深底）或浅色模式混排？**
- 后果：假定"字是深色"的颜色估计器会在白字上取到背景色。
- 对策：ColorEstimator 全程用"距背景模型的距离"分类（§2.4），不预设亮度极性；深/浅两套语料进 U4。回归保护：U4 覆盖深色 50%。

**③ 如果用户替换文本含 emoji/生僻字，匹配字体缺字？**
- 后果：tofu 方块 / 渲染炸。
- 对策：编辑提交时对**当前文本**做覆盖检查（`fit.reportMissingGlyphs()`）→ 缺则提示"XX 字体缺字，请换字体"并禁用确认；系统 fallback 链不上崩溃面。

### 9.2 最可能被推翻的假设（三级降级）

> **"截图文本与 CoreText 渲染，经二值化+规范缩放后，字形掩码 Dice 仍是字体的判别特征。"**

- **为什么可能错**：Chromium（浏览器截图大头）在部分缩放级别/非 Retina 下做 hinting，字形**重排**超过 2px 容差；低分辨率文字（<12px）二值化后信息量不足，Dice 关系崩塌；Subpixel RGB 边缘在深底上可能产生 1px 彩色环并在二值化后留下"重影笔画"。
- **降级链**：① 渲染超采样（2–3× 渲染后降采样）缓冲 hinting 漂移 + 距离场指标（掩码膨胀 1–2px 的 Chamfer 距离，容忍亚像素，见 §7 第 3 行）；② 若 U1 基准正确率 < 90% 且调参不可修复 → 匹配指标切"距离场 Dice"（同 §7）；③ 终极降级 = 视觉参数近似 + 手动选择（已内置于链上），产品承诺降为"近似可修正"，不阻塞交付主链路。
- **验证门槛**：U1 基准（CoreText 渲染图）与真实语料差异允许 ≤ 5 个百分点的确认（§6.4 人工判定的量化旁证）；超出即触发降级链第 ② 步。

### 9.3 决策-前置依赖-失效回退索引

| 决策 | 前置依赖 | 失效回退 |
|------|---------|---------|
| Vision OCR 固定 zh-Hans+en-US | 截图语言分布假设 | 手动框选 + 逐块 re-OCR；v1.1 加语言设置 |
| 匹配阈值 Dice≥0.86/k_min=0.5/τ 等 | 初值需校准 | 校准任务绑定 U1 基准（≥90% 门禁），阈值入配置表可调 |
| 自研 inpaint 首发 | 背景以平坦/渐变为主的假设 | 数据超线 → OpenCV 切换（契约不变） |
| Command+物化 undo | 变更可枚举假设 | 若 v1.1 引入自由画笔 → 该区域改快照叠加（混合模型） |
| macOS 14+ 部署目标 | 逐字框 API | 部署目标降级 → 聚合路径，无阻塞 |
| 单机无网络 | 全离线 | 字体缺失永不联网下载（PRD NFR-2 硬约束），近似+手动 |

---

## 10. 待 zongguan 裁决项（PRD 模糊/缺口，架构师不得自行猜测）

| # | 事项 | 模糊点 | 架构当前假设（供裁决参考） |
|---|------|--------|---------------------------|
| A | 字号显示单位 | PRD 只说"字号"，未定 pt/px/与 Retina 比例关系 | 内部一律 px（渲染即像素，无换算误差）；UI 显示 px 并附 2x 折算 pt 参考 |
| B | 最小字号下限数值 | PRD"自动缩放至最小字号仍超限"未定义"最小字号" | 相对下限 k_min=0.5×原字号（保排版感知）；备选绝对下限 8px |
| C | 撤销/重做范围 | PRD FR-6"修改结果可撤销"是否含几何操作（移动/缩放/增删块） | 架构默认含全部文档变更（内容+几何+增删），仅"预览确认"入栈 |
| D | 近似匹配的展示口径 | "近似匹配：XX 字体"是否连同字重展示（如"苹方 中黑 近似"） | 默认展示 字体+字重，供手动下拉精修 |

---

## 11. 附录：关键参数初值表（统一校准入口）

| 参数 | 初值 | 用途 | 调参门槛 |
|------|------|------|---------|
| 匹配阈值 | Dice ≥ 0.86 exact；0.70–0.86 approx；<0.70 unmatched | FontMatcher | U1 ≥90% 门禁 |
| 歧义判定 | 1st/2nd 差 < 0.03 | FontMatcher.ambiguous | 人工判定语料 |
| 粗筛保留 | top-12 family | 阶段1 | 性能 + 正确率 |
| 规范行高 | 32px / 64px（两级） | 掩码归一 | 同一 |
| 字距下限 | 1px 空洞（跟踪下限可负） | SpacingEstimator | U5 |
| k_min | 0.5 | FitCalculator | 极端长度用例 |
| 碰撞阈值 | 重叠 > 2px | CollisionDetector | 合成用例 |
| 低置信度 | confidence < 0.5 | 弱化标记 | 真实语料 |
| 低对比度 | 相对亮度差 < 0.08 | 误检标记 | U4 + 人工 |
| LRU 缓存 | 4000 条目 | 性能 | 基准机 |
| undo 栈 | 50 步 / 256MB 上限 | 内存护栏 | 冒烟 |

---

*本文档为 v1.0 架构基线。任何决策变更（尤其阈值、部署目标、inpaint 演进）需 zongguan 记录到决策日志。下游开工前置：zhenhai 以 §4 契约为准，xiaoyou 以 §3/§5 状态与反馈契约为准，shouye 以 §6 为测试基准。*