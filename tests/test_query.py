"""查询卡片 SQL 真库验证（只读）。运行： python tests/test_query.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.db import connect, list_tables
from ui.helpers import read_df
from ui.querysql import build_query, count_sql

A, B = "硕士", "总0924"
PAIRS = [
    ("学位类型", "录取类型"),
    ("专业码", "录取专业代码"),
    ("研究方向", "录取研究方向（2027年目录方向）"),
    ("指导教师", "导师姓名"),
]

with connect() as conn:
    tables = list_tables(conn)
    assert A in tables and B in tables, tables

    def run(join, conds=()):
        spec = {"a_table": A, "b_table": B, "join": join, "pairs": PAIRS, "conds": list(conds)}
        a_cols = list(cols_a)
        b_cols = list(cols_b)
        sql, params = build_query(spec, a_cols, b_cols, limit=5001)
        df = read_df(conn, sql, params)
        csql, cparams = count_sql(spec, a_cols, b_cols)
        total = int(read_df(conn, csql, cparams).iloc[0, 0])
        return df, total, sql

    from ui.helpers import columns
    cols_a = columns(conn, A)
    cols_b = columns(conn, B)

    # 1) 三种连接都能跑、行数关系符合语义（左连 ⊇ 内连；右连 ⊆ 左连集合的行数不必然，但都能出数）
    df_l, n_l, sql_l = run("left")
    df_i, n_i, _ = run("inner")
    df_r, n_r, _ = run("right")
    print(f"left={n_l} inner={n_i} right={n_r}")
    # 左连：A 每行至少出现一次（对照表同键多行时会成倍，属标准 SQL 语义）
    assert n_l >= 501, n_l
    assert n_i <= n_l, (n_i, n_l)
    assert n_i > 0
    assert n_r >= n_i, (n_r, n_i)      # 右连 ≥ 内连（B 侧未命中的行也带进来）
    assert len(df_l) <= 5001

    # 2) 重名列自动加表名前缀
    assert f"{B}_医院" in df_l.columns, df_l.columns.tolist()
    assert "医院" in df_l.columns

    # 3) 条件筛选：等值
    df_e, n_e, _ = run("left", [{"side": "a", "col": "医院", "op": "eq", "vals": ["华山医院"]}])
    print(f"医院=华山医院 → {n_e} 行")
    assert 0 < n_e < 501

    # 4) 条件：包含（LIKE 参数绑定）
    df_c, n_c, _ = run("left", [{"side": "a", "col": "医院", "op": "contains", "vals": ["华"]}])
    assert n_c >= n_e

    # 5) 条件：在…之中（多值参数）
    df_m, n_m, _ = run("left", [{"side": "a", "col": "学位类型", "op": "in", "vals": ["学硕", "专硕"]}])
    print(f"学位类型 in (学硕,专硕) → {n_m} 行")
    assert n_m > 0

    # 6) 条件：IS NULL（B 侧列）
    df_n, n_n, _ = run("left", [{"side": "b", "col": "导师姓名", "op": "null", "vals": []}])
    assert n_n > 0

    # 7) 条件：between（数值）
    df_b, n_b, _ = run("left", [{"side": "b", "col": "复试成绩（满分100分）", "op": "between", "vals": ["90", "100"]}])
    print(f"复试成绩 90-100 → {n_b} 行")
    assert n_b > 0

    # 8) 无 B 的单表查询
    spec1 = {"a_table": A, "b_table": None, "join": "left", "pairs": [], "conds": []}
    sql1, _ = build_query(spec1, cols_a, [])
    df1 = read_df(conn, sql1, None)
    assert len(df1) == 501
    assert sql1.count("JOIN") == 0

    # 9) 参数是绑定的，注入串原样当值（不进 SQL 文本）
    spec_i = {"a_table": A, "b_table": None, "join": "left", "pairs": [],
              "conds": [{"side": "a", "col": "医院", "op": "eq", "vals": ["'; DROP TABLE 硕士; --"]}]}
    sql_i, par_i = build_query(spec_i, cols_a, [])
    assert "DROP" not in sql_i and par_i == ["'; DROP TABLE 硕士; --"]

    # 10) 全量展示排序规则：查询带 ORDER BY（在 LIMIT 前），count 永不带排序
    from ui.helpers import code_order, ordered_columns, order_clause
    with connect() as c2:
        oa = ordered_columns(c2, A)
        ob = ordered_columns(c2, B)
    assert code_order(oa)[:1] == ["代码"], code_order(oa)
    order_by = " ORDER BY " + ", ".join(p for p in (order_clause(oa, "a."), order_clause(ob, "b.")) if p)
    assert 'a."代码" NULLS LAST' in order_by, order_by
    spec_o = {"a_table": A, "b_table": B, "join": "left", "pairs": PAIRS, "conds": []}
    sql_o, _ = build_query(spec_o, cols_a, cols_b, limit=5001, order_by=order_by)
    assert "ORDER BY" in sql_o and sql_o.index("ORDER BY") < sql_o.index("LIMIT"), sql_o[-200:]
    csql_o, _ = count_sql(spec_o, cols_a, cols_b)
    assert "ORDER BY" not in csql_o, csql_o
    # 真跑一遍：按代码列单调不降（数值列直接比）
    df_o = read_df(conn, sql_o, None)
    codes = df_o["代码"].dropna().tolist()
    assert codes == sorted(codes), "结果未按代码升序"
    print(f"[OK] ORDER BY 接线：查询带排序（代码升序 {codes[0]}→{codes[-1]}）、count 不带")

print("test_query: ALL PASS")
