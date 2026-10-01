"""写回执行：校验 → 目标列就位 → 备份 → UPDATE（单事务，失败全回滚）。"""
from datetime import datetime

from .db import columns, qi, qstr, table_exists
from .match import (count_subquery, exists_subquery, guard_pred, pair_pred,
                    vlookup_subquery)


class SpecError(Exception):
    """带错误码的异常，UI 侧映射成人话（PRD §六）。"""

    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(f"{code}: {detail}")
        self.detail = detail


def validate(conn, spec) -> dict:
    """校验表/列存在，返回列类型信息。"""
    if not spec.get("pairs"):
        raise SpecError("no_pairs", "未勾选对应字段")
    if not table_exists(conn, spec["a_table"]):
        raise SpecError("table_missing", spec["a_table"])
    if not table_exists(conn, spec["src_table"]):
        raise SpecError("table_missing", spec["src_table"])
    a_cols = columns(conn, spec["a_table"])
    s_cols = columns(conn, spec["src_table"])
    for a_col, s_col in spec["pairs"]:
        if a_col not in a_cols:
            raise SpecError("col_missing", f"{spec['a_table']}.{a_col}")
        if s_col not in s_cols:
            raise SpecError("col_missing", f"{spec['src_table']}.{s_col}")
    if spec.get("status_col") and spec["status_col"] not in s_cols:
        raise SpecError("col_missing", f"{spec['src_table']}.{spec['status_col']}")
    if spec["kind"] == "vlookup":
        if spec.get("fill_col") not in s_cols:
            raise SpecError("col_missing", f"{spec['src_table']}.{spec.get('fill_col')}")
    return {"a_cols": a_cols, "s_cols": s_cols}


def target_sql_type(spec, s_cols: dict) -> str:
    """PRD §四：判断→text；计数→integer；vlookup→跟随源列。"""
    if spec["kind"] == "count":
        return "integer"
    if spec["kind"] == "exists":
        return "text"
    return s_cols[spec["fill_col"]]


def computed_expr(spec) -> str:
    if spec["kind"] == "count":
        return count_subquery(spec)
    if spec["kind"] == "exists":
        return f"CASE WHEN {exists_subquery(spec)} THEN '是' ELSE '否' END"
    if spec["kind"] == "vlookup":
        expr = vlookup_subquery(spec)
        if spec.get("default") not in (None, ""):
            expr = f"COALESCE({expr},{qstr(spec['default'])})"
        return expr
    raise SpecError("bad_kind", str(spec.get("kind")))


def _ensure_target(cur, a_table, target_col, sql_type, cols):
    if target_col not in cols:
        cur.execute(f"ALTER TABLE {qi(a_table)} ADD COLUMN {qi(target_col)} {sql_type}")
    elif cols[target_col] != sql_type:
        cur.execute(
            f"ALTER TABLE {qi(a_table)} ALTER COLUMN {qi(target_col)} TYPE {sql_type} "
            f"USING {qi(target_col)}::{sql_type}"
        )


def dry_run(conn, spec) -> dict:
    """只读预演：算出将变化/将清空的行数，不碰数据库。"""
    info = validate(conn, spec)
    a, expr = spec["a_table"], computed_expr(spec)
    guard = guard_pred(spec["pairs"])
    tgt = qi(spec["target_col"])
    cur = conn.cursor()
    if spec["target_col"] in info["a_cols"]:
        cur.execute(
            f"SELECT count(*) FROM {qi(a)} a WHERE {guard} "
            f"AND ({tgt}::text IS DISTINCT FROM ({expr})::text)"
        )
        changed = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {qi(a)} a WHERE NOT ({guard}) AND {tgt} IS NOT NULL")
        cleared = cur.fetchone()[0]
    else:
        cur.execute(f"SELECT count(*) FROM {qi(a)} a WHERE {guard}")
        changed = cur.fetchone()[0]
        cleared = 0
    cur.execute(f"SELECT count(*) FROM {qi(a)} a WHERE NOT ({guard})")
    skipped = cur.fetchone()[0]
    conn.rollback()  # dry_run 绝不留下未提交事务
    return {"changed": changed, "cleared": cleared, "guard_skipped": skipped}


def _update_sql(spec) -> tuple:
    """(先执行的清空语句, 后执行的写入语句)。writeback 与确认页展示共用同一来源，零漂移。"""
    guard = guard_pred(spec["pairs"])
    tgt = qi(spec["target_col"])
    clear = (
        f"UPDATE {qi(spec['a_table'])} a SET {tgt} = NULL "
        f"WHERE NOT ({guard}) AND {tgt} IS NOT NULL"
    )
    main = (
        f"UPDATE {qi(spec['a_table'])} a SET {tgt} = {computed_expr(spec)} "
        f"WHERE {guard}"
    )
    return clear, main


def explain_sql(spec) -> list:
    """确认执行页展示用：writeback 真正会跑的两条 UPDATE。只读，不碰库。"""
    return list(_update_sql(spec))


def sample_sql(spec, n=10) -> str:
    """抽样核对（只读）：匹配键 →（vlookup）对侧命中行与带出值 → 库里现值，随机 n 行。"""
    guard = guard_pred(spec["pairs"])
    sel = [f"a.{qi(c)} AS {qi(c)}" for c, _ in spec["pairs"]]
    join = ""
    if spec["kind"] == "vlookup":
        pred = pair_pred(spec["pairs"], "a", "m",
                         spec.get("normalize", True), spec.get("strip_digits", False),
                         spec.get("match_mode", "exact"))
        sel += [f"m.{qi(s)} AS {qi(s + '（对照表）')}" for _, s in spec["pairs"]]
        sel.append(f"m.{qi(spec['fill_col'])} AS {qi('对侧带出值')}")
        join = f" LEFT JOIN {qi(spec['src_table'])} m ON {pred}"
    sel.append(f"a.{qi(spec['target_col'])} AS {qi('库里现值')}")
    return (f"SELECT {', '.join(sel)} FROM {qi(spec['a_table'])} a{join} "
            f"WHERE {guard} ORDER BY random() LIMIT {n}")


def writeback(conn, spec, backup_name=None) -> dict:
    """单事务写回（PRD §五）。with conn: 异常自动 ROLLBACK，原表零改动。"""
    stats = dry_run(conn, spec)
    with conn:
        info = validate(conn, spec)
        cur = conn.cursor()
        sql_type = target_sql_type(spec, info["s_cols"])
        _ensure_target(cur, spec["a_table"], spec["target_col"], sql_type, info["a_cols"])
        if backup_name:
            try:
                cur.execute(f"CREATE TABLE {qi(backup_name)} AS TABLE {qi(spec['a_table'])}")
            except Exception as e:  # noqa: BLE001
                raise SpecError("backup_failed", str(e)) from e
            stats["backup"] = backup_name
        # 守卫行（垃圾总计行）的目标列置 NULL，不写入任何计算值（PRD §二）
        clear_sql, main_sql = _update_sql(spec)
        cur.execute(clear_sql)
        cur.execute(main_sql)
        if cur.rowcount == 0:
            raise SpecError("update_zero", spec["a_table"])
        guard = guard_pred(spec["pairs"])
        cur.execute(
            f"SELECT {qi(spec['target_col'])}::text, count(*) FROM {qi(spec['a_table'])} a "
            f"WHERE {guard} GROUP BY 1 ORDER BY 2 DESC"
        )
        stats["distribution"] = cur.fetchall()
        cur.execute(
            f"SELECT count(*) FROM {qi(spec['a_table'])} a WHERE NOT ({guard}) "
            f"AND {qi(spec['target_col'])} IS NOT NULL"
        )
        stats["guard_violations"] = cur.fetchone()[0]
    return stats


def verify_match(conn, spec) -> dict:
    """只读复现校验：现有列值 vs 引擎计算值，仅统计守卫行。"""
    info = validate(conn, spec)
    a = spec["a_table"]
    guard = guard_pred(spec["pairs"])
    cur = conn.cursor()
    if spec["target_col"] in info["a_cols"]:
        cur.execute(
            f"SELECT a.{qi(spec['target_col'])}, {computed_expr(spec)} FROM {qi(a)} a WHERE {guard}"
        )
        rows = cur.fetchall()
    else:
        rows = []
    match = sum(1 for c, e in rows if c == e)
    conn.rollback()
    return {"total": len(rows), "match": match, "mismatch": len(rows) - match}


def backup_name(table: str) -> str:
    return f"{table}_bak_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


KEEP_BACKUPS = 5  # 每张源表最多保留的备份数：防备份表无限堆积撑爆库（表都是千行级，5份足够回滚）


def prune_backups(conn, keep=KEEP_BACKUPS) -> list:
    """每张源表只留最近 keep 份备份，多余的 DROP。返回被清理的表名。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name LIKE '%\\_bak\\_%'"
    )
    by_src = {}
    for (name,) in cur.fetchall():
        by_src.setdefault(name.split("_bak_", 1)[0], []).append(name)
    dropped = []
    for names in by_src.values():
        names.sort()  # 备份名内嵌时间戳 → 字典序 = 时间序
        for old in (names[:-keep] if keep > 0 else names):
            cur.execute(f"DROP TABLE {qi(old)}")
            dropped.append(old)
    if dropped:
        conn.commit()
    return dropped


def vlookup_multihit(conn, spec) -> int:
    """vlookup 黄条：对照表命中>1 的主表行数（只读）。"""
    from .match import vlookup_multihit_sql

    cur = conn.cursor()
    cur.execute(vlookup_multihit_sql(spec))
    n = cur.fetchone()[0]
    conn.rollback()
    return n
