"""查询卡片 SQL 生成（只读，PRD §四①）。条件值走参数绑定，防注入。"""
from engine.db import qi
from engine.match import pair_pred

JOIN_LABELS = {
    "left": "A表全保留，对照表对得上的带过来，对不上的留空",
    "inner": "只要两边都能对上的",
    "right": "只要对照表里有的，把A表信息贴上去",
}

OPS = [
    ("等于", "eq"), ("不等于", "ne"), ("包含（模糊搜）", "contains"),
    ("大于", "gt"), ("小于", "lt"),
    ("在…之中（多选值）", "in"),
    ("是空的", "null"), ("不是空的", "notnull"),
    ("介于两个数之间", "between"),
]
OP_BY_LABEL = dict(OPS)


def build_query(spec, a_cols, b_cols, limit=None, order_by=""):
    """spec: {a_table, b_table|None, join, pairs, conds:[{side,col,op,vals}]}
    返回 (sql, params)。conds 为空 = 无条件。order_by = 调用方给好的 ORDER BY 子句（含前导空格）。"""
    sel = [f"a.{qi(c)}" for c in a_cols]
    if spec.get("b_table"):
        for c in b_cols:
            expr = f"b.{qi(c)}"
            sel.append(f'{expr} AS {qi(spec["b_table"] + "_" + c)}' if c in a_cols else expr)
    sql = f"SELECT {', '.join(sel)} FROM {qi(spec['a_table'])} a"
    params = []
    if spec.get("b_table"):
        join = {"left": "LEFT JOIN", "inner": "INNER JOIN", "right": "RIGHT JOIN"}[spec["join"]]
        sql += f" {join} {qi(spec['b_table'])} b ON {pair_pred(spec['pairs'], 'a', 'b')}"
    where = []
    for c in spec.get("conds", []):
        ref = f"{'a' if c['side'] == 'a' else 'b'}.{qi(c['col'])}"
        op, vals = c["op"], c.get("vals") or []
        if op == "eq":
            where.append(f"{ref} = %s"); params.append(vals[0])
        elif op == "ne":
            where.append(f"{ref} <> %s"); params.append(vals[0])
        elif op == "contains":
            where.append(f"{ref} LIKE %s"); params.append(f"%{vals[0]}%")
        elif op == "gt":
            where.append(f"{ref} > %s"); params.append(vals[0])
        elif op == "lt":
            where.append(f"{ref} < %s"); params.append(vals[0])
        elif op == "in":
            where.append(f"{ref} IN ({','.join(['%s'] * len(vals))})"); params.extend(vals)
        elif op == "null":
            where.append(f"{ref} IS NULL")
        elif op == "notnull":
            where.append(f"{ref} IS NOT NULL")
        elif op == "between":
            where.append(f"{ref} BETWEEN %s AND %s"); params.extend(vals[:2])
    if where:
        sql += " WHERE " + " AND ".join(where)
    if order_by:
        sql += order_by
    if limit:
        sql += f" LIMIT {int(limit)}"
    return sql, params


def count_sql(spec, a_cols, b_cols):
    """同条件下的总行数（不含 LIMIT）。"""
    sql, params = build_query(spec, a_cols, b_cols)
    end = sql.index(" FROM ")
    return "SELECT count(*)" + sql[end:], params
