"""匹配内核：归一化 + 配对键谓词生成。字段名全部来自用户勾选，零硬编码。"""
from .db import qi, qstr


def norm(expr: str) -> str:
    """PRD §五：去首尾空格 + 全角括号→半角。两边同施。"""
    return f"replace(replace(btrim({expr}),'（','('),'）',')')"


def pair_pred(pairs, a_alias="a", b_alias="b", normalize=True) -> str:
    """配对键 → 'AND 等值' 谓词。pairs = [(A列, 对照列), ...]，顺序即用户勾选顺序。"""
    if not pairs:
        raise ValueError("至少勾选一对对应字段")
    parts = []
    for a_col, b_col in pairs:
        left, right = f"{a_alias}.{qi(a_col)}", f"{b_alias}.{qi(b_col)}"
        parts.append(f"{norm(left)}={norm(right)}" if normalize else f"{left}={right}")
    return " AND ".join(parts)


def guard_pred(pairs, a_alias="a") -> str:
    """守卫：第一配对列 IS NOT NULL —— 垃圾总计行整行不碰（PRD §五）。"""
    return f"{a_alias}.{qi(pairs[0][0])} IS NOT NULL"


def in_filter(col_expr: str, values) -> str:
    """状态过滤，值精确匹配（复现既往口径：不归一化）。"""
    if not values:
        raise ValueError("状态过滤值不能为空")
    return f"{col_expr} IN ({','.join(qstr(v) for v in values)})"


def count_subquery(spec, a_alias="a") -> str:
    """计算②：数次数（PRD §四）。src = 对照表。"""
    src_alias = "c"
    preds = [pair_pred(spec["pairs"], a_alias, src_alias, spec.get("normalize", True))]
    if spec.get("status_col") and spec.get("status_values"):
        preds.append(in_filter(f"{src_alias}.{qi(spec['status_col'])}", spec["status_values"]))
    inner = f"SELECT count(*) FROM {qi(spec['src_table'])} {src_alias} WHERE " + " AND ".join(preds)
    return f"({inner})"


def exists_subquery(spec, a_alias="a") -> str:
    """计算③：判断在不在（PRD §四）。"""
    src_alias = "b"
    preds = [pair_pred(spec["pairs"], a_alias, src_alias, spec.get("normalize", True))]
    inner = f"SELECT 1 FROM {qi(spec['src_table'])} {src_alias} WHERE " + " AND ".join(preds)
    return f"EXISTS ({inner})"


def vlookup_subquery(spec, a_alias="a") -> str:
    """计算②卡片补一列：取第一行（多行命中由上层出黄条警告）。"""
    src_alias = "v"
    preds = [pair_pred(spec["pairs"], a_alias, src_alias, spec.get("normalize", True))]
    inner = (
        f"SELECT {src_alias}.{qi(spec['fill_col'])} FROM {qi(spec['src_table'])} {src_alias} "
        f"WHERE " + " AND ".join(preds) + " LIMIT 1"
    )
    return f"({inner})"
