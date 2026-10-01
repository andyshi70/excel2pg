# excel2pg + YIfan

一个仓库，两个配套工具：

## excel2pg — Excel → PostgreSQL 导入器

Excel 一键进库，按 `excel名_sheet名` 自动建表，同名表覆盖重导。

- 代码：`src/`（核心 `src/importer.py`）
- Excel 放进：`src/excel/*.xlsx`
- 运行：`python src/importer.py`

## yifan/ — YIfan 数据小工具（Streamlit WebUI）

给不写 SQL 的同事用的网页界面：查数据、判断在不在、数出现次数、Vlookup 带值，写回前自动备份、失败整单回滚。

- 说明：[yifan/README.md](yifan/README.md)（快速开始 / 数据安全 / 测试验收）
- 启动：`cd yifan && streamlit run app.py`

## 关系

```text
Excel ──excel2pg──▶ PostgreSQL(yifan 库) ◀──读写── YIfan WebUI
```

导入层负责把 Excel 变成表；WebUI 负责在此之上查数、算数、写回。
