# 沪深北数据续补与发布验收

2026-11-25 正式发布 `cn-34e4f8dc1c27321b0ba3e9967d4dc63b35ab0e53a8dc7cb258dcf5413e1d074a`。研究输入截至 2026-06-30，标签观察期截至 2026-07-31。下表按续补前后的同一组 10,378,768 个有效输入证券日计算。 [正式发布指针](<E:/QuantData/numeric/latest_cn.json>) · [版本清单](<E:/QuantData/numeric/cn-34e4f8dc1c27321b0ba3e9967d4dc63b35ab0e53a8dc7cb258dcf5413e1d074a/manifest.json>) · [数据契约](<E:/Kurumi/docs/kurumi_numeric_dataset_contract.md>)

## 覆盖变化

| 缺口 | 续补前 | 正式新版 | 净减少 |
|---|---:|---:|---:|
| 目标股类股本 | 171,017 | 92,065 | 78,952 |
| 发行人总市值 | 200,549 | 113,654 | 86,895 |
| 至少缺一项核心财务 | 2,286,451 | 1,416,973 | 869,478 |
| 财报锚点 | 23,411 | 5,740 | 17,671 |
| 申万一级行业归属 | 5,771,956 | 3,452,977 | 2,318,979 |
| 股数单位链 | 124 | 120 | 4 |

七项核心财务齐备的有效输入增至 **8,961,795** 个。北交所齐备的输入由 178,141 增至 **201,028 / 217,747**，剩余 16,719 个至少缺一项。经营活动现金流 TTM 新增 648,778 个有效值。含标签观察期的全网格股数单位链缺口由 348 降至 332。 [发布覆盖统计](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/delivery/expanded_release_coverage.json>)

总换手率中位数可用日期由 271 增至 1,834 日。20 日和 60 日均线上方比例分别由 2,358 增至 2,370 日及由 934 增至 943 日。 [市场与行业覆盖对照](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/delivery/coverage_comparison.json>)

## 来源和处理方法

- 财务使用本地供应商档案、发行人和交易所原件，并核对会计口径、单位、报告期和公开日期。覆盖 3,145 家发行人的原件查找共核验 3,912 份不同 PDF。按公告编号恢复了 140 家此前缺原件的发行人。旧新三板的 190 份原件形成 376 个可核验财务金额候选，覆盖 64 家发行人。最终准入 23,576 个直接财务金额、1,523 个正式可比期金额和 1 个正式更正金额。由已公开组成期在本地复算 TTM。 [财务准入回执](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/finance-stage/expanded_finance_stage_audit.json>) · [原件检索](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/ipo_source_coverage_summary.json>) · [旧新三板核验](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/older_neeq_financial_audit.json>)
- 股本按历史发行及注销、章程和实施原件确认，并与本地 CSMAR 和 TuShare 交叉核对。跨市场市值使用完整股类、适用股数单位、当时可得的未复权报价及汇率。海尔智家 D 股纳入 1,953 个有效历史报价与 1,991 个欧元兑人民币参考汇率，并按德国实际时区确定可用时间。 [跨股类准入](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/class-stage/haier_issuer_capitalization_audit.json>) · [股本原件核验](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/class-stage/remaining_primary_share_schedules_audit.json>) · [发行人 D 股上市](https://smart-home.haier.com/media/xahjxv5h/qingdao-haier-co-ltd-successfully-listed-on-the-ceinex-d-share-market-today.pdf) · [欧洲央行汇率](https://data.ecb.europa.eu/data/datasets/EXR/EXR.D.CNY.EUR.SP00.A)
- 行业按可证明的公开日和生效日连接申万成分原表及 CSMAR 行业历史，准入 4,155 个区间。股数单位通过公告、公司行动和相邻报价复核。另保存 2,024 份有独立公开时点的财报正文，覆盖 1,101 家发行人。数值版 `text_ref` 使用契约定义的占位值。 [行业来源](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/industry-stage/dated_index_inclusion_audit.json>) · [股数单位核验](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/unit-stage/additional_cash_unit_originals_audit.json>) · [财报正文](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/issuer_reports_pit/issuer_reports_pit.parquet>)

## 数据质量与契约

- 发布版本的 24 项全量 SQL 检查均为零违规。落盘文件及样本、时点证据、Karpo 原生加载和个股因子独立复算四项验收均通过。无可核实停牌解释的缺报价、报价缺复权因子、有报价日未知限价以及未核实的已报停牌均为零。 [正式验收](<E:/QuantData/numeric/cn-34e4f8dc1c27321b0ba3e9967d4dc63b35ab0e53a8dc7cb258dcf5413e1d074a/reports/validation_results.json>)
- 依历史原件更正了 2,284 个旧股本键和 4 个旧发行人市值键。股本更正中，国航有 15 个证券日处于登记已生效但公开确认尚未可用的区间，按契约使用缺失掩码。时点回放确认既有 BigQuant 股本证明保全，原有同财报锚点的财务值逐字段核对通过。 [全量回放](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/candidate_replay_summary.json>) · [股本更正证据](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/class-stage/issuer_class_repairs_audit.json>) · [原始证据冻结](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/frozen/cn-pit-5d015b233a613b4f79cd4828/expanded_source_admissions.json>)
- 对正式文件逐键核验了 11,745,773 个证券日、6,022 个既有 BigQuant 股本证明及 10,355,238 个使用相同财报锚点的证券日。34,855,830 条标签的 12 个分片与原版字节一致。11,745,245 条行情来源记录逐字段一致。414 个既有发行人市值的末位差异落在浮点容差内。30 项相关回归测试通过。 [发布前后核验](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/delivery/issued_release_quality_and_delta.json>)

## 剩余缺口和渠道状态

- 股本缺口中，68,977 个仍有未消解的数量冲突，23,088 个缺合格的历史股类证明。剩余发行人估值还受退市或非上市普通股类报价、完整股类与单位证据限制。财务缺口涉及原件缺失、报告不含所需组成期、会计口径差异或缺少当时版本。行业缺口主要需要原始申万成员档案和历史公告时点。 [逐证券缺口](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/delivery/remaining_security_intervals.parquet>)
- 2,789 个具备前一日成分范围的市场交易日仍缺完整市值权重分母。市场及行业收益仍按契约保留缺失掩码，正式版本的完整性状态为 **`INCOMPLETE`**。 [市场与行业逐日缺口](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/delivery/remaining_context_sessions.parquet>)
- 下载尽量合并同一时期的目录请求，并复用已保存的原文和行情。BigQuant 本轮新增计费单元格为 **0**，最后的额度回执为本周已用 7,040,701 / 50,000,000。三张补缺相关的 BigQuant 表返回权限限制。CSMAR 港股查询返回 2026-11-25 当日额度限制 `-2404`，TuShare 的 `hk_daily` 补采复测仍受日限。 [BigQuant SDK](https://bigquant.com/wiki/doc/vac4qwmQr4) · [SDK 额度回执](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/bigquant_metadata_probe.json>) · [渠道核验](<E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/remaining_channel_audit.json>)
