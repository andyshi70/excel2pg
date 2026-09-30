"""执行四个固定计算的写回（每表一次备份，单事务）。

用法：
  python -m engine.apply --dry    # 只预演，不写
  python -m engine.apply          # 真实写回
"""
import sys

from . import specs as S
from .db import connect, qi
from .ops import backup_name, dry_run, verify_match, writeback


def main(argv) -> int:
    dry = "--dry" in argv
    backed_up = set()
    with connect() as conn:
        if dry:
            print("== 预演（不写库）==")
            for spec in S.FIXED:
                d = dry_run(conn, spec)
                print(f"  {spec['a_table']}.{spec['target_col']}: "
                      f"将更新 {d['changed']} 行，守卫行清空 {d['cleared']} 行，"
                      f"跳过守卫行 {d['guard_skipped']} 行")
            return 0

        for spec in S.FIXED:
            name = None
            if spec["a_table"] not in backed_up:
                name = backup_name(spec["a_table"])
                backed_up.add(spec["a_table"])
            st = writeback(conn, spec, backup_name=name)
            print(f"== {spec['a_table']}.{spec['target_col']} 写回完成 ==")
            print(f"  变化 {st['changed']} 行；守卫行清空 {st['cleared']} 行；"
                  f"备份 {st.get('backup', '(同表已备过)')}；"
                  f"守卫行残留非空 {st['guard_violations']}（必须为 0）")
            top = st["distribution"][:6]
            print(f"  分布(前6): {top}")

        print("== 写回后复检（计数列应仍 500/500、200/200）==")
        ok = True
        for spec in (S.SHUOSHI_COUNT, S.ZHIBO_COUNT):
            r = verify_match(conn, spec)
            ok &= r["mismatch"] == 0
            print(f"  {'PASS' if r['mismatch'] == 0 else 'FAIL'} "
                  f"{spec['a_table']}.{spec['target_col']}: {r['match']}/{r['total']}")

        cur = conn.cursor()
        cur.execute(
            f'SELECT {qi("推免已招")}, {qi("推免目录开放情况")} FROM {qi("硕士")} '
            f'WHERE {qi("学位类型")} IS NULL'
        )
        row = cur.fetchone()
        conn.rollback()
        print(f"== 垃圾总计行（应为 (None, None)）: {row} ==")
        ok &= row == (None, None)
        print("== 结论:", "全部通过" if ok else "有失败项", "==")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
