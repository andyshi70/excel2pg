# 项目进展汇报 — pxiu（2026-08-30）

## v0.4 交付：改字像素化接线 ✅（CEO 验收项收口）

| 阶段 | 产出 | 结论 |
|------|------|------|
| Core 补口 | analyzeStyles + CI 根因（zhenhai） | 49/49 → 52/52 测试 |
| UI 接线 | EditorState 改 Core 权威 + patch 叠加（xiaoyou） | build 通过 |
| QA | qa_report_v04 + 镜像仲裁复核（shouye） | **A2/A3/B 更正 PASS** |
| 审查 | code_review_v04（dana） | **Approve** |
| 打包 | Pxiu-1.0.0-alpha.3.dmg（shouye/SRE） | 冒烟通过 |

## CEO 验收项：ch.jpg v0.20.1 → v1.21.1

- **结果：通过**。改字物化真实（版本区 (592,717) 像素被替换，patch 逐像素一致）；undo/redo 像素级回退；导出图含新字
- 过程乌龙如实记录：上轮 QA 报"镜像缺陷"，仲裁复测证明是验证脚本方向解读错误（同机 debug/release 双模式均正确，上轮自己的导出文件与当前逐像素全等）——**镜像从未发生**

## 交付物

- `/Users/evandy/opencode/pxiu/dist/Pxiu-1.0.0-alpha.3.dmg`（799,224B，SHA-256 `d987b8f8…dfbdfd`，arm64 / macOS≥14.0，ad-hoc）
- 自 alpha.1 累积：静态首页（shy.jpg）+ 画布 100% 缩放（滚轮/捏合/工具栏/适应窗口）+ 改字像素物化 + 撤销像素回退

## 文档链（本次闭环）

- 决策：decisions_2026-08-30.md（D-029 ~ D-034）
- QA：qa_report_zoom_ch / qa_report_v04 / qa_report_mirror_arbitration
- 审查：code_review_zoom_ch / code_review_v04
- 前端审计：ui_audit_v0.4；后端实现：api_implementation_v0.3

## 遗留（v0.4.1 排期，非阻塞）

1. R1/R2 清洁项：undo 删块 phase 残留、重复打开 loading 语义（zhenhai 补 deselect/setLoading）
2. 测试缺口：rgbaDraw 慢路径方向 / EXIF orientation>1 / HEIC 行序补测
3. UI 图形正确性人工目测（本环境无显示会话，仅代码级+冒烟）
4. 优雅退出挂起为环境特性（alpha.2 对照同款）；未公证、未覆盖 Intel/旧系统