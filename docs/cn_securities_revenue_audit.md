# 东方证券与招商证券合并营业收入核验

复核冻结财务事实中的东方证券（`600958.SH`）45 期和招商证券（`600999.SH`）57 期，共 102 期。每一份文件与既有证券、会计期、首次披露日精确对应。采用正式合并利润表的经营收入总额，旧报表标题可能写作「营业收入」。每份报表都查到利息净收入和手续费及佣金净收入列在该合计以下。旧版三季报同时有 7–9 月和 1–9 月列时，取 1–9 月本年累计，合并与母公司并排时取合并金额。招商证券 2012 年报的正式利润表为盖章扫描件，人工逐列核验并绑定第 90 页图像与原始 PDF 的哈希。[原报表逐期收据](../artifacts/cn_numeric_followup/financial_securities_revenue/verified/single_field_originals.jsonl) · [来源盘点](../artifacts/cn_numeric_followup/financial_securities_revenue/verified/source_audit.json) · [招商证券 2014 三季报原件](https://static.cninfo.com.cn/finalpage/2014-10-28/1200341600.PDF)

现有 CSMAR 2013–2017 文件中有这两家发行人的 32 条标准季末、合并口径数据。原始字段字典称 `B001101000` 为「营业收入」且这 32 条全为空，称 `B001100000` 为「营业总收入」且 32 条均有值。后者与正式报表总额的逐期分级比较为 0/32 相符。专项复算的六份报表显示，该字段分别精确等于手续费及佣金净收入、利息净收入及其他业务收入之和。招商证券 2015 年中报的三项相加为 10,815,863,717.91 元，正式合并利润表当期营业收入为 15,863,491,420.23 元。该期另列 2,441,263,768.69 元投资收益，以及其他计入营业收入的分项。替换金额以发行人原表为准。[CSMAR 字段与检核](../artifacts/cn_numeric_followup/financial_securities_revenue/verified/csmar_fields_and_source_crosscheck.json) · [六份原件分项复算](../artifacts/cn_numeric_followup/financial_securities_revenue/verified/independent_filed_revenue_component_checks.json)

以 V6 冻结财务来源为替换基线，在 V5 已发布的 Parquet 上全量对两家发行人的有效输入股票日执行 PIT 重放。两个隔离计算版本均采用既有正式财报选择逻辑，加入营收分期口径检查后还验证不能拼接已知不同范围的营业收入。数据替换保持其他财务数值、各原版披露时点和快照 ID。首个补充披露可用日以前的快照一致。所有下表中跨口径缺失的数值在省略检查时均会被错误生成。[全量回放汇总](../artifacts/cn_numeric_followup/financial_securities_revenue/accounting_transitions/guarded_replay/summary.json) · [东方证券逐快照回放](../artifacts/cn_numeric_followup/financial_securities_revenue/accounting_transitions/guarded_replay/600958/replay.json) · [招商证券逐快照回放](../artifacts/cn_numeric_followup/financial_securities_revenue/accounting_transitions/guarded_replay/600999/replay.json)

| 发行人 | 有效输入日 | 恢复当期 TTM | 恢复一年前 TTM | 当期 TTM 缺失 | 一年前 TTM 缺失 |
| --- | ---: | ---: | ---: | --- | --- |
| 招商证券 | 2,598 | 2,570 | 2,524 | 28 跨口径 | 74 跨口径 |
| 东方证券 | 2,500 | 2,042 | 1,711 | 180 历史不足，278 跨口径 | 397 历史不足，392 跨口径 |

招商证券从 2014-07-01 起将符合控制条件的结构化资管计划纳入合并范围，2014Q3 正式报告已执行新准则。2014-10-28 的政策原公告及附件披露 2013Q3 与 2013 年度的合并利润表调整值。将附件的调整额与原年度、季度的总额相加后，分别与正式比较栏精确一致。2015Q1 与 2015H1 原件提供 2014Q1 与 2014H1 的新口径比较额，按各自公开日派生新版本。披露前继续使用当时可取得的原版。仍欠同口径组成期的早期组合保持为空。[招商证券原始政策和调整表](https://static.cninfo.com.cn/finalpage/2014-10-28/1200341599.PDF) · [四条招商证券追溯版本](../artifacts/cn_numeric_followup/financial_securities_revenue/accounting_transitions/600999/policy_revision_additions.jsonl)

东方证券 2017 年报开始把资产处置收益列入营业收入。原件及比较期附注分别核定 2016FY 的 -750,107.55 元、2017Q1 的 32,500 元、2017H1 的 517,675.37 元与 2017Q3 的 335,927.85 元差额，对应可用日来自 2017 年报及 2018 年三份各期财报。调整所处时段缺同口径组成期的组合保留为空。[财会〔2017〕30 号通知](https://czt.hunan.gov.cn/czt/ztzl/kjxxw/zcfg_1/201801/t20180108_5059518.html) · [东方证券追溯版本和正式附注页](../artifacts/cn_numeric_followup/financial_securities_revenue/accounting_transitions/600958/policy_revision_additions.jsonl)

东方证券自 2025 年半年度报告公布起披露新的仓单会计处理。原先计入营业收入和营业成本的无实物仓单交易改按净额计入投资收益。保留 2025Q1 按原时点披露的 5,381,713,789.37 元。补充四个正式重述版本，其披露日分别为 2025-08-30（2024H1）、2025-10-31（2024Q3）及 2026-03-28（2024FY 和 2025Q1）。最后一条由 2025 年报正文明确给出修订前后金额，2026Q1 正式比较列复核修订后为 3,884,727,756.24 元。真实回放中，切换后 2025H1 和 2025Q3 因欠缺统一口径保留空值，2025FY 和 2026Q1 的 TTM 分别恢复为 15,358,190,328.79 元和 15,563,641,747.82 元。2024Q1 同口径原件仍未取得，影响上述新口径同比。[东方证券会计政策公告](https://static.cninfo.com.cn/finalpage/2025-08-30/1224628188.PDF) · [财政部仓单问答](https://kjs.mof.gov.cn/gongzuotongzhi/202507/t20250703_3967197.htm)

四个东方证券上市前组成期另行核验。2014Q3 合并营业收入 3,532,621,209.56 元来自 2014-12-09 公开的更新招股书，2014FY 5,499,603,011.02 元来自 2015-03-10 的正式招股书，均与后续披露的正式比较栏一致。2014Q1 和 2014H1 金额分别随 2015Q1、2015H1 正式比较栏进入 PIT。在上表的基础上，这四期多恢复 128 个当期 TTM 和 217 个上一年 TTM，东方证券合计为 2,170 和 1,928 个有效交易日。早至 2015Q1 的 52 个交易日仍缺当时已知的完整 2014H1 数据，跨口径冲突计数保持不变。[2014Q3 原件公开日旁证](https://finance.people.com.cn/stock/n/2014/1210/c67815-26179926.html) · [2015-03-10 正式招股书](https://static.cninfo.com.cn/finalpage/2015-03-10/1200685696.PDF) · [上市前四期的有效日回放](../artifacts/cn_numeric_followup/financial_securities_revenue/prelisting_orient/verified/prelisting_replay.json)

## 重放和发布输入

在 `E:\Kurumi` 使用含 `pypdf`、`duckdb` 和项目依赖的 Python。原始快照和输入股票日均从真实版本只读。重放命令采用同一应用代码的隔离基线和带口径检查版本。

```powershell
$env:PYTHONPATH = 'E:\Kurumi\src'
$a = 'artifacts/cn_numeric_followup/financial_securities_revenue'
$g = 'artifacts/cn_numeric_followup/release7_input/revenue_accounting_guard'
$p = Get-Content artifacts/cn_numeric_followup/release6_input/frozen_path.txt
$v = 'E:/QuantData/numeric/cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c'
python scripts/recover_cn_securities_revenue.py --collection $a --additional-collection "$a/early" --base "$p/financial_versions.jsonl" --output "$a/verified" --release $v --orient-revisions
python scripts/stage_cn_securities_revenue_transitions.py --source $a --verified "$a/verified" --base "$p/financial_versions.jsonl" --output "$a/accounting_transitions"
python scripts/verify_cn_securities_revenue_transitions.py --release $v --base "$a/verified" --staged "$a/accounting_transitions" --output "$a/accounting_transitions/guarded_replay" --baseline-implementation "$g/baseline_cn_pit.py" --pit-implementation "$g/src/kurumi/cn_pit.py"
python scripts/recover_cn_orient_prelisting_revenue.py --collection "$a/prelisting_orient" --originals "$a/verified/single_field_originals.jsonl" --baseline "$a/accounting_transitions/guarded_replay/600958/after/financial_versions.jsonl" --release $v --output "$a/prelisting_orient/verified" --pit-implementation "$g/src/kurumi/cn_pit.py"
```

冻结时，两个发行人的 `financial_versions.jsonl` 与各自的 `review.json` 可按 V6 中的旧行 SHA-256 匹配替换，四条招商证券、八条东方证券收入修订和四条东方证券上市前组成期按各自披露时点追加。两个完整输入都需要启用 `revenue_accounting_basis` 检查。[替换、新版本行数与哈希](../artifacts/cn_numeric_followup/financial_securities_revenue/accounting_transitions/source_audit.json)
