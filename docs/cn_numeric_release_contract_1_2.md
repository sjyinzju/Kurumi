# 沪深北数值数据集 1.2 发布结果

2026-11-25 正式发布 **`NUMERIC_READY`**。预测样本截至 2026-06-30，标签观察截至 2026-07-31。默认训练配置已读取新包。 [版本清单](<E:/QuantData/numeric/cn-b519d594da0eb663306489cacf98fe1c3409ad405501fd2df7a67aea8a9ed6f1/manifest.json>) · [发布指针](<E:/QuantData/numeric/latest_cn.json>) · [数据契约 1.2](<E:/Kurumi/docs/kurumi_numeric_dataset_contract.md>)

## 覆盖变化

股票字段以 10,378,768 个有效输入证券日为分母，市场收益以 2,790 个交易日为分母，严格行业收益以 79,011 个行业交易日为分母。扩展行业归属以 7,209,690 条实际训练样本为分母。 [正式分片前后对账](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/verified_release.json>)

| 指标 | 修订前可用 | 发布后可用 | 发布后覆盖 |
|---|---:|---:|---:|
| 市场 1 日收益 | 0 | 2,724 | 97.63% |
| 市场 20 日收益 | 0 | 2,648 | 94.91% |
| 市场 60 日收益 | 0 | 2,488 | 89.18% |
| 严格行业 1 日收益 | 0 | 69,678 | 88.19% |
| 严格行业 20 日收益 | 0 | 61,122 | 77.36% |
| 严格版个股 20 日行业相对收益 | 0 | 6,164,730 | 59.40% |
| 目标股类股本和股类市值 | 10,286,703 | 10,288,474 | 99.13% |
| 发行人市值 | 10,265,114 | 10,266,885 | 98.92% |
| 七项核心财务齐全 | 8,961,795 | 8,961,802 | 86.35% |
| 股数单位链 U | 10,378,648 | 10,378,684 | 缺 84 日 |
| 训练样本的行业归属，含独立扩展 | 3,914,073 | 7,197,059 | 99.82% |

市场按至少 95% 证券数量和 95% 已知前期市值重新归一化。已发布日收益中，两项实际最低覆盖分别为 **95.08%** 和 **98.97%**。全市场真实市值分母仍缺完整证据，真实市值覆盖率保留空值。行业额外要求有效成员至少 5 个、按权重计算的有效样本数至少 3。独立复算在 5 个交易日核对了 150 个市场或行业组合，其中 126 个有效收益逐项通过。 [组合权重复算](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/verified_release.json>)

按披露原件补回 1,771 个有效证券日的股本和发行人市值。财报原件使营业收入、归母净利润和经营现金流三项 TTM 各新增 90 个有效证券日。核实公司行动后补回全观察范围内 37 个 U 缺口，另按真实生效日纠正 20,760 个既有 U 值。三六零沿用稳定证券身份，并将代码变更前的 768 条历史显示代码改回 `601313`。 [来源准入及回放](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/final_original_replay.json>) · [美康生物招股说明书](https://static.cninfo.com.cn/finalpage/2015-04-13/1200820923.PDF) · [历史代码变更公告](https://static.cninfo.com.cn/finalpage/2018-02-13/1204419027.PDF)

## 训练可用性

沪、深、北覆盖训练、验证、校准和测试四段。正式监督索引有 **10,360,981** 条至少一个期限可监督的样本，其中训练 7,209,690 条、验证 608,311 条、校准 651,003 条、测试 1,891,977 条。1、5、20 日均纳入按交易所与时间段的核心依赖验收。24 项全量 SQL 检查零违规，分片与掩码、时点前缀、Karpo 原生加载、个股因子独立复算四项检查全部通过。 [正式验收](<E:/QuantData/numeric/cn-b519d594da0eb663306489cacf98fe1c3409ad405501fd2df7a67aea8a9ed6f1/reports/validation_results.json>)

11,745,773 条证券日的原始行情和价格复权口径、11,618,610 条样本的时间切分和输入掩码均通过逐键核对。包含 34,855,830 条记录的 12 个标签分片与监督索引保持逐字节一致。`Xstock`、`Xmarket` 和 `Xchoice` 的接口及 Y 的定义沿用原契约。正式验收对 16 个真实样本检查了原生编码和价格窗口，并以实际配置重新加载四段样本。 [逐键核对](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/verified_release.json>) · [训练配置加载回执](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/configured_loader.json>)

默认配置使用严格时点数据。可通过 `NumericDataset.from_config("configs/cn_numeric.toml", industry_profile="historical_train")` 开展独立扩展训练实验。该扩展使用申万原始档案、CSMAR、TuShare、BigQuant 和已核实的证券别名，共准入 15,220 个区间，为训练段新增 3,282,986 条行业归属，覆盖北交所 62,079 条训练样本。扩展分片含 7,022,911 条 5 日和 6,684,343 条 20 日行业相对收益。验证、校准和测试继续采用严格时点输入，加载对照逐项相同。本轮未开展模型训练。 [行业归属逐交易所核验](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/verified_training_industry.json>) · [行业扩展来源回执](<E:/QuantData/numeric/cn-b519d594da0eb663306489cacf98fe1c3409ad405501fd2df7a67aea8a9ed6f1/reports/industry_training_history.json>)

## 剩余缺口与来源

- **严格行业**仍有 3,452,977 个有效证券日缺当期公开的申万归属或实施档案。独立扩展仍有 12,631 条沪深训练样本遇到未解决的历史来源冲突。 [扩展逐样本缺口](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/remaining_historical_training_industry.parquet>)
- **股本及市值**分别缺 90,294 和 111,883 个有效证券日。需要合格的历史股类股数，或其他股类的合规报价、汇率和单位连续性证据。BigQuant 的股本事件表、行业变更表和港股日线曾实测拒绝授权。CSMAR 港股当日额度及 TuShare 港股接口限频也有回执。 [已实测的渠道和权限](<E:/Kurumi/docs/cn_numeric_release_20261125_current_channels.md>)
- **财务及股数单位链**仍有 5,740 个有效输入缺合格报表锚点，1,416,966 个至少缺一项核心财务。还需注明原始披露时间及合并口径的报告和计算 TTM 所需的组成期。84 个有效证券日的 U 缺口仍需要可核实到同一普通股类的实施条款。 [逐证券、区间与字段原因](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/remaining_security_intervals.parquet>)
- **组合上下文**仍有 65 个交易日未达到市场日收益覆盖要求，首日缺前期母集。滚动收益遇到缺档保留缺失标记。 [市场和行业逐会话缺口](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/delivery/remaining_context_sessions.parquet>)

BigQuant 本轮合并查询并复用了已下载的抽样记录。新增消耗 **277,491** 个单元格，周累计为 **7,318,192 / 50,000,000**。 [北交所查询回执](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/bigquant_sw/receipt.json>) · [沪深冲突核验回执](<E:/Kurumi/artifacts/cn_numeric_followup/contract-1_2-20261125/bigquant_sw/mainland_receipt.json>) · [BigQuant 申万行业字段](https://bigquant.com/data/datasources/cn_stock_factors_industry)
