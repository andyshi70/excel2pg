# 进度报告 2026-08-31

## 本轮完成：三个渲染 bug 修复 + alpha.4 交付

### CEO 上报问题（目测 alpha.3）
对 Hermes 广告图版本号修改为 v1.21.1 后发现：
1. 原白色字体渲染为黑色
2. 字体方向反了（镜像）
3. 字体大小与原图不匹配

### 根因（独立脚本验证，非猜测）
| Bug | 根因 | 证据 |
|---|---|---|
| 白→黑 | TextRenderer attrs 缺 kCTForegroundColorAttributeName，CTLineDraw 无视 setFillColor 永远画黑 | 设颜色属性→白字可 OCR；不设→全黑 |
| 镜像 | CGBitmapContext 默认坐标系（左下原点 y 上）与 CoreText 一致，原代码误用 UIKit 翻转序列 → 字形上下颠倒 | 5 变种 OCR 实验：不翻转精确读回 v1.21.1 |
| 字号 | SizeEstimator 单一行高锚（bbox.height/1.15），细窄字体虚大 | bbox 高 70px vs 真实字号偏小 |

### 历史 QA 盲区说明
旧验证是"渲染结果 vs 模板"像素对比——模板与结果同源，颠倒也自洽。本次用 Vision OCR + CEO 目测首次暴露。

### 执行链
- zhenhai：三修复 + 5 条语义测试（OCR 读回原文防盲区复发），57 tests 全绿（52 存量零回归）
- shouye：独立验证渲染修复成立（颜色/方向/字号/CJK/合成位置），发现 1 个缺口：test.png 已固化黑渲染像素，分析层读损坏图无法自愈
- dana：Approve(conditional)，条件 c1 = CEO 确认重做数据源
- **CEO 确认：从原图重新打开 → 缺口不构成阻塞，c1 解除**

### 打包 alpha.4（含自查纠错）
- 构建 v05 release → 覆盖 Pxiu.app → ad-hoc 签名 → 打 dmg
- 自查发现：首次打包时 cp 源路径写错，dmg 可能装旧二进制 → **已重打替换**
- 最终验证：hdiutil verify VALID；__text 纯代码段与 v05 产物逐字节一致（off 6608）；签名有效；GUI 冒烟存活(10s)

### 交付物
- `dist/Pxiu-1.0.0-alpha.4.dmg`
  - SHA256: `4c07a33f7b5e9b50321212961c508afa748a3f953cd396c3a041f54497268950`
  - 大小: 503,365 B
- 文档：api_implementation_v05 / qa_report_v05 / code_review_v05 / decisions 2026-08-31

### 遗留（非阻塞，已在 backlog）
1. R1/R2 编辑器状态清理（deselect/setLoading，v0.4.1）
2. rgbaDraw 慢路径/EXIF>1/HEIC 行序补测
3. Hermes 字体实装后回归 OCR/字号锚（dana c2）
4. 无 perCharBoxes + 松 bbox 的 SizeEstimator 路径测试（dana c3）
5. 若 CEO 需在已损坏图上复用 → 补"重分析/恢复原始色"独立能力（D-035 记）

### 决策日志
- D-035: 三渲染 bug 根因 + 修复派发（2026-08-31）
- D-036: CEO 确认从原图重开 → c1 解除，交付 alpha.4