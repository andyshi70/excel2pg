"""查询卡片（PRD §四①）：只读，不回写。单/双表 + 三种连接大白话 + 多条件。"""
import logging

import streamlit as st

from engine.db import columns, qi
from engine.match import pair_pred

from .errors import humanize
from .helpers import (checkbox_multi, df_to_xlsx, distinct_values,
                      order_clause, ordered_columns, read_df, ui_tables)
from .querysql import JOIN_LABELS, OP_BY_LABEL, OPS, build_query, count_sql

LIMIT = 5001  # 多取 1 行用于判断是否超限


def _init():
    if "q" not in st.session_state:
        st.session_state.q = {
            "a": None, "use_b": False, "b": None, "join": "left",
            "a_cols": [], "b_cols": [], "conds": [],
        }


def render(conn):
    _init()
    q = st.session_state.q
    tables = ui_tables(conn)
    st.caption("本查询只看不改数据库，随时查、随便试。")

    q["a"] = st.selectbox("从哪张表查？", tables,
                          index=tables.index(q["a"]) if q["a"] in tables else 0)
    q["use_b"] = st.checkbox("再连一张表一起查", value=q["use_b"])
    a_cols = sorted(columns(conn, q["a"]))
    b_cols = []
    if q["use_b"]:
        opts = [t for t in tables if t != q["a"]]
        if q["b"] not in opts:
            q["b"] = opts[0]
        q["b"] = st.selectbox("连哪张表？", opts, index=opts.index(q["b"]))
        b_cols = sorted(columns(conn, q["b"]))
        st.caption("怎么连？" )
        q["join"] = st.radio("两张表怎么连？", list(JOIN_LABELS), format_func=lambda k: JOIN_LABELS[k],
                             index=list(JOIN_LABELS).index(q["join"]), horizontal=False)
        left_common = a_cols
        q["a_cols"] = checkbox_multi(f"左边：{q['a']} 的字段（按顺序对应）", left_common,
                                     [c for c in q["a_cols"] if c in left_common], "qcol_a")
        q["b_cols"] = checkbox_multi(f"右边：{q['b']} 的字段（按顺序对应左边）", b_cols,
                                     [c for c in q["b_cols"] if c in b_cols], "qcol_b")
        if len(q["a_cols"]) != len(q["b_cols"]) or not q["a_cols"]:
            st.warning("两边字段数量要一样多，按顺序一一对应。")
        elif q["a_cols"]:
            pairs = [f"{a} ↔ {b}" for a, b in zip(q["a_cols"], q["b_cols"])]
            st.info("配对：\n\n" + "\n\n".join(f"{i + 1}. {p}" for i, p in enumerate(pairs)))

    # ---- 条件区
    st.markdown("**筛选条件**（不加条件 = 全部显示）")
    refs = [("a", c, f"{q['a']}.{c}") for c in a_cols]
    if q["use_b"] and q.get("b"):
        refs += [("b", c, f"{q['b']}.{c}") for c in b_cols]
    ref_label = {label: (side, col) for side, col, label in refs}
    for i, cond in enumerate(q["conds"]):
        c1, c2, c3, c4 = st.columns([4, 3, 3, 1])
        labels = [lbl for _, _, lbl in refs]
        cur_label = f"{q['a']}.{cond['col']}" if cond["side"] == "a" and f"{q['a']}.{cond['col']}" in labels \
            else (f"{q.get('b')}.{cond['col']}" if f"{q.get('b')}.{cond['col']}" in labels else labels[0])
        with c1:
            label = st.selectbox("字段" if i == 0 else "", labels, index=labels.index(cur_label), key=f"cref{i}")
        with c2:
            op_label = st.selectbox("说法" if i == 0 else "", [l for l, _ in OPS],
                                    index=[l for l, _ in OPS].index(
                                        next((l for l, o in OPS if o == cond["op"]), "等于")), key=f"cop{i}")
        side, col = ref_label[label]
        op = OP_BY_LABEL[op_label]
        vals = cond.get("vals") or []
        with c3:
            if op in ("null", "notnull"):
                cond.update(side=side, col=col, op=op, vals=[])
                st.caption("（不用填值）" if i == 0 else "")
            elif op == "in":
                ref = f"{side}.{qi(col)}"
                pool = distinct_values(conn, q[side], col) if not cond.get("_pool") else cond["_pool"]
                cond["_pool"] = pool
                picked = checkbox_multi("值（多选）" if i == 0 else "", pool,
                                        [v for v in vals if v in pool], f"cval{i}", columns=1)
                cond.update(side=side, col=col, op=op, vals=picked)
            elif op == "between":
                v1 = st.text_input("从" if i == 0 else "", value=str(vals[0]) if len(vals) > 0 else "", key=f"cv1{i}")
                v2 = st.text_input("到" if i == 0 else "", value=str(vals[1]) if len(vals) > 1 else "", key=f"cv2{i}")
                cond.update(side=side, col=col, op=op, vals=[v1, v2])
            else:
                v = st.text_input("值" if i == 0 else "", value=str(vals[0]) if vals else "", key=f"cval{i}")
                cond.update(side=side, col=col, op=op, vals=[v])
        with c4:
            st.write("")
            if st.button("删", key=f"cdel{i}"):
                q["conds"].pop(i)
                st.rerun()
    if st.button("+ 加一个条件"):
        q["conds"].append({"side": "a", "col": a_cols[0], "op": "eq", "vals": [""]})
        st.rerun()

    ready = True
    if q["use_b"]:
        ready = len(q["a_cols"]) == len(q["b_cols"]) and bool(q["a_cols"])
    for cond in q["conds"]:
        if cond["op"] in ("in",) and not cond.get("vals"):
            ready = False
        if cond["op"] not in ("null", "notnull", "in") and not str(cond.get("vals", [""])[0]):
            ready = False
        if cond["op"] == "between" and not all(str(v) for v in cond.get("vals", ["", ""])):
            ready = False
    if not ready:
        st.warning("还有没填完的：连接字段数量对齐 / 条件值没填。")
    if st.button("查一下", type="primary", disabled=not ready, key="run_query"):
        try:
            spec = {
                "a_table": q["a"],
                "b_table": q["b"] if q["use_b"] else None,
                "join": q["join"],
                "pairs": list(zip(q["a_cols"], q["b_cols"])) if q["use_b"] else [],
                "conds": [c for c in q["conds"]],
            }
            bcols = sorted(columns(conn, q["b"])) if q["use_b"] else []
            # 全量展示按代码列排序（规则 2026-09-30）；count 不带排序
            parts = [order_clause(ordered_columns(conn, q["a"]), "a.")]
            if q["use_b"]:
                parts.append(order_clause(ordered_columns(conn, q["b"]), "b."))
            parts = [p for p in parts if p]
            order_by = f" ORDER BY {', '.join(parts)}" if parts else ""
            sql, params = build_query(spec, a_cols, bcols, limit=LIMIT, order_by=order_by)
            df = read_df(conn, sql, params)
            csql, cparams = count_sql(spec, a_cols, bcols)
            total = read_df(conn, csql, cparams).iloc[0, 0]
            try:  # 展示用：把参数内联进 SQL，用户可复制去任何工具复跑核对（不执行）
                with conn.cursor() as _mc:
                    shown = _mc.mogrify(sql, params).decode() if params else sql
                conn.rollback()
            except Exception:  # noqa: BLE001
                shown = sql
            st.session_state.q_result = {
                "df": df.head(LIMIT - 1), "total": int(total),
                "title": f"{q['a']}" + (f" ⋈ {q['b']}" if q["use_b"] else ""),
                "sql": shown,
            }
        except Exception as e:  # noqa: BLE001
            logging.exception("query failed")
            st.error(humanize(e))


def render_result(res):
    """渲染查询结果（显示在查询表单下方）。"""
    st.markdown(f"### 查询结果：{res['title']}")
    st.caption(f"共 {res['total']} 行" + ("（只显示前 5000 行，下载是全量）" if res["total"] > len(res["df"]) else ""))
    if res.get("sql"):
        with st.expander("🔎 看本次查询的 SQL（可复制去任何数据库工具复跑核对）"):
            st.code(res["sql"], language="sql")
            st.caption(f"原样复跑这条 SQL，行数应等于 {res['total']} —— 对上即查询无误。")
    st.dataframe(res["df"], use_container_width=True, height=520)
    st.download_button("⬇ 下载 Excel（xlsx）", df_to_xlsx(res["df"]),
                       file_name=f"查询结果.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="dl_query")
