# A 股数值数据优化 v1

`cn-efficiency-v1` 以正式发布 `cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3` 为只读来源。新池复用行情、财报、市场与行业共享表，另存监督覆盖、隔离索引和覆盖统计。正式数据的底表精度完整保留。 [构建脚本](../scripts/build_cn_efficiency_pool.py) · [加载器](../src/kurumi/cn_efficiency_pool.py)

## 全量核验

| 口径 | 结果 |
| --- | ---: |
| 原始证券日样本 | 11,618,610 |
| 输入合格 | 10,378,768 |
| 至少一个有效期限，旧版 → 新版 | 10,360,981 → 10,376,684 |
| 获得恢复监督的样本 | 313,173 |
| 确切重复 | 0 |
| 隔离样本 | 1,241,926 |
| 1 日有效监督 | 10,369,918 |
| 5 日有效监督 | 10,347,081 |
| 20 日有效监督 | 10,310,226 |

全量重放 34,855,830 条期限记录。恢复 407,020 条原切分边界掩码下、可由目标交易日和复权行情验证的监督，461 条目标日停牌期限继续屏蔽。隔离样本包括 894,377 条历史窗口有停牌、345,465 条历史不足及 2,084 条无可用目标。12 项全量输入检查均通过。 [价格、成交量及复权来源核验](../scripts/audit_cn_efficiency_quote_lineage.py)

完整池保留已有的 2015—2026 年候选时期、2,730 个有效交易日期、59 个严格时点行业代码及 9 种市场状态。新池包含 148,619 个低波动、1,041,298 个低流动性样本及 3,191 个合格的退市前样本。有效监督中有 446,768 个零收益和 1,658,595 个绝对对数收益达到 `ln(1.2)` 的期限。尾部指标用于核对覆盖。全量有效池按实际紧凑格式做输入重复筛查，完整输入与去掉身份段后的输入均没有确切重复。 [输入审计](../scripts/audit_cn_efficiency_inputs.py)

## 日期视图与输入

日期区间和预算均可调。指定日期末日后，默认将其作为可用标签截止日。`--split` 沿用原切分的监督掩码。预算视图按月、市场、行业、证券和交易日排序，以随机相位进行等距抽样，记录每条样本的入选概率及其逆概率权重。确认段在 50,000 条预算下，与简单随机相比，5 个交易日内的同证券相邻入选次数平均从 5,103 降至 801，两者均覆盖 55 个月份与市场状态组合。可用 `--coverage-order market` 优先覆盖市场状态。 [采样对照脚本](../scripts/audit_cn_efficiency_sampling.py)

813 条真实 tokenizer 样本覆盖旧训练期 9 年及 3 个交易所。紧凑输入中位数 7,323 → 6,356 tokens，均值下降 13.17%，独立确认段均值下降 13.01%。全部保留 60 日窗口、原显示精度、因子、缺失语义、三期限和每期限七档。按缺失字段重新分组的候选平均再节省约 0.19%，保留当前模板。 [Tokenizer 核验](../scripts/probe_cn_efficiency_render.py) · [渲染器](../src/kurumi/cn_efficiency_render.py)

30 个因子的缺失总数均与原因台账吻合。旧训练范围的 435 对因子均观察到字段值或掩码差异。九个可复算摘要的删减候选在轻量 CPU 模型上的表现因期限而异，近期 10 日加多尺度汇总候选未通过前推门槛。冻结输入保留完整窗口与因子。候选评估使用 2015—2019 拟合段、2020—2021 前推验证及 2022—2023 独立确认。 [因子剖析](../scripts/profile_cn_efficiency_features.py) · [CPU 对照](../scripts/probe_cn_efficiency_features.py)

## 复现

在仓库根目录设置 `PYTHONPATH`。将 `$source` 指向上述正式发布，输出到全新目录。日期与预算仅用于验证接口。

```powershell
$env:PYTHONPATH = 'src'
$source = '<immutable numeric package directory>'
$pool = 'artifacts/cn-efficiency-v1'
python scripts/build_cn_efficiency_pool.py --source $source --output $pool
python scripts/select_cn_efficiency_view.py --pool "$pool/pool.parquet" --output artifacts/date-view.parquet --start 2019-06-01 --end 2019-06-28 --split train --budget 8
python scripts/render_cn_efficiency_view.py --pool $pool --view artifacts/date-view.parquet --layout compact --output artifacts/date-view.jsonl
```

构建会生成 `audit.json` 与 `coverage_*.csv`，包含逐年、逐月、行业和市场状态统计。Tokenizer 核验使用 Karpo 原生代码修订 `6600011eb5cf46232d056ec0717dc726146d29de` 及基座 tokenizer 修订 `b8e6fd7463cea8662c556d6257955d7ef9c10d19`。轻量 CPU 对照另需 NumPy、scikit-learn 和 threadpoolctl。仓库交付物为代码、测试及汇总口径，数据产物在本地生成。
