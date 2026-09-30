"""读库辅助：预览、去重值、结果集、xlsx。全部只读除 writeback 外。"""
import io

import pandas as pd

from engine import specs as S
from engine.db import columns, connect, list_tables, qi


def ui_tables(conn) -> list:
    """界面上可见的表：过滤掉自动备份表（小白不该看见/操作它们）。"""
    return [t for t in list_tables(conn) if "_bak_" not in t]


def read_df(conn, sql, params=None) -> pd.DataFrame:
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.rollback()
    return pd.DataFrame(rows, columns=cols)


def table_head(conn, table: str, n: int = 50) -> pd.DataFrame:
    return read_df(conn, f"SELECT * FROM {qi(table)} LIMIT {int(n)}")


def distinct_values(conn, table: str, col: str, limit: int = 300) -> list:
    df = read_df(
        conn,
        f"SELECT DISTINCT {qi(col)} FROM {qi(table)} WHERE {qi(col)} IS NOT NULL "
        f"ORDER BY 1 LIMIT {int(limit)}",
    )
    return df.iloc[:, 0].tolist()


def table_shape(conn, table: str) -> tuple:
    cur = conn.cursor()
    cur.execute(f"SELECT count(*) FROM {qi(table)}")
    n = cur.fetchone()[0]
    conn.rollback()
    return n, len(columns(conn, table))


def missing_targets(conn) -> list:
    """重导入探测（PRD §五）：固定计算的目标列还在吗。"""
    missing = []
    for spec in S.FIXED:
        cols = columns(conn, spec["a_table"])
        if not cols or spec["target_col"] not in cols:
            missing.append(f"{spec['a_table']}.{spec['target_col']}")
    return missing


def default_target(kind: str, a_table: str, a_cols: dict) -> str:
    """预填目标列（决策4：各写各的，界面统一标签）。"""
    known = {
        ("count", "硕士"): "推免已招",
        ("count", "直博"): "推免总数",
        ("exists", "硕士"): "推免目录开放情况",
        ("exists", "直博"): "目录开放情况",
    }
    if (kind, a_table) in known and known[(kind, a_table)] in a_cols:
        return known[(kind, a_table)]
    # 通用回退：含关键词的已有列
    kw = "已招" if kind == "count" else ("开放" if kind == "exists" else None)
    if kw:
        for c in a_cols:
            if kw in c:
                return c
    return ""


def df_to_xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="结果")
    return buf.getvalue()


__all__ = [
    "connect", "list_tables", "ui_tables", "columns", "qi",
    "read_df", "table_head", "distinct_values", "table_shape",
    "missing_targets", "default_target", "df_to_xlsx",
]
