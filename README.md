# YIfan 数据小工具

给不写 SQL 的同事用的 PostgreSQL 数据表工具：**点几下按钮，答案自己出来** —— 查数据、判断在不在、数出现次数、Vlookup 带值，改表前自动备份，出错整单回滚，表上一个字节都不会悄悄坏掉。

配套数据导入工具见姊妹仓库 **[excel2pg](https://github.com/andyshi70/excel2pg)**（Excel 一键进库）。

---

## 能做什么

首页四张卡片，点卡片进向导，一步一步走，最后**确认**才真正改库：

| 卡片 | 干什么 | 改库吗 |
|---|---|---|
| 🔍 **查数据** | 单表或两表关联随便查，条件随便加 | ❌ 只读 |
| ✅ **判断在不在** | 每个条目去对照表找一找：找到=是，没找到=否 | ✅ 写回目标列 |
| 🔢 **数出现次数** | 每个条目在明细表里出现几次就填几（招了几个人） | ✅ 写回目标列 |
| 📋 **Vlookup** | 对照另一张表，把某个值带过来填进新列，对不上的填默认值 | ✅ 写回新列 |

全部向导化：选表 → 选键 →（可选筛选）→ 预演数字 → 确认页看人话总结 + 真实 SQL → **确认执行** → 结果显示在正下方（抽样核对表 + Excel 下载）。

## 数据安全（改表的底线）

- **写回前自动备份**：每张被更新的表先整表复制一份（`原表名_bak_时间戳`），备份与更新在**同一事务**里 —— 失败整体回滚，不留半截
- **自动轮换**：每张源表只保留最近 **5 份**备份，旧的自动清理，不会撑爆库
- **垃圾行守卫**：总计/垃圾行的目标列强制置 NULL，不写入任何计算值
- **失败零残留**：任何一步异常 → `ROLLBACK`，原表原样；测试跑完自动删自己产生的备份
- **导入不混入**：侧栏「数据表」列表永远看不到 `_bak_` 表

## 页面布局

```
┌──────────┬─────────────────────────────────────┐
│ 侧栏      │ YIfan 数据小工具（左上角）            │
│ · 数据表  │ 想做什么？选一个 ← 四张卡片           │
│ · 导入    ├─────────────────────────────────────┤
│ · 预览    │ 确认执行后：结果在正下方（全宽）       │
│ · 备份    │ ✅ 更新行数 · 抽样核对 · Excel 下载   │
└──────────┴─────────────────────────────────────┘
```

- 侧栏可收起（左上角 `»` 展开），「🕘 最近的自动备份表」只显示库里真实存在的备份
- 首屏**零黑话**：不出现 SQL / JOIN / 主键 / 公式（有 e2e 断言盯着）

## 快速开始

### 1. 环境

- Python **3.14**（开发验证版本）
- PostgreSQL

### 2. 安装依赖

```bash
pip install -r requirements.txt
# streamlit==1.64.0  psycopg2-binary==2.9.13  pandas==3.0.6
# openpyxl==3.1.5    python-dotenv==1.2.3
```

### 3. 配置数据库凭据

凭据**不在仓库里**，来自一个 env 文件（默认读 excel2pg 的 `.env`，可用环境变量 `YIFAN_ENV_FILE` 指到别处）：

```bash
PGHOST=localhost
PGPORT=5432
PGDATABASE=yifan
PGUSER=你的用户名
PGPASSWORD=你的密码        # 永不入库、永不打印、永不写日志
```

### 4. 启动

```bash
streamlit run app.py
# 浏览器打开 http://localhost:8501
```

改代码保存即自动重启（`.streamlit/config.toml` 已开 `runOnSave`）。

## 测试与验收

```bash
python tests/test_match.py    # 匹配引擎（次数/判断/Vlookup 三档规则）
python tests/test_query.py    # 查询卡片
python tests/test_safety.py   # 失败路径：坏配置/零匹配/备份失败必须整体回滚
python tests/test_e2e.py      # 向导端到端（AppTest 模拟点击，真库幂等写回，跑完不留痕）
python -m engine.verify       # 黄金基准：硕士 500/500、直博 200/200 全对齐才叫过
```

改完跑一遍全绿再提交，是这个项目的完成门槛。

## 目录结构

```
yifan/
├── app.py                 # 入口： streamlit run app.py
├── engine/                # 计算引擎（纯 Python，可独立测试）
│   ├── db.py              #   连接 + 标识符安全（凭据只来自 .env）
│   ├── specs.py           #   操作规格（选了什么 → 引擎听得懂的结构）
│   ├── match.py           #   键匹配：次数 / 判断 / Vlookup 三档
│   ├── ops.py             #   写回（单事务 + 备份 + 轮换）、预演、SQL 解释
│   ├── apply.py           #   批量套用
│   └── verify.py          #   黄金基准复核
├── ui/                    # Streamlit 界面（小白话，零黑话）
│   ├── main.py            #   布局、侧栏、首页卡片、结果区
│   ├── calcs.py           #   写回向导五步（含确认页/结果页）
│   ├── querycard.py       #   查数据卡片
│   ├── helpers.py         #   人话化、表结构、xlsx 导出
│   └── store.py           #   界面配置存取（.ui_config.json，不入库）
├── tests/                 # 四套回归 + 黄金基准
├── .streamlit/config.toml # 主题 + runOnSave + 藏 Deploy
├── workspace/product/     # PRD（决策记录 1-25）
├── AGENTS.md              # 项目硬约束（AC 驱动、证据优先）
└── requirements.txt
```

## 技术栈

| 层 | 选型 | 为什么 |
|---|---|---|
| 界面 | Streamlit 1.64 | 小白向导流最短路径，无前端构建 |
| 数据库 | PostgreSQL + psycopg2 | 项目本体，事务保证写回安全 |
| 数据 | pandas + openpyxl | Excel 预览/导出 |
| 配置 | python-dotenv | 凭据与代码彻底分离 |

## 相关

- **[excel2pg](https://github.com/andyshi70/excel2pg)** — Excel 导入层（`src/excel/` 放文件，点按钮进库，同名覆盖）
- PRD 决策记录：`workspace/product/prd_yifan_webui_v1_2026-09-30.md`
- 项目约束与工作流：`AGENTS.md`

