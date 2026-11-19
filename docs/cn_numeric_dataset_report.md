# CN 数值数据集报告

`INCOMPLETE`。版本 `cn-8dfdd9db8a90fd88e132e3675fd31e311e02b5a50ad437cca7f8bdff7198e03b`。数据目录为 `E:\QuantData\numeric\cn-8dfdd9db8a90fd88e132e3675fd31e311e02b5a50ad437cca7f8bdff7198e03b`。

包含沪、深、北普通 A 股。价格及监督观察截至 2026-07-31，样本截至 2026-06-30。Xtext 记录为 `not_built`。

## 存储和清理

| 目录 | 迁移前文件 | 迁移前 GiB | 迁移后文件 | 迁移后 GiB |
|---|---:|---:|---:|---:|
| `00_raw` | 434,934 | 8.275 | 434,934 | 8.275 |
| `10_canonical` | 1,077,205 | 90.248 | 1,074,079 | 89.458 |
| `40_qlib` | 105,854 | 0.022 | 105,854 | 0.022 |
| `80_quarantine` | 113 | 0.000 | 113 | 0.000 |
| `90_metadata` | 939 | 0.526 | 949 | 0.527 |
| `numeric` | 0 | 0.000 | 1,208 | 22.737 |
| `quant.duckdb` | 1 | 1.125 | 1 | 1.125 |
| `reports` | 1,158 | 10.024 | 1,159 | 10.024 |

全盘可用空间由 42.596 GiB 变为 18.368 GiB。发布清单内文件大小合计 3.049 GiB。

已删失效进度临时文件 2 个和空审计目录 64 个，释放 18,880 字节。经等价性验证的 Canonical 回收 3,126 个文件，释放 847,904,002 字节。

本轮另清理了 2 个未发布的旧导出目录，涉及 3 个文件和 62,703,550 字节。

当前发布复用了旧版本中逐字节一致的 39 个 Parquet 文件。

构建阶段定时观测的 numeric 最大占用 22.892 GiB，E 盘最少剩余 14.878 GiB。抽样按文件身份合并硬链接。目录清单按路径统计。

当前 quant 注册表、活跃视图及仍被实际版本引用的源分片供原项目使用。训练包读取以本版本的 Parquet 清单为入口。

回收后检查了 8,540 个当前分片和 46 个注册版本的引用。历史版本共引用 9,435 个不同分片，缺失 0 个。另有 1,065,522 个非活跃注册分片，等价性或引用证据并未全部核实。

旧全库备份计划已按回收范围归档并退役，原哈希及回收判据留档。见 [旧库回收记录](cn_legacy_reclamation.md)。

## 六张核心表

| 表 | 主键 | 行数 | 起止日期 | Parquet GiB |
|---|---|---:|---|---:|
| `stock_daily` | instrument_id, local_trade_date | 11,745,773 | 2015-01-05 至 2026-07-31 | 1.227 |
| `stock_fundamental_asof` | fundamental_snapshot_id | 186 | 2012-03-09 至 2026-04-29 | 0.000 |
| `market_daily` | market_id, local_trade_date | 2,813 | 2015-01-05 至 2026-07-31 | 0.000 |
| `industry_daily` | market_id, industry_system, classification_version, industry_code, local_trade_date | 363 | 2025-12-03 至 2026-07-31 | 0.000 |
| `samples` | sample_id | 11,618,610 | 2015-01-05 至 2026-06-30 | 0.082 |
| `labels` | sample_id, horizon | 34,855,830 | 2015-01-05 至 2026-06-30 | 1.250 |

完整字段、Arrow 类型、单位和主键见发布包 `schema.json`。按交易所、年份、字段和原因的分布见 `reports/field_coverage.parquet`，30 个因子、市场及行业字段的分母、有效项与覆盖见 `reports/feature_coverage.parquet`。

## 全量覆盖

| 交易所 | 证券日 | 实际收盘 | 复权有效 | 输入有效 | 停牌事实 | 停牌时点证据 | 股数 | 发行人市值 | U 链 | 财务 | 行业 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BSE | 246,184 | 245,453 | 246,183 | 224,672 | 731 | 0 | 0 | 0 | 0 | 0 | 0 |
| SSE | 4,887,224 | 4,800,666 | 4,887,070 | 4,427,053 | 86,558 | 3,049 | 184 | 184 | 183 | 5,647 | 47,500 |
| SZSE | 6,612,365 | 6,416,740 | 6,612,359 | 5,848,131 | 195,611 | 7,631 | 293 | 293 | 292 | 22,689 | 55,891 |

## 因子与市场状态覆盖

下表分母为各表实际发布行数。行业表只列已有可核验归属线索的行业和时段，完整母集门槛独立核查。

| 表 | 字段 | 有效值 | 发布行数 |
|---|---|---:|---:|
| `industry_daily` | `above_ma20_ratio` | 0 | 363 |
| `industry_daily` | `activity_proxy_ratio_20d` | 0 | 363 |
| `industry_daily` | `advance_ratio` | 0 | 363 |
| `industry_daily` | `excess_market_20d` | 0 | 363 |
| `industry_daily` | `return_1d` | 0 | 363 |
| `industry_daily` | `return_20d` | 0 | 363 |
| `industry_daily` | `return_5d` | 0 | 363 |
| `industry_daily` | `return_60d` | 0 | 363 |
| `industry_daily` | `volatility_20d_daily` | 0 | 363 |
| `industry_daily` | `volatility_60d_daily` | 0 | 363 |
| `market_daily` | `above_ma20_ratio` | 0 | 2,813 |
| `market_daily` | `above_ma60_ratio` | 0 | 2,813 |
| `market_daily` | `activity_proxy_ratio_20d` | 0 | 2,813 |
| `market_daily` | `advance_ratio` | 0 | 2,813 |
| `market_daily` | `drawdown_from_peak_60d` | 0 | 2,813 |
| `market_daily` | `return_1d` | 0 | 2,813 |
| `market_daily` | `return_20d` | 0 | 2,813 |
| `market_daily` | `return_5d` | 0 | 2,813 |
| `market_daily` | `return_60d` | 0 | 2,813 |
| `market_daily` | `return_dispersion_1d` | 0 | 2,813 |
| `market_daily` | `suspension_ratio` | 0 | 2,813 |
| `market_daily` | `turnover_total_median` | 0 | 2,813 |
| `market_daily` | `volatility_20d_daily` | 0 | 2,813 |
| `market_daily` | `volatility_60d_daily` | 0 | 2,813 |
| `stock_daily` | `beta_market_60d` | 0 | 11,745,773 |
| `stock_daily` | `book_to_market` | 477 | 11,745,773 |
| `stock_daily` | `drawdown_from_peak_60d` | 10,514,180 | 11,745,773 |
| `stock_daily` | `earnings_yield_ttm` | 293 | 11,745,773 |
| `stock_daily` | `excess_industry_20d` | 0 | 11,745,773 |
| `stock_daily` | `excess_industry_5d` | 0 | 11,745,773 |
| `stock_daily` | `excess_market_20d` | 0 | 11,745,773 |
| `stock_daily` | `excess_market_5d` | 0 | 11,745,773 |
| `stock_daily` | `liabilities_to_assets` | 18,465 | 11,745,773 |
| `stock_daily` | `liquidity_proxy_percentile_20d` | 11,132,961 | 11,745,773 |
| `stock_daily` | `market_cap_percentile` | 477 | 11,745,773 |
| `stock_daily` | `net_margin_ttm` | 654 | 11,745,773 |
| `stock_daily` | `operating_cashflow_to_assets_ttm` | 625 | 11,745,773 |
| `stock_daily` | `price_ma20_gap` | 11,132,961 | 11,745,773 |
| `stock_daily` | `price_ma60_gap` | 10,514,180 | 11,745,773 |
| `stock_daily` | `profit_change_to_assets` | 156 | 11,745,773 |
| `stock_daily` | `residual_volatility_60d` | 0 | 11,745,773 |
| `stock_daily` | `return_1d` | 11,444,894 | 11,745,773 |
| `stock_daily` | `return_20d` | 11,116,311 | 11,745,773 |
| `stock_daily` | `return_5d` | 11,373,623 | 11,745,773 |
| `stock_daily` | `return_60d` | 10,499,856 | 11,745,773 |
| `stock_daily` | `revenue_growth_yoy_ttm` | 156 | 11,745,773 |
| `stock_daily` | `roa_ttm` | 625 | 11,745,773 |
| `stock_daily` | `roe_ttm` | 3,438 | 11,745,773 |
| `stock_daily` | `sales_to_market_ttm` | 293 | 11,745,773 |
| `stock_daily` | `turnover_total_1d` | 477 | 11,745,773 |
| `stock_daily` | `turnover_total_mean_20d` | 439 | 11,745,773 |
| `stock_daily` | `volatility_20d_daily` | 11,116,311 | 11,745,773 |
| `stock_daily` | `volatility_60d_daily` | 10,499,856 | 11,745,773 |
| `stock_daily` | `volume_ratio_1_20` | 407 | 11,745,773 |

## 样本与监督

| Split | 期限 | 候选 | 有效 | 无效 | 七档计数（0 至 6） |
|---|---:|---:|---:|---:|---|
| train | 1 | 8,367,214 | 7,203,863 | 1,163,351 | 431,903 / 1,548,950 / 1,553,559 / 213,780 / 1,607,892 / 1,391,169 / 456,610 |
| train | 5 | 8,367,214 | 7,162,243 | 1,204,971 | 464,264 / 1,598,994 / 1,574,968 / 81,371 / 1,510,381 / 1,454,387 / 477,878 |
| train | 20 | 8,367,214 | 7,049,522 | 1,317,692 | 453,074 / 1,699,106 / 1,537,841 / 34,495 / 1,419,404 / 1,419,249 / 486,353 |
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
| train | 1 | `input_invalid` 1,150,456、`target_suspended` 7,665、`cross_split` 5,220、`target_missing_quote` 10 |
| train | 5 | `input_invalid` 1,150,456、`target_suspended` 28,404、`cross_split` 26,101、`target_missing_quote` 10 |
| train | 20 | `input_invalid` 1,150,456、`cross_split` 104,452、`target_suspended` 62,751、`target_delisted_no_quote` 24、`target_missing_quote` 9 |
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

至少有一个有效期限的实际清单行数为 `calibration` 651,003、`test` 1,891,977、`train` 7,209,524、`validation` 608,311。

| 交易所 | 涉及证券 | 无报价且未解释 | F 缺失 | 缺口日期范围 |
|---|---:|---:|---:|---|
| BSE | 1 | 0 | 1 | 2026-02-03 至 2026-02-03 |
| SSE | 8 | 0 | 154 | 2015-01-05 至 2026-02-03 |
| SZSE | 20 | 14 | 6 | 2015-03-20 至 2026-02-03 |

逐证券逐日缺键见 `reports/quote_gaps.parquet`。停牌披露原版可得证据与供应商事后记录分别计数。

## 补采与证据

日历、补采请求、证据原件来源、公开时间及版本哈希见 `reference/`。每日实际收盘与经证实停牌的市场估值分开保存。停牌填估值的规则只适用于市场与行业聚合。

- `daily` 完成 296/296 个证券范围，覆盖计划 11,235 个缺键，源响应匹配 14 个键。错误统计为 `{}`。

- `adj_factor` 完成 211/211 个证券范围，覆盖计划 358 个缺键，源响应匹配 0 个键。错误统计为 `{}`。

- `suspend_d` 完成 296/296 个证券范围，覆盖计划 11,235 个缺键，源响应匹配 2,291 个键。错误统计为 `{}`。

冷却后重新取得东方财富和宁波银行 2024Q1–2026Q1 各九期原始合并财报。126 个原件数值均与独立同发行人、同会计期数据在披露精度下一致。合入新增 11 个报告版本并核准 7 个已有版本，两家 2026Q1 均形成四项当期 TTM 和经济口径可比的上年同期收入与归母 TTM。

东方财富的财务收入采用原件合并利润表中的经营收入合计口径。2026Q1 收入 TTM 复算为 17,613,181,150.97 元，净利率为 74.42%。证据涵盖 9 期合并收入。另按原件累计列修正 7 个早期银行财报字段，27 个早期财报版本的合并收入保留为缺失。见 [2025 年年报](https://static.cninfo.com.cn/finalpage/2026-03-20/1225019509.PDF) 和 [2026 年一季报](https://static.cninfo.com.cn/finalpage/2026-04-25/1225185763.PDF)。

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
| `split_and_buffer` | 0 |
| `calendar_bse_vs_trading_dates` | 0 |
| `features_finite_and_domain` | 0 |
| `features_explained_nulls` | 0 |
| `features_sparse_reasons` | 0 |
| `features_coverage_gates` | 0 |

独立分区哈希与页脚校验核对 86 个文件。按交易所和 split 抽样复算 12 条真实样本。原生编码状态为 `passed`， 检查 18 条样本。

按 12 个年份独立从标签重建并逐行核对 10,360,815 条实际训练清单，期限掩码及 split 全部一致。

真实量价因子独立复算的样本及数值差异保存在对应的机器可读验收结果中。

真实披露和行业证据的前缀截断及扰动检查另存机器可读结果，包括时间、数值和原版引用的对比。

真实样本的编码缓存命中返回相同 token 和标记。数据版本、样本、文本版本及文本条件在验收中形成独立条目。缓存命名空间还包含模板、编码器及 tokenizer 版本，上限为 8 GiB。

独立 Arrow 扫描核实 2,325 个字段原因分组及 315,096,919 个稀疏原因记录，和发布表逐组一致。

## 阻塞和训练影响

原始财务表的本地严格可知时间晚于样本截止。可证实的公告版本进入 PIT 快照，其余历史金额保留为未验证。跨股类的股数、股本生效版本、拆合股与送转动作全集以及历史申万分类是主要依赖缺口。市场和行业缺少可核实的完整前期分母时，按契约将相应指标保留 NULL。样本、标签和掩码可用于构建验收，正式加载默认检查发布状态。

TuShare `bak_basic` 实测权限拒绝。可访问的 `daily_basic` 和 `index_member_all` 能提供对照值，历史版本追溯仍需原件。巨潮原件首批请求可用，后续 36 个发行人的请求及重试返回 HTTP 403。实际补齐的申万原始附件仅覆盖少数行业和月份，不能据此补写全行业历史。

冷却后对三个发行人复测均返回 HTTP 200。两个沪深发行人查询有公告，北交所发行人的同类查询为空。此前 HTTP 403 为暂时故障，后续获取情况见财务来源记录。

深交所试营业期的完整开休市证据仍缺，5 只早期股票的上市期龄共涉及 13,424 个候选日。已复核的样本资格规则保留这些候选，期龄字段为 NULL。

申万官方历史 XLS 获得 12,934 条记录，旧 RAR 中有 11,803 条历史记录。两版存在同一生效键分类改写和更新日期变化，现有公开网页存档未绑定被下载的旧版原始文件。另一路理杏仁请求返回 HTTP 401。见 [申万来源核验](cn_industry_source_audit.md)。

原沪市 XBRL 入口重定向至公司列表，浦发银行的经营概览未返回原始财报实例链接。原深市实例入口实测连接失败。沪市公告传输服务列有 XBRL 实例文档，公开产品页没有历史实例下载清单。来源核对覆盖沪深公开入口、传输服务说明及北交所定期报告指南。见 [沪市公告服务](https://www.sseinfo.com/services/other/announcement/) 和 [深市原平台说明](https://www.szse.cn/aboutus/trends/news/t20090213_517801.html)。

- `share_verified` 在 11,745,296 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

- `unit_chain_verified` 在 11,745,298 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

- `finance_verified` 在 11,717,437 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

- `industry_verified` 在 11,642,382 个证券日缺可用值，涉及输入可选字段与状态覆盖，影响范围详见覆盖表。

### 缺口影响的候选数

各缺失列可重叠，按实际样本索引连接当日记录。财务栏统计缺少任何可用快照的候选。

| Split | 候选 | 行情输入有效 | 缺证券股本 | 缺发行人市值 | 缺 U 链 | 缺财务快照 | 缺行业 |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 8,367,214 | 7,216,758 | 8,367,214 | 8,367,214 | 8,367,214 | 8,346,929 | 8,367,214 |
| validation | 626,520 | 613,535 | 626,520 | 626,520 | 626,520 | 625,060 | 626,520 |
| calibration | 669,981 | 656,282 | 669,981 | 669,981 | 669,981 | 668,356 | 669,981 |
| test | 1,954,895 | 1,892,027 | 1,954,464 | 1,954,464 | 1,954,465 | 1,950,228 | 1,865,569 |
| 1 日聚合 | 状态 | 行数 | 收益有效 | 成员完整 | 市值覆盖 ≥99% | 市值覆盖无法计算 |
|---|---|---:|---:|---:|---:|---:|
| `market_daily` | `insufficient_history` | 1 | 0 | 1 | 0 | 1 |
| `market_daily` | `missing_source` | 2,812 | 0 | 2,812 | 0 | 2,812 |
| `industry_daily` | `unverified_version` | 363 | 0 | 0 | 0 | 363 |

财务分母为 186 份实际共享快照。来源公告版本及条件期保存在发布包 `reference/`。

| 财务字段 | 非空快照数 |
|---|---:|
| `revenue_ttm` | 11 |
| `net_income_total_ttm` | 11 |
| `net_income_parent_ttm` | 12 |
| `operating_cashflow_ttm` | 11 |
| `assets` | 135 |
| `liabilities` | 131 |
| `parent_equity` | 159 |
| `assets_4q_ago` | 85 |
| `parent_equity_4q_ago` | 98 |
| `revenue_ttm_4q_ago` | 3 |
| `net_income_parent_ttm_4q_ago` | 3 |

## 命令

```powershell
$python = 'E:/quant/.venv/Scripts/python.exe'
$env:PYTHONPATH = 'E:/Kurumi/src;E:/Kurumi/reference/karpo-decision/src;E:/Kurumi/artifacts/karpo-runtime'
& $python scripts/build_cn_numeric.py --prices-only --calendar-prehistory artifacts/cn-calendar/trade_cal --suspension-evidence artifacts/cn_numeric/suspension_augmented_input.json
& $python scripts/backfill_cn_prices.py --endpoint daily --endpoint adj_factor --endpoint suspend_d
& $python scripts/build_cn_numeric.py --compute-only --calendar-prehistory artifacts/cn-calendar/trade_cal --suspension-evidence artifacts/cn_numeric/suspension_augmented_input.json --pit-evidence artifacts/cn_numeric/pit_corrected_input
& $python scripts/build_cn_numeric.py --calendar-prehistory artifacts/cn-calendar/trade_cal --suspension-evidence artifacts/cn_numeric/suspension_augmented_input.json --pit-evidence artifacts/cn_numeric/pit_corrected_input
$dataset = 'E:/QuantData/numeric/cn-8dfdd9db8a90fd88e132e3675fd31e311e02b5a50ad437cca7f8bdff7198e03b'
& $python scripts/verify_cn_numeric.py $dataset
& $python scripts/check_numeric_loading.py $dataset --representative --price-prefix --allow-incomplete --karpo-assets artifacts/karpo-b8e6fd7 --recovered-ttm-audit artifacts/cn_pit_finance_corrected/targeted_recovery_result.json
```

构建阶段按价格、PIT、监督、特征和 Parquet 分区记录断点。原生检查依赖的轻量配置和 tokenizer 可由 `scripts/fetch_karpo_encoding.py artifacts/karpo-b8e6fd7` 重新获取。

训练代码使用 `kurumi.numeric_loader.NumericDataset`，通过 `iter_sample_ids(split)` 取得实际清单，通过 `load_batch(sample_ids)` 取得模型输入、监督和审计。

```python
from itertools import islice
from kurumi.numeric_loader import NumericDataset

dataset = NumericDataset.from_config('configs/cn_numeric.toml', allow_incomplete=True)
batch = dataset.load_batch(list(islice(dataset.iter_sample_ids('train'), 32)))
```
