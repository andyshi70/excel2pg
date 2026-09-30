"""入口：三栏布局（左=表列表/预览，中=操作向导，右=结果）。"""
import logging

import streamlit as st

from engine.db import get_conn
from ui import calcs, querycard, store
from ui.errors import MESSAGES, humanize
from ui.helpers import (columns, df_to_xlsx, distinct_values, missing_targets,
                        table_head, table_shape, ui_tables)

CARDS = [
    ("query", "🔍 查数据", "只读：单表或连一张表查，条件随便加，不改数据库"),
    ("vlookup", "📋 补一列", "对照另一张表，把某个值带过来填进新列（类似 VLOOKUP）"),
    ("exists", "✅ 判断在不在", "每个条目去对照表找一找：找到=是，没找到=否"),
    ("count", "🔢 数出现次数", "每个条目在明细表里出现几次，就填几（招了几个人）"),
]


def _sidebar(tables, conn):
    with st.sidebar:
        st.header("📁 数据表")
        sel = st.selectbox("点一张表看看", ["（先不看）"] + tables)
        if sel != "（先不看）":
            n, m = table_shape(conn, sel)
            st.caption(f"{sel}：{n} 行 × {m} 列")
            st.dataframe(table_head(conn, sel), height=280, use_container_width=True)
            cols = sorted(columns(conn, sel))
            c = st.selectbox("看某列都有哪些值（选筛选值时照着抄）", ["（不看）"] + cols)
            if c != "（不看）":
                vals = distinct_values(conn, sel, c)
                st.code("\n".join(str(v) for v in vals[:60]) + ("\n…" if len(vals) > 60 else ""))
        baks = store.load().get("last_backups") or []
        if baks:
            with st.expander("🕘 最近的自动备份表（要恢复旧数据时用它们）"):
                st.code("\n".join(baks[:10]))


def _results_right():
    res = st.session_state.get("results")
    if res:
        for r in res:
            st.markdown(f"### ✅ {r['table']}.{r['target']}")
            st.caption(
                f"更新 {r['changed']} 行 · 显示 {r['rows']} 行 · "
                f"跳过垃圾行 {r['guard_skipped']} 行"
            )
            if r.get("backup"):
                st.caption(f"备份表：{r['backup']}（需要恢复时可用它）")
            if r.get("total") and r["zero"] >= r["total"]:
                st.error(MESSAGES["zero_match"])
            elif r["kind"] == "count" and r["zero"]:
                st.warning(f"有 {r['zero']} 行算出来是 0 —— 对照表里一个都没数到，"
                           f"可能是这些方向/导师还没人录取，也可能是数据没覆盖，注意核对。")
            elif r["kind"] == "exists" and r["zero"]:
                st.info(f"有 {r['zero']} 行结果是「否」（对照表里没找到）。"
                        f"如果这个数大得反常，检查一下两边字段配对。")
            if r.get("multihit"):
                st.warning(f"对照表里有 {r['multihit']} 行都对上了（多行命中），只取了第一行的值。")
            st.dataframe(r["df"], use_container_width=True, height=420)
            st.download_button(
                "⬇ 下载结果 Excel（xlsx）", df_to_xlsx(r["df"]),
                file_name=f"{r['table']}_{r['target']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{r['table']}_{r['target']}",
            )
            st.divider()
        if st.button("↩ 回到首页，做下一个操作"):
            st.session_state.results = None
            st.session_state.mode = None
            st.rerun()
    elif st.session_state.get("mode") == "query" and st.session_state.get("q_result"):
        querycard.render_result(st.session_state.q_result)
    else:
        st.caption("结果会显示在这里。")
        st.caption("👆 先在中间点一张卡片开跑；执行结果、提示和 Excel 下载都会出现在这一栏。")


def main():
    st.set_page_config(page_title="yifan 数据小工具", page_icon="🗂️", layout="wide")
    st.markdown("## 🗂️ yifan 数据小工具 —— 点一点，答案自己出来")
    for k, v in (("mode", None), ("results", None), ("wiz", None)):
        st.session_state.setdefault(k, v)
    conn = None
    try:
        conn = get_conn()
        tables = ui_tables(conn)
    except Exception as e:  # noqa: BLE001
        logging.exception("startup failed")
        st.error(humanize(e))
        if conn:
            conn.close()
        return
    try:
        _sidebar(tables, conn)
        miss = missing_targets(conn)
        if miss:
            st.warning(f"检测到表被重新导入过，之前算的结果没了：{'、'.join(miss)} —— "
                       f"回到首页对应卡片重跑一次即可（配置会自动带出）。")

        mid, right = st.columns([6, 5])
        with mid:
            if st.session_state.mode == "query":
                if st.button("← 回到首页"):
                    st.session_state.mode = None
                    st.rerun()
                querycard.render(conn)
            elif st.session_state.mode in ("count", "exists", "vlookup"):
                calcs.set_conn(conn)
                if st.button("← 回到首页"):
                    st.session_state.mode = None
                    st.session_state.wiz = None
                    st.rerun()
                calcs.render(conn)
            else:
                st.markdown("### 想做什么？选一个")
                st.caption("四张卡片，点卡片进入向导，一步一步走，最后确认才真正改表。")
                row = st.columns(2)
                for i, (kind, title, desc) in enumerate(CARDS):
                    with row[i % 2]:
                        if st.button(f"{title}", key=f"card_{kind}", use_container_width=True):
                            calcs.set_conn(conn)
                            st.session_state.mode = kind
                            if kind != "query":
                                st.session_state.wiz = calcs.new_wiz(kind, tables)
                            st.session_state.results = None
                            st.rerun()
                        st.caption(desc)
        with right:
            _results_right()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
