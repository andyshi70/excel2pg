"""匹配内核：归一化 + 配对键谓词生成。字段名全部来自用户勾选，零硬编码。"""
from .db import qi, qstr


def norm(expr: str) -> str:
    """PRD §五：去首尾空格 + 全角括号→半角。两边同施。"""
    return f"replace(replace(btrim({expr}),'（','('),'）',')')"


def _strip_digits_sql(expr: str) -> str:
    """剥掉末尾数字（张文宏1 → 张文宏）。"""
    return f"regexp_replace({expr}, '[0-9]+$', '')"


def _is_name_col(*col_names) -> bool:
    """只对导师类字段做数字后缀归一 —— 专业码带数字，绝不能剥（PRD §二坑3）。"""
    return any(k in c for c in col_names for k in ("导师", "教师", "姓名"))


def pair_pred(pairs, a_alias="a", b_alias="b", normalize=True, strip_digits=False) -> str:
    """配对键 → 'AND 等值' 谓词。pairs = [(A列, 对照列), ...]，顺序即用户勾选顺序。"""
    if not pairs:
        raise ValueError("至少勾选一对对应字段")
    parts = []
    for a_col, b_col in pairs:
        left, right = f"{a_alias}.{qi(a_col)}", f"{b_alias}.{qi(b_col)}"
        if normalize:
            left, right = norm(left), norm(right)
        if strip_digits and _is_name_col(a_col, b_col):
            left, right = _strip_digits_sql(left), _strip_digits_sql(right)
        parts.append(f"{left}={right}")
    return " AND ".join(parts)


def guard_pred(pairs, a_alias="a") -> str:
    """守卫：第一配对列 IS NOT NULL —— 垃圾总计行整行不碰（PRD §五）。"""
    return f"{a_alias}.{qi(pairs[0][0])} IS NOT NULL"


def in_filter(col_expr: str, values) -> str:
    """状态过滤，值精确匹配（复现既往口径：不归一化）。"""
    if not values:
        raise ValueError("状态过滤值不能为空")
    return f"{col_expr} IN ({','.join(qstr(v) for v in values)})"


def _preds(spec, b_alias):
    return pair_pred(
        spec["pairs"], "a", b_alias,
        spec.get("normalize", True),
        spec.get("strip_digits", False),
    )


def count_subquery(spec, a_alias="a") -> str:
    """计算④：数次数（PRD §四）。src = 对照表。"""
    preds = [_preds(spec, "c")]
    if spec.get("status_col") and spec.get("status_values"):
        preds.append(in_filter(f"c.{qi(spec['status_col'])}", spec["status_values"]))
    return f"(SELECT count(*) FROM {qi(spec['src_table'])} c WHERE " + " AND ".join(preds) + ")"


def exists_subquery(spec, a_alias="a") -> str:
    """计算③：判断在不在（PRD §四）。"""
    return (
        f"EXISTS (SELECT 1 FROM {qi(spec['src_table'])} b WHERE {_preds(spec, 'b')})"
    )


def vlookup_subquery(spec, a_alias="a") -> str:
    """计算②：取第一行（多行命中由上层出黄条警告）。"""
    inner = (
        f"SELECT v.{qi(spec['fill_col'])} FROM {qi(spec['src_table'])} v "
        f"WHERE {_preds(spec, 'v')} LIMIT 1"
    )
    return f"({inner})"


def vlookup_multihit_sql(spec) -> str:
    """有多少行在对照表里命中 >1 行（黄条警告计数）。"""
    return (
        f"SELECT count(*) FROM {qi(spec['a_table'])} a WHERE {guard_pred(spec['pairs'])} "
        f"AND (SELECT count(*) FROM {qi(spec['src_table'])} v WHERE {_preds(spec, 'v')}) > 1"
    )
