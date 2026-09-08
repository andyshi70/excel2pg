# UI 审计报告 v0.6 · 2026-09-03

## 范围

图片导入功能（拖拽 / 粘贴 / 选择文件）+ 画布缩放平移。审计对象：`App.tsx`、`EditorCanvas.tsx`、`useImageEditor.ts`、`ToolBar.tsx`、`styles/editor.css`。

## 关联文档

- `workspace/product/page_states_pxiu_2026-08-28.md` —— 状态矩阵（本任务改动不新增状态节点，仅复用 `home_empty` / `home_loading` / `editor_*`）
- `workspace/architecture/api_contract_v1.yaml` —— 图片支持格式约束（PNG / JPEG / WebP）

## 改动清单

| 文件 | 改动 |
|------|------|
| `src/hooks/useImageEditor.ts` | `openImage` 重构为 `loadFile(file)`：格式白名单校验（`image/png` / `image/jpeg` / `image/webp`），加载新图前 revoke 旧 objectURL 防泄漏 |
| `src/App.tsx` | 新增全局 `paste` 监听（window）；拖放/文件选择改走 `loadFile` 并捕获格式错误 |
| `src/components/Canvas/EditorCanvas.tsx` | 画布缩放（滚轮 0.2–5x）+ 平移（按住空格+拖拽）；新增缩放/平移提示条；文本块随视口一同变换，坐标天然对齐 |
| `src/components/Toolbar/ToolBar.tsx` | 空状态新增「导入图片」主按钮 + 格式提示 `PNG · JPEG · WebP` |
| `src/styles/editor.css` | 新增 `.canvas-viewport`、`.canvas-zoom-hint`、`.toolbar-format-hint`；画布改 `overflow:hidden` 适配视口变换 |

## 交互态语义审计

### 1. 状态机兼容性

导入成功后仍走原 `page_state` 流转：`home_loading → editor_loading → editor_idle / editor_notext`。未新增或改写任何 `EditorPageState` 节点，与 page_states 矩阵一致，无破坏。

### 2. 文件类型校验（核心安全点）

`loadFile` 前置校验，非法格式直接 throw，不进入「异步 OCR 失败 → 清空回 home_empty」的误判路径。错误经 catch 打日志，UI 不发假成功提示。与 api_contract 的 `INVALID_IMAGE_FORMAT` 语义对齐（前端先拦，后端仍有兜底）。

### 3. 画布坐标系（缩放对齐正确性）

文本块是 `.canvas-viewport` 的子元素，随视口 `translate + scale` 一并变换，故 OCR bbox（像素坐标，相对图片原点）在任意缩放/平移下与图片保持一比一贴合。**关键正确性点**：缩放必须作用在包裹图片与块的同一容器上，否则块坐标会与图的缩放脱节。

### 4. 点击命中层级

`.canvas-click-area`（z-index 0）置于 viewport 之前 → viewport（后续兄弟，默认层）压在其上：点击图片/块命中 viewport，点击空白区命中 click-area 触发取消选中。行为与原实现一致。

## 对抗审查 —— 自问边界场景

1. **「预览确认是否受 pan 干扰？」** —— 手指按住空格时 pointerdown 会 `preventDefault` 并进入平移，不触发 click-area 取消选中；松开后正常。无冲突。
2. **「粘贴事件是否与编辑器内文字粘贴冲突？」** —— 本编辑器当前无文本输入框，`paste` 仅响应图片 item；若未来加入检查器输入框，需改为对输入框做局部处理，避免全局拦截剪贴板文本。**预留标记**。
3. **「连续拖入多张 / 拖入非法文件？」** —— `files[0]` 只取首张；非法格式交由 loadFile 校验拒绝。可接受。

## 最可能被挑战的假设

「缩放默认基点为视口中心（top:50%/left:50% + transform-origin center）」——滚轮缩放时画面以中心而非鼠标位置缩放，属于基础实现。若验收要求「以鼠标指针为缩放锚点」，需在 scale 变更时按鼠标相对视口偏移补偿 offset。本期未实现，标记为已知降级项。

## 验证

- `npm run build`（tsc + vite build）通过，TypeScript 编译无误。
- 项目当前无 `npm test` 脚本及测试基建（package.json 仅 dev/build/preview/tauri）；以 `tsc` 类型检查作为编译期验证。

## 待办 / 标记

- [x] 术语统一：ToolBar 空状态原「导入图片」+「打开文件」双按钮功能重叠，按 taste-skill「NO DUPLICATE CTA INTENT」已收敛为单一「导入图片」主 CTA。
- [ ] 缩放锚点升级（鼠标指针居中）列为后续体验增强。
- [ ] 进程内若引入检查器/编辑输入框，需收敛 paste 监听范围。
