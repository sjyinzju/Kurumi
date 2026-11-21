# CN 市场与行业市值分母核验

## V7 发布后的分母复算

当前版本 `cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a` 有 2,813 个市场会话，其中 2,812 个有前日母集。独立复算的前日母集人数与发布数据逐日一致。合计 2,058,395 个前日成员记录缺可验证的普通 A 股类股数，每日缺 285 至 1,745 个，中位数 720.5。按有效收益成员数量计算，有 1,801 个会话达到 99%。完整资本分母可核验的会话为零。 [V7 全量回执](../artifacts/cn_numeric_followup/release7_input/market_weight_blockers_actual.json)

| 交易所 | 前日母集成员记录 | 缺普通 A 股类股数 |
| --- | ---: | ---: |
| SSE | 4,884,915 | 966,410 |
| SZSE | 6,609,472 | 1,054,704 |
| BSE | 245,853 | 37,281 |

2026-06-30 有 5,504／5,526 个有效收益成员，人数覆盖约 99.60%。前日 4,859 个成员具备已验证的实际成交估值，市值合计约 96.475 万亿元。该部分市值作为当日权重分母的下界单独记载，前日仍有 650 个成员缺股类股数。 [逐日与逐所指标](../artifacts/cn_numeric_followup/release7_input/market_weight_blockers_actual.json)

## V5 发布后的分母复算

实际发布版本 `cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c` 的 2,812 个前日母集人数全部通过独立复算。累计缺普通 A 股类股数的前日母集记录为 2,074,690，较 V4 减少 36,307。按日仍缺 288 至 1,751 个可验证股类数量，中位数 725。1,801 个市场日有效成员数量达到 99%。已建立的完整市值分母为零。 [V5 全量分母回执](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c.json)

| 交易所 | 前日母集成员日 | 缺少普通 A 股类股数 | 其中实际行情及 F 齐全 | 有股类股数但缺有效实际复权价格 |
|---|---:|---:|---:|---:|
| SSE | 4,884,915 | 982,705 | 955,070 | 58,921 |
| SZSE | 6,609,472 | 1,054,704 | 1,030,263 | 171,166 |
| BSE | 245,853 | 37,281 | 37,271 | 721 |

2026-06-30 有 5,504／5,526 个有效收益成员，数量覆盖率 99.60%。前日有 4,856 个成员具备已验证的实际成交估值，合计约 95.315 万亿元。仍有 653 个成员缺前日 A 股类股数，17 个有股数而缺有效实际复权价，其中一个具有已核实停牌估值的条件。 [分母与当前状态逐日回执](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c.json)

## V4 发布后的分母复算

对实际发布版本 `cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc` 重算 2,812 个有前置交易日的市场日期，前日母集人数全部与发布数据一致。各市场日缺少 312 至 1,753 个已验证股类股数，中位数 739.5。V4 缺股类股数的前日成员记录为 2,110,997，较 V3 减少 362,709。仍有 1,801 个市场日的有效估值收益数量达到 99%。完整资本分母均无法复算，资本覆盖率为 NULL。 [V4 市场权重逐年及逐所回执](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

| 交易所 | 前日母集成员日 | 缺少普通 A 股类股数 | 其中实际行情及 F 齐全 | 有股类股数但缺有效实际复权价格 |
|---|---:|---:|---:|---:|
| SSE | 4,884,915 | 1,015,207 | 986,685 | 58,034 |
| SZSE | 6,609,472 | 1,057,348 | 1,032,907 | 171,166 |
| BSE | 245,853 | 38,442 | 38,432 | 721 |

2026-06-30 市场有 5,504／5,526 个有效收益成员，数量覆盖率 99.60%。前日已验证股类股数与实际交易估值在 4,820 个成员上相交，合计约 92.247 万亿元。其余 689 个成员缺少可验证股类股数，17 个有股数而无有效实际复权价格，其中一个具备进一步停牌估值候选条件。 [2026-06-30 市场日明细](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

## V3 逐日分母独立复算

实测发布 `cn-27e5ff0cbcccc52e25e4fe03e8f8ac7da7662b480ed3753e6523e62de69f65b6`。从发行证券的前一市场开市日复算母集，2,812 个有前置交易日的日期均与 `market_daily.coverage.return_1d.n_expected` 一致。三所存续期间的交易日历在此区间对齐。首日 2015-01-05 缺预热。

| 交易所 | 前日母集成员日 | 缺少可验证的普通 A 股类股数 | 其中实际行情及 F 齐全 | 有股类股数但缺有效实际复权价格 |
|---|---:|---:|---:|---:|
| SSE | 4,884,915 | 1,336,728 | 1,302,016 | 51,844 |
| SZSE | 6,609,472 | 1,098,536 | 1,072,096 | 169,167 |
| BSE | 245,853 | 38,442 | 38,432 | 721 |

有前置开市记录的每个市场日均缺少 471 至 1,868 个证券的前日股类股数，中位数 868。1,801 个市场日按有效收益成员的数量达到 99%，所有这些日期的完整资本分母仍不可计算。2026-06-30 有 5,503／5,526 个有效收益成员，数量覆盖率 99.58%。6 月 29 日具备已验证股类股数及实际估值的 4,641 个证券合计约 81.195 万亿元，另有 868 个证券缺前日股类股数，其中沪 448、深 368、北 52；17 个证券有股数，实际复权价格仍缺。部分已知值是完整分母的下界。 [机器可读逐日权重核验](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-27e5ff0cbcccc52e25e4fe03e8f8ac7da7662b480ed3753e6523e62de69f65b6.json)

## V2 发布实测

`cn-20796d534b7d3ba59a8054c95d4341bac4e0212ee3b50219d4f78282d5910790` 发布的上海有效证券市值 3,496,751 行，增加 317,028 行。深圳 5,227,017 行，增加 281,302 行。北京 204,229 行，合计缺少证券市值 2,817,776 行。`market_daily` 的 2,813 行和 `industry_daily` 的 363 行仍没有合规资本分母和有效组合收益。下文四家北交所股本补采的 28 个源文件哈希均未在该发布版本的 `pit_provenance` 中作为股本引用。这些补采已冻结并完成独立试算，所影响证券在此版的股类资本行数与对照版一致。 [V2 全量核验](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/cn-20796d534b7d3ba59a8054c95d4341bac4e0212ee3b50219d4f78282d5910790.json) · [V2 四家溯源核验](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/cn-20796d534b7d3ba59a8054c95d4341bac4e0212ee3b50219d4f78282d5910790_bse_provenance_check.json)

## 对照版全量结果

对照版本为 `cn-1778218fa1d94642379210bd3438e987cef73a84925f5e8442d23f2f23d2d2d6`。后续各公司生效证据的潜在补齐数量均以此版为参照。[对照版机器可读核验](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/released_denominator_audit.json)

2015-01-05 至 2026-07-31 的股票开市日密集网格按交易所列裁剪读取。下表的已知证券市值为实际收盘对应的普通股股类市值，缺失数包括行情缺失的证券日。停牌同日依赖包括已知 F、拆股链和股类股数。形成停牌估值还需连续、可用的前置估值。

| 交易所 | 股票开市日 | 可用实际收盘及 F | 已知股类股数 | 已知证券市值 | 缺少证券市值 | 报告／验证整日停牌 | 验证停牌且具备同日依赖 |
|---|---:|---:|---:|---:|---:|---:|---:|
| SSE | 4,887,224 | 4,800,666 | 3,231,499 | 3,179,723 | 1,707,501 | 86,558／3,049 | 1,529 |
| SZSE | 6,612,365 | 6,416,754 | 5,110,835 | 4,945,715 | 1,666,650 | 195,611／7,631 | 6,612 |
| BSE | 246,184 | 245,453 | 204,950 | 204,229 | 41,955 | 731／5 | 3 |

2,813 个 `market_daily` 日期均无可发布组合收益。首日缺预热历史，其后 2,812 日均为 `missing_source`，前一日资本覆盖与停牌估值权重均为空。收益有效成员数为 11,444,917，历史母集成员日数为 11,740,240。部分日期按数量计算超过 99%，契约门槛以完整母集资本分母计算。363 个 `industry_daily` 行均为 `unverified_version`，已知成员合计为 102,780 个成员日，其中 102,447 个成员日具备估值收益。完整历史行业母集与前一日股类资本仍需分别取证。

沪深直接取证的 `official_frozen_v2` 接收了 13,470 条记录，涉及 3,033 个证券。成熟后的 15,405 个生效段检查了未来终点未被提前使用。股类证据流有 9 个多股类版本，该证据流与 `official_frozen_v1` 逐字节一致。[冻结输入核验](E:/Kurumi/artifacts/cn_numeric_followup/capital/official_frozen_v2/runtime_input_acceptance.json) [股类冻结核验](E:/Kurumi/artifacts/cn_numeric_followup/capital/official_frozen_v2/official_share_freeze_audit.json)

## 替代来源实测

抽取六个日期，共经过 17 个日期与交易所组合。TuShare 候选从注册库指向的有效月分区读取并按旧库生效规则去重。东方财富候选只统计 A、B、H 拆分可加总回供应商总股本的行。CSMAR `TRD_Capchg` 使用最近生效日匹配，仅量化候选交集。供应商公告日期字段及生效日期均未用于推定历史原始版本。[机器可读日期探针](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/released_denominator_audit.json)

| 2026-06-30 | 当日证券开市网格 | 发布的有效证券市值 | TuShare 通用总市值 | CSMAR 最近生效发行人股数 | 东方财富可加总 A 股候选 |
|---|---:|---:|---:|---:|---:|---:|
| SSE | 2,310 | 1,710 | 2,296 | 2,310 | 2,222 |
| SZSE | 2,894 | 2,304 | 2,889 | 2,894 | 2,886 |
| BSE | 323 | 268 | 322 | 323 | 323 |

同日匹配的多股类候选中，上海 151 只、深圳 80 只证券的 TuShare 股数与发行人总数一致，且偏离 A 股类股数。工商银行发行人总数 356,406,257,089 股，A 股 269,612,212,539 股。万科两个数分别为 11,930,709,471 和 9,724,196,533 股，特力 A 为 431,058,320 和 392,778,320 股。`daily_basic` 的 `total_share` 和 `total_mv` 服从通用总量口径。`stk_premarket` 从 2024-05-01 起提供通用总股本和流通股本，文档规定另行开通，本次未用凭据请求该接口。[TuShare 每日指标](https://tushare.pro/document/2?doc_id=32) [TuShare 盘前股本](https://tushare.pro/document/2?doc_id=329)

CSMAR `TRD_Dalyr.Dsmvtll` 文档口径从总股本扣除流通 B、H 和其他境外流通股，据该字段说明仍需独立确认其他股类、限制股与原始时间版本。当前本地只有计数和失败回执，历史样例查询返回 `-2404` 当日下载达到上限。`TRD_Capchg` 已留档 142,626 条，`Nshra` 为流通 A 股，原提取没有公开时间字段。`TRD_Cptl` 实施事件已另行用于可核验子集。三个表所需的完整历史来源链仍未建立。[CSMAR 数据说明](https://file.csmar.com/group1/M00/AA/99/CuIKV2XAnKiABeLbAB4nDGC5Ano840.pdf) [CSMAR 本机审计](E:/Kurumi/docs/cn_csmar_source_audit.md)

深交所发布的两个月末跨所统计有 A 股类别总市值，可做量级复核。2024-10-31，发布证券市值之和占此汇总的比例分别为上海 54.84%、深圳 78.08%、北京 92.88%。2025-07-31 对应为 47.55%、63.62%、79.54%。这些比例用于事后诊断，当时的证券母集对齐、逐证券停牌估值和对应的点时公开版本无法由月末四舍五入汇总验证。上海历史个股市值排行只列前十，公司概况索引也标明应以原 PDF 为准。行业与市场的日度资本分母依旧需要逐证券证据。[深交所 2024 年 10 月统计](https://docs.static.szse.cn/www/aboutus/research/secuities/daily/W020241121369413914940.pdf) [深交所 2025 年 7 月统计](https://zqscdb.szse.cn/cn/article/pdf/preview/c74d6083-fd28-4742-83ee-11178e9fb21d.pdf) [上交所历史市值排名](https://www.sse.com.cn/market/stockdata/marketvalue/main/index_his.shtml) [上交所公司概况](https://www.sse.com.cn/assortment/stock/list/info/company/)

## 北交所公开来源

当前页面的官方股票列表接口返回 HTTP 200，响应含 `xxzgb` 总股本、`xxfxsgb` 非限售股本、`xxtpbz` 停牌标志、日期字段 `xxjsrq` 和 `xxgxsj` 记录更新时间。2026-11-20 对 `920000` 的对照查询以及附 `xxjsrq=20260630` 查询，响应哈希完全相同，均为当日 08:30 的快照。交易支持平台 `NQXX.DBF` 规范包含相应的股本、停牌和记录时间字段，现有研究环境未取得按历史交易日归档的原始 DBF。公开统计页面可读，两个附属脚本访问返回 HTTP 403。公告查询直接探针返回 HTTP 200，正文为请求参数异常。[北交所上市公司列表](https://www.bse.cn/nq/listedcompany.html) [交易支持平台数据接口规范](https://www.bse.cn/uploads/6/file/public/202209/20220902201701_kas8vw9r25.pdf) [北交所统计](https://www.bse.cn/static/statisticdata.html) [公开请求回执](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/bse_issuer_probe_receipt.json)

北交所站点、巨潮和公告镜像保留了部分发行人历史披露。北交所旧代码 `830799` 和新代码 `920799` 锁定同一只艾融软件。档案给出 2022 年末普通股总数 210,688,500 股，2023 年末为 210,369,300 股。审计保留实际公开日和原文件哈希，逐段取证进展记录在同目录的北交所发行人回执。公告能修复点时股本子集。全市场所需的完整历史证券日、公司行动和停牌证据仍未取得。[新旧代码对照](https://www.bse.cn/service/code_mapping.html) [艾融软件 2022 年报](https://www.bse.cn/disclosure/2023/2023-04-26/4977c9e9351545fc9547c4def1c3cf9b.pdf) [艾融软件 2023 年财务报表](https://www.bse.cn/disclosure/2024/2024-04-19/c3f451e91d85451e9256f7dfc1f534b5.pdf)

艾融软件的 8 条已发布实施公告及其更正版文本均与有效期档案复核。12 个公告 JSON 原件及单独的 PDF 请求回执均已留存，后者返回 HTML，正文来源保留为镜像。对照 CSMAR 的股类拆分与公告生效日，实际发布版中的 977 个有价格但无股类资本证券日可以补证。复用 `build_pit` 对该证券的真实 1,143 个证券日和供应商比较记录试算，991 行从已有空值变为有值。额外 14 行处于生效与公告时点之间或来源日期争议，继续使用旧已公开股数会保留过期计量，仍需单列处理。现有正市值与试算相同。[艾融软件逐行范围](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/bse_830799_capital_coverage.json) [实际 PIT 试算](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/frozen_830799/real_materialization_audit.json)

按实际未覆盖证券日对下一批五家北交所发行人做定向补采，查询 53 个股本事件和 132 个可定位的候选公告，26 个事件在至少一个正文中见到相同股数。请求回执区分 HTTP 567 和连接代理错误。逐项核对精确日期、前后总股数、股类身份和连续生效链后，追加大唐药业 7 个可用版本和同享科技 4 个可用版本。分别可为 550 和 676 个旧版有价格缺市值的证券日补证。同享科技有 13 个证券日涉及供应商时间口径差异，发行人的 2024-080 原件确认 2024-06-12 登记，CSMAR 记录的 2024-06-30 为较晚的观察日。[下一批取证回执](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/bse_direct_followup/bse_archive_candidate_audit.json) [大唐药业资料](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/frozen_920433/datang_capital_audit.json) [同享科技资料](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/frozen_920167/920167_capital_audit.json)

德源药业随后取得 9 个生效阶段的原始材料，其中 2023-044、2023-074 和 2024-080 确定三次注销的实际生效日期及变更前后股数。另两份官方权益分派实施公告确认 2025 年和 2026 年转增的生效日期。该补采可为 603 个旧版有价格缺市值的证券日补证。四家合计 28 个冻结版本，涵盖 2,806 个有价格缺市值的证券日。生产 PIT 对四家 4,572 个证券日及实际 `daily_basic` 的股本比较记录试算后，既有正市值均一致。试算中另有 29 行沿用了当时最新公开股数，包含比对供应商生效日期分歧与公告晚于生效的日期，列在覆盖回执中。[德源药业公告原件回执](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/deyuan_support/deyuan_originals_receipt.json) [德源药业资料](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/frozen_920735/920735_capital_audit.json) [四家冻结清单](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/bse_additional_share_freeze_manifest.json) [四家实际 PIT 试算](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/real_materialization_four_issuers.json)

三家发行人的实际 PIT 试算共读取 3,429 个证券日，既有正市值无变化。共 2,203 个缺失证券日具备公告时点和生效期证据。另有 19 个原缺失证券日和 7 个原有正市值证券日，实际注销生效早于日期级公告的纳入时点。艾融软件另有一日发生供应商与发行人登记日不一致。任一公告索引的 `eitime` 字段属于生产时间。现场未取得这些日期的可公开时分秒或事先确认的截止日。保留此前版本所用的当时可得信息，逐日附上审计证据。[三家实际 PIT 试算](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/real_materialization_three_issuers.json) [逐日公开时点差异](E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/bse_share_disclosure_lag_audit.json) [东方财富字段说明](https://quantapi.eastmoney.com/Upload/EMQuantAPI_Python.html?_=639264418875952885) [北交所文件分发测试方案](https://www.neeq.cc/uploads/1/file/public/202502/20250226194410_7geq0u1r9r.pdf)

## 复核命令

```powershell
$latest = Get-Content E:/QuantData/numeric/latest_cn.json -Raw | ConvertFrom-Json
$original = Get-ChildItem E:/QuantData/numeric/.build-cn/sources/csmar/requests/TRD_Capchg -Filter '*.jsonl.gz' -File | Select-Object -First 1
python E:/Kurumi/scripts/audit_cn_market_denominator.py "E:/QuantData/numeric/$($latest.path)" `
  --csmar-capital $original.FullName `
  --eastmoney-capital E:/Kurumi/artifacts/cn_equity_candidates/eastmoney_equity_cn.parquet `
  --output "E:/Kurumi/artifacts/cn_numeric_followup/market_denominator/$($latest.dataset_version).json"
```
