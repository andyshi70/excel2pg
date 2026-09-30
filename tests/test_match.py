"""匹配内核断言自检（无 DB）。运行： python tests/test_match.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.db import qi, qstr
from engine.match import (
    count_subquery,
    exists_subquery,
    guard_pred,
    in_filter,
    norm,
    norm_loose,
    pair_pred,
    vlookup_subquery,
)
from engine.ops import computed_expr

# --- 标识符转义
assert qi('研究方向（x）') == '"研究方向（x）"'
assert qi('含"引号') == '"含""引号"'
assert qstr("录取") == "'录取'"
assert qstr("it's") == "'it''s'"

# --- 归一化表达式：btrim + 双向括号替换
assert norm('a."研究方向"') == (
    "replace(replace(btrim(a.\"研究方向\"),'（','('),'）',')')"
)

# --- 配对谓词：顺序即勾选顺序，全字段 AND 等值
pairs = [("学位类型", "录取类型"), ("专业码", "录取专业代码")]
p = pair_pred(pairs, "a", "c")
assert p.count(" AND ") == 1
assert 'norm' not in p and "btrim" in p
assert 'a."学位类型"' in p and 'c."录取类型"' in p
assert 'a."专业码"' in p and 'c."录取专业代码"' in p
# 不归一化变体
assert "btrim" not in pair_pred(pairs, "a", "c", normalize=False)

# --- 空配对必须报错
try:
    pair_pred([])
    raise AssertionError("empty pairs should raise")
except ValueError:
    pass

# --- 守卫 = 第一配对列 IS NOT NULL
assert guard_pred(pairs) == 'a."学位类型" IS NOT NULL'

# --- 模糊匹配三档谓词形态
assert norm_loose('a."x"').startswith("lower(") and "translate(" in norm_loose('a."x"')
pl = pair_pred(pairs, "a", "c", mode="loose")
assert "lower(" in pl and "translate(" in pl and pl.count(" AND ") == 1  # 宽松=仍是等值，1 个连接符
pco = pair_pred(pairs, "a", "c", mode="contains")
assert pco.count("LIKE") == 4 and pco.count("length(") == 4  # 2 对 × (2 长度守卫 + 2 方向)
assert "btrim" in pair_pred(pairs, "a", "c")  # 精确默认不变
try:
    pair_pred(pairs, mode="fuzzy")
    raise AssertionError("unknown mode should raise")
except ValueError:
    pass

# --- 状态过滤：IN + 值转义
f = in_filter('c."是否录取"', ["录取", "专项录取"])
assert f == 'c."是否录取" IN (\'录取\',\'专项录取\')'
assert in_filter("x", ["a'b"]) == "x IN ('a''b')"

# --- 三类子查询形态
cspec = {"kind": "count", "a_table": "硕士", "src_table": "总0924",
         "pairs": pairs, "status_col": "是否录取", "status_values": ["录取"]}
cs = count_subquery(cspec)
assert cs.startswith('(SELECT count(*) FROM "总0924" c WHERE ')
assert 'c."是否录取" IN (\'录取\')' in cs
assert cs.count(" AND ") >= 2  # 2 对键 + 1 过滤

espec = {"kind": "exists", "a_table": "硕士", "src_table": "二轮推免开放目录", "pairs": pairs}
es = exists_subquery(espec)
assert es.startswith('EXISTS (SELECT 1 FROM "二轮推免开放目录" b WHERE ')
assert "btrim" in es

vspec = {"kind": "vlookup", "a_table": "硕士", "src_table": "总0924",
         "pairs": pairs, "fill_col": "分组"}
vs = vlookup_subquery(vspec)
assert vs.startswith('(SELECT v."分组" FROM "总0924" v WHERE ')
assert vs.endswith("LIMIT 1)")

# --- computed_expr 三形态 + 默认值 COALESCE
assert computed_expr(cspec).startswith("(SELECT count(*)")
assert computed_expr(espec).startswith("CASE WHEN EXISTS (")
assert computed_expr(vspec) == vs
assert "COALESCE" in computed_expr(dict(vspec, default="无"))

print("test_match: ALL PASS")
