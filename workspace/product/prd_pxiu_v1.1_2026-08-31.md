# PRD: pxiu 视觉继承式文本替换（选 B）

- 项目: pxiu（图片文字编辑）
- 版本: v1.1（D-037，2026-08-31）
- 状态: 已评审（CEO 确认选 B）

## 1. 一句话产品定义

> 用户在图片上改文字时，**只有字符内容变化**，字体颜色/字号/位置/背景补全等一切视觉风格 100% 继承原图，观感等同"原图天生就是这个文字"。

## 2. 需求背景

CEO 连续三次反馈（alpha.3 黑字/镜像/字号、alpha.4 重申）后亲自澄清：
v0.20.0 改成 v1.21.1，只是数字变，其他所有原图片风格都不变。

## 3. 需求条款（Acceptance Criteria）

### AC-1 字号继承（核心）
- 输入: `block(v0.20.0)` + `newText(v1.21.1)` + `style(fontSizePx=f0)`
- 当 `newText` 渲染的自然 ink 宽 ≤ 原 ink 宽 → `fontSizeUsed == f0`（k=1，**不缩放**）
- 当 `newText` 自然宽 > 原 ink 宽 → `fontSizeUsed = f0 × k`，k = 原ink宽/自然宽（**只缩**）
- 永不放大: 新文本更短时字号不变大（继承 f0）

### AC-2 颜色继承（回归保持）
- 渲染前景色 = style.color（kCTForegroundColorAttributeName 生效）
- v05 已修复白→黑，本迭代回归确认

### AC-3 方向（回归保持）
- 不引入新翻转；基线锚定保持 v05 语义

### AC-4 超长兜底
- 新文本超宽到 k < minScale(0.5) → textTooLong（现有行为，保持）

### AC-5 位置
- 基线对齐原文字位置不变（现有 BlockPatchBuilder.layout 保持）

## 4. 技术方案（zhanshen 已勘察，选 B 只需语义测试 + 审计）

现状核查（代码已读）：
- `FitCalculator.fit` 已天然"只缩不放"（k0<1 才缩放）
- 关键缺口: **无测试覆盖选 B 三态** + 确认字号继承路径无副作用

改动范围（zhenhai）：
1. 审计 FitCalculator 由 StyleEstimators 传入的 f0 链路（fontSizePx 来源无误）
2. 新增语义测试（TextRenderingSemanticsTests.swift）：
   - 变宽 → k<1 且 fontSizeUsed < f0
   - 等宽/变窄 → k=1 且 fontSizeUsed == f0
   - 永不放大（极短文本 → 仍 k=1, 字号 = f0）
3. 回归 57 tests

## 5. 不做（YAGNI）
- 不做 A 方案（永不缩放、不处理碰撞）
- 不做字体商店/装饰字体下载（环境限制，如实告知）
- 不做"超宽时字号继承但溢出"（选 B 已否决溢出）

## 6. 验收
- swift test -c release --no-parallel 全绿（57 + 新增）
- QA 独立验证（合成夹具，避开损坏 test.png）
- 同宽段 E2E: v0.20.0→v1.21.1 字号一致

## 7. 交付物
- alpha.5 dmg + 文档链（api_implementation/qa_report/code_review/decisions）

## 8. 风险
- Hermes 字体本机未装 → 顶替字体字形差异（环境限制，非本迭代可解，如实告知 CEO）
- SizeEstimator 字号源头误差仍可能被带入射出（超宽才触发缩放，正常段字号 100% 继承已隔离）