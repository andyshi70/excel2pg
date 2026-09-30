"""写回安全性自检（真库，故意失败 → 必须完整回滚）。运行： python tests/test_safety.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import specs as S
from engine.db import connect, list_tables, qi
from engine.ops import SpecError, validate, writeback
from ui.errors import humanize

with connect() as conn:
    def snap():
        cur = conn.cursor()
        cur.execute(f"SELECT count(*), sum({qi('推免已招')})::int, "
                    f"count({qi('推免目录开放情况')}) FROM {qi('硕士')}")
        row = cur.fetchone()
        tables = set(list_tables(conn))
        conn.rollback()
        return row, tables

    before, tables_before = snap()

    # 1) 非法目标列名 → ALTER 必失败 → 事务回滚，备份表也不能留下
    bad = dict(S.SHUOSHI_EXISTS, target_col="")
    try:
        writeback(conn, bad, backup_name="硕士_bak_should_not_exist")
        raise AssertionError("应当抛异常")
    except Exception as e:  # noqa: BLE001
        print(f"[OK] 失败写回抛出: {type(e).__name__}")

    after, tables_after = snap()
    assert after == before, (before, after)
    assert tables_after == tables_before, "回滚后不应留下备份表"
    print(f"[OK] 原表零变化: {after}；无残留备份表")

    # 2) 校验阶段拦截：列不存在 → SpecError + 可翻译的人话
    try:
        validate(conn, dict(S.SHUOSHI_COUNT, pairs=[("不存在的列", "录取类型")]))
        raise AssertionError("应当抛 SpecError")
    except SpecError as e:
        msg = humanize(e)
        assert e.code == "col_missing" and "没找到" in msg, msg
        print(f"[OK] 人话报错: {msg}")

    # 3) 空配对拦截
    try:
        validate(conn, dict(S.SHUOSHI_COUNT, pairs=[]))
        raise AssertionError("应当抛 SpecError")
    except SpecError as e:
        assert e.code == "no_pairs"
        print(f"[OK] 空配对拦截: {humanize(e)}")

print("test_safety: ALL PASS")
