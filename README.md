# Kurumi：文本的样本外增量价值

“经济学中的机器学习”个人研究项目。基座为 `MachinePulseAI/karpo-decision-31B`；比较结构化金融数据相同、后训练文本条件不同的模型。文本可能无效，结论由统一样本外实验决定。

`X_state` 为决策时可得的结构化数据及可选文本；`X_choice` 为任务和选项空间；`Y` 为未来真实收益与标签，仅用于监督和评价。主输出为固定期限收益区间概率分布。预测期限、分档、样本范围和训练规模尚未确定。本轮没有下载权重或启动训练。

## 当前交付

- [真实数据报告](docs/data_report.md)、[完整字段字典](docs/field_dictionary.md)
- `docs/inventory/`：数据集清单、每字段质量分母、有效文件清单、目录容量、Raw 抽样、Qlib 缓存和来源代码哈希
- [参考实现索引](reference/README.md)：外部实现复用边界
- `src/kurumi/paths.py`：外部只读源与输出路径配置检查
- `scripts/`：只读、可复现盘点及报告生成；`tests/`：输出边界检查

## 安装与运行

Python 3.11–3.12。轻量基础依赖仅 DuckDB/PyArrow；盘点复用外部 `quant` 模块，还需 `quant` extra（不会安装或写入 E:\quant）。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[quant,dev]'
Copy-Item configs/paths.example.toml configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/inventory.py --config configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/supplement.py --config configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/auxiliary_tables.py --config configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/schema_consistency.py
.\.venv\Scripts\python.exe scripts/relationship_details.py
.\.venv\Scripts\python.exe scripts/render_report.py
.\.venv\Scripts\python.exe scripts/verify_inventory.py
.\.venv\Scripts\python.exe -m pytest -q
```

本轮实际使用现有 `E:\quant\.venv\Scripts\python.exe`，未安装新依赖；命令及版本见报告。主要扫描会读取全部有效 Canonical，耗时和临时磁盘占用取决于数据规模。DuckDB 内存上限 3GB、单线程；溢出及临时表只写 `artifacts/`（不提交 Git），不会把整个外部数据库复制进仓库。自然键包含分区日期时，逐事件分区解析最新版本以限制窗口大小。`--skip-tree` 只用于明确复用已有目录普查，非新的全目录统计；`--retry-errors` 需保留本地中间审计库且来源数据库 size/mtime 未变。

脚本不加载 `.env`、不调用 API、不实例化外部 `Registry`。外部 DuckDB 使用 `read_only=True`，仅复用无写入副作用的契约加载器和 SQL 生成函数。配置 output 不允许位于任一外部根目录中。快照是读事务开始时注册表中 active 指针及文件列表；需正式实验时再锁定不可变 manifest 和代码版本。

## 后续实验边界

数据处理先固定证券、交易日、版本、信息时钟与标签定义，再构造 `X_state/X_choice/Y`。Karpo 适配需阅读原生决策输入输出契约，不能直接套用通用聊天分类格式。后训练与推理的文本条件分别记录；使用相同样本、标签、时间切分及训练预算比较。标签跨分割区间需要 purge/embargo，概率评估至少包括 log loss、Brier 和校准，同时报告方向/区间预测准确率及有效分母。

不直接继承旧项目标签、收益曲线或认证结论；时间切分不能消除基座可能记忆历史结果的风险。大型数据、权重、环境、缓存和凭证不提交。
