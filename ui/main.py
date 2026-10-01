"""入口：双区布局（左=侧栏导航/表列表/导入Excel，右=主区：操作在上、结果显示正下方）。"""
import logging
import subprocess
import sys
from pathlib import Path

import streamlit as st

from engine.db import get_conn
from ui import calcs, querycard, store
from ui.errors import MESSAGES, humanize
from ui.helpers import (columns, df_to_xlsx, distinct_values, missing_targets,
                        table_head, table_shape, ui_tables)

EXCEL2PG = Path("/Users/evandy/excel2pg")
IMPORTER = EXCEL2PG / "src" / "importer.py"
EXCEL_DIR = EXCEL2PG / "src" / "excel"

CARDS = [
    ("query", "🔍 查数据", "只读：单表或连一张表查，条件随便加，不改数据库"),
    ("vlookup", "📋 Vlookup", "对照另一张表，把某个值带过来填进新列"),
    ("exists", "✅ 判断在不在", "每个条目去对照表找一找：找到=是，没找到=否"),
    ("count", "🔢 数出现次数", "每个条目在明细表里出现几次，就填几（招了几个人）"),
]

STYLE = """
<style>
/* ===== YIfan 简约版（侧栏导航 + 卡片网格，内容贴顶、无 banner） ===== */

/* 内容顶到置顶：藏空 header、收紧主区上边距 */
header[data-testid="stHeader"] { display: none; }
div.block-container { padding-top: 1.2rem !important; padding-bottom: 1.2rem; }
/* 首标题与侧栏品牌 YIfan 同一水平线（36px = CDP 实测中心差） */
.yf-title-row { margin-top: 36px !important; }

/* 侧栏：浅灰底、细分隔线、小号分区标题（25rem 保证 30px 品牌一行放下） */
section[data-testid="stSidebar"] { background: #FAFAFA; border-right: 1px solid #E4E4E7; width: 25rem !important; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
  font-size: 12px; letter-spacing: .06em; color: #71717A;
  font-weight: 600; margin: 1.3rem 0 .3rem;
}
.yf-brand { font-size: 30px; font-weight: 700; color: #18181B; letter-spacing: -.02em; margin: 0 0 6px; white-space: nowrap; }
section[data-testid="stSidebar"] [data-testid="stButton"] button { font-size: 13.5px; padding: .45rem .8rem; }

/* 首页卡片：带边框容器 = 卡；标题按钮变卡内大标题，描述在卡内 */
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stMarkdownContainer"] .yf-carddesc) {
  border: 1px solid #E4E4E7 !important; border-radius: 14px !important;
  background: #FFFFFF; padding: 10px 12px 4px !important;
  box-shadow: 0 1px 2px rgba(24,24,27,.04);
}
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stMarkdownContainer"] .yf-carddesc)
    [data-testid="stButton"] button {
  border: none !important; background: transparent !important; box-shadow: none !important;
  text-align: left !important; font-size: 15.5px !important; font-weight: 650 !important;
  color: #18181B !important; padding: 8px 8px 2px !important; min-height: auto !important;
}
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stMarkdownContainer"] .yf-carddesc)
    [data-testid="stButton"] button:hover {
  color: #6D4AF0 !important; background: #F5F3FF !important; border-radius: 10px !important;
}
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stMarkdownContainer"] .yf-carddesc)
    [data-testid="stButton"] button:focus { box-shadow: none !important; }
.yf-carddesc {
  font-size: 12.5px !important; color: #71717A !important; line-height: 1.55 !important;
  margin: 0 8px 8px !important;
}
/* 卡片网格：两张一排，列间距 */
div[data-testid="stColumn"] [data-testid="stVerticalBlock"]:has(.yf-carddesc) { margin-bottom: 4px; }
</style>
"""


def _style():
    st.markdown(STYLE, unsafe_allow_html=True)


def _sidebar(tables, conn):
    with st.sidebar:
        st.markdown('<div class="yf-brand">🗂️ YIfan 数据小工具</div>', unsafe_allow_html=True)
        st.header("📁 数据表")
        if st.button("📥 导入 Excel 数据", use_container_width=True,
                     help="把要导入的 Excel 放进指定目录，点一下全部导入；同名表会被覆盖"):
            files = sorted(list(EXCEL_DIR.glob("*.xlsx")) + list(EXCEL_DIR.glob("*.xlsm")))
            if not files:
                st.warning(f"目录里还没有 Excel —— 把文件放进 {EXCEL_DIR} 再点按钮。")
            else:
                try:
                    with st.spinner(f"正在导入 {len(files)} 个文件（同名表覆盖重导）…"):
                        p = subprocess.run(
                            [sys.executable, str(IMPORTER)],
                            cwd=str(EXCEL2PG), capture_output=True, text=True, timeout=600,
                        )
                except subprocess.TimeoutExpired:
                    st.error("导入超时（超过 10 分钟），请检查文件是否异常大。")
                    p = None
                if p is not None:
                    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
                    if p.returncode == 0:
                        tables = ui_tables(conn)  # 同一次运行里刷新表列表
                        st.success("导入完成，表列表已刷新。")
                        with st.expander("看导入日志"):
                            st.code(out[-6000:])
                    else:
                        st.error("导入失败，日志如下（表没改坏的部分会保留）。")
                        st.code(out[-6000:])
        st.caption(f"Excel 放这里：{EXCEL_DIR}（同名表会被覆盖，导入后记得重跑计算）")
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
            # cfg 只是历史索引，表可能已被轮换清理/手动删除 —— 只显示库里真实存在的
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename = ANY(%s)",
                    (baks,),
                )
                live = {r[0] for r in cur.fetchall()}
            baks = [b for b in baks if b in live]
        if baks:
            with st.expander("🕘 最近的自动备份表（要恢复旧数据时用它们）"):
                st.code("\n".join(baks[:10]))


def _results():
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
            if r.get("sample") is not None and len(r["sample"]):
                with st.expander("🔍 抽样核对（随机 10 行：匹配键 → 库里现值 —— 打开原 Excel 抽对几行）"):
                    st.dataframe(r["sample"], use_container_width=True, height=320)
                    st.caption("对法：拿这几行的匹配键回你原来的 Excel，用同样的算法（数次数 / 判断 / VLOOKUP）查一遍 —— "
                               "对上即结果正确；「对照表」「对侧带出值」列显示的是命中那行的原值。")
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


def main():
    st.set_page_config(page_title="YIfan 数据小工具", page_icon="🗂️", layout="wide")
    _style()
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
            st.markdown('<h3 class="yf-title-row">想做什么？选一个</h3>', unsafe_allow_html=True)
            st.caption("四张卡片，点卡片进入向导，一步一步走，最后确认才真正改表。")
            # 每行独立一排 columns：同一行两张卡从同一条基线开始（塞一个 columns 轮流填会错行）
            for r in range(2):
                row = st.columns(2)
                for j in range(2):
                    kind, title, desc = CARDS[r * 2 + j]
                    with row[j]:
                        with st.container(border=True):
                            if st.button(f"{title}", key=f"card_{kind}", use_container_width=True):
                                calcs.set_conn(conn)
                                st.session_state.mode = kind
                                if kind != "query":
                                    st.session_state.wiz = calcs.new_wiz(kind, tables)
                                st.session_state.results = None
                                st.rerun()
                            st.markdown(f'<div class="yf-carddesc">{desc}</div>',
                                        unsafe_allow_html=True)
        # 单栏布局：操作在上，结果显示正下方（不再分左右）
        _results()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
