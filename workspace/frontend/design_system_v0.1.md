# 设计系统 — 截图文字无痕修改工具（pxiu）

- 版本：v0.1
- 日期：2026-08-28
- 撰写：xiaoyou（前端工程师）
- 来源：`Sources/PxiuApp/Style.swift`（单一真源）
- 主题：克制的创作型工具美学；无 AI 渐变；自适应浅色/深色（系统语义色）；对比度优先；简体中文界面

设计原则：
- **不引入自定义色板**，全面采用系统语义色（AppKit `NSColor` / SwiftUI `Color`），以获得免费的浅/深色适配与无障碍高对比。
- **明度分层**：背景(window/canvas) < 面板(control) < 前景(text)。
- **克制动效**：仅选中/面板用轻弹簧；内容操作无炫技动画。
- **Token 双命名空间**：`DS.Color`（SwiftUI `Color`，用于 View）与 `DS.NSColor`（AppKit 原始，用于需要 NSColor 的底层），避免 NSColor↔Color 反复包转。

---

## 1. 色板（DS.Color / DS.NSColor）

| Token | SwiftUI | AppKit 语义 | 用途 |
|---|---|---|---|
| `Color.accent` | accentColor | — | 主按钮/选中强调 |
| `Color.panelBackground` | controlBackgroundColor | — | 检查器/面板背景 |
| `Color.canvasBackground` | windowBackgroundColor | — | 画布外露背景 |
| `Color.blockStroke` / `NSColor.blockStroke` | systemBlue | systemBlue | 文字块虚线框 |
| `Color.lowConfidenceStroke` | systemOrange | systemOrange | 低置信度(<0.5)块弱化标记 |
| `Color.selectedStroke` | systemBlue | systemBlue | 选中块高亮边框 |
| `Color.collisionStroke` | systemRed | systemRed | 碰撞红色实线高亮（重叠>2px） |
| `Color.selectionHandleFill` | controlAccentColor | controlAccentColor | 角柄填充 |
| `Color.warningBar` | systemYellow | systemYellow | 近似匹配提示条（非错误） |
| `Color.danger` | systemRed | systemRed | 错误提示条 |
| `Color.success` | systemGreen | systemGreen | 导出成功提示条 |

### 语义分级
- 中性信息 → `panelBackground`/`.tertiary`
- 弱警告（近似匹配/残影/复杂效果） → `warningBar`（黄色）
- 硬阻断（碰撞/超界/无法匹配） → `danger`/`collisionStroke`（红色）

---

## 2. 字体与字号（DS.Typeface）

| Token | 值 | 用途 |
|---|---|---|
| `Typeface.caption` | 11 | 次要说明/识别原文 |
| `Typeface.body` | 13 | 正文/输入框 |
| `Typeface.subhead` | 15 | 编辑区小节标题 |
| `Typeface.title` | 17 | 面板大标题 |

- 中文界面文案；数值/标题可用 `.medium`/`.semibold` 加权（局部）。
- 检查器"字体"下拉填充**全部系统字体**（`SystemFonts.swift`，NodeJS 无关，纯 CoreText）。

---

## 3. 间距（DS.Spacing）

| Token | 值 |
|---|---|
| `xs` | 4 |
| `s` | 8 |
| `m` | 12 |
| `l` | 16 |
| `xl` | 24 |

节奏：元素间 `s`/`m`；分区之间 `l`；检查器内 `m` 为基准留白。

---

## 4. 圆角（DS.Radius）

| Token | 值 | 用途 |
|---|---|---|
| `control` | 6 | 输入框/下拉 |
| `pill` | 999 | 主按钮（胶囊） |
| `panel` | 8 | 面板/卡片 |

---

## 5. 动效（DS.spring / DS.ease）

| Token | 定义 | 用途 |
|---|---|---|
| `spring` | response 0.25 / damping 0.8 | 选中/面板过渡 |
| `ease` | easeOut 0.18 | 短促元素过渡 |

原则：动效服务于状态反馈，不喧宾夺主；内容重绘无动画。

---

## 6. 交互常量（DS.Gesture）

| 常量 | 值 | 用途 |
|---|---|---|
| 拖拽移动最小位移 | 10 | 区分点击与拖拽 |
| 添加框选最小位移 | 2 | 框选灵敏度 |
| 角柄命中阈值 | 视 DS.Gesture 实现 | 缩放 |
| 碰撞阈值 | 2px（Core `CollisionDetector`) | 与 Core 一致 |

---

## 7. 无障碍与主题

- 全部颜色为系统语义 → 浅/深色自动适配，满足 WCAG 对比（系统色内置）。
- 碰撞/错误用红色 + 文案双重传达（非仅色相）。
- 低置信度块用橙色弱化，提供视觉区分但不隐藏信息。

*（xiaoyou 产出；与 `ui_audit_v0.1_2026-08-28.md` 配套）*
