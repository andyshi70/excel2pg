"""三张计算卡片的向导（PRD §四）：一次只问一件事、预填可改、人话确认、事务执行。"""
import logging

import streamlit as st

from engine import specs as S
from engine.db import columns, qi, table_exists
from engine.ops import backup_name, dry_run, validate, vlookup_multihit, writeback

from . import store
from .errors import humanize
from .helpers import (default_target, distinct_values, order_clause,
                      ordered_columns, read_df, ui_tables)

STEPS = {
    "count": ["选主表", "选对照表", "对应字段", "统计范围", "写到哪一列", "可选筛选", "确认执行"],
    "exists": ["选主表", "选对照表", "对应字段", "写到哪一列", "可选筛选", "确认执行"],
    "vlookup": ["选主表", "选对照表", "对应字段", "带出哪一列", "写到哪一列", "可选筛选", "确认执行"],
}
TITLE = {
    "count": "数出现次数：数数招了几个人",
    "exists": "判断在不在：是 / 否",
    "vlookup": "Vlookup：从对照表带个值过来",
}
DEFAULT_SRC = {"count": ["总0924", "录取+候补0922"], "exists": ["二轮推免开放目录"], "vlookup": ["二轮推免开放目录", "总0924"]}

# vlookup 三档匹配方式（页面可选）
MODE_OPTS = {
    "exact": "精确一致（默认，以前的行为）",
    "loose": "宽松一致：忽略空格、大小写、全半角",
    "contains": "包含就算：一边包含另一边（文字列用，数字编码列别用）",
}
MODE_PHRASE = {
    "exact": "",
    "loose": "（按宽松规则比对：忽略空格、大小写、全半角）",
    "contains": "（按包含规则比对：一边包含另一边就算对上）",
}


def new_wiz(kind: str, tables: list) -> dict:
    saved = store.load().get(kind, {})
    src = saved.get("src")
    if not src or not table_exists(_CONN, src):
        src = next((t for t in DEFAULT_SRC[kind] if t in tables), tables[-1])
    return {
        "kind": kind, "step": 0,
        "a_tables": [t for t in saved.get("a_tables", ["硕士", "直博"]) if t in tables] or tables[:1],
        "src": src,
        "a_cols": saved.get("a_cols", []),
        "src_cols": saved.get("src_cols", []),
        "status_col": saved.get("status_col"),
        "status_values": saved.get("status_values"),
        "fill_col": saved.get("fill_col"),
        "default": saved.get("default", ""),
        "targets": saved.get("targets", {}),
        "filter_col": saved.get("filter_col"),
        "filter_values": saved.get("filter_values", []),
        "strip_digits": saved.get("strip_digits", False),
        "match_mode": saved.get("match_mode", "exact"),
    }


_CONN = None  # new_wiz 里探测表用，main 每轮注入


def set_conn(conn):
    global _CONN
    _CONN = conn


def build_spec(w: dict, a_table: str) -> dict:
    kind = w["kind"]
    spec = {
        "kind": kind, "a_table": a_table, "src_table": w["src"],
        "pairs": list(zip(w["a_cols"], w["src_cols"])),
        "normalize": True, "strip_digits": w["strip_digits"],
    }
    tgt = w["targets"].get(a_table)
    if not tgt:
        raise ValueError(f"还没选「{a_table}」的结果写到哪一列")
    mode, val = tgt
    if mode == "existing":
        spec["target_col"] = val
    elif mode == "new" and val:
        spec["target_col"] = val
    else:
        raise ValueError(f"「{a_table}」的新列名还没填")
    if kind == "count":
        spec["status_col"] = w["status_col"]
        spec["status_values"] = w["status_values"]
    if kind == "vlookup":
        spec["fill_col"] = w["fill_col"]
        spec["default"] = w["default"]
        spec["match_mode"] = w.get("match_mode", "exact")
    return spec


def _summary_line(w, a_table, spec) -> str:
    keys = "+".join(w["a_cols"])
    tgt = spec["target_col"]
    if w["kind"] == "count":
        who = "、".join(w["status_values"] or [])
        return (f"在「{w['src']}」里数每个「{keys}」组合下 **{who}** 的人数，写进「{a_table}」表的「{tgt}」列")
    if w["kind"] == "exists":
        return (f"判断「{a_table}」每个「{keys}」在不在「{w['src']}」里，写进「{tgt}」列（是/否）")
    d = w["default"] or "空"
    return (f"把「{w['src']}」的「{w['fill_col']}」带过来填进「{a_table}」表的「{tgt}」列，对不上的填「{d}」"
            f"{MODE_PHRASE.get(w.get('match_mode', 'exact'), '')}")


def _save_cfg(w: dict):
    cfg = store.load()
    cfg[w["kind"]] = {k: v for k, v in w.items() if k not in ("step", "kind")}
    store.save(cfg)


def _validate_step(w: dict) -> str:
    """返回空串=可以下一步，否则阻止并显示。"""
    k = w["kind"]
    if w["step"] == 0 and not w["a_tables"]:
        return "至少选一张主表"
    if w["step"] == 2:
        if not w["a_cols"] or not w["src_cols"]:
            return "两边都要选字段"
        if len(w["a_cols"]) != len(w["src_cols"]):
            return "两边字段数量要一样多，按顺序一一对应"
    if k == "count" and STEPS[k][w["step"]] == "统计范围":
        if not w["status_col"] or not w["status_values"]:
            return "要统计的状态至少选一个"
    if STEPS[k][w["step"]] == "写到哪一列":
        for t in w["a_tables"]:
            tgt = w["targets"].get(t)
            if not tgt or (tgt[0] == "new" and not tgt[1]):
                return f"「{t}」还没选结果写到哪一列"
    return ""


def _step_body(w: dict, conn):
    kind, tables = w["kind"], None
    tables = ui_tables(conn)
    step = STEPS[kind][w["step"]]

    if step == "选主表":
        st.caption("要对哪张表动手？可以多选，每张表各算一遍，最后一次确认全部执行。")
        w["a_tables"] = st.multiselect("主表", tables, default=w["a_tables"])
    elif step == "选对照表":
        opts = [t for t in tables if t not in w["a_tables"]]
        if not opts:
            st.error("主表把所有表都占了，对照表没得选 —— 回上一步少选一张主表。")
            return
        st.caption("去哪张表里找（数数 / 判断 / 取值）")
        cur = w["src"] if w["src"] in opts else opts[0]
        w["src"] = st.selectbox("对照表", opts, index=opts.index(cur))
    elif step == "对应字段":
        st.caption("两边各选几个字段，**按勾选顺序一一对应**（字段名不一样没关系，比如左边「研究方向」对应右边「录取研究方向（2027年目录方向）」）。")
        a_sets = [set(columns(conn, t)) for t in w["a_tables"]]
        common = sorted(set.intersection(*a_sets)) if a_sets else []
        s_cols = sorted(columns(conn, w["src"]))
        w["a_cols"] = st.multiselect(f"左边：{ '、'.join(w['a_tables']) } 的字段", common, default=[c for c in w["a_cols"] if c in common])
        w["src_cols"] = st.multiselect(f"右边：{w['src']} 的字段", s_cols, default=[c for c in w["src_cols"] if c in s_cols])
        if len(w["a_cols"]) != len(w["src_cols"]):
            st.warning("两边选的字段数量不一样，顺序对应会错位 —— 数量要相同。")
        elif w["a_cols"]:
            pairs = [f"{a} ↔ {b}" for a, b in zip(w["a_cols"], w["src_cols"])]
            st.info("配对关系：\n\n" + "\n\n".join(f"{i+1}. {p}" for i, p in enumerate(pairs)))
        w["strip_digits"] = st.checkbox(
            "忽略导师姓名末尾的数字（「张文宏1」和「张文宏」看作同一人）",
            value=w["strip_digits"],
            help="只对导师/教师/姓名类字段生效，绝不会动专业码这类数字字段。默认关：你以前的算法没开它。",
        )
        if kind == "vlookup":
            w["match_mode"] = st.selectbox(
                "怎么算「对上了」？（匹配方式）",
                list(MODE_OPTS), format_func=lambda k: MODE_OPTS[k],
                index=list(MODE_OPTS).index(w.get("match_mode", "exact")),
                help="精确=两边一模一样才算对上。宽松=写法差个空格/大小写/全半角也算。"
                     "包含=一边装着另一边就算（注意：数字编码列别用，1002 会误配 100210）。",
            )
    elif step == "统计范围":
        s_cols = sorted(columns(conn, w["src"]))
        default_status = "是否录取" if "是否录取" in s_cols else s_cols[0]
        cur = w["status_col"] if w["status_col"] in s_cols else default_status
        w["status_col"] = st.selectbox("按哪一列判断「算不算数」？", s_cols, index=s_cols.index(cur),
                                       help="一般就是「是否录取」这类状态列。")
        vals = distinct_values(conn, w["src"], w["status_col"])
        prefer = [v for v in ["录取", "专项录取"] if v in vals]
        saved = [v for v in (w["status_values"] or []) if v in vals]
        w["status_values"] = st.multiselect(
            "只数哪些状态的人？（默认只数正式录取的）", vals, default=saved or prefer or vals[:1],
            help="把候补、未录取也算上会把数字抬高；你以前的口径 = 只数录取+专项录取。",
        )
    elif step == "带出哪一列":
        s_cols = ordered_columns(conn, w["src"])  # 表内真实列顺序 = Excel 列序数
        opts = [f"第{i}列 · {c}" for i, c in enumerate(s_cols, 1)]
        base = s_cols.index(w["fill_col"]) if w["fill_col"] in s_cols else 0

        # 换过对照表时状态可能越界 → 清掉走默认
        if "fill_ord" in st.session_state and not (1 <= st.session_state["fill_ord"] <= len(s_cols)):
            for k in ("fill_ord", "fill_pick", "_fill_ord_prev"):
                st.session_state.pop(k, None)
        if "fill_pick" in st.session_state and st.session_state["fill_pick"] not in opts:
            for k in ("fill_pick", "_fill_ord_prev"):
                st.session_state.pop(k, None)

        # 下拉改了 → 数字跟着变（必须在 number_input 渲染前写）
        if "fill_pick" in st.session_state and "fill_ord" in st.session_state:
            pi = opts.index(st.session_state["fill_pick"])
            if opts[st.session_state["fill_ord"] - 1] != opts[pi]:
                st.session_state["fill_ord"] = pi + 1
                st.session_state["_fill_ord_prev"] = pi + 1

        if "fill_ord" not in st.session_state:
            st.session_state["fill_ord"] = base + 1
        n = st.number_input(
            "直接填列序数（1 = 第1列，就是 Excel VLOOKUP 里那个「第几列」）",
            min_value=1, max_value=len(s_cols), step=1, key="fill_ord",
        )
        if st.session_state.get("_fill_ord_prev") not in (None, n):
            st.session_state["fill_pick"] = opts[n - 1]  # 数字改了 → 下拉跳过去
        st.session_state["_fill_ord_prev"] = n
        pick = st.selectbox(
            f"把「{w['src']}」的哪一列带过来？（第N列 = 表里真实列序数）", opts,
            index=base, key="fill_pick",
        )
        w["fill_col"] = s_cols[opts.index(pick)]
        w["default"] = st.text_input("对不上时填什么？（留空 = 空着）", value=w["default"])
    elif step == "写到哪一列":
        st.caption("选已有列 = 覆盖旧值；也可以新建一列。")
        for t in w["a_tables"]:
            cols = sorted(columns(conn, t))
            opts = ["（新建一列）"] + cols
            mode, val = w["targets"].get(t, (None, None))
            if mode == "existing" and val in cols:
                idx = opts.index(val)
            elif mode == "new":
                idx = 0
            else:
                guess = default_target(kind, t, columns(conn, t))
                idx = opts.index(guess) if guess else 0
            sel = st.selectbox(f"「{t}」表：结果写到哪一列？", opts, index=idx)
            if sel == "（新建一列）":
                name = st.text_input(f"「{t}」：新列叫什么名字？", value=val if mode == "new" else "")
                w["targets"][t] = ("new", name)
            else:
                w["targets"][t] = ("existing", sel)
    elif step == "可选筛选":
        st.caption("只影响右边看到的和下载的内容，**不影响计算**（计算永远全表跑）。不选就跳过。")
        common = sorted(set.intersection(*[set(columns(conn, t)) for t in w["a_tables"]]))
        opts = ["（不筛选）"] + common
        cur = w["filter_col"] if w["filter_col"] in common else "（不筛选）"
        sel = st.selectbox("按哪一列筛？", opts, index=opts.index(cur))
        if sel == "（不筛选）":
            w["filter_col"], w["filter_values"] = None, []
        else:
            w["filter_col"] = sel
            vals = distinct_values(conn, w["a_tables"][0], sel)
            saved = [v for v in w["filter_values"] if v in vals]
            w["filter_values"] = st.multiselect(f"只显示「{sel}」为这些值的行", vals, default=saved)
    elif step == "确认执行":
        _render_confirm(w, conn)


def _render_confirm(w: dict, conn):
    st.markdown("**即将做的事（人话版）**")
    plans, errors = [], []
    for t in w["a_tables"]:
        try:
            spec = build_spec(w, t)
            validate(conn, spec)
            plans.append((t, spec))
        except Exception as e:  # noqa: BLE001
            errors.append(f"「{t}」：{humanize(e)}")
    for t, spec in plans:
        st.markdown(f"- {_summary_line(w, t, spec)}")
    if w.get("filter_col") and w.get("filter_values"):
        st.markdown(f"- 只显示「{w['filter_col']}」在这些值里的行（不影响计算）")
    st.markdown("- 执行前每张表自动备份，随时可恢复")
    for e in errors:
        st.error(e)
    if errors:
        return
    for t, spec in plans:
        try:
            d = dry_run(conn, spec)
            st.caption(f"「{t}」：将更新 {d['changed']} 行；垃圾行跳过 {d['guard_skipped']} 行")
        except Exception as e:  # noqa: BLE001
            logging.exception("dry_run failed")
            st.error(f"「{t}」：{humanize(e)}")
            return
    if st.button("确认执行", type="primary", key="do_execute"):
        _execute(w, conn, plans)


def _execute(w: dict, conn, plans):
    backed = set()
    results = []
    new_baks = []
    try:
        for t, spec in plans:
            name = backup_name(t) if t not in backed else None
            st_wb = writeback(conn, spec, backup_name=name)
            if name:
                backed.add(t)
                new_baks.append(name)
            df_sql = f"SELECT * FROM {qi(t)}"
            params = []
            if w.get("filter_col") and w.get("filter_values"):
                df_sql += f" WHERE {qi(w['filter_col'])} IN ({','.join(['%s'] * len(w['filter_values']))})"
                params = w["filter_values"]
            oc = order_clause(ordered_columns(conn, t))
            if oc:  # 全量展示按代码排序
                df_sql += f" ORDER BY {oc}"
            df = read_df(conn, df_sql, params or None)
            dist = dict(st_wb["distribution"])
            if spec["kind"] == "count":
                zero = dist.get("0", 0)
            elif spec["kind"] == "exists":
                zero = dist.get("否", 0)
            else:
                zero = dist.get(None, 0)
            multihit = vlookup_multihit(conn, spec) if spec["kind"] == "vlookup" else 0
            results.append({
                "table": t, "target": spec["target_col"], "kind": spec["kind"],
                "changed": st_wb["changed"], "backup": st_wb.get("backup"),
                "guard_skipped": st_wb.get("guard_skipped", 0),
                "zero": zero, "total": sum(dist.values()),
                "rows": len(df), "multihit": multihit, "df": df,
            })
    except Exception as e:  # noqa: BLE001
        logging.exception("writeback failed")
        st.error(humanize(e))
        st.caption("已整体回滚，你的表没有被改动。")
        return
    _save_cfg(w)
    if new_baks:
        cfg = store.load()
        cfg["last_backups"] = (new_baks + cfg.get("last_backups", []))[:20]
        store.save(cfg)
    st.session_state.results = results
    st.success(f"完成：{len(results)} 张表已写入。右侧查看结果。")


def render(conn):
    w = st.session_state.wiz
    steps = STEPS[w["kind"]]
    c0, _ = st.columns([4, 1])
    with c0:
        st.subheader(f"{TITLE[w['kind']]} · 第 {w['step'] + 1}/{len(steps)} 步：{steps[w['step']]}")
    _step_body(w, conn)
    err = _validate_step(w)
    if err:
        st.warning(err)
    cols = st.columns(2)
    with cols[0]:
        if w["step"] > 0 and st.button("← 上一步"):
            w["step"] -= 1
            st.rerun()
    with cols[1]:
        if steps[w["step"]] != "确认执行":
            if st.button("下一步 →", disabled=bool(err)):
                w["step"] += 1
                st.rerun()
        elif st.button("← 重新配置"):
            w["step"] = max(0, len(steps) - 2)
            st.rerun()
