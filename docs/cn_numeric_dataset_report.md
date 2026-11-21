# CN 数值数据集报告

`INCOMPLETE`。版本 `cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a`。数据目录为 `E:\QuantData\numeric\cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a`。

包含沪、深、北普通 A 股。价格及监督观察截至 2026-07-31，样本截至 2026-06-30。Xtext 记录为 `not_built`。

## 存储和清理

| 目录 | 迁移前文件 | 迁移前 GiB | 迁移后文件 | 迁移后 GiB |
|---|---:|---:|---:|---:|
| `00_raw` | 434,934 | 8.275 | 434,934 | 8.275 |
| `10_canonical` | 1,077,205 | 90.248 | 1,074,079 | 89.458 |
| `40_qlib` | 105,854 | 0.022 | 105,854 | 0.022 |
| `80_quarantine` | 113 | 0.000 | 113 | 0.000 |
| `90_metadata` | 939 | 0.526 | 949 | 0.527 |
| `numeric` | 0 | 0.000 | 2,648 | 49.925 |
| `quant.duckdb` | 1 | 1.125 | 1 | 1.125 |
| `reports` | 1,158 | 10.024 | 1,159 | 10.024 |

全盘可用空间由 42.596 GiB 变为 25.948 GiB。发布清单内文件大小合计 3.426 GiB。

本轮开始时 E 盘剩余约 28.71 GiB。目录对比以首轮建设前保存的清单为基线。

本轮清除了两个与现行／冻结清单无引用的旧财务试算文件，合计 782,711,202 字节。操作期间另有构建写盘，E 盘实测净回升 342,638,592 字节。旧库目录总量、盘符剩余量和本轮操作释放量各自统计。 [旧库回收记录](cn_legacy_reclamation.md)

第四版记录 316 次物理采样。DuckDB 临时文件最大实占 0.000 GiB。硬链接只计一次。

第五版记录 461 次物理采样。DuckDB 临时文件最大实占 0.000 GiB，硬链接只计一次。

第五版清理三个独立、校验相同的生成副本，共 778,885,687 字节。E 盘即时实测净回升 778,891,264 字节。 [回收回执](../artifacts/cn_numeric_followup/release5_input/working_copy_reclamation.json)

第六版记录 421 次物理采样。DuckDB 临时文件最大实占 0.000 GiB，硬链接只计一次。

第六版核验并清除五个独立工作副本，共 796710928 字节。E 盘实测净增 796721152 字节。 [回收回执](../artifacts/cn_numeric_followup/release6_input/working_copy_reclamation.json)

第七版物理盘采样 362 次，构建期间 E 盘最小剩余 23.433 GiB。

第七版清除 3 个与冻结字节完全相同的工作副本，E 盘即时净增 775536640 字节。 [工作副本](../artifacts/cn_numeric_followup/release7_input/working_copy_reclamation.json)

清除一个可按原 SHA-256 重建的单发行人财务试算，实占 477366177 字节。E 盘即时净增 477368320 字节。 [试算清理](../artifacts/cn_numeric_followup/release7_input/trial_reclamation.json)

已删失效进度临时文件 2 个和空审计目录 64 个，释放 18,880 字节。经等价性验证的 Canonical 回收 3,126 个文件，释放 847,904,002 字节。

本轮另清理了 2 个未发布的旧导出目录，涉及 3 个文件和 62,703,550 字节。

当前发布复用了旧版本中逐字节一致的 32 个 Parquet 文件。

构建阶段定时观测的 numeric 最大占用 38.027 GiB，E 盘最少剩余 23.433 GiB。抽样按文件身份合并硬链接。目录清单按路径统计。

当前 quant 注册表、活跃视图及仍被实际版本引用的源分片供原项目使用。训练包读取以本版本的 Parquet 清单为入口。

回收后检查了 8,540 个当前分片和 46 个注册版本的引用。历史版本共引用 9,435 个不同分片，缺失 0 个。另有 1,065,522 个非活跃注册分片，等价性或引用证据并未全部核实。

旧全库备份计划已按回收范围归档并退役，原哈希及回收判据留档。见 [旧库回收记录](cn_legacy_reclamation.md)。

## 六张核心表

| 表 | 主键 | 行数 | 起止日期 | Parquet GiB |
|---|---|---:|---|---:|
| `stock_daily` | instrument_id, local_trade_date | 11,745,773 | 2015-01-05 至 2026-07-31 | 1.518 |
| `stock_fundamental_asof` | fundamental_snapshot_id | 198,118 | 2012-03-09 至 2026-05-15 | 0.024 |
| `market_daily` | market_id, local_trade_date | 2,813 | 2015-01-05 至 2026-07-31 | 0.000 |
| `industry_daily` | market_id, industry_system, classification_version, industry_code, local_trade_date | 13,987 | 2023-02-08 至 2026-07-31 | 0.000 |
| `samples` | sample_id | 11,618,610 | 2015-01-05 至 2026-06-30 | 0.086 |
| `labels` | sample_id, horizon | 34,855,830 | 2015-01-05 至 2026-06-30 | 1.250 |

完整字段、Arrow 类型、单位和主键见发布包 `schema.json`。按交易所、年份、字段和原因的分布见 `reports/field_coverage.parquet`，30 个因子、市场及行业字段的分母、有效项与覆盖见 `reports/feature_coverage.parquet`。

## 全量覆盖

| 交易所 | 证券日 | 实际收盘 | 复权有效 | 输入有效 | 停牌事实 | 停牌时点证据 | 股数 | 发行人市值 | U 链 | 财务 | 行业 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BSE | 246,184 | 245,453 | 246,184 | 224,672 | 731 | 731 | 208,853 | 208,071 | 246,184 | 241,357 | 323 |
| SSE | 4,887,224 | 4,800,666 | 4,887,224 | 4,427,053 | 86,558 | 3,115 | 3,920,503 | 3,837,619 | 4,886,247 | 4,811,972 | 53,777 |
| SZSE | 6,612,365 | 6,416,754 | 6,612,365 | 5,848,297 | 195,611 | 7,787 | 5,557,244 | 5,371,400 | 6,610,856 | 6,540,184 | 63,782 |

### 本轮前后对比

| 交易所 | 实际收盘 | 股数 | 发行人市值 | U 链 | 财务 | 行业 |
|---|---:|---:|---:|---:|---:|---:|
| BSE | 245,453 → 245,453 | 0 → 208,853 | 0 → 208,071 | 0 → 246,184 | 0 → 241,357 | 0 → 323 |
| SSE | 4,800,666 → 4,800,666 | 184 → 3,920,503 | 184 → 3,837,619 | 183 → 4,886,247 | 5,647 → 4,811,972 | 47,500 → 53,777 |
| SZSE | 6,416,740 → 6,416,754 | 293 → 5,557,244 | 293 → 5,371,400 | 292 → 6,610,856 | 22,689 → 6,540,184 | 55,891 → 63,782 |

## 因子与市场状态覆盖

下表分母为各表实际发布行数。行业表只列已有可核验归属线索的行业和时段，完整母集门槛独立核查。

| 表 | 字段 | 上版有效值 | 有效值 | 发布行数 |
|---|---|---:|---:|---:|
| `industry_daily` | `above_ma20_ratio` | 0 | 0 | 13,987 |
| `industry_daily` | `activity_proxy_ratio_20d` | 0 | 0 | 13,987 |
| `industry_daily` | `advance_ratio` | 0 | 0 | 13,987 |
| `industry_daily` | `excess_market_20d` | 0 | 0 | 13,987 |
| `industry_daily` | `return_1d` | 0 | 0 | 13,987 |
| `industry_daily` | `return_20d` | 0 | 0 | 13,987 |
| `industry_daily` | `return_5d` | 0 | 0 | 13,987 |
| `industry_daily` | `return_60d` | 0 | 0 | 13,987 |
| `industry_daily` | `volatility_20d_daily` | 0 | 0 | 13,987 |
| `industry_daily` | `volatility_60d_daily` | 0 | 0 | 13,987 |
| `market_daily` | `above_ma20_ratio` | 0 | 0 | 2,813 |
| `market_daily` | `above_ma60_ratio` | 0 | 0 | 2,813 |
| `market_daily` | `activity_proxy_ratio_20d` | 0 | 0 | 2,813 |
| `market_daily` | `advance_ratio` | 0 | 0 | 2,813 |
| `market_daily` | `drawdown_from_peak_60d` | 0 | 0 | 2,813 |
| `market_daily` | `return_1d` | 0 | 0 | 2,813 |
| `market_daily` | `return_20d` | 0 | 0 | 2,813 |
| `market_daily` | `return_5d` | 0 | 0 | 2,813 |
| `market_daily` | `return_60d` | 0 | 0 | 2,813 |
| `market_daily` | `return_dispersion_1d` | 0 | 0 | 2,813 |
| `market_daily` | `suspension_ratio` | 0 | 0 | 2,813 |
| `market_daily` | `turnover_total_median` | 0 | 0 | 2,813 |
| `market_daily` | `volatility_20d_daily` | 0 | 0 | 2,813 |
| `market_daily` | `volatility_60d_daily` | 0 | 0 | 2,813 |
| `stock_daily` | `beta_market_60d` | 0 | 0 | 11,745,773 |
| `stock_daily` | `book_to_market` | 477 | 8,277,175 | 11,745,773 |
| `stock_daily` | `drawdown_from_peak_60d` | 10,514,180 | 10,514,344 | 11,745,773 |
| `stock_daily` | `earnings_yield_ttm` | 293 | 3,364,539 | 11,745,773 |
| `stock_daily` | `excess_industry_20d` | 0 | 0 | 11,745,773 |
| `stock_daily` | `excess_industry_5d` | 0 | 0 | 11,745,773 |
| `stock_daily` | `excess_market_20d` | 0 | 0 | 11,745,773 |
| `stock_daily` | `excess_market_5d` | 0 | 0 | 11,745,773 |
| `stock_daily` | `liabilities_to_assets` | 18,465 | 10,172,855 | 11,745,773 |
| `stock_daily` | `liquidity_proxy_percentile_20d` | 11,132,961 | 11,133,038 | 11,745,773 |
| `stock_daily` | `market_cap_percentile` | 477 | 9,455,691 | 11,745,773 |
| `stock_daily` | `net_margin_ttm` | 654 | 4,408,764 | 11,745,773 |
| `stock_daily` | `operating_cashflow_to_assets_ttm` | 625 | 2,891,032 | 11,745,773 |
| `stock_daily` | `price_ma20_gap` | 11,132,961 | 11,133,038 | 11,745,773 |
| `stock_daily` | `price_ma60_gap` | 10,514,180 | 10,514,344 | 11,745,773 |
| `stock_daily` | `profit_change_to_assets` | 156 | 3,283,970 | 11,745,773 |
| `stock_daily` | `residual_volatility_60d` | 0 | 0 | 11,745,773 |
| `stock_daily` | `return_1d` | 11,444,894 | 11,444,912 | 11,745,773 |
| `stock_daily` | `return_20d` | 11,116,311 | 11,116,391 | 11,745,773 |
| `stock_daily` | `return_5d` | 11,373,623 | 11,373,657 | 11,745,773 |
| `stock_daily` | `return_60d` | 10,499,856 | 10,500,022 | 11,745,773 |
| `stock_daily` | `revenue_growth_yoy_ttm` | 156 | 4,106,162 | 11,745,773 |
| `stock_daily` | `roa_ttm` | 625 | 3,553,771 | 11,745,773 |
| `stock_daily` | `roe_ttm` | 3,438 | 3,522,693 | 11,745,773 |
| `stock_daily` | `sales_to_market_ttm` | 293 | 3,313,013 | 11,745,773 |
| `stock_daily` | `turnover_total_1d` | 477 | 9,455,691 | 11,745,773 |
| `stock_daily` | `turnover_total_mean_20d` | 439 | 8,859,235 | 11,745,773 |
| `stock_daily` | `volatility_20d_daily` | 11,116,311 | 11,116,391 | 11,745,773 |
| `stock_daily` | `volatility_60d_daily` | 10,499,856 | 10,500,022 | 11,745,773 |
| `stock_daily` | `volume_ratio_1_20` | 407 | 11,103,425 | 11,745,773 |

## 样本与监督

| Split | 期限 | 候选 | 有效 | 无效 | 七档计数（0 至 6） |
|---|---:|---:|---:|---:|---|
| train | 1 | 8,367,214 | 7,204,031 | 1,163,183 | 431,912 / 1,548,978 / 1,553,595 / 213,783 / 1,607,936 / 1,391,205 / 456,622 |
| train | 5 | 8,367,214 | 7,162,408 | 1,204,806 | 464,276 / 1,599,021 / 1,575,009 / 81,375 / 1,510,415 / 1,454,431 / 477,881 |
| train | 20 | 8,367,214 | 7,049,692 | 1,317,522 | 453,096 / 1,699,161 / 1,537,862 / 34,495 / 1,419,447 / 1,419,278 / 486,353 |
| validation | 1 | 626,520 | 608,160 | 18,360 | 53,065 / 136,405 / 125,680 / 13,515 / 129,857 / 112,418 / 37,220 |
| validation | 5 | 626,520 | 587,208 | 39,312 | 62,560 / 143,202 / 126,817 / 4,971 / 111,238 / 99,944 / 38,476 |
| validation | 20 | 626,520 | 508,836 | 117,684 | 64,195 / 125,177 / 107,426 / 1,819 / 91,114 / 88,027 / 31,078 |
| calibration | 1 | 669,981 | 650,887 | 19,094 | 30,707 / 143,820 / 139,765 / 15,589 / 144,942 / 126,104 / 49,960 |
| calibration | 5 | 669,981 | 629,517 | 40,464 | 22,236 / 141,139 / 148,199 / 6,315 / 129,623 / 122,312 / 59,693 |
| calibration | 20 | 669,981 | 550,432 | 119,549 | 9,546 / 83,027 / 123,321 / 2,560 / 116,848 / 121,470 / 93,660 |
| test | 1 | 1,954,895 | 1,891,181 | 63,714 | 101,238 / 402,164 / 423,212 / 44,049 / 430,361 / 362,963 / 127,194 |
| test | 5 | 1,954,895 | 1,889,664 | 65,231 | 106,464 / 387,394 / 428,570 / 18,166 / 426,494 / 385,873 / 136,703 |
| test | 20 | 1,954,895 | 1,888,189 | 66,706 | 107,398 / 415,639 / 385,047 / 7,983 / 412,829 / 407,899 / 151,394 |

### 监督无效原因

| Split | 期限 | 无效原因及数量 |
|---|---:|---|
| train | 1 | `input_invalid` 1,150,290、`target_suspended` 7,673、`cross_split` 5,220 |
| train | 5 | `input_invalid` 1,150,290、`target_suspended` 28,415、`cross_split` 26,101 |
| train | 20 | `input_invalid` 1,150,290、`cross_split` 104,452、`target_suspended` 62,756、`target_delisted_no_quote` 24 |
| validation | 1 | `input_invalid` 12,985、`cross_split` 5,194、`target_suspended` 181 |
| validation | 5 | `cross_split` 25,967、`input_invalid` 12,985、`target_suspended` 360 |
| validation | 20 | `cross_split` 103,962、`input_invalid` 12,985、`target_suspended` 730、`target_delisted_no_quote` 7 |
| calibration | 1 | `input_invalid` 13,699、`cross_split` 5,251、`target_suspended` 144 |
| calibration | 5 | `cross_split` 26,269、`input_invalid` 13,699、`target_suspended` 496 |
| calibration | 20 | `cross_split` 105,065、`input_invalid` 13,699、`target_suspended` 785 |
| test | 1 | `input_invalid` 62,868、`target_suspended` 846 |
| test | 5 | `input_invalid` 62,868、`target_suspended` 2,363 |
| test | 20 | `input_invalid` 62,868、`target_suspended` 3,812、`target_delisted_no_quote` 26 |

各 split 的实际训练清单和期限掩码见 `reports/training_samples.parquet`。按交易所、年份、行业、期限、分档和排除原因的全量统计见 `reports/coverage.parquet`。

至少有一个有效期限的实际清单行数为 `calibration` 651,003、`test` 1,891,977、`train` 7,209,690、`validation` 608,311。

## 补采与证据

日历、补采请求、证据原件来源、公开时间及版本哈希见 `reference/`。每日实际收盘与经证实停牌的市场估值分开保存。停牌填估值的规则只适用于市场与行业聚合。

14 个早期深市证券日按 BaoStock 的实际成交恢复，东方财富同日开、高、低、收逐项一致。已定位旧停牌标志造成的错误过滤，并保留原供应商记录及双来源回执。161 个停牌日 F 已按独立除权除息档案和有据可核的累计因子重建。停牌估值未写入实际收盘。

北交所凯德石英的停牌及复牌公告已下载原件并登记 SHA-256。停牌期在交易状态和估值审计使用原始公开日，股权转让意向不产生股数单位变化。 [停牌公告](https://www.bse.cn/disclosure/2026/2026-01-29/14d53ccbd40e40828a179b7a9c63ea8e.pdf) · [复牌公告](https://www.bse.cn/disclosure/2026/2026-02-05/3d193f56481b41c8a416c4f09b890461.pdf)

冻结财务输入含 219,460 个经核验版本。依照深交所公告恢复中航电测至中航成飞的代码沿革，两个代码实际补采 18 个财务请求，归并保留 46 个新增版本。该发行人共有 57 个前缀可用财务版本，覆盖 2012Q1 至 2026Q1。恒大高新原件的历史报告和更正前快照已独立复算。

上交所 22,045 个与深交所 40,165 个候选公告日全部实际完成查询。归并前版原件共保留 15,628 个去重的沪深官方股本版本，覆盖 3,364 只证券。另一批北交所四家发行人的 28 个股本公告版本逐日期核对，已有 2,806 个受影响证券日可独立核实等值，披露晚于生效的区间单列审计。

股数单位链新增纳入 101 只证券的 1,311 条独立早期股本记录、北交所开市基准修正和中航成飞换码前后共 87 条原始分派响应。全网格来源复算指出余下 5,918 个股数单位链缺口，按日保存原因。沪深交易所的 A+H 原件另提供 10 个独立可定位有效期间，生产口径和独立算式在三家公司核对 2,152 个证券日。 [A+H 来源和复算](cn_mainland_share_monthly_source_audit.md)

CSMAR 官方 SDK 完成 20 批实际下载、438,829 条源记录。压缩分片、字段和数量均已核验。TuShare 历史申万成员实取 2,012 条、当前成员 5,916 条，保存响应及版本核验结果。 [CSMAR 采集审计](cn_csmar_source_audit.md) · [申万来源核验](cn_industry_source_audit.md)

第四版相对第三版的合格证券股本增加 362,893 个证券日，发行人估值增加 218,532 日，股数单位链增加 784 日。北交所 731 个无实际成交的开市日均取得停牌证据。 [第四版实际变动](../artifacts/cn_numeric_followup/release4_input/actual_release_delta.json)

五家含已退市 B 股的发行人，用旧股类真实报价、当时可用汇率和原件股本进行了独立回放。三家公司历史简称已按五条经核验原件归并。 [退市 B 股核验](cn_retired_b_siblings_audit.md) · [简称核验](cn_security_name_audit.md)

第五版相对第四版实际净增 36,354 个核验股本证券日、165,470 个发行人市值证券日、2,533 个股数单位链证券日，财务引用变动 +90 个证券日。 [第五版发布变动](../artifacts/cn_numeric_followup/release5_input/actual_release_delta.json)

第四版构建入口遗漏股类报价分片。第五版完整冻结 640,659 笔实际股类报价及 6,116 笔时点汇率。新冻结和计算入口在股类输入不全时直接报错。 同所历史代码、跨所发行人引用、历史简称、限价和招商港口 2017 年正式财报已进入第五版。 [构建记录](cn_numeric_execution.md) · [历史简称与跨所身份核验](cn_security_name_audit.md)

第五版对 124 只 A 股生成 164,057 个实际跨股类估值日，来源时点全量核对。17,279 个监督标签仅更新目标来源编号。 [跨股类和标签验收](cn_cross_class_release_audit.md)

三宗跨所迁移恢复发行人引用。观典防务 2022Q1 已能按当时财务期连接，七项金额仍标记未核实。六类定向样本的真实原生输入与未来信息隔离已另行核验。 [定向原生输入验收](cn_native_identity_validation.json)

归档报表公司类型用于审计财务字段覆盖，按实际有效输入日量化 TTM 营收是否形成，并单列已具发行人市值的缺口。 [财务报告类型分层](../artifacts/cn_numeric_followup/financial_revenue_family_v5.json)

第六版相对第五版实际净增 16,033 个核验股本证券日，发行人市值变动 +15,637 个证券日，股数单位链变动 +115 个证券日。 财务与行业时点覆盖分别增加 10,004 和 14,491 个证券日。 验证停牌事实变动 +222 个证券日。 [第六版实际差额](../artifacts/cn_numeric_followup/release6_input/actual_release_delta.json)

北交所早期正式合并报表按历史发行人与次日可用时点导入。申万分别导入 2026-06-30 全截面和 2023–2025 的可证历史截面。归属仅用于证据覆盖的会话。停牌事实及单位变换由发行人原始公告核验，真实收盘与停牌估值各自处理。 [北交所财务原件](cn_bse_financial_originals_audit.md) · [申万来源](cn_industry_source_audit.md)

第七版相对第六版实际增加 264 个合格股本证券日和 4,318 个发行人市值证券日。六家发行人的变更按公开原件、同日外币报价和汇率复算。 [A/H 股本增量](cn_v7_ah_capital_recovery.md)

第七版纳入 215 个有原件证据的同公开时点财务版本和 16 个其后公开的比较期修订。时点连接先选择已公开版本，仅在收入成分口径可比时计算单季、TTM 与一年以前的 TTM。 [证券公司原件](cn_securities_revenue_audit.md) · [观典防务原件](cn_832317_financial_originals_audit.md) · [八家普通行业发行人](cn_original_revenue_comparability.md) · [实际差额](../artifacts/cn_numeric_followup/release7_input/actual_release_delta.json)

第七版逐个验证 34855830 条监督记录的保留结果，并对 BSE 的实际可用七项财务量逐年计数。 [发布后独立对比](../artifacts/cn_numeric_followup/release7_input/independent_v7.json)

第七版逐日前期成员复算发现 2058395 个缺普通 A 股类股数的前期成员记录，影响 2812 日。可核验的完整资本分母有 0 日。 [最新分母全量回执](../artifacts/cn_numeric_followup/release7_input/market_weight_blockers_actual.json)

- `daily` 完成 296/296 个证券范围，覆盖计划 11,235 个缺键，源响应匹配 14 个键。错误统计为 `{}`。

- `adj_factor` 完成 211/211 个证券范围，覆盖计划 358 个缺键，源响应匹配 0 个键。错误统计为 `{}`。

- `suspend_d` 完成 296/296 个证券范围，覆盖计划 11,235 个缺键，源响应匹配 2,291 个键。错误统计为 `{}`。

六条只在事后档案中证实的全日停牌用于监督原因和审计。该来源提供可核查的实际状态，历史公开时间缺失。见 [剩余报价键来源核查](cn_suspension_residual_sources.json)。

## 验收

| 全量检查 | 违规数 |
|---|---:|
| `primary_key_stock_daily` | 0 |
| `primary_key_stock_fundamental_asof` | 0 |
| `primary_key_market_daily` | 0 |
| `primary_key_industry_daily` | 0 |
| `primary_key_samples` | 0 |
| `primary_key_labels` | 0 |
| `valid_window` | 0 |
| `candidate_horizons` | 0 |
| `target_calendar_and_label_formula` | 0 |
| `fundamental_time` | 0 |
| `sample_source_refs` | 0 |
| `split_and_buffer` | 0 |
| `calendar_bse_vs_trading_dates` | 0 |
| `features_finite_and_domain` | 0 |
| `features_explained_nulls` | 0 |
| `features_sparse_reasons` | 0 |
| `features_coverage_gates` | 0 |
| `input_identity_and_clock` | 0 |
| `fundamental_source_versions` | 0 |
| `selected_pit_source_times` | 0 |
| `industry_effective_time` | 0 |
| `split_event_source_time` | 0 |
| `issuer_class_set_availability` | 0 |
| `label_bin_edges_and_zero` | 0 |

独立分区哈希与页脚校验核对 153 个文件。按交易所和 split 抽样复算 12 条真实样本。原生编码状态为 `passed`， 检查 16 条样本。

按 12 个年份独立从标签重建并逐行核对 10,360,981 条实际训练清单，期限掩码及 split 全部一致。

真实量价因子独立复算的样本及数值差异保存在对应的机器可读验收结果中。

真实披露和行业证据的前缀截断及扰动检查另存机器可读结果，包括时间、数值和原版引用的对比。

真实样本的编码缓存命中返回相同 token 和标记。数据版本、样本、文本版本及文本条件在验收中形成独立条目。缓存命名空间还包含模板、编码器及 tokenizer 版本，上限为 8 GiB。

## 阻塞和训练影响

股本、跨股类和财报仍有逐证券区间的证据断点。市场、行业缺前一期完整资本分母时，覆盖率不能计算。有效成员覆盖不足 99% 时，状态及依赖的相对因子继续缺失。监督、各期限掩码及实际训练清单独立保留。

港交所直连试采后发现站点条款明确限制自动采集与训练用途，已停用直连来源，实际冻结输入进入零条试采记录。能够独立核验的 A+H 文件来自沪深两所。 [来源审计](cn_hkex_monthly_source_audit.md)

第五版实测有 2,074,690 个前期普通 A 股资本成员记录缺准确股类股数，2,812 个市场日缺完整分母。现有 TuShare 盘前股本接口实测权限拒绝，候选日期范围自 2024-05 起。两所授权股本产品需另行核对历史原始版本、股类及实际公布时点。 [全量分母复算](cn_market_denominator_audit.md) · [批量来源及权限](cn_capital_bulk_source_audit.md)

CSMAR 首日 20 页、438,829 条已复核。次日实际续采 39 个范围均返回权限码 -2501，11 个失败在计数、28 个失败在明细，新增为零。SDK 会话可认证，昨日已读的 23 行对照表今日也无法查询。申万、股本、分派及后续财务报表的未取得范围逐项登记。 [官方续采与对照](cn_csmar_source_audit.md)

历史公开的申万归属仍呈稀疏截面。第二日 CSMAR 申万分类和指数公告接口均无明细。既有发行人公开原件、历史档案和指数样本的取证用途单列。 [历史行业原件](cn_industry_source_audit.md)

对第六版北交所有效输入逐个检查累计组成期，171,428 日缺可核实的收入版本，44,498 日缺足够历史。现有原件余项涉及合并范围、会计准则或归母净利口径的歧义，无法组成可批量采用的当时可得财务量。 [逐期检查及来源探测](../artifacts/cn_numeric_followup/release7_input/bse_remaining_income_source_audit.json)

需要在当前数据上提前开展研究时，可由用户另行批准一条受限实验分支。该分支使用同一证券样本、时间切分、标签与监督掩码，统一屏蔽当前无法构建的市场及行业相对特征。所有文本条件使用同一数值输入。样本外结论只覆盖该受限数值条件，完整契约的发布状态继续由原验收判定。

自动判定识别 66 个结构性依赖范围。逐项原因见 `reports/quality_summary.json`。各 split、年份、交易所及已核验行业的 PIT 分母见 `reports/pit_coverage_by_stratum.parquet`，同口径的因子覆盖见 `reports/stock_factor_coverage_by_stratum.parquet`，前置期和其余上市会计期的七项证据覆盖见 `reports/financial_period_coverage.parquet`。

- `share_verified` 在 2,059,173 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

- `unit_chain_verified` 在 2,486 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

- `finance_verified` 在 152,260 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

- `industry_verified` 在 11,627,891 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

### 缺口影响的候选数

各缺失列可重叠，按实际样本索引连接当日记录。财务栏统计缺少任何可用快照的候选。

| Split | 候选 | 行情输入有效 | 缺证券股本 | 缺发行人市值 | 缺 U 链 | 缺财务快照 | 缺行业 |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 8,367,214 | 7,216,924 | 1,613,015 | 1,861,843 | 1,909 | 138,877 | 8,366,336 |
| validation | 626,520 | 613,535 | 92,609 | 96,081 | 479 | 3,132 | 626,520 |
| calibration | 669,981 | 656,282 | 89,098 | 93,275 | 27 | 1,458 | 665,229 |
| test | 1,954,895 | 1,892,027 | 247,727 | 259,874 | 68 | 8,103 | 1,856,708 |
| 1 日聚合 | 状态 | 行数 | 收益有效 | 成员完整 | 市值覆盖 ≥99% | 市值覆盖无法计算 |
|---|---|---:|---:|---:|---:|---:|
| `market_daily` | `insufficient_history` | 1 | 0 | 1 | 0 | 1 |
| `market_daily` | `missing_source` | 2,812 | 0 | 2,812 | 0 | 2,812 |
| `industry_daily` | `insufficient_history` | 13,536 | 0 | 0 | 0 | 13,536 |
| `industry_daily` | `missing_source` | 31 | 0 | 31 | 0 | 31 |
| `industry_daily` | `unverified_version` | 420 | 0 | 0 | 0 | 420 |

财务分母为 198,118 份实际共享快照。来源公告版本及条件期保存在发布包 `reference/`。

| 财务字段 | 非空快照数 |
|---|---:|
| `revenue_ttm` | 84,697 |
| `net_income_total_ttm` | 86,295 |
| `net_income_parent_ttm` | 86,286 |
| `operating_cashflow_ttm` | 63,369 |
| `assets` | 182,309 |
| `liabilities` | 182,306 |
| `parent_equity` | 182,312 |
| `assets_4q_ago` | 162,059 |
| `parent_equity_4q_ago` | 162,060 |
| `revenue_ttm_4q_ago` | 83,621 |
| `net_income_parent_ttm_4q_ago` | 85,204 |

## 命令

```powershell
$python = 'E:/quant/.venv/Scripts/python.exe'
$env:PYTHONPATH = 'E:/Kurumi/src;E:/Kurumi/reference/karpo-decision/src;E:/Kurumi/artifacts/karpo-runtime'
& $python scripts/build_cn_numeric.py --prices-only --calendar-prehistory artifacts/cn-calendar/trade_cal --suspension-evidence 'E:/QuantData/numeric/cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a/reference/official_suspensions.json' --spill-dir (Join-Path $env:TEMP 'kurumi-cn-followup-spill') --memory-limit-gib 8
& $python scripts/backfill_cn_prices.py --endpoint daily --endpoint adj_factor --endpoint suspend_d
& $python scripts/build_cn_numeric.py --compute-only --calendar-prehistory artifacts/cn-calendar/trade_cal --suspension-evidence 'E:/QuantData/numeric/cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a/reference/official_suspensions.json' --spill-dir (Join-Path $env:TEMP 'kurumi-cn-followup-spill') --memory-limit-gib 8 --pit-evidence 'E:/QuantData/numeric/.build-cn/sources/pit-releases/cn-pit-45a7a89e77f38280e50fbe39'
& $python scripts/build_cn_numeric.py --calendar-prehistory artifacts/cn-calendar/trade_cal --suspension-evidence 'E:/QuantData/numeric/cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a/reference/official_suspensions.json' --spill-dir (Join-Path $env:TEMP 'kurumi-cn-followup-spill') --memory-limit-gib 8 --pit-evidence 'E:/QuantData/numeric/.build-cn/sources/pit-releases/cn-pit-45a7a89e77f38280e50fbe39'
$dataset = 'E:/QuantData/numeric/cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a'
& $python scripts/verify_cn_numeric.py $dataset
& $python scripts/check_numeric_loading.py $dataset --representative --price-prefix --allow-incomplete --karpo-assets artifacts/karpo-b8e6fd7
```

构建阶段按价格、PIT、监督、特征和 Parquet 分区记录断点。原生检查依赖的轻量配置和 tokenizer 可由 `scripts/fetch_karpo_encoding.py artifacts/karpo-b8e6fd7` 重新获取。

本版示例启用显式 QA 开关。正式后训练入口会检查 `NUMERIC_READY`。

训练代码使用 `kurumi.numeric_loader.NumericDataset`，通过 `iter_sample_ids(split)` 取得实际清单，通过 `load_batch(sample_ids)` 取得模型输入、监督和审计。

```python
from itertools import islice
from kurumi.numeric_loader import NumericDataset

dataset = NumericDataset.from_config('configs/cn_numeric.toml', allow_incomplete=True)
batch = dataset.load_batch(list(islice(dataset.iter_sample_ids('train'), 32)))
```
