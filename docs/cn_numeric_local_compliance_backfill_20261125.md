# 沪深北数值数据本地续补与训练验收

2026-11-25，正式发布 **`NUMERIC_READY`**。新版沿用数据契约 1.2。预测样本截至 2026-06-30，标签观察截至 2026-07-31。 [正式发布指针](<E:/QuantData/numeric/latest_cn.json>) · [版本清单](<E:/QuantData/numeric/cn-525769da0005f7eebd6e6748894e410085a5c343eebd6bdd16c18b0d792ef424/manifest.json>) · [数据契约](<E:/Kurumi/docs/kurumi_numeric_dataset_contract.md>)

## 实际补齐

此前补录的原财报已有 BigQuant、CSMAR 交叉核验。部分后续更正记录的更正范围没有涉及经营现金流，却没有继承该已核验金额。本轮逐项比对前版标识和哈希、发行人、财政期间、币种、合并范围及原披露时间，按第 3.2 节允许的规则恢复 90 个更正版本中的原金额。正式包对 201,497 个财务快照逐键比较，已有金额、快照时点和财政锚点零变化。本轮仅复用本地资料。 [契约第 3.2 节](<E:/Kurumi/docs/kurumi_numeric_dataset_contract.md:191>) · [财务准入回执](<E:/QuantData/numeric/cn-525769da0005f7eebd6e6748894e410085a5c343eebd6bdd16c18b0d792ef424/reference/financial_cashflow_carry_admission.json>) · [正式分片前后对账](<E:/Kurumi/artifacts/cn_numeric_followup/local-compliance-20261125/final_published_comparison.json>)

| 以 10,378,768 个有效输入证券日统计 | 补齐前 | 补齐后 | 新增 |
|---|---:|---:|---:|
| 经营活动现金流净额 TTM | 9,650,019 | 9,652,550 | 2,531 |
| 经营现金流／资产因子 | 9,596,067 | 9,598,598 | 2,531 |
| 七项核心财务齐全 | 8,961,802 | 8,963,846 | 2,044 |

## 直接训练

- 严格时点训练使用现有配置。独立行业扩展使用新增配置，仅在训练切分启用历史重建。两个配置均已实际读取这次发布。 [严格训练配置](<E:/Kurumi/configs/cn_numeric.toml>) · [历史行业扩展配置](<E:/Kurumi/configs/cn_numeric_historical_train.toml>)
- 监督索引包含 10,360,981 条样本，其中 7,209,690 条用于训练。全部监督样本有真实官方市场基准。用 10 条真实样本进行加载与 Karpo 原生编码核验，覆盖新恢复金额、缺股本、缺财报、缺 U、市场部分覆盖和行业扩展。两个配置产生相同的标签掩码，抽查的验证、校准和测试输入逐项相同。 [全量基准检查与抽样键](<E:/Kurumi/artifacts/cn_numeric_followup/local-compliance-20261125/training_gap_sample_plan.json>) · [双配置原生加载回执](<E:/Kurumi/artifacts/cn_numeric_followup/local-compliance-20261125/final_configured_gap_cases.json>)
- 24 项全量 SQL 检查零违规，四项独立发布验收全部通过。34,855,830 条标签、12 个样本分片和实际监督索引的哈希均一致。11,745,773 个证券日的实际行情、复权价格、身份和主要来源字段一致。组合统计及 489 个发行人市值的差异均在契约浮点容差内。本轮未启动模型训练。 [正式验收](<E:/QuantData/numeric/cn-525769da0005f7eebd6e6748894e410085a5c343eebd6bdd16c18b0d792ef424/reports/validation_results.json>) · [正式包对账](<E:/Kurumi/artifacts/cn_numeric_followup/local-compliance-20261125/final_published_comparison.json>)

## 仍缺原始证据的字段

有效输入中仍有 1,414,922 日至少缺一项核心财务，3,452,977 日缺严格申万归属，90,294 日缺股本，111,883 日缺发行人市值，84 日缺 U。同一证券日可能计入多个字段。申万本地公开版本和已定时的指数公告逐键复核后，能支持的相应归属已在正式包。U 的 84 日重新检查了公告时点、实施条款、股数基数和除权参考价，当前档案未能通过交叉核验。剩余字段按契约保留掩码，核心训练验收无阻塞。 [申万本地来源重验](<E:/Kurumi/artifacts/cn_numeric_followup/local-compliance-20261125/local_strict_industry_overlap.json>) · [U 重验明细](<E:/Kurumi/artifacts/cn_numeric_followup/local-compliance-20261125/remaining_units_local_recheck.json>) · [新版覆盖报告](<E:/QuantData/numeric/cn-525769da0005f7eebd6e6748894e410085a5c343eebd6bdd16c18b0d792ef424/reports/quality_summary.json>)
