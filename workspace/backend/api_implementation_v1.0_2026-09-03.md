# pxiu 实现说明 v1.0 — 后端 FastAPI 脚手架

- 版本：v1.0
- 产出者：zhenhai（后端工程师）
- 日期：2026-09-03
- 前置文档：`workspace/architecture/api_contract_v1.yaml`（API 契约）
- 范围：Python FastAPI 后端脚手架，搭建路由骨架 + 占位服务 + Pydantic 模型
- 路径：`pxiu-app/server/`
- 最终结果：**pytest tests/：6 passed, 0 failed**；`from main import app` 加载 OK

> 说明：本交付为**新代码库脚手架**（Python FastAPI 服务），与既有 Swift 渲染引擎（v07 及之前）不同项目体。仅搭建骨架，OCR/样式分析/修复/渲染均以占位实现占位，后续按契约填充。

---

## Part A — 目的与结构

### A.1 业务本质
为「本地图片文字智能编辑器」提供本地 HTTP 服务。前端（Tauri/React）需调用后端能力：OCR 识别、样式分析、背景修复、文字渲染、导出。脚手架先行，打通路由与请求/响应链路，能力逐项填充。

### A.2 项目结构
```
server/
├── main.py                 # FastAPI 入口，CORS，路由挂载，/health
├── routers/
│   ├── __init__.py
│   ├── ocr.py              # POST /api/ocr
│   ├── analyze.py          # POST /api/analyze-style
│   ├── inpaint.py          # POST /api/inpaint
│   ├── render.py           # POST /api/render-text
│   └── export.py           # POST /api/export
├── services/
│   ├── __init__.py
│   ├── ocr_service.py      # recognize_text（占位）
│   ├── style_analyzer.py   # analyze_style（占位）
│   ├── inpaint_service.py  # inpaint_image（占位）
│   └── render_service.py   # render_text_on_image / export_image（占位）
├── models/
│   ├── __init__.py
│   └── schemas.py          # Pydantic 模型
├── requirements.txt
└── tests/
    ├── __init__.py
    └── test_api.py         # 6 项基础 API 测试
```

## Part B — 接口实现对照（对应 api_contract_v1.yaml）

| 契约路径 | 方法 | 路由文件 → 服务占位 | 说明 |
|---|---|---|---|
| `/api/ocr` | POST | `routers/ocr.py` → `ocr_service.recognize_text` | multipart 上传 file，占位返回空 items |
| `/api/analyze-style` | POST | `routers/analyze.py` → `style_analyzer.analyze_style` | multipart(file+bbox JSON)，占位返回默认样式 |
| `/api/inpaint` | POST | `routers/inpaint.py` → `inpaint_service.inpaint_image` | multipart(file+bboxes JSON)，占位回显原图 base64 |
| `/api/render-text` | POST | `routers/render.py` → `render_service.render_text_on_image` | JSON 请求，占位回显 image_base64 |
| `/api/export` | POST | `routers/export.py` → `render_service.export_image` | JSON 请求，占位解码返回二进制 |
| `/health` | GET | `main.py` | 健康检查 `{status: ok}` |

### B.1 Pydantic 模型（models/schemas.py）
- OCR：`OCRItem, OCRResponse`
- 样式：`RGB, FontCandidate, StyleAnalysisResponse`
- 修复：`InpaintResponse`
- 渲染：`TextStyle, RenderTextRequest, RenderTextResponse`
- 导出：`ExportFormat(enum), ExportRequest, ExportResponse`
- 通用：`ErrorResponse`

> 注：契约 BoundingBox 为 `[x1,y1,x2,y2]` 四元数组；脚手架 schema 占位保留四角点语义，填充真实逻辑时需与契约对其。

## Part C — 占位服务说明

全部服务层函数返回 mock 数据，标注 `# TODO:` 待真实实现：
- `ocr_service.recognize_text`：返回 `success/items/width/height`
- `style_analyzer.analyze_style`：返回默认样式（黑、24px、regular、left）
- `inpaint_service.inpaint_image`：读取上传字节原样 base64 回显（OpenCV 待接入）
- `render_service.render_text_on_image`：回显入参 image_base64（Pillow 待接入）
- `render_service.export_image`：base64 解码返回二进制（导出格式待接入）

## Part D — 验证

```
python -c "from main import app; print('FastAPI app loads OK')"   # OK
pytest tests/    # 6 passed, 0 failed
```

## Part E — 待办（占位替换）
- [ ] PaddleOCR 集成（`ocr_service`）— 注意 paddle 2.6.1 在本机 Python3.9/arm64 无 wheel，需评估 python 版本或降级方案
- [ ] 样式分析核心（`style_analyzer`）
- [ ] OpenCV inpaint（`inpaint_service`）
- [ ] Pillow 渲染（`render_service`）
- [ ] 错误处理按 `error_codes_v1.0.yaml` 接入

## Part F — 启动命令
```
cd /Users/evandy/opencode/pxiu/pxiu-app/server && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765 --reload
```
