"""固定计算的预填配置 = 通用引擎的特例（PRD §八决策18）。
口径已由只读复现验证：硕士.推免已招 500/500、直博.推免总数 200/200。
"""

# 计数键配对（A 列, 对照表列），顺序 = 用户勾选顺序
_COUNT_PAIRS = [
    ("学位类型", "录取类型"),
    ("专业码", "录取专业代码"),
    ("研究方向", "录取研究方向（2027年目录方向）"),
    ("指导教师", "导师姓名"),
]
# 判断键配对：B 表研究方向列名带长后缀
_EXISTS_PAIRS = [
    ("学位类型", "学位类型"),
    ("专业码", "专业码"),
    ("研究方向", "研究方向（文字应尽量精简，不超过20个字）"),
    ("指导教师", "指导教师"),
]

SHUOSHI_COUNT = {
    "kind": "count",
    "label": "数出硕士每个条目正式录取了几个人",
    "a_table": "硕士",
    "src_table": "总0924",
    "pairs": _COUNT_PAIRS,
    "status_col": "是否录取",
    "status_values": ["录取", "专项录取"],
    "target_col": "推免已招",
}

ZHIBO_COUNT = {
    "kind": "count",
    "label": "数出直博每个条目正式录取了几个人",
    "a_table": "直博",
    "src_table": "总0924",
    "pairs": _COUNT_PAIRS,
    "status_col": "是否录取",
    "status_values": ["录取", "专项录取"],
    "target_col": "推免总数",
}

SHUOSHI_EXISTS = {
    "kind": "exists",
    "label": "判断硕士条目在不在推免目录里",
    "a_table": "硕士",
    "src_table": "二轮推免开放目录",
    "pairs": _EXISTS_PAIRS,
    "target_col": "推免目录开放情况",
}

ZHIBO_EXISTS = {
    "kind": "exists",
    "label": "判断直博条目在不在推免目录里",
    "a_table": "直博",
    "src_table": "二轮推免开放目录",
    "pairs": _EXISTS_PAIRS,
    "target_col": "目录开放情况",
}

FIXED = [SHUOSHI_COUNT, ZHIBO_COUNT, SHUOSHI_EXISTS, ZHIBO_EXISTS]
