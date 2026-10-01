"""只读复现校验（PRD §七阶段1验收）。不修改任何数据。

用法： python -m engine.verify
退出码 0 = 两条硬验收（500/500、200/200）全部通过。
"""
import sys

from . import specs as S
from .db import connect, qi
from .ops import computed_expr, guard_pred, validate, verify_match


def exists_dist(conn, spec):
    """计算③分布（无历史真值，只给是/否统计）。"""
    cur = conn.cursor()
    cur.execute(
        f"SELECT {computed_expr(spec)}, count(*) FROM {qi(spec['a_table'])} a "
        f"WHERE {guard_pred(spec['pairs'])} GROUP BY 1 ORDER BY 2 DESC"
    )
    dist = cur.fetchall()
    conn.rollback()
    return dist


def main() -> int:
    ok = True
    with connect() as conn:
        print("== 1. 计数口径复现（硬验收：与你 Excel 时代现值逐行一致）==")
        for spec in (S.SHUOSHI_COUNT, S.ZHIBO_COUNT):
            r = verify_match(conn, spec)
            status = "PASS" if r["mismatch"] == 0 else "FAIL"
            ok &= r["mismatch"] == 0
            print(f"  [{status}] {spec['a_table']}.{spec['target_col']}: "
                  f"{r['match']}/{r['total']} 一致，差 {r['mismatch']} 行")

        print("== 2. 反证：去掉状态过滤后只能部分复现（证明过滤条件必要）==")
        for spec in (S.SHUOSHI_COUNT, S.ZHIBO_COUNT):
            nofilter = dict(spec)
            nofilter["status_col"] = None
            nofilter["status_values"] = None
            r = verify_match(conn, nofilter)
            print(f"  [info] {spec['a_table']} 不过滤是否录取: "
                  f"{r['match']}/{r['total']} 一致（应显著低于全数）")

        print("== 3. 归一化收益（计算③ 是/否分布）==")
        for spec in (S.SHUOSHI_EXISTS, S.ZHIBO_EXISTS):
            on = exists_dist(conn, dict(spec, normalize=True))
            off = exists_dist(conn, dict(spec, normalize=False))
            hit_on = sum(n for v, n in on if v == "是")
            hit_off = sum(n for v, n in off if v == "是")
            print(f"  [info] {spec['a_table']}.{spec['target_col']}: 归一化开 → 是={hit_on} 否={sum(n for v, n in on if v == '否')}；"
                  f"关 → 是={hit_off}（开比关多 {hit_on - hit_off} 行命中）")
    print("== 结论:", "全部通过" if ok else "有失败项", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
