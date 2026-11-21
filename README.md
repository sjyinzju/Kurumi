# Kurumi

## 项目简介

Kurumi 是「经济学中的机器学习」个人研究项目，研究在结构化金融数据相同的条件下，收益预测后训练中加入新闻、公告或两者，是否改善样本外预测准确率和概率质量。实验在统一的推理环境中比较四组模型，以测试结果判断文本是否带来增量价值。

项目计划基于 `MachinePulseAI/karpo-decision-31B` 后训练一个 A 股与美股共用的决策模型。模型预测个股未来 **1、5、20 个交易日**的收益分布，每个期限输出七档收益区间、各档概率及实际收益率边界，可分别汇总下跌、零收益和上涨的概率。

## 后训练路径

1. **共同金融理解训练**。以中英文金融材料、问题和候选答案构造辅助任务，训练模型理解财务口径、数值关系和事件证据，得到四组共享的初始化检查点。
2. **收益监督训练**。在 X-Lab H100 上按 1∶1 混合 A 股与美股样本，三个期限等权，只对有效标签计算 `交叉熵 + 0.5 × Brier + 0.5 × 归一化 RPS`。四组复用相同的结构化输入、样本、标签、时间切分与更新预算，每组运行三个随机种子。
3. **选点、校准与测试**。按验证集 NLL 选取检查点，在独立校准集上按市场和期限拟合六个温度，再在时间留出的测试集报告 NLL、Brier、RPS、七档准确率和校准表现。

| 组别 | 收益监督阶段的文本 |
| --- | --- |
| G0 | 无新闻或公告 |
| GN | 新闻 |
| GA | 公告 |
| GNA | 新闻与公告 |

主评估中，四组都使用包含新闻和公告的同一套完整推理输入。另对 G0 和 GNA 做无文本推理诊断，以分别观察训练时加入文本与推理时提供文本的影响。最终发布候选从 GNA 的检查点中按验证集 NLL 选出。 [后训练路径与实验设计](docs/kurumi_post_training_plan.md)

## 预计决策模型架构

```text
X_state（个股、市场与行业、可选文本） + X_choice（三个期限的收益区间）
    → Karpo 原生 Encoder → Packed 前向（冻结骨干 + 共享 LoRA）
    → 共享原生 Readout
    → 三组七档 logits → 按市场和期限做温度缩放与 softmax
```

两个市场和三个期限共享骨干、LoRA 和原生 Readout。训练更新注意力与 MLP 投影上的 LoRA 以及原生 Readout，保留 Karpo 原生问题分支和选项读出。三个期限各自归一化，得到三组边际收益分布。数值输入组装与原生编码接入已有实现，完整监督训练和模型发布属于后续阶段。 [数值输入加载器](src/kurumi/numeric_loader.py) · [Karpo 数值编码接入](src/kurumi/karpo_numeric.py)

## 数据契约概况

样本以稳定证券身份和本地交易日索引。信息截止于目标市场当地交易日的 `23:59:59`，并保存对应的 UTC 时点。价格、财务版本、行业归属、历史股票池和文本均按当时可得信息取值。训练、验证、校准、测试按时间顺序划分，并为跨越阶段边界的各期限标签分别设置掩码。基座可能记忆历史结果的风险单独记录。

| 对象 | 内容与用途 |
| --- | --- |
| `X_state` | `Xstock` 包含最近 60 个交易日的量价序列、财务快照和 30 个核心因子。`Xmarket` 包含市场和行业状态及覆盖信息。`Xtext` 预留新闻和公告及其来源信息。 |
| `X_choice` | 三个预测期限及其有序收益区间。切点使用过去 60 个日对数收益的样本标准差乘以期限平方根作为尺度，在 ±0.5 和 ±1.5 倍尺度处分档，并单列零收益。 |
| `Y` | 各期限本币复权收盘至收盘收益、标准化收益、档位和有效性，只用于监督与评价。 |
| `audit` | 数据版本、来源、切分和排除原因，供复现和审计。 |

数值数据包由版本化清单和六张核心 Parquet 表组成，加载器按样本组装输入、监督和审计信息。**当前 A 股数值包已完成构建与发布检查，状态仍为 `INCOMPLETE`**，主要缺口涉及历史股本、财务及行业覆盖。正式训练入口要求 `NUMERIC_READY`，当前版本可显式用于质检。美股和新闻公告文本待接入。 [数值数据契约](docs/kurumi_numeric_dataset_contract.md) · [A 股数据报告](docs/cn_numeric_dataset_report.md) · [构建与验收记录](docs/cn_numeric_execution.md)

## 未来规划与开源发布

1. 补齐 A 股数值数据覆盖，按同一契约接入美股，落实新闻和公告的历史可得时间与选材规则。
2. 验证原生训练链路，完成四组收益监督实验、概率校准和样本外比较，记录数据版本、基座版本与运行配置。
3. **GitHub** 开源训练和评估代码、数据契约、实验配置及复现说明。**Hugging Face** 发布验证集选定的 GNA 模型包，包含 LoRA 权重、更新后的原生 Readout、精确基座版本、输入输出配置、校准参数和模型卡。受来源许可限制的原始数据通过获取说明和配置引用。

## 本地开发与资料

项目使用 Python 3.11 或 3.12。运行测试可安装 `dev` extra。源数据盘点还需 `quant` extra 和本地 `quant` 源码，路径通过配置指定，外部源码和原始数据按只读方式使用。 [路径配置示例](configs/paths.example.toml)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[quant,dev]'
.\.venv\Scripts\python.exe -m pytest -q
```

源数据盘点流程需要配置外部数据路径，全量扫描的耗时和临时磁盘占用取决于数据规模。

```powershell
Copy-Item configs/paths.example.toml configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/inventory.py --config configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/supplement.py --config configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/auxiliary_tables.py --config configs/paths.local.toml
.\.venv\Scripts\python.exe scripts/schema_consistency.py
.\.venv\Scripts\python.exe scripts/relationship_details.py
.\.venv\Scripts\python.exe scripts/render_report.py
.\.venv\Scripts\python.exe scripts/verify_inventory.py
```

- [源数据盘点报告](docs/data_report.md) · [字段字典](docs/field_dictionary.md) · [盘点清单](docs/inventory/)
- [金融后训练研究参考](docs/research_references.md) · [本地参考资料索引](docs/references/README.md)
