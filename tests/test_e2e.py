"""向导端到端（AppTest 模拟点击，真库幂等写回）。运行： python tests/test_e2e.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from streamlit.testing.v1 import AppTest

at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
at.run()
assert not at.exception, at.exception


def btn(label):
    for b in at.button:
        if b.label == label:
            return b
    raise AssertionError(f"按钮没找到: {label}  现有: {[b.label for b in at.button]}")


def ms(label):
    for m in at.multiselect:
        if m.label == label:
            return m
    raise AssertionError(f"多选没找到: {label}  现有: {[m.label for m in at.multiselect]}")


def sb(label):
    for s in at.selectbox:
        if s.label == label:
            return s
    raise AssertionError(f"下拉没找到: {label}  现有: {[s.label for s in at.selectbox]}")


def tick(prefix, cols):
    """勾选字段（顺序=勾选顺序）；已勾的跳过（保留原顺序）。"""
    for c in cols:
        k = f"{prefix}::{c}"
        box = next((x for x in at.checkbox if x.key == k), None)
        assert box is not None, f"勾选框没找到: {k}  现有: {[x.key for x in at.checkbox]}"
        if not box.value:
            box.set_value(True).run()
            assert not at.exception, at.exception


# ---- 勾选顺序 = 配对顺序（独立新会话，不污染主流程）
at2 = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
at2.run()
assert not at2.exception, at2.exception
for lbl in ("📋 Vlookup", "下一步 →", "下一步 →"):
    next(b for b in at2.button if b.label == lbl).click().run()
assert not at2.exception, at2.exception
_left_t = ["学位类型", "专业码", "研究方向", "指导教师"]
_right_t = ["指导教师", "研究方向（文字应尽量精简，不超过20个字）", "专业码", "学位类型"]
for side, cols in (("pcol_a", _left_t), ("pcol_b", _right_t)):
    for c in cols:
        k = f"{side}::{c}"
        box = next(x for x in at2.checkbox if x.key == k)
        box.set_value(True).run()
assert not at2.exception, at2.exception
_info = [i.value for i in at2.info if "配对关系" in i.value]
_expect = "\n\n".join(f"{i+1}. {a} ↔ {b}" for i, (a, b) in enumerate(zip(_left_t, _right_t)))
assert _info and _expect in _info[0], f"配对没按勾选顺序:\n实际={_info}\n期望={_expect}"
print("[OK] 勾选顺序=配对顺序（右侧倒序勾也按点的顺序配对）")
del at2


# ---- 首页：四张卡片都在
labels = [b.label for b in at.button]
for need in ("🔍 查数据", "📋 Vlookup", "✅ 判断在不在", "🔢 数出现次数"):
    assert need in labels, f"缺少卡片 {need}: {labels}"
print("[OK] 首页四张卡片齐全")

# ---- AC4b 回归：用户可见文案不出现禁词
ui_text = "\n".join(m.value for m in at.markdown) + "\n" + "\n".join(c.value for c in at.caption)
for banned in ("SQL", "JOIN", "主键", "公式"):
    assert banned not in ui_text, f"禁词 {banned} 出现在界面: {ui_text[:300]}"
print("[OK] 首屏无 SQL/JOIN/主键/公式 禁词")

# ---- 备份表不出现在左栏表列表
sidebar_sel = next(s for s in at.selectbox if s.label == "点一张表看看")
assert not any("_bak_" in o for o in sidebar_sel.options), sidebar_sel.options
print(f"[OK] 左栏表列表已隐藏备份表（可见 {len(sidebar_sel.options)} 张）")

# ---- 导入按钮：存在；目录为空时点击给引导（不触发真导入）
assert "📥 导入 Excel 数据" in [b.label for b in at.button], [b.label for b in at.button]
from pathlib import Path  # noqa: E402

if not list(Path("/Users/evandy/excel2pg/src/excel").glob("*.xls*")):
    btn("📥 导入 Excel 数据").click().run()
    assert not at.exception, at.exception
    assert any("目录里还没有 Excel" in w.value for w in at.warning), [w.value for w in at.warning]
    print("[OK] 导入按钮：空目录点击 → 人话引导")
else:
    print("[OK] 导入按钮存在（目录有 Excel，跳过点击避免测试触发真导入）")

# ---- 记录「开放情况」两列的初始状态（规则：默认放空，只有判断卡片会碰它）
from engine.db import connect, qi  # noqa: E402

# 重置向导预填，隔离用户手工配置（结束时本测试会把预填写成两表齐的默认态）
import json  # noqa: E402

cfg_path = os.path.join(ROOT, ".ui_config.json")
if os.path.exists(cfg_path):
    _cfg = json.load(open(cfg_path, encoding="utf-8"))
    for _k in ("exists", "count", "vlookup"):
        _cfg.pop(_k, None)
    json.dump(_cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def open_state():
    with connect() as c:
        cur = c.cursor()
        cur.execute(f'SELECT count({qi("推免目录开放情况")}) FROM {qi("硕士")}')
        a = cur.fetchone()[0]
        cur.execute(f'SELECT count({qi("目录开放情况")}) FROM {qi("直博")}')
        b = cur.fetchone()[0]
        c.rollback()
        return a, b


ORIG_OPEN = open_state()
print(f"[OK] 开放情况初始状态: 硕士={ORIG_OPEN[0]} 直博={ORIG_OPEN[1]}")


def assert_code_sorted(df, table, label):
    """全量展示规则：按代码列升序、空值在后（与界面 ORDER BY 同口径）。"""
    from ui.helpers import code_order, ordered_columns
    with connect() as c:
        keys = code_order(ordered_columns(c, table))
    got = df[keys].reset_index(drop=True)
    want = df.sort_values(keys, kind="stable", na_position="last").reset_index(drop=True)[keys]
    assert got.equals(want), f"{label} 未按代码排序，键={keys}"

# ---- 走「判断在不在」向导
btn("✅ 判断在不在").click().run()
assert not at.exception, at.exception
assert any("第 1/6 步：选主表" in s.value for s in at.subheader), [s.value for s in at.subheader]
assert ms("主表").value == ["硕士", "直博"], ms("主表").value
print("[OK] 步1 主表预填 硕士+直博")

btn("下一步 →").click().run()
assert not at.exception, at.exception
assert sb("对照表").value == "二轮推免开放目录", sb("对照表").value
print("[OK] 步2 对照表预填 二轮推免开放目录")

btn("下一步 →").click().run()
assert not at.exception, at.exception
tick("pcol_a", ["学位类型", "专业码", "研究方向", "指导教师"])
tick("pcol_b", ["学位类型", "专业码", "研究方向（文字应尽量精简，不超过20个字）", "指导教师"])
assert not at.exception, at.exception
assert any("4. 指导教师 ↔ 指导教师" in m.value for m in at.info), [m.value for m in at.info]
print("[OK] 步3 字段配对（4对，含长列名）")

btn("下一步 →").click().run()
assert not at.exception, at.exception
sb("「硕士」表：结果写到哪一列？").set_value("推免目录开放情况")
sb("「直博」表：结果写到哪一列？").set_value("目录开放情况").run()
print("[OK] 步4 目标列预填")

btn("下一步 →").click().run()
assert not at.exception, at.exception
print("[OK] 步5 可选筛选（默认跳过）")

btn("下一步 →").click().run()
assert not at.exception, at.exception
text = "\n".join(m.value for m in at.markdown)
assert "即将做的事" in text and "判断" in text and "自动备份" in text, text[:500]
assert "将更新" in "\n".join(c.value for c in at.caption), "缺少 dry_run 预演数字"
print("[OK] 步6 人话确认页 + dry_run 预演")

btn("确认执行").click().run()
assert not at.exception, at.exception
res = at.session_state["results"]
assert res and len(res) == 2, res
assert {r["table"] for r in res} == {"硕士", "直博"}
assert res[0]["df"] is not None and len(res[0]["df"]) > 0
assert not any("回滚" in e.value for e in at.error), [e.value for e in at.error]
print(f"[OK] 执行成功: {[(r['table'], r['target'], r['changed'], r['rows']) for r in res]}")
assert any("完成" in s.value for s in at.success), [s.value for s in at.success]

# ---- 幂等：再跑一遍，changed 应为 0（值是行的纯函数）
btn("↩ 回到首页，做下一个操作").click().run()
btn("✅ 判断在不在").click().run()
for _ in range(5):
    btn("下一步 →").click().run()
btn("确认执行").click().run()
res2 = at.session_state["results"]
assert res2, f"第二次执行无结果; errors={[e.value for e in at.error]} success={[s.value for s in at.success]} exc={at.exception}"
assert all(r["changed"] == 0 for r in res2), [(r["table"], r["changed"]) for r in res2]
print(f"[OK] 幂等重跑: changed 全 0")

# ---- 查询卡片（只读）
btn("↩ 回到首页，做下一个操作").click().run()
btn("🔍 查数据").click().run()
assert not at.exception, at.exception
sb("从哪张表查？").set_value("硕士").run()
next(b for b in at.button if b.key == "run_query").click().run()
assert not at.exception, at.exception
qr = at.session_state.get("q_result")
assert qr and qr["total"] == 501, qr
print(f"[OK] 单表查询: total={qr['total']}")
assert_code_sorted(qr["df"], "硕士", "单表查询结果")
print("[OK] 查询结果按代码排序")

# ---- 连表查询 + 条件（真库 SQL，只读）
cb = next(x for x in at.checkbox if x.label == "再连一张表一起查")
cb.set_value(True).run()
assert not at.exception, at.exception
sb("连哪张表？").set_value("总0924").run()
assert not at.exception, at.exception
ms("左边：硕士 的字段（按顺序对应）").set_value(["学位类型", "专业码", "研究方向", "指导教师"])
ms("右边：总0924 的字段（按顺序对应左边）").set_value(
    ["录取类型", "录取专业代码", "录取研究方向（2027年目录方向）", "导师姓名"]
).run()
assert not at.exception, at.exception
next(b for b in at.button if b.label == "+ 加一个条件").click().run()
assert not at.exception, at.exception
next(s for s in at.selectbox if s.label == "字段").set_value("硕士.医院")
next(t for t in at.text_input if t.key == "cval0").set_value("华山医院").run()
assert not at.exception, at.exception
next(b for b in at.button if b.key == "run_query").click().run()
assert not at.exception, at.exception
qr2 = at.session_state.get("q_result")
assert qr2 and qr2["total"] == 134, qr2  # 与 tests/test_query.py 手工 SQL 一致
print(f"[OK] 连表+条件查询: total={qr2['total']}（=手写 SQL 基准 134）")

# ---- 「数出现次数」向导（7 步，幂等执行）
btn("← 回到首页").click().run()
btn("🔢 数出现次数").click().run()
assert any("第 1/7 步" in s.value for s in at.subheader), [s.value for s in at.subheader]
for _ in range(2):  # 主表 → 对照表 → 配对
    btn("下一步 →").click().run()
tick("pcol_a", ["学位类型", "专业码", "研究方向", "指导教师"])
tick("pcol_b", ["录取类型", "录取专业代码", "录取研究方向（2027年目录方向）", "导师姓名"])
btn("下一步 →").click().run()  # 统计范围（默认 录取+专项录取）
assert not at.exception, at.exception
sv = next(m for m in at.multiselect if m.label.startswith("只数哪些状态"))
assert sv.value == ["录取", "专项录取"], sv.value
btn("下一步 →").click().run()  # 写到哪一列
btn("下一步 →").click().run()  # 可选筛选
btn("下一步 →").click().run()  # 确认
assert "数每个" in "\n".join(m.value for m in at.markdown), [m.value for m in at.markdown]
pre_open = open_state()
btn("确认执行").click().run()
assert not at.exception, at.exception
assert open_state() == pre_open, f"数出现次数改动了开放情况列: {pre_open} -> {open_state()}"
print(f"[OK] 数出现次数未碰开放情况列（保持 {pre_open}）")
rc = at.session_state["results"]
assert len(rc) == 2 and all(r["kind"] == "count" for r in rc), rc
assert all(r["changed"] == 0 for r in rc), [(r["table"], r["changed"]) for r in rc]  # 阶段1已写入，幂等
print(f"[OK] 计数向导执行（幂等）: {[(r['table'], r['target'], r['zero']) for r in rc]}")
assert any(r["zero"] > 0 for r in rc), "0命中统计缺失"
print(f"[OK] 0命中统计: {[(r['table'], r['zero']) for r in rc]}")
assert_code_sorted(rc[0]["df"], rc[0]["table"], "计算结果")
print("[OK] 计算结果全量展示按代码排序")

# ---- 「Vlookup」vlookup（新建列 + 执行 + 清理痕迹）
btn("↩ 回到首页，做下一个操作").click().run()
btn("📋 Vlookup").click().run()
btn("下一步 →").click().run()
btn("下一步 →").click().run()  # 对照表默认 二轮推免开放目录
tick("pcol_a", ["学位类型", "专业码", "研究方向", "指导教师"])
tick("pcol_b", ["学位类型", "专业码", "研究方向（文字应尽量精简，不超过20个字）", "指导教师"])
assert not at.exception, at.exception
# 匹配方式：默认精确，页面可切模糊（本次用宽松跑全流程）
_mbox = sb("怎么算「对上了」？（匹配方式）")
assert _mbox.value == "exact", _mbox.value
_mbox.set_value("loose").run()
assert not at.exception, at.exception
print("[OK] vlookup 匹配方式默认精确、可切宽松（本次按宽松跑）")
btn("下一步 →").click().run()  # 带出哪一列
# 列序数标签（第N列 = 表内真实列顺序，Excel 序数口径）
from ui.helpers import ordered_columns  # noqa: E402

with connect() as _c:
    _src_cols = ordered_columns(_c, "二轮推免开放目录")
_fill_label = f"第{_src_cols.index('三级学科') + 1}列 · 三级学科"
sb("把「二轮推免开放目录」的哪一列带过来？（第N列 = 表里真实列序数，取值按列名）").set_value(_fill_label).run()
assert not at.exception, at.exception
print(f"[OK] vlookup 带出列可按列序数选择: {_fill_label}")
assert len(at.number_input) == 0, "「直接填列序数」输入框应已删除（取值按列名，序数只是标签）"
print("[OK] 列序数输入框已删除（下拉按 第N列·列名 选，取值按列名）")
btn("下一步 →").click().run()  # 写到哪一列 → 默认新建
next(t for t in at.text_input if "硕士」：新列" in t.label).set_value("测试带出列")
next(t for t in at.text_input if "直博」：新列" in t.label).set_value("测试带出列").run()
assert not at.exception, at.exception
btn("下一步 →").click().run()  # 筛选
btn("下一步 →").click().run()  # 确认
btn("确认执行").click().run()
assert not at.exception, at.exception
rv = at.session_state["results"]
assert len(rv) == 2 and all(r["kind"] == "vlookup" for r in rv), rv
assert all(r["target"] == "测试带出列" for r in rv), rv
print(f"[OK] vlookup 执行: {[(r['table'], r['changed'], r['rows']) for r in rv]}")

# 清理：删测试列 + vlookup 预填配置（不动用户真实列）
with connect() as c:
    cur = c.cursor()
    for t in ("硕士", "直博"):
        cur.execute(f'ALTER TABLE {qi(t)} DROP COLUMN IF EXISTS {qi("测试带出列")}')
    c.commit()
import json
cfg_path = os.path.join(ROOT, ".ui_config.json")
if os.path.exists(cfg_path):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    cfg.pop("vlookup", None)
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("[OK] 已清理 vlookup 测试列与配置")

# 清理：若测试前开放情况是空的，把判断卡片测试写入的值也还原为空（规则：默认放空）
if ORIG_OPEN == (0, 0):
    with connect() as c:
        cur = c.cursor()
        cur.execute(f'UPDATE {qi("硕士")} SET {qi("推免目录开放情况")} = NULL')
        cur.execute(f'UPDATE {qi("直博")} SET {qi("目录开放情况")} = NULL')
        c.commit()
    print(f"[OK] 开放情况列已还原为空（{open_state()}）")
else:
    print(f"[OK] 开放情况列原值非空（{ORIG_OPEN}），保留测试结果")

print("test_e2e: ALL PASS")
