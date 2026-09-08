# pxiu 后端：POST /api/ocr 文字识别实现

- 版本：v1.2
- 产出者：zhenhai（后端工程师）
- 日期：2026-09-04
- 前置：`workspace/architecture/api_contract_v1.yaml`（OCR 端点为独立无状态图像处理能力，不涉及数据库写入，故无需 `db_schema_*.sql`）

## 目标

实现 `POST /api/ocr`，调用 PaddleOCR 识别图片中的文字，返回每个文本块的内容、坐标（最小外接矩形 bbox）、置信度与旋转角度；在 PaddleOCR 未安装时降级为可明确的错误响应。

## 方案选型

| 方案 | 说明 | 结论 |
|------|------|------|
| A. PaddleOCR 同步推理 | 满足需求；重量级依赖（paddlepaddle ~数百 MB），部分环境安装困难 | **采用**（配 fallback） |
| B. 轻量 OCR（EasyOCR/tesseract） | EasyOCR 仍需 torch，tesseract 依赖系统二进制 | 未选（需求指定 PaddleOCR） |
| C. 纯图像模板匹配 | 无法做通用文字识别 | 未选 |

**决策：方案 A + 强制 fallback。** 安装成功走 PaddleOCR；`ImportError` 时 `PADDLEOCR_AVAILABLE=False`，识别接口返回结构完整的错误响应而非抛 500，便于前端稳定消费。

## 修改文件

| 文件 | 变更 |
|------|------|
| `services/ocr_service.py` | 占位实现 → 完整 PaddleOCR 集成 + fallback |
| `routers/ocr.py` | 无改动（已正确调用 `recognize_text`） |
| `tests/test_ocr_service.py` | 新增单元测试（7 例） |

## 核心逻辑（ocr_service.py）

1. **导入守卫**：`try: from paddleocr import PaddleOCR`，失败置 `PADDLEOCR_AVAILABLE=False`。
2. **懒加载单例**：`get_ocr()` 全局缓存 `_ocr_instance`，避免多次加载模型。
3. **识别转换**：对每条检测结果 line：
   - `box_points = line[0]`（`[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`）
   - `text = line[1][0]`，`confidence = line[1][1]`
   - `bbox`：取四点 `[min(x), min(y), max(x), max(y)]`（最小外接矩形）
   - `angle`：`atan2(p2.y-p1.y, p2.x-p1.x)` 基于上边两点，保留两位小数
4. **返回**：`{success, items[], width, height}`。

### 角度符号约定

图像坐标 y 轴向下，故上边线右端点 y 增大（视觉顺时针）→ 角度为正，与契约 `angle: 正值为顺时针` 一致。

### fallback 响应

当 `PADDLEOCR_AVAILABLE=False`：

```json
{
  "success": false,
  "error": {
    "code": "OCR_ENGINE_UNAVAILABLE",
    "message": "PaddleOCR 未安装，请检查 Python 环境"
  },
  "items": [],
  "width": 0,
  "height": 0
}
```

## 与契约一致性

- `OCRItem`：`text / bbox / confidence / angle` 四字段齐全，类型匹配 `BoundingBox=[x1,y1,x2,y2]`。
- `OCRResponse`：`success / items / width / height` 齐全，`success=true` 时 `items` 为数组。
- 错误结构符合 `ErrorResponse`（`code/message`）。

## 测试

`tests/test_ocr_service.py`：7 例，覆盖

- `calculate_angle`：水平 0°、顺时针正角、逆时针负角、两位小数精度
- `get_bbox_from_points`：最小外接矩形、float 坐标保留
- fallback：PaddleOCR 不可用时返回 `OCR_ENGINE_UNAVAILABLE`

## 验证结果（本机）

```
OCR service loads OK
PADDLEOCR_AVAILABLE = False   # 本环境未装 paddleocr，fallback 生效
POST /api/ocr → 200 {"success": false, "error": {"code": "OCR_ENGINE_UNAVAILABLE", ...}}
pytest: 13 passed (6 旧 API + 7 新增)
```

> 注：本开发环境未安装 paddlepaddle/paddleocr，故集成路径经 fallback 验证；真实推理路径待具备 PaddleOCR 环境后按同类逻辑回归。
