# 决策日志 2026-08-31

| 编号 | 决策 | 级别 | 依据 | 状态 |
|------|------|------|------|------|
| D-035 | CEO 报告三个渲染 bug（黑字/镜像/字号）→ L2 派发 zhenhai 修复 | L2 | CEO 目测 test.png + 独立脚本试验定位根因 | 已派发，待修复 |

## D-035 详情

**背景**：CEO 在 alpha.3 上对 Hermes 图版本号修改为 v1.21.1 后目测发现：
1. 原白色字体渲染为黑色
2. 字体方向反了（镜像）
3. 字体大小与原图不匹配

参照图：`/Users/evandy/Desktop/backup/test.png`（3008×1280，Hermes 广告图）。

**根因定位（独立脚本 + Vision OCR + 像素级分析，非 QA 自洽验收）**：

### Bug 1：白→黑（根因确凿）
- `TextRenderer.render` 构造 CTLine 时 attrs **仅含字体（+可选 tracking），缺 `kCTForegroundColorAttributeName`**
- `CTLineDraw` 使用 **attributed string 属性**渲染，无视 `ctx.setFillColor(fg)` → 永远用默认黑色
- 证据：实验脚本设颜色属性→白字 OCR 可读；不设→全黑 OCR 空
- 影响：无论 ColorEstimator 分析出什么前景色，渲染恒为黑字

### Bug 2：镜像（根因确凿）
- **坐标假设错误**：`CGContext(data:)` 创建的 CGBitmapContext 默认坐标系是 Quartz 样式（原点左下、y 向上），与 CoreText 一致，**无需翻转**
- 但 TextRenderer:92-94 套用了 UIKit 视图绘制的惯例 `translate(0,ph) + scale(1,-1)` → 坐标系翻转为左上原点 → 字形**上下颠倒**
- 证据：独立脚本 5 变种实验——
  - `notransform`（不翻转，textPosition=pad）→ OCR 精确读出 `v1.21.1` ✅
  - 现序列 `tr_padAscent` → OCR 读出 `1.13.1V`（颠倒）❌
  - 苹果官方序列（含 textMatrix.identity）→ `r.rS.lv` ❌
- **历史 QA 盲区解释**：V0.4 像素对比验证拿"渲染器输出 vs 同一渲染器输出"比对，同源必自洽 → 垂直颠倒从未暴露。本次 CEO 目测 + 独立 OCR 才首次发现
- 参考：TextRenderer 内注释「旧实现 baselineY=pad+descent 使字形 ascent 顶部超出补丁盒被裁剪（P2-3）」——历史版本已受同类坐标问题困扰，本次为根因清除

### Bug 3：字号不匹配（根因疑似，修复时验证）
- `SizeEstimator.estimate`: `fontSize0 = bbox.height / 1.15`（激进猜测）+ 单向收敛 `fontSize0 × (bbox.height / probe.lineHeight)`
- 问题：Hermes 广告版本号字体细窄，detector bbox 高度（70px）与字形实际字号偏差大 → 渲染字号虚大
- 修复需联动 FitCalculator（宽度适配）与基线布局，避免"字号对了但宽高比错"

**修复方向（spike 已验证技术可行性）**：
1. attrs 增加 `kCTForegroundColorAttributeName = style.color`
2. 移除 textMatrix/translate/scale 翻转序列，textPosition 直接用 pad 起；或改用显式 `ctx.textMatrix` 正确定义
3. SizeEstimator 用行高/字面宽双约束 + FitCalculator 迭代收敛；渲染后字号与 bbox 高度做一致性校验（新测试）

**验收方式（防 QA 自洽盲区复发）**：
- 新增视觉语义测试：渲染文本 → Vision OCR → 断言可读回原文案（方向验证）
- 新增颜色测试：渲染前景色 → 采样 patch 像素 → 断言接近 style.color
- 新增字号测试：渲染 ink 高度 → 断言与 bbox 高度比例合理
- QA 阶段：导出渲染结果 PNG，人工目测 + OCR 复核

**流程**：L2（渲染器核心 bug 修复，代码级改动）→ 派 zhenhai（TDD 先行）→ shouye QA（含 OCR 语义测试）→ dana 审查 → 打包 alpha.4 → 汇报 CEO

| 编号 | 决策 | 级别 | 依据 | 状态 |
|------|------|------|------|------|
| D-036 | CEO 确认从原始未损坏源图重开 → QA 缺口（test.png 已固化黑像素）不构成阻塞，c1 解除，打包 alpha.4 交付 | L2 | CEO 明确答复 + dana Approve(conditional) 前置条件满足 | 已完成 |
| D-037 | CEO 明确核心需求 =「P图换字」改字仅内容变化，字体颜色/大小/风格继承原图；宽度策略选 B：正常场景字号 100% 继承不缩放，仅新文字超宽时等比缩小兜底 | L2 | CEO 三连报 + 亲自澄清需求 + 选 B | 已完成（alpha.5 交付） |
| D-038 | 多块编辑只有一处生效 → 根因=切块时 select 静默丢弃前一块预览（EditorState.select 不物化、EditorDocument.select 覆盖 phase、pendingEdit 单槽）。修复：切块/完成输入时自动物化前一块（auto-confirm）；前一块被阻塞/预览未完成时**拒绝切块并提示**（方案 A） | L2 | CEO 报 bug + 代码证据链 + CEO 选 A | 已记录，待派发 |

## D-037 详情

**背景**：CEO 验收 alpha.4 后重申核心诉求，明确优先级最高的产品约束：

> "我的要求是，改了文字之后，不管是新增还是删除文字，最后的结果都是保持原文字的字体颜色和大小不变，只是改文字。比如 v0.20.0 我改成 v1.21.1，只是数字变，其他所有原图片风格都不变。"

**需求本质拆解（第一性原理）**：
- 产品 = **P 图换字**：一个文字块变内容，其余一切（字符颜色、字号、字体字形、字间距、位置、背景抹除补全）100% 继承原图，观感应等同"原图天生就是这个文字"。
- 现有管线本质是"分析→重绘"，有 3 个环节主动偏离继承：
  1. FitCalculator 按原 ink 宽**主动缩放字号**（k0 = target/natural，minScale=0.5）→ 新文字宽窄不同字号就被改
  2. SizeEstimator 用 bbox.height/1.15 **猜字号** → 装饰字体天生带误差（v05 已加 ink 宽双约束改进，但变长文本仍走缩放）
  3. Hermes 等广告装饰字体本机未装 → 系统字体顶替 → 字形风格差异（环境限制，非 bug）

**CEO 选择 B（宽度策略）**：正常场景（新文字宽 ≤ 原文字宽）字号 100% 继承不变；仅新文字超宽时等比缩小兜底（minScale 0.5 限制内）。不选 A（永不缩放、盖住相邻内容不处理）。

**执行范围**：
- zhenhai：审计/改造 → 选 B 语义：变短文本字号保持 f0（k=1），变长才缩放（k<1），永不放大（现 FitCalculator 已具"只缩不放"，重点补语义测试与回归）
- 补齐选项 B 三条语义测试：①新文字更宽→k<1 ②更窄/等宽→k=1 字号不变 ③永不放大（新文字更窄不放大字号）
- shouye QA：真实场景 E2E（v0.20.0→v1.21.1 同宽段 + 新增/删减文本变长变短两态）
- dana 审查 → alpha.5 打包 → 汇报

**流程**：L2（渲染语义核心改动）→ zhenhai（TDD 先行）→ shouye QA → dana 审查 → alpha.5 → 汇报 CEO