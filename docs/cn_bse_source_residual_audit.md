# 北交所复权差异与停牌来源核验

首轮缺口盘点基于实际发布版 `cn-20796d534b7d3ba59a8054c95d4341bac4e0212ee3b50219d4f78282d5910790`。实际发布的 V4 `cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc` 已逐键通过 784 个新增单位链来源的回读，包括北交所 82 个键和沪深精度 702 个键。全部 726 个目标停牌日可从实际训练包复验。北交所现有 731 个已证实整日停牌日，供应商报告且未经证实的记录为零。四个实际送转单位乘数和各目标键的原始收盘、成交股数、F 分别与 V3 按键对照。 [V4 独立发布验收](E:/Kurumi/artifacts/cn_numeric_followup/capital/bse_remaining_reported_halts/bse_release_verification_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

V3 到 V4 的 34,855,830 条标签已逐键流式比较。15,372 条仅更新 `target_provenance_id`，对应 13,299 条历史证券简称来源和 2,073 条北交所停牌来源。所有 13 个其余字段逐条一致，包括未来收益、标准化收益、分档、目标日期、监督掩码及无效原因。 [全量标签差异及原始引用核验](E:/Kurumi/artifacts/cn_numeric_followup/label_release_diff_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

## 股数单位链

82 个单位链缺口包含 55 个来源精度变化、23 个现金分派和四个真实送转。原始报价与复权因子共核验 108 个 TuShare 原始批次的哈希及行数。三套独立档案检查相邻交易日间的实施分派、股本变更及可用历史范围。

| 交易日 | 比较证券数 | F 值改变 | 与同日精度方向一致 |
|---|---:|---:|---:|
| 2022-04-20 | 90 | 73 | 73 |
| 2022-05-30 | 93 | 77 | 73 |
| 2022-06-30 | 100 | 90 | 89 |
| 2023-06-01 | 198 | 169 | 167 |
| 2024-05-15 | 248 | 204 | 202 |
| 2024-06-26 | 249 | 214 | 210 |

精度分组在三位与四位小数间切换。47 个缺口有前收盘、上一实际收盘及公司行动档案共同验证。另有七个缺口处在独立证明的连续停牌期间。连城数控 2022-06-30 仅涉及高管所持股份分类变动，总股本仍为 232,502,800 股，F 从 2.2117 变为 2.212，当日参考前收盘与前一实际收盘均为 70.51 元。核验仅覆盖表列日期和精确匹配的证券。未找到供应商针对这些日期的精度公告。 [TuShare 复权因子](https://tushare.pro/document/2?doc_id=28) · [TuShare 日线字段](https://tushare.pro/document/2?doc_id=27) · [连城数控半年度报告](https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=8499596&stockid=835368)

23 个现金分派均找到在除息日前公布的实施原件。22 个有交易的样本用发行人公告中的除息参考口径复算至分，与供应商前收盘完全一致。泰祥股份在 2022-05-18 的现金分派发生于持续停牌期间，停牌原件和分派原件均已核验。对回购专户剔除的案例分别保存每参与股现金和按全部股本折算的参考派息。 [北交所交易规则（试行）](https://www.bse.cn/uploads/6/file/public/202109/20210909101516_y5wn2y3ft9.pdf)

| 证券 | 生效交易日 | 原件公告号 | 每旧股单位乘数 |
|---|---|---|---:|
| 920414.BJ 欧普泰 | 2023-06-07 | 2023-047 | 2.0 |
| 920970.BJ 大禹生物 | 2023-06-14 | 2023-049 | 2.0 |
| 920593.BJ 鼎智科技 | 2023-09-21 | 2023-109 | 2.0 |
| 920765.BJ 美之高 | 2025-06-09 | 2025-028 | 1.3 |

合并复演通过生产来源解析器、精确生效区间和累计单位链检查。四个乘数来自送转实施条款，覆盖补充仅作用于按档案核验的交易日。四只证券的生效日前单位前缀已逐一比对。 [美之高实施公告](https://static.cninfo.com.cn/finalpage/2025-05-28/1223715103.PDF)

## 历史停牌

三只转板股票的初始公告、六份停牌期间公告和终止上市公告合计证明 439 个开市交易日。其余 287 个供应商报告的停牌日分属 22 只股票、33 个区间。285 个交易日由提前公布的停牌、续停和复牌原件证明。所有 33 个复牌日的已发布行情均有真实正价格，核验区间不包含复牌日。 [北交所 2021 年停复牌业务指南](https://www.bse.cn/cxjg_list/200010918.html) · [北交所 2022 年转板指引](https://www.bse.cn/cxjg_list/200011821.html)

浩淼科技 2023-10-16 与曙光数创 2025-05-26 的交易所原件仅提供公告日。同日新闻发布记录分别证明 22:43:10 和 09:03 前同一停牌事实已公开，均早于 23:59:59 样本时点。曙光数创的时间源精确到分钟，09:03:00 是公开可得的保守上界。留存原件日期和公众可得上界的独立来源证据，未将供应商处理时间或新闻时间写成发行人首次公开时间。 [浩淼同期采访](https://www.nbd.com.cn/articles/2023-10-16/3055106.html) · [曙光同期报道](https://m.caizhongshe.cn/article-7332570465183659952.html) · [曙光北交所原件](https://www.bse.cn/disclosure/2025/2025-05-26/0e8f91103615427aa3c0451e8cc5f7da.pdf)

合计 726 个来源增强交易日的检查包括交易所开市日、证券存续区间、原始行情批次和源记录。220 个有效输入的既有目标此前已标注 `target_suspended`。这些停牌证据用于核验状态和来源，220 个目标的监督和真实收益仍不可用。

## 沪深同期精度核查

沪深此前有 5,566 个未解释的 F 跳变。对四个整批可复现的精度切换日核验了 1,024 个精确匹配候选。其中 702 个通过原始批次、前收盘及完整独立公司行动档案三重检查。其余 322 个候选仍有同日档案事件、报价变化或报价缺口，保留原有缺失状态。

| 交易日 | 沪深比较证券数 | F 值改变 | 与同日精度方向一致 | 通过完整核验的缺口 |
|---|---:|---:|---:|---:|
| 2018-08-16 | 3,536 | 3,134 | 2,938 | 241 |
| 2018-08-28 | 3,537 | 3,138 | 2,947 | 241 |
| 2022-06-30 | 4,716 | 1,263 | 1,203 | 153 |
| 2024-05-15 | 5,114 | 322 | 299 | 67 |

沪深来源核验使用 `scripts/audit_cn_mainland_factor_precision.py`。增量及生产来源复演位于 `artifacts/cn_numeric_followup/capital/mainland_precision_pass1`。2023-06-01 的 405/416 和 2024-06-25 的 349/353 个沪深缺口前后均为三位小数，变化幅度集中在 0.001。其精度变化来源仍待证实，保留原状态。

## 沪深现金除息核查

在排除上述 702 个精度条目后，既有 CSMAR 和 TuShare 档案有 3,118 个候选符合证券身份、公告日、除息日和名义含税金额一致，且没有同期单位变动候选。1,884 个候选的企业现金派息与当日原始参考前收盘精确一致，F 原始值同时通过记录精度约束。

另有 663 个候选的名义派息与参考前收盘不同。对全部 663 个取得并核对了发行人公开实施原件，649 个可按公告明确披露的差异化派息参考量复算，均通过原始报价及因子记录精度检查。其中 53 个以原件或更正版逐条人工复核。宁德时代 2026-04-22 以 A 股总股本折算后的每股 6.9065252 元计算除息，名义分派为 6.957 元。

合计可补证 2,533 个沪深现金除息交易日，其中上海 1,281、深圳 1,252。与精度增量合并，生产来源解析与精确生效段共复演通过 3,235 个独立键。14 个差异化派息候选因原件未明确股票除息参考金额或结算口径保留；571 个缺少相邻实际报价，其中 554 个前后均无报价、14 个仅前日缺失、三个仅当日缺失。发行人回购价格或转债价格调整保留为旁证。 [沪深现金冻结增量](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/frozen_all_verified/split_coverage_mainland_cash_additions.jsonl) · [机器可读复演](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/frozen_all_verified/cash_combined_production_audit.json)

对 571 个缺少相邻报价的候选，已逐项核查 2020 年以后的 14 个键。全部取得发行人现金分派及停复牌原件。33 个有效原始行情分片在所审 27 个无报价证券日中没有对应记录。生产停牌解析复演通过 25 个当时已知的整日停牌键。中广核技 2022-06-28、联合光电 2025-05-20 的停牌原件只有当日日期，缺少独立的日内公开时点，未进入停牌增量。 [联合光电停牌原件](https://static.cninfo.com.cn/finalpage/2025-05-20/1223591254.PDF) · [沪深停牌补采回执](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_cash_2020_2026/suspended_cash_verified_receipt.json)

13 个现金除息键通过最终实际成交原始报价、暂停期间完整的交易所开市格、当时公开的现金口径及 F 的记录精度复核，另行冻结为 U 覆盖来源。深深房 2020-05-14 实施原件将具体除息日期写为 2019 年，该现金除息键继续保留缺失状态。此组文件独立记录，进入构建时按各发布版本的来源清单确认。 [深深房实施公告及同日续停公告](https://epaper.cs.com.cn/zgzqb/html/2020-05/14/nw.D110000zgzqb_20200514_5-B043.htm) · [停牌增量](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_cash_2020_2026/suspension_cash_on_halt_additions.json) · [现金除息覆盖增量](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_cash_2020_2026/split_coverage_cash_on_halt_additions.jsonl)

2019 年的 8 个候选均取得发行人现金分派及停复牌材料，原始行情分片及生产解析复验支持 7 个 U 覆盖键和 12 个已知整日停牌日。深深房 2019-05-21 的原件日期一致，前 60 个日历日仍无可用的原始成交锚点，保留该 U 缺口。已单独冻结其停牌证据。 [2019 年逐项来源及复验](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_cash_2019/suspended_cash_verified_receipt.json)

2018 年的 91 个候选均通过精确现金及股数单位覆盖复验。相邻的 182 个无报价交易日中，174 个通过日期级公开规则。两只长期停牌证券的历史真实成交锚点跨越 2018-08-16 与 2018-08-28 的供应商精度切换。四个单位覆盖键和相邻八个整日停牌日分别有原始 F 行、完整独立事件档案和提前公开的发行人停牌证据。派思股份 2018-06-01 的发行人原件确认 5 月 31 日登记及每股现金 0.015 元。三组现金停牌证据和这四个精度键合并后，共对 115 个精确单位覆盖日和 219 个精确停牌日执行生产解析复验。 [2018 年逐项核验](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_cash_2018/suspended_cash_verified_receipt.json) · [四个精度键](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_precision_bridge_2018/suspended_cash_verified_receipt.json) · [冻结增量](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/frozen_suspended_cash_2018_2026_final/suspended_cash_followup_audit.json)

对八个只有公告日期的沪深停牌日，另取得三个有同日时间戳的公开事实来源。新华制药 2018-01-25、金正大 2018-06-15、鸿利智汇 2018-05-28 的开市停牌分别已于 08:19:59、09:17:03、07:35:59 前公开。三日的时间证据与发行人原件分列，原始行情均确认无报价，生产解析已复验。其余五日仍无足够匹配的同时期公开时钟。 [新华制药同时期报道](https://finance.sina.com.cn/stock/s/2018-01-25/doc-ifyqyuhy6206750.shtml) · [金正大同时期报道](https://www.nbd.com.cn/articles/2018-06-15/1226317.html) · [鸿利智汇同时期报道](https://finance.sina.com.cn/stock/s/2018-05-28/doc-ihcaquev2321760.shtml) · [独立时间证据](E:/Kurumi/artifacts/cn_numeric_followup/capital/mainland_cash_gaps/suspended_cash_2018/public_clocks/same_day_halt_clock_audit.json)

## 复验入口

- `scripts/audit_cn_bse_factor_discrepancies.py` 读取原始报价与因子批次和独立行动档案。
- `scripts/collect_cn_bse_residual_cash.py`、`scripts/verify_cn_bse_cash_originals.py` 保存实施原件并复算除息。
- `scripts/freeze_cn_bse_unit_additions.py` 复演生产来源解析和单位链。
- `scripts/verify_cn_bse_halt_additions.py`、`scripts/collect_cn_bse_reported_halts.py`、`scripts/verify_cn_bse_reported_halts.py`、`scripts/freeze_cn_bse_halt_clocks.py` 核验原件、真实交易日与市场状态补充记录。
- `scripts/audit_cn_mainland_cash_gaps.py`、`scripts/collect_cn_mainland_differential_cash.py`、`scripts/verify_cn_mainland_differential_cash.py` 和 `scripts/freeze_cn_mainland_cash_gaps.py` 按名义派息及公告明确的差异化结算口径复算原始参考前收盘并冻结增量。
- `scripts/collect_cn_mainland_suspended_cash.py` 和 `scripts/verify_cn_mainland_suspended_cash.py` 取得并复核缺少相邻实际报价时的分派和停复牌原件。

机器可读结果位于 `artifacts/cn_numeric_followup/capital/action_reconciled_full_extension/bse_split_v4_full_additions`、`artifacts/cn_numeric_followup/capital/action_reconciled_full_extension/bse_suspension_v4_additions` 及 `artifacts/cn_numeric_followup/capital/bse_remaining_reported_halts`。供后续构建合并的文件与来源回执在各子目录同存。
