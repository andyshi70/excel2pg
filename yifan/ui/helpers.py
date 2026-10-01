"""读库与界面辅助：预览、去重值、结果集、xlsx、勾选框多选。全部只读除 writeback 外。"""
import io

import pandas as pd
import streamlit as st

from engine import specs as S
from engine.db import columns, connect, list_tables, qi


def _toggle_order(order_key, ck, opt):
    """勾/取消勾时维护勾选顺序（顺序 = 配对顺序）。"""
    order = st.session_state.get(order_key, [])
    if st.session_state.get(ck):
        if opt not in order:
            order.append(opt)
    else:
        order = [o for o in order if o != opt]
    st.session_state[order_key] = order


def checkbox_multi(label, options, selected, key, help=None, columns=2):
    """勾选框多选（替代多选下拉）：列表常驻直接勾，不用反复开下拉。返回勾选顺序列表。"""
    st.caption(label)
    if help:
        st.caption(help)
    order_key, prefix = f"{key}__order", f"{key}::"
    # 换过选项集（切表/切列）→ 旧勾选作废，按预填重建
    if st.session_state.get(f"{key}__sig") != tuple(options):
        for k in [k for k in st.session_state if k.startswith(prefix)]:
            st.session_state.pop(k)
        st.session_state.pop(order_key, None)
        st.session_state[f"{key}__sig"] = tuple(options)
        st.session_state[order_key] = [o for o in selected if o in options]
    order = st.session_state.setdefault(order_key, [])
    cols = st.columns(columns)
    for i, opt in enumerate(options):
        ck = f"{prefix}{opt}"
        st.session_state.setdefault(ck, opt in order)
        with cols[i % columns]:
            st.checkbox(opt, key=ck, on_change=_toggle_order, args=(order_key, ck, opt))
    return [o for o in order if o in options]


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


def ordered_columns(conn, table: str) -> list:
    """表内真实列顺序（Excel 的列序数就是它），不按字母排。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,),
    )
    cols = [r[0] for r in cur.fetchall()]
    conn.rollback()
    return cols


def code_order(cols: list) -> list:
    """展示排序键：名字像代码的列（「代码」优先，其次按列序数；排除证件号码这类号码列）。"""
    codes = [c for c in cols if "码" in c and "号码" not in c]
    return sorted(codes, key=lambda c: (c != "代码", cols.index(c)))


def order_clause(cols: list, prefix: str = "") -> str:
    """ORDER BY 后面的键列表（不含关键字），多表拼接后统一加一次 ORDER BY。"""
    return ", ".join(f"{prefix}{qi(c)} NULLS LAST" for c in code_order(cols))


def table_head(conn, table: str, n: int = 50) -> pd.DataFrame:
    oc = order_clause(ordered_columns(conn, table))
    sql = f"SELECT * FROM {qi(table)}" + (f" ORDER BY {oc}" if oc else "") + f" LIMIT {int(n)}"
    return read_df(conn, sql)


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
    "ordered_columns", "code_order", "order_clause",
]
