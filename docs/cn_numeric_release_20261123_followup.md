# CN 数值数据 v1.1 续补

2026-11-23，北京时间。正式发布 `cn-5e6f043b08b3ff9dc073f7fe5354ee4e4b6952cde903e5f199ea04f56946ccaa`，状态为 **`INCOMPLETE`**。24 项全量违规计数均为零。发布分片和监督掩码、PIT 前缀、Karpo 原生加载以及个股因子独立复算均通过。 [发布指针](<E:/QuantData/numeric/latest_cn.json>) · [发布清单](<E:/QuantData/numeric/cn-5e6f043b08b3ff9dc073f7fe5354ee4e4b6952cde903e5f199ea04f56946ccaa/manifest.json>) · [验收结果](<E:/QuantData/numeric/cn-5e6f043b08b3ff9dc073f7fe5354ee4e4b6952cde903e5f199ea04f56946ccaa/reports/validation_results.json>)

## 补齐范围

本轮以 `cn-55087bfbf246610b9cd5441573d4e40c9025823e9cb63006f43f8d8a3f72d7f8` 为基线。覆盖率截至 2026-06-30，以 10,378,768 个有效输入证券日和 217,747 个北交所有效输入证券日为分母。停牌行数覆盖全体候选证券日。

| 指标 | 基线 | 续补后 | 净增 |
|---|---:|---:|---:|
| 证券股本 | 10,035,608 | 10,039,065 | 3,457 |
| 发行人市值 | 9,740,460 | 10,008,755 | 268,295 |
| 北交所七项核心财务齐备 | 135,315 | 142,136 | 6,821 |
| 北交所经营现金流 TTM | 161,259 | 165,450 | 4,191 |
| 股数单位 U 可用 | 10,377,317 | 10,377,320 | 3 |
| 历史简称可用 | 10,378,721 | 10,378,759 | 38 |
| 已验证整日停牌 | 270,692 | 271,100 | 408 |

本地股类结构档案新增 845 个针对目标证券股本缺口的版本，核定了 252 只证券的 3,738 个多股类股本结构。山东地矿 2017-04-24 定向转增后的 510,931,166 股采用实施公告，区间在 2017-06-30 的下一次股本变动处截止。该次定向转增按股东类别差异实施，U 链仍保留断点。港股休市日的旧报价遵循契约 v1.1，以对应股类行动档案核对报价日至估值日的股数单位，保留实际报价年龄。 [山东地矿原始实施公告](https://static.cninfo.com.cn/finalpage/2017-04-19/1203324034.PDF) · [数据契约](<E:/Kurumi/docs/kurumi_numeric_dataset_contract.md>)

北交所原件补入 835 项字段，其中 546 项补入已有版本，289 项来自 44 个新增历史版本。分别复核合并报表表内金额、附注栏、跨行字段名和报告期。在原件证实适用挂牌场所时，采用全国股转系统自 2020-01-03 起施行的会计口径。档案仍保留版本披露时间，用于重算 TTM 和同比组成期。 [股转系统历史规则](https://www.neeq.com.cn/class_c0/200011905.html) · [财务原件复核](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/finance/partial_financial_review.json>) · [股转原件复核](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/finance-neeq/partial_financial_review.json>)

历史简称按可证实的交易所生效日启用。原件显示仅拟议且既有简称可以确认的日期，恢复既有简称。新增简称证据覆盖预测期 38 个证券日及观察缓冲期 1 个证券日。三笔现金分配通过已实施条款和行动档案校验，量序列沿用同一股数单位。 [历史简称证据](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/names-reviewed/name_session_audit.json>) · [U 链证据](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/unit/split_additions_audit.json>)

## 发行人市值依赖

基线 638,308 个有效输入证券日缺发行人市值。其中 343,160 个缺目标证券股数，288,622 个尚缺完整股类集合，3,044 个目标股数与股类结构不一致，3,364 个已有早期兄弟股类报价但股数单位未对齐，118 个财报本位币尚未确认。

新结构获准后，同一基线缺口中有 974 个证券日股类与股数已齐全且只缺港股报价，均为拉夏贝尔 `603157.SH` 的 `06116.HK` 报价。已取得的 CSMAR 报价补回其中 246 日。剩余 728 日中，有 2 日早于本地首笔有效收盘，分别为 2017-12-25 和 2017-12-26。其余 726 日在 2019-01-02 至 2022-03-30 之间，本地最新有效收盘仍是 2018-12-28 的报价。 [原版市值缺口](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/issuer-audit/issuer_cap_gap_audit.json>) · [股类结构补入后的缺口](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/issuer-audit-structured/issuer_cap_gap_audit.json>)

新版 370,013 个发行人市值缺口中，339,703 个缺目标股数，15,905 个缺完整股类集合，13,039 个股类结构的目标股数不一致，1,168 个有早期报价但缺价格单位连续性证据，196 个财报本位币未核定，2 个没有可用的历史报价。 [最终逐证券日市值依赖](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/delivery/issuer_cap_remaining_by_dependency.parquet>)

## 市场与行业状态

预测期 2,790 个市场日中，市场广度和收益离散度各由 1,778 日增至 1,792 日，20 日均线上方比例由 546 日增至 576 日，总换手率中位数由 52 日增至 56 日。市值加权的市场组合收益仍缺有效权重分母。申万一级行业归属覆盖 4,448,405 个有效输入，行业状态索引有 61,224 行，历史完整行业母集仍未核定。

## 样本与监督掩码

11,618,610 个候选样本对应 34,855,830 条期限标签。可监督样本至少有一个有效期限。

| 切分 | 可监督样本 | 1 日有效 | 5 日有效 | 20 日有效 | 三个期限均有效 |
|---|---:|---:|---:|---:|---:|
| 训练 | 7,209,690 | 7,204,031 | 7,162,408 | 7,049,692 | 7,028,817 |
| 验证 | 608,311 | 608,160 | 587,208 | 508,836 | 508,512 |
| 校准 | 651,003 | 650,887 | 629,517 | 550,432 | 549,997 |
| 测试 | 1,891,977 | 1,891,181 | 1,889,664 | 1,888,189 | 1,885,584 |

逐键比较全部 34,855,830 条标签，有 1,338 条更新了目标来源引用。收益、档位、有效掩码、无效原因和目标交易日逐条一致。 [训练样本及掩码](<E:/QuantData/numeric/cn-5e6f043b08b3ff9dc073f7fe5354ee4e4b6952cde903e5f199ea04f56946ccaa/reports/training_samples.parquet>) · [标签差异](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/delivery/label_release_diff.json>)

## CSMAR 下载

复用旧档案和回执后新增 3,002 条源记录。八个年度合并范围取得 2,706 条停牌公告，十一个简称公告范围取得 49 条记录，首段港股报价范围取得 247 条。CSMAR 在处理第二段港股报价时返回当日额度耗尽 `-2404`。续采计划保留 2019–2022 和 2023–2024 两段未完成请求及 2017-12-22 的休市前收盘锚点。2019–2022 范围已有 758 条记录的计数回执。 [下载归档校验](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/csmar_capture_audit_final.json>) · [报价续采计划](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/pending_quotes_plan.json>) · [报价服务回执](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/exact_quotes_4year.log>)

## 剩余缺口及训练影响

| 缺口 | 证券日 | 影响与证据状态 |
|---|---:|---|
| 证券股本 | 339,703 | 仍缺历史版本、股类口径或变动区间的合格证据。证券市值、换手及其相关因子按依赖标缺。 |
| 发行人市值 | 370,013 | 剩余依赖包括证券股本、完整股类、可用报价、价格单位或财报本位币。估值和加权状态按依赖保留缺失。 |
| 北交所七项核心财务至少缺一项 | 75,611 | 合并金额及 TTM 组成期仍有待核定的原版与字段。已读取原件有会计口径、具体表期、金额栏或合并表不明确的记录。 |
| 申万一级行业归属 | 5,930,363 | 归属和相应行业特征依赖历史有效分类及母集。 |
| 股数单位 U | 1,448 | 尚缺可应用于全股类的具体实施条款、股数口径或事件时间，成交量和量比等保留掩码。 |
| 历史简称 | 9 | 剩余日期仍待分别核定交易所实际交易名或历史公开时点。CSMAR 简称公告仅有零点占位时间的日期仍需要时点证据。 |
| 候选整日停牌 | 11,624 | 已报告停牌仍待当时的公告或续停证据。对应交易状态与依赖行情的监督按证据标记。 |

最终缺口按字段、证券、首末日期、原因代码和财务锚点登记。市场和行业状态按交易日登记。 [覆盖率对照](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/delivery/coverage_comparison.json>) · [逐证券缺口](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/delivery/remaining_security_intervals.parquet>) · [市场和行业缺口](<E:/Kurumi/artifacts/cn_numeric_followup/local-residual-20261123/delivery/remaining_context_sessions.parquet>)
