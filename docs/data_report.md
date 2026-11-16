# 真实数据盘点报告

扫描开始（UTC）：2026-11-16T15:27:37.072330+00:00；查询结束：2026-11-16T15:47:38.167022+00:00。
用户本地时区为 Asia/Shanghai（UTC+8）；这两个时间为本次实际执行时钟。外部数据未更新或改写。本报告不宣称研究/生产就绪。

## 结论与口径

发现 88 个来源契约，67 个有当前有效 Canonical 文件；67 个完成全字段全行 SQL 解码与统计，逻辑行合计 134,002,459。有效文件共 8,540 个，扫描错误 0 项。无文件的契约不视为已拥有的数据。
股票日线实际截止：20260922，不能视为截至本次盘点日的最新行情。没有完整的独立文本正文库，也没有可直接沿用的本研究标签。
主要实质风险：日历覆盖和历史股票主表关联存在缺口；当前主表漏掉3个有历史行情的代码；指数日线存在大量空OHLC及1472条非正收盘价，不能直接作为完整指数特征输入。
本次全目录文件普查：1,620,204 个文件，118,348,612,297 字节（逻辑文件容量，非 NTFS 实际分配空间）。目录访问问题 0 项。
目录统计、footer 行数、逻辑行数均为明确范围内精确值；没有用抽样估算全库行数。不存在的数据不生成模拟替代。有效物理行不等于逻辑样本，旧文件与缓存不能叠加。

## 检查方法与可复现命令

```powershell
cd E:\Kurumi
& E:\quant\.venv\Scripts\python.exe -u scripts/inventory.py
& E:\quant\.venv\Scripts\python.exe scripts/supplement.py
& E:\quant\.venv\Scripts\python.exe scripts/auxiliary_tables.py
& E:\quant\.venv\Scripts\python.exe scripts/schema_consistency.py
& E:\quant\.venv\Scripts\python.exe scripts/relationship_details.py
& E:\quant\.venv\Scripts\python.exe scripts/render_report.py
```

运行环境：Python `3.11.9`；DuckDB `1.5.5`；其余依赖版本见 `environment.json`。未安装依赖、未加载凭证、未请求外部 API。
1. `os.scandir` 递归统计 QuantData 所有普通文件的路径分组、字节、扩展名和 mtime；不跟随符号链接。空目录另在初始化时检查。quant 代码树排除环境、Git、依赖/工具缓存（排除清单在 JSON）；这些目录不作为数据源。
2. 外部 DuckDB `read_only=True`，读取 active 指针并保存 `active_files.csv`，逐一读取全部有效 Parquet footer，比较每分区 schema。注册行数与 footer 行数分别保留。只读事务中的 active 列表是盘点输入，非新建数据版本。
3. 复用 `quant.data.storage.lake` 的 SQL。对全部有效物理行计算物理行、不同内容观察对、不同内容数；再按原契约自然键/内容键取最新观察版本，落盘到本仓库临时审计库，统计所有字段 NULL、浮点非有限值、时间范围、代码覆盖、键空值及若干价格异常。逻辑视图用于盘点，**不能作为历史 X_state**。
4. 日线与因子、daily_basic、涨跌停、主数据、交易所日历作全量关联。时间缺口以每证券首末已见日之间的开市日为分母，未扣停牌或特殊生命周期；不能直接解释为数据遗漏。
5. Raw 仅确定性抽样：每个有批次的 endpoint 按路径排序前三个文件，共 201 个，4096 行/批完整解码；注册表 Raw 总行数仅元数据声明，未重解码所有 Raw。非活动/孤立 Canonical 仅目录容量普查，未全量解码或重新计算 SHA256。
6. Qlib 所有二进制文件只检查字节长度可被4整除且含首个 float32 日历偏移；每导出读取前三个文件的头64字节。未全量验证缓存数值/哈希或日历对齐。CSV 审计表按行流式计数；SQLite 用 mode=ro 读取 schema 和行数。旧审计快照 DuckDB 未逐库重审。
7. 首轮 1GB/四线程 DISTINCT 聚合触及内存上限，已停止并改用可落盘 GROUP BY、单线程3GB后重跑。指数日线 latest 窗口仍触及上限，再按自然键含日期的事件年分区独立解析版本；补跑命令为 `scripts/inventory.py --retry-errors --skip-tree`。仅在源库 size/mtime 与前次结束一致时允许补跑，前次错误保留在 retry_history；最终表只使用最终结果。

源数据库前后 size/mtime 一致：`True`；仅是附加观察，不替代只读连接保障。未尝试源码 Git 状态修复；`git -C E:\quant rev-parse HEAD` 被权限限制，改保存 55 个非敏感来源代码/配置内容哈希。

## 来源、链路与复用

已读取外部 README、设置、来源适配器、字段契约、存储/校验、PIT、复权、股票池、动量和 Qlib 导出代码。主要来源是 Tushare HTTPS JSON API；本轮依据本地保存的 `official_api_schema.json` 获取字段语义和来源 URL，未在线重核官方定义，描述的真实性限于这份保存记录。Raw 不是交易所原始逐笔或原始公告正文。
`fetch_tasks → raw_batches → 00_raw/tushare/<endpoint>/<抓取年>/<月>/<batch>.parquet + JSON → validate_frame → 10_canonical/<endpoint>/<事件年/月或snapshot>/<uuid或compact>.parquet → canonical_parts(active) → latest / PIT → dataset_versions manifest → Qlib`。
Canonical 按契约统一数值为 double、文本为 string，附观察/可得时间、内容/版本/批次哈希；压实保留历史观察，旧文件仍存在。事件无源 ID 时用内容键，不能把两次同值事件证明为同一真实事件。`_batch_id` 连 raw_batches；Raw sidecar 连 task、请求参数及文件哈希。源财报有不同报告类型/更新标志，不能随意合并。
主关联为行情/因子/估值/涨跌停的 `(ts_code,trade_date)`，主数据以 ts_code 关联，指数成分以 `(index_code,con_code,trade_date)`，行业按 in_date/out_date 映射但仍需可得时钟；宏观为 date/month/quarter，绝不能按统计期当公开日。全部自然键见下表与 datasets.json；字段及元数据含义见字段字典。
仓库初始仅 AGENTS.md，无 reference 项目。新建的 reference/README.md 是只读参考索引，未复制外部代码。`Registry` 构造会写目录/DDL，禁止在盘点调用。外部旧项目评估文档提及的 E:\AI_quantization 不在本轮实查范围。

## 目录与容量

容量按所有文件相加，含旧版和重复缓存。具体路径例子、扩展名及修改时间在 filesystem_data.json。mtime 不是信息发布时间。

| 目录（E:\QuantData 下） | 文件数 | 字节 | 最近文件修改 UTC |
|---|---:|---:|---|
| (root) | 1 | 1,207,971,840 | 2026-10-21T00:21:41.125322+00:00 |
| 00_raw/tushare/adj_factor | 5,758 | 104,588,428 | 2026-09-24T06:31:37.703978+00:00 |
| 00_raw/tushare/balancesheet | 11,820 | 628,962,895 | 2026-09-29T09:59:35.194396+00:00 |
| 00_raw/tushare/block_trade | 5,756 | 33,028,968 | 2026-09-30T21:00:24.790772+00:00 |
| 00_raw/tushare/bse_mapping | 6 | 19,893 | 2026-09-23T05:22:49.949618+00:00 |
| 00_raw/tushare/cashflow | 11,820 | 436,667,830 | 2026-09-29T12:37:31.285323+00:00 |
| 00_raw/tushare/cn_cpi | 6 | 29,886 | 2026-10-01T18:18:44.139282+00:00 |
| 00_raw/tushare/cn_gdp | 6 | 19,411 | 2026-10-01T18:18:41.789136+00:00 |
| 00_raw/tushare/cn_m | 6 | 26,859 | 2026-10-01T18:18:49.163059+00:00 |
| 00_raw/tushare/cn_pmi | 6 | 125,419 | 2026-10-01T18:18:51.369071+00:00 |
| 00_raw/tushare/cn_ppi | 6 | 71,630 | 2026-10-01T18:18:46.799127+00:00 |
| 00_raw/tushare/cn_schedule | 288 | 510,688 | 2026-10-01T18:23:39.245501+00:00 |
| 00_raw/tushare/daily | 5,756 | 540,215,867 | 2026-09-23T14:11:10.330232+00:00 |
| 00_raw/tushare/daily_basic | 5,756 | 1,297,562,545 | 2026-09-24T15:20:56.412439+00:00 |
| 00_raw/tushare/daily_info | 5,756 | 29,868,001 | 2026-10-01T19:18:34.089883+00:00 |
| 00_raw/tushare/disclosure_date | 13,768 | 36,687,839 | 2026-09-29T20:52:07.134450+00:00 |
| 00_raw/tushare/dividend | 11,862 | 66,375,667 | 2026-10-03T13:48:34.215484+00:00 |
| 00_raw/tushare/etf_limit | 5,756 | 34,251,687 | 2026-09-25T07:38:47.395915+00:00 |
| 00_raw/tushare/express | 11,816 | 104,601,295 | 2026-09-29T17:01:10.577059+00:00 |
| 00_raw/tushare/fina_audit | 11,816 | 34,245,892 | 2026-09-29T23:26:13.875145+00:00 |
| 00_raw/tushare/fina_indicator | 11,824 | 919,513,812 | 2026-10-04T01:58:19.576144+00:00 |
| 00_raw/tushare/fina_mainbz | 41,654 | 170,596,263 | 2026-09-30T10:41:32.949403+00:00 |
| 00_raw/tushare/forecast | 11,818 | 81,272,614 | 2026-09-29T14:19:19.298443+00:00 |
| 00_raw/tushare/fund_adj | 5,994 | 30,723,139 | 2026-09-25T13:35:45.310640+00:00 |
| 00_raw/tushare/fund_basic | 14 | 374,534 | 2026-09-23T05:22:31.240008+00:00 |
| 00_raw/tushare/fund_daily | 5,756 | 139,857,722 | 2026-09-25T01:45:00.910596+00:00 |
| 00_raw/tushare/fund_div | 5,830 | 25,084,305 | 2026-09-25T06:10:50.705227+00:00 |
| 00_raw/tushare/fund_nav | 5,830 | 83,382,123 | 2026-09-25T04:41:09.895082+00:00 |
| 00_raw/tushare/fund_share | 6,130 | 20,332,964 | 2026-09-25T15:43:59.704456+00:00 |
| 00_raw/tushare/gz_index | 288 | 674,873 | 2026-10-01T18:28:09.546738+00:00 |
| 00_raw/tushare/hsgt_top10 | 5,756 | 24,343,503 | 2026-09-30T18:23:35.496250+00:00 |
| 00_raw/tushare/income | 11,826 | 386,546,997 | 2026-09-29T07:32:41.745795+00:00 |
| 00_raw/tushare/index_basic | 30 | 868,376 | 2026-09-23T05:22:40.935464+00:00 |
| 00_raw/tushare/index_classify | 26 | 96,829 | 2026-09-23T05:22:49.193068+00:00 |
| 00_raw/tushare/index_daily | 39,788 | 1,094,227,634 | 2026-10-04T02:48:36.787535+00:00 |
| 00_raw/tushare/index_dailybasic | 5,756 | 26,989,537 | 2026-09-26T03:15:20.886117+00:00 |
| 00_raw/tushare/index_member_all | 1,770 | 6,198,665 | 2026-09-28T06:45:16.684755+00:00 |
| 00_raw/tushare/index_weight | 3,112 | 11,750,815 | 2026-09-26T01:59:58.851980+00:00 |
| 00_raw/tushare/margin | 5,756 | 18,384,615 | 2026-09-30T14:11:13.410758+00:00 |
| 00_raw/tushare/margin_detail | 5,756 | 343,487,299 | 2026-09-30T15:32:44.366879+00:00 |
| 00_raw/tushare/margin_secs | 5,756 | 111,469,311 | 2026-09-30T16:59:51.240828+00:00 |
| 00_raw/tushare/moneyflow | 5,756 | 1,057,413,055 | 2026-09-30T12:16:54.781476+00:00 |
| 00_raw/tushare/namechange | 11,816 | 27,533,791 | 2026-10-01T18:07:15.139011+00:00 |
| 00_raw/tushare/new_share | 288 | 1,367,385 | 2026-10-01T18:09:43.129166+00:00 |
| 00_raw/tushare/pledge_detail | 11,816 | 56,688,347 | 2026-09-30T23:23:15.271730+00:00 |
| 00_raw/tushare/pledge_stat | 11,816 | 44,688,256 | 2026-09-30T22:15:15.176224+00:00 |
| 00_raw/tushare/repurchase | 306 | 2,493,080 | 2026-10-03T13:56:36.300564+00:00 |
| 00_raw/tushare/sf_month | 6 | 13,646 | 2026-10-01T18:18:53.645641+00:00 |
| 00_raw/tushare/share_float | 15,664 | 153,634,532 | 2026-10-04T04:44:09.031427+00:00 |
| 00_raw/tushare/shibor | 288 | 385,201 | 2026-10-01T18:12:08.045436+00:00 |
| 00_raw/tushare/shibor_lpr | 36 | 35,674 | 2026-10-20T03:25:18.975974+00:00 |
| 00_raw/tushare/shibor_quote | 34 | 82,301 | 2026-10-20T03:22:04.526699+00:00 |
| 00_raw/tushare/stk_holdernumber | 11,816 | 26,245,910 | 2026-10-01T00:59:26.145634+00:00 |
| 00_raw/tushare/stk_holdertrade | 310 | 8,407,834 | 2026-10-01T01:01:35.369224+00:00 |
| 00_raw/tushare/stk_limit | 5,756 | 172,870,281 | 2026-09-24T22:35:02.310606+00:00 |
| 00_raw/tushare/stk_managers | 11,816 | 94,355,962 | 2026-10-01T16:23:01.706877+00:00 |
| 00_raw/tushare/stk_rewards | 11,818 | 44,345,298 | 2026-10-01T14:56:51.884735+00:00 |
| 00_raw/tushare/stk_seasoned | 288 | 7,695,121 | 2026-10-01T16:25:18.520144+00:00 |
| 00_raw/tushare/stock_basic | 14 | 809,056 | 2026-09-23T05:22:27.438555+00:00 |
| 00_raw/tushare/stock_company | 14 | 11,736,752 | 2026-10-01T18:07:20.718777+00:00 |
| 00_raw/tushare/suspend_d | 5,756 | 11,507,406 | 2026-09-24T23:48:29.553528+00:00 |
| 00_raw/tushare/sz_daily_info | 5,756 | 20,343,470 | 2026-10-01T20:11:19.994939+00:00 |
| 00_raw/tushare/top10_floatholders | 11,816 | 86,218,308 | 2026-10-01T04:38:42.736673+00:00 |
| 00_raw/tushare/top10_holders | 11,816 | 82,133,591 | 2026-10-01T02:42:10.320661+00:00 |
| 00_raw/tushare/top_inst | 5,756 | 80,497,942 | 2026-09-30T20:23:22.883396+00:00 |
| 00_raw/tushare/top_list | 5,756 | 48,381,488 | 2026-09-30T19:49:50.821008+00:00 |
| 00_raw/tushare/trade_cal | 98 | 211,722 | 2026-09-23T05:22:23.719977+00:00 |
| 00_raw/tushare/wz_index | 288 | 1,423,438 | 2026-10-01T18:25:58.274107+00:00 |
| 10_canonical/adj_factor | 272 | 889,069,622 | 2026-09-24T06:32:02.541752+00:00 |
| 10_canonical/balancesheet | 56,539 | 7,310,407,693 | 2026-09-29T09:59:43.650799+00:00 |
| 10_canonical/block_trade | 3,052 | 151,152,930 | 2026-09-30T21:00:25.798854+00:00 |
| 10_canonical/bse_mapping | 2 | 66,382 | 2026-09-23T05:22:50.072360+00:00 |
| 10_canonical/cashflow | 61,308 | 6,075,980,128 | 2026-09-29T12:37:32.623915+00:00 |
| 10_canonical/cn_cpi | 14 | 244,303 | 2026-10-01T18:18:45.039278+00:00 |
| 10_canonical/cn_gdp | 12 | 170,555 | 2026-10-01T18:18:42.578971+00:00 |
| 10_canonical/cn_m | 14 | 218,653 | 2026-10-01T18:18:49.909003+00:00 |
| 10_canonical/cn_pmi | 14 | 662,934 | 2026-10-01T18:18:52.199438+00:00 |
| 10_canonical/cn_ppi | 14 | 415,471 | 2026-10-01T18:18:47.675480+00:00 |
| 10_canonical/cn_schedule | 12 | 159,872 | 2026-10-01T18:23:19.895359+00:00 |
| 10_canonical/daily | 348 | 1,260,706,354 | 2026-09-23T14:11:44.074774+00:00 |
| 10_canonical/daily_basic | 316 | 1,722,147,857 | 2026-09-24T15:21:20.991653+00:00 |
| 10_canonical/daily_info | 3,048 | 64,492,867 | 2026-10-01T19:18:35.120299+00:00 |
| 10_canonical/disclosure_date | 89,937 | 3,611,650,747 | 2026-09-29T20:52:08.506431+00:00 |
| 10_canonical/dividend | 55,293 | 2,516,882,405 | 2026-10-03T13:48:35.026979+00:00 |
| 10_canonical/etf_limit | 203 | 174,332,151 | 2026-09-25T07:38:50.936870+00:00 |
| 10_canonical/express | 20,727 | 845,838,217 | 2026-09-29T17:01:12.739632+00:00 |
| 10_canonical/fina_audit | 57,987 | 1,881,027,418 | 2026-09-29T23:26:14.943005+00:00 |
| 10_canonical/fina_indicator | 63,061 | 9,373,312,518 | 2026-10-04T01:58:20.873009+00:00 |
| 10_canonical/fina_mainbz | 69,295 | 3,151,906,006 | 2026-09-30T10:41:35.131945+00:00 |
| 10_canonical/forecast | 15,972 | 967,435,159 | 2026-09-29T14:19:21.020870+00:00 |
| 10_canonical/fund_adj | 320 | 222,713,534 | 2026-09-25T13:35:50.095960+00:00 |
| 10_canonical/fund_basic | 4 | 696,943 | 2026-09-23T05:22:31.383464+00:00 |
| 10_canonical/fund_daily | 407 | 324,523,028 | 2026-09-25T01:45:05.909281+00:00 |
| 10_canonical/fund_div | 36 | 1,123,024 | 2026-09-25T06:10:36.026664+00:00 |
| 10_canonical/fund_nav | 18 | 243,907,940 | 2026-09-25T04:41:27.374927+00:00 |
| 10_canonical/fund_share | 42 | 149,761,685 | 2026-09-25T15:44:07.790731+00:00 |
| 10_canonical/gz_index | 41 | 637,880 | 2026-10-01T18:26:49.634505+00:00 |
| 10_canonical/hsgt_top10 | 2,923 | 56,040,993 | 2026-09-30T18:23:37.287837+00:00 |
| 10_canonical/income | 62,286 | 7,469,305,809 | 2026-09-29T07:32:46.235291+00:00 |
| 10_canonical/index_basic | 9 | 3,160,834 | 2026-09-23T05:22:41.289395+00:00 |
| 10_canonical/index_classify | 13 | 345,269 | 2026-09-23T05:22:49.462430+00:00 |
| 10_canonical/index_daily | 108,091 | 18,443,730,227 | 2026-10-04T04:48:38.548558+00:00 |
| 10_canonical/index_dailybasic | 3,072 | 59,966,026 | 2026-09-26T03:15:22.123279+00:00 |
| 10_canonical/index_member_all | 4,533 | 76,633,942 | 2026-09-28T06:45:18.046398+00:00 |
| 10_canonical/index_weight | 1,345 | 320,788,779 | 2026-09-26T01:59:43.386904+00:00 |
| 10_canonical/margin | 3,072 | 43,630,285 | 2026-09-30T14:11:15.068047+00:00 |
| 10_canonical/margin_detail | 3,064 | 1,499,531,720 | 2026-09-30T15:32:46.288467+00:00 |
| 10_canonical/margin_secs | 3,064 | 1,222,140,800 | 2026-09-30T16:59:52.990391+00:00 |
| 10_canonical/moneyflow | 3,064 | 3,641,106,542 | 2026-09-30T12:16:56.904902+00:00 |
| 10_canonical/namechange | 6,202 | 207,048,713 | 2026-10-01T18:07:15.758730+00:00 |
| 10_canonical/new_share | 146 | 4,293,447 | 2026-10-01T18:09:43.776457+00:00 |
| 10_canonical/pledge_detail | 20,633 | 1,278,054,928 | 2026-09-30T23:23:14.416948+00:00 |
| 10_canonical/pledge_stat | 39,088 | 2,522,158,431 | 2026-09-30T22:15:15.483252+00:00 |
| 10_canonical/repurchase | 155 | 13,355,218 | 2026-10-03T13:56:37.518365+00:00 |
| 10_canonical/sf_month | 14 | 168,387 | 2026-10-01T18:18:54.363005+00:00 |
| 10_canonical/share_float | 1,009 | 515,719,549 | 2026-10-04T04:44:24.663496+00:00 |
| 10_canonical/shibor | 155 | 2,015,407 | 2026-10-01T18:12:08.729218+00:00 |
| 10_canonical/shibor_lpr | 17 | 187,328 | 2026-10-20T03:25:19.701791+00:00 |
| 10_canonical/shibor_quote | 15 | 601,095 | 2026-10-20T03:22:05.485883+00:00 |
| 10_canonical/stk_holdernumber | 57,871 | 2,433,179,197 | 2026-10-01T00:59:26.916733+00:00 |
| 10_canonical/stk_holdertrade | 155 | 36,952,027 | 2026-10-01T01:01:35.801309+00:00 |
| 10_canonical/stk_limit | 3,072 | 2,148,215,108 | 2026-09-24T22:35:24.304471+00:00 |
| 10_canonical/stk_managers | 45,604 | 2,589,665,417 | 2026-10-01T16:23:02.336898+00:00 |
| 10_canonical/stk_rewards | 82,617 | 4,303,676,654 | 2026-10-01T14:56:53.306262+00:00 |
| 10_canonical/stk_seasoned | 155 | 11,983,804 | 2026-10-01T16:25:19.156745+00:00 |
| 10_canonical/stock_basic | 4 | 1,507,145 | 2026-09-23T05:22:27.567722+00:00 |
| 10_canonical/stock_company | 6 | 12,418,059 | 2026-10-01T18:07:21.434956+00:00 |
| 10_canonical/suspend_d | 3,072 | 85,198,613 | 2026-09-24T23:48:30.491320+00:00 |
| 10_canonical/sz_daily_info | 3,066 | 52,158,141 | 2026-10-01T20:11:21.144755+00:00 |
| 10_canonical/top10_floatholders | 55,249 | 3,089,664,518 | 2026-10-01T04:38:44.772227+00:00 |
| 10_canonical/top10_holders | 59,726 | 3,179,042,819 | 2026-10-01T02:42:10.817362+00:00 |
| 10_canonical/top_inst | 3,070 | 512,523,536 | 2026-09-30T20:23:23.727529+00:00 |
| 10_canonical/top_list | 3,072 | 119,770,433 | 2026-09-30T19:49:52.957803+00:00 |
| 10_canonical/trade_cal | 34 | 2,288,564 | 2026-09-23T05:22:22.301085+00:00 |
| 10_canonical/wz_index | 154 | 3,155,994 | 2026-10-01T18:25:58.901024+00:00 |
| 40_qlib | 1 | 188 | 2026-09-23T05:33:45.833635+00:00 |
| 40_qlib/0e4a03a042a75d520cbc52d82fa57e9f0097b4669b58ed0e3c842a4f6050f179 | 54,134 | 11,945,378 | 2026-09-23T05:15:44.174181+00:00 |
| 40_qlib/1be752ccd0c3447847521c799e8461d39526f31c5c160812af64e52a1f0662d2 | 51,719 | 11,429,842 | 2026-09-23T05:33:45.759910+00:00 |
| 80_quarantine/balancesheet | 2 | 8,227 | 2026-09-26T04:11:08.379715+00:00 |
| 80_quarantine/cashflow | 2 | 6,242 | 2026-09-26T04:19:04.676017+00:00 |
| 80_quarantine/dividend | 22 | 16,288 | 2026-10-01T14:14:52.994423+00:00 |
| 80_quarantine/fina_indicator | 3 | 9,774 | 2026-10-04T01:58:20.125525+00:00 |
| 80_quarantine/fund_daily | 36 | 5,472 | 2026-09-25T01:45:01.113393+00:00 |
| 80_quarantine/income | 2 | 5,483 | 2026-09-26T03:45:18.432582+00:00 |
| 80_quarantine/index_daily | 32 | 32,914 | 2026-10-04T02:48:37.214517+00:00 |
| 80_quarantine/repurchase | 14 | 5,011 | 2026-10-03T13:56:36.779033+00:00 |
| 90_metadata | 12 | 34,887 | 2026-10-21T00:21:41.492812+00:00 |
| 90_metadata/gc | 871 | 162,179,616 | 2026-09-29T06:04:24.809674+00:00 |
| 90_metadata/logs | 6 | 52,736,392 | 2026-10-20T05:25:52.578532+00:00 |
| 90_metadata/manifests | 50 | 350,356,961 | 2026-10-20T04:04:41.144583+00:00 |
| reports/data_audit | 53 | 9,756,147 | 2026-10-21T00:09:56.619021+00:00 |
| reports/data_integrity | 160 | 1,884,944,367 | 2026-10-17T15:52:37.677870+00:00 |
| reports/data_quality | 594 | 8,690,526,169 | 2026-10-17T15:34:23.981232+00:00 |
| reports/pit_coverage | 242 | 125,956,523 | 2026-10-17T15:34:06.366122+00:00 |
| reports/research_readiness | 109 | 52,101,065 | 2026-10-17T15:49:50.583895+00:00 |

`20_pit/30_features/50_predictions/60_backtests/70_live` 初始化时文件遍历为空，不能把目录存在当作已拥有特征、标签或预测。quant 的 .venv/.git 和 .cache/uv 依赖缓存未统计字节；不是本轮市场数据集。其余 .cache 下的 pytest、元数据恢复和读取基准缓存单独普查，见 supplement.json 的 quant_cache_census，未将测试数据当作生产样本。

## 全部数据集

绝对路径、分区列表、物理版本行、文件数/容量和所有质量计数均见 datasets.json；有效文件逐项见 active_files.csv。以下行数为本次 latest 逻辑精确统计；‘无有效文件’不等于该接口从未有过数据。日期取契约 _event_date，主数据是上市日、财务常为公告日、宏观常为统计期末，不是统一交易日期。

| 数据集 | 类别/频率 | 行数 | 事件时间范围 | 覆盖(ts_code数) | 自然键 | 已记录权限状态 |
|---|---|---:|---|---:|---|---|
| trade_cal | master/事件/快照或来源相关 | 9386 | 2013-12-27 00:00:00 ~ 2026-11-01 00:00:00 | 不适用 | exchange,cal_date | available |
| stock_basic | master/事件/快照或来源相关 | 5907 | 1990-12-01 00:00:00 ~ 2026-09-23 00:00:00 | 5907 | ts_code | available |
| fund_basic | master/事件/快照或来源相关 | 2912 | 1998-04-07 00:00:00 ~ 2026-09-28 00:00:00 | 2912 | ts_code | available |
| index_basic | master/事件/快照或来源相关 | 10604 | 1991-04-04 00:00:00 ~ 2026-09-17 00:00:00 | 10604 | ts_code | available |
| index_classify | master/事件/快照或来源相关 | 870 | None ~ None | 不适用 | index_code,src | available |
| namechange | master/事件/快照或来源相关 | 14218 | 1990-12-01 00:00:00 ~ 2026-09-30 00:00:00 | 5905 | 内容身份，无源事件ID | empty |
| stock_company | master/事件/快照或来源相关 | 6294 | None ~ None | 6294 | ts_code | available |
| new_share | master/事件/快照或来源相关 | 3252 | 2015-01-12 00:00:00 ~ 2026-09-21 00:00:00 | 3252 | ts_code,ipo_date | available |
| bse_mapping | master/事件/快照或来源相关 | 248 | None ~ None | 不适用 | 内容身份，无源事件ID | available |
| stock_st | status/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| st | status/事件/快照或来源相关 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| bak_basic | status/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| stock_hsgt | status/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date,type | permission_denied |
| daily | market/交易日 | 11764739 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5825 | ts_code,trade_date | available |
| adj_factor | market/交易日 | 12277865 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5831 | ts_code,trade_date | available |
| daily_basic | market/交易日 | 11674467 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5904 | ts_code,trade_date | available |
| stk_limit | market/交易日 | 12046364 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5976 | ts_code,trade_date | available |
| suspend_d | status/交易日 | 334629 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 4443 | 内容身份，无源事件ID | empty |
| fund_daily | fund/交易日 | 2770397 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 2714 | ts_code,trade_date | available |
| fund_nav | fund/事件/快照或来源相关 | 3040262 | 2015-01-04 00:00:00 ~ 2026-09-22 00:00:00 | 2823 | ts_code,nav_date | available |
| fund_div | fund/事件/快照或来源相关 | 4083 | 2015-01-07 00:00:00 ~ 2026-09-22 00:00:00 | 418 | 内容身份，无源事件ID | available |
| etf_limit | fund/交易日 | 2235250 | 2019-06-26 00:00:00 ~ 2026-09-22 00:00:00 | 2582 | ts_code,trade_date | available |
| etf_basic | fund/事件/快照或来源相关 | 无有效文件 | None ~ None | 不适用 | ts_code | permission_denied |
| etf_index | fund/事件/快照或来源相关 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| fund_adj | fund/交易日 | 2958557 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 2713 | ts_code,trade_date | available |
| fund_portfolio | fund/事件/快照或来源相关 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| fund_share | fund/事件/快照或来源相关 | 2058878 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 2767 | ts_code,trade_date | available |
| etf_share_size | fund/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| index_weight | index/事件/快照或来源相关 | 862089 | 2015-01-30 00:00:00 ~ 2026-08-31 00:00:00 | 不适用 | index_code,con_code,trade_date | available |
| index_dailybasic | index/交易日 | 40888 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 15 | ts_code,trade_date | available |
| index_member_all | industry/事件/快照或来源相关 | 7920 | 1984-05-09 00:00:00 ~ 2026-09-24 00:00:00 | 5914 | 内容身份，无源事件ID | empty |
| sw_daily | industry/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| ci_index_member | industry/事件/快照或来源相关 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| ci_daily | industry/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| income | financial/事件/快照或来源相关 | 304376 | 2015-01-01 00:00:00 ~ 2026-09-03 00:00:00 | 5865 | ts_code,end_date,ann_date,f_ann_date,report_type,update_flag,comp_type | available |
| balancesheet | financial/事件/快照或来源相关 | 317069 | 2015-01-01 00:00:00 ~ 2026-09-01 00:00:00 | 5865 | ts_code,end_date,ann_date,f_ann_date,report_type,update_flag,comp_type | available |
| cashflow | financial/事件/快照或来源相关 | 315608 | 2015-01-01 00:00:00 ~ 2026-09-03 00:00:00 | 5861 | ts_code,end_date,ann_date,f_ann_date,report_type,update_flag,comp_type | available |
| fina_indicator | financial/事件/快照或来源相关 | 389530 | 2015-04-07 00:00:00 ~ 2026-09-30 00:00:00 | 5864 | ts_code,end_date,ann_date,update_flag | available |
| forecast | financial/事件/快照或来源相关 | 83958 | 2015-01-01 00:00:00 ~ 2026-09-18 00:00:00 | 5670 | 内容身份，无源事件ID | empty |
| express | financial/事件/快照或来源相关 | 20609 | 2015-01-06 00:00:00 ~ 2026-08-24 00:00:00 | 4113 | 内容身份，无源事件ID | empty |
| dividend | financial/事件/快照或来源相关 | 212937 | 1991-03-17 00:00:00 ~ 2026-09-22 00:00:00 | 5819 | 内容身份，无源事件ID | available |
| disclosure_date | financial/事件/快照或来源相关 | 300176 | 1990-12-31 00:00:00 ~ 2026-08-31 00:00:00 | 5890 | 内容身份，无源事件ID | available |
| fina_audit | financial/事件/快照或来源相关 | 63516 | 2015-01-01 00:00:00 ~ 2026-08-31 00:00:00 | 5810 | 内容身份，无源事件ID | empty |
| fina_mainbz | financial/事件/快照或来源相关 | 1780812 | 2015-02-28 00:00:00 ~ 2026-06-30 00:00:00 | 5843 | 内容身份，无源事件ID | available |
| moneyflow | flow/交易日 | 11421685 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5822 | ts_code,trade_date | available |
| margin | flow/交易日 | 6579 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 不适用 | trade_date,exchange_id | available |
| margin_detail | flow/交易日 | 6436851 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5223 | ts_code,trade_date | available |
| margin_secs | flow/交易日 | 7858001 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5131 | 内容身份，无源事件ID | available |
| hsgt_top10 | flow/交易日 | 50010 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 628 | 内容身份，无源事件ID | empty |
| moneyflow_ths | flow/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| moneyflow_dc | flow/交易日 | 无有效文件 | None ~ None | 不适用 | ts_code,trade_date | permission_denied |
| moneyflow_ind_ths | flow/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| moneyflow_cnt_ths | flow/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| moneyflow_ind_dc | flow/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| moneyflow_mkt_dc | flow/交易日 | 无有效文件 | None ~ None | 不适用 | trade_date | permission_denied |
| top_list | event/交易日 | 198701 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 6504 | 内容身份，无源事件ID | empty |
| top_inst | event/交易日 | 2388918 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 6268 | 内容身份，无源事件ID | empty |
| block_trade | event/交易日 | 559254 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 15335 | 内容身份，无源事件ID | empty |
| repurchase | event/事件/快照或来源相关 | 62681 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 3727 | 内容身份，无源事件ID | available |
| pledge_stat | event/事件/快照或来源相关 | 1646734 | 2014-03-07 00:00:00 ~ 2026-09-18 00:00:00 | 4462 | ts_code,end_date | available |
| pledge_detail | event/事件/快照或来源相关 | 220409 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 3399 | 内容身份，无源事件ID | empty |
| stk_holdernumber | event/事件/快照或来源相关 | 473194 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 5610 | 内容身份，无源事件ID | available |
| stk_holdertrade | event/事件/快照或来源相关 | 160788 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 5423 | 内容身份，无源事件ID | empty |
| top10_holders | event/事件/快照或来源相关 | 2319216 | 2014-12-26 00:00:00 ~ 2026-09-30 00:00:00 | 5825 | 内容身份，无源事件ID | available |
| top10_floatholders | event/事件/快照或来源相关 | 2098029 | 2015-01-17 00:00:00 ~ 2026-09-30 00:00:00 | 5784 | 内容身份，无源事件ID | available |
| share_float | event/事件/快照或来源相关 | 6270894 | 2005-08-19 00:00:00 ~ 2026-09-19 00:00:00 | 5326 | 内容身份，无源事件ID | empty |
| stk_rewards | event/事件/快照或来源相关 | 1642908 | 1992-05-26 00:00:00 ~ 2026-09-21 00:00:00 | 5896 | 内容身份，无源事件ID | available |
| stk_managers | event/事件/快照或来源相关 | 363487 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 5799 | 内容身份，无源事件ID | available |
| stk_seasoned | event/事件/快照或来源相关 | 9736 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 3852 | 内容身份，无源事件ID | empty |
| stk_shock | event/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| stk_high_shock | event/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| stk_alert | event/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| limit_list_d | event/交易日 | 无有效文件 | None ~ None | 不适用 | 内容身份，无源事件ID | permission_denied |
| shibor | macro/事件/快照或来源相关 | 2904 | 2015-01-04 00:00:00 ~ 2026-09-22 00:00:00 | 不适用 | date | available |
| shibor_quote | macro/事件/快照或来源相关 | 5830 | 2015-01-04 00:00:00 ~ 2019-03-29 00:00:00 | 不适用 | 内容身份，无源事件ID | available |
| shibor_lpr | macro/事件/快照或来源相关 | 365 | 2015-01-04 00:00:00 ~ 2019-06-28 00:00:00 | 不适用 | date | available |
| cn_gdp | macro/季度 | 46 | 2015-03-31 00:00:00 ~ 2026-06-30 00:00:00 | 不适用 | quarter | available |
| cn_cpi | macro/月 | 140 | 2015-01-31 00:00:00 ~ 2026-08-31 00:00:00 | 不适用 | month | available |
| cn_ppi | macro/月 | 140 | 2015-01-31 00:00:00 ~ 2026-08-31 00:00:00 | 不适用 | month | available |
| cn_m | macro/月 | 140 | 2015-01-31 00:00:00 ~ 2026-08-31 00:00:00 | 不适用 | month | available |
| cn_pmi | macro/月 | 141 | 2015-01-31 00:00:00 ~ 2026-09-30 00:00:00 | 不适用 | month | available |
| sf_month | macro/月 | 140 | 2015-01-31 00:00:00 ~ 2026-08-31 00:00:00 | 不适用 | month | available |
| cn_schedule | macro/事件/快照或来源相关 | 131 | 2026-01-04 00:00:00 ~ 2026-09-30 00:00:00 | 不适用 | 内容身份，无源事件ID | available |
| wz_index | macro/事件/快照或来源相关 | 2703 | 2015-01-04 00:00:00 ~ 2026-09-22 00:00:00 | 不适用 | date | available |
| gz_index | macro/事件/快照或来源相关 | 644 | 2015-01-02 00:00:00 ~ 2019-03-04 00:00:00 | 不适用 | date | empty |
| daily_info | context/交易日 | 55398 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 33 | 内容身份，无源事件ID | empty |
| sz_daily_info | context/交易日 | 41454 | 2015-01-05 00:00:00 ~ 2026-09-22 00:00:00 | 22 | 内容身份，无源事件ID | empty |
| index_daily | index/事件/快照或来源相关 | 23785538 | 2015-01-01 00:00:00 ~ 2026-09-22 00:00:00 | 9598 | ts_code,trade_date | available |

权限状态是 endpoint_capabilities 的历史探测值，并非本轮联网验证；例如 empty 状态与磁盘已有历史记录可以同时成立。抓取时间范围在每表 ranges._ingested_at（序列化保留显式时区偏移，如+08:00，与底层UTC时刻等价），mtime 在目录清单；没有据此承诺更新频率。

## 质量与完整性

NULL 分母均为该字段所属数据集的 latest 逻辑行数；nonfinite 只检查 float/double，NaN/Inf 不等于 SQL NULL。全部原始计数见 fields.json。以下只展示发现项，未展示项不扩展为未执行检查的通过。

| 数据集 | NULL字段数 / 已观察字段数 | 全NULL字段数 | 浮点非有限值 | schema变体数 | 物理行−观察对（重复观察） | 观察对−内容数（重观察） |
|---|---:|---:|---:|---:|---:|---:|
| trade_cal | 4/16 | 4 | 0 | 2 | 0 | 894 |
| stock_basic | 10/29 | 4 | 0 | 2 | 0 | 5,907 |
| fund_basic | 21/37 | 6 | 0 | 2 | 0 | 2,912 |
| index_basic | 11/25 | 5 | 0 | 1 | 0 | 10,604 |
| index_classify | 6/19 | 5 | 0 | 1 | 0 | 870 |
| namechange | 6/18 | 3 | 0 | 2 | 0 | 8 |
| stock_company | 16/30 | 5 | 0 | 2 | 0 | 6,294 |
| new_share | 5/24 | 4 | 0 | 2 | 0 | 19 |
| bse_mapping | 5/16 | 5 | 0 | 1 | 0 | 248 |
| daily | 8/25 | 3 | 0 | 2 | 0 | 149,779 |
| adj_factor | 3/15 | 3 | 0 | 2 | 0 | 150,197 |
| daily_basic | 21/31 | 4 | 0 | 2 | 0 | 149,777 |
| stk_limit | 4/19 | 3 | 0 | 2 | 0 | 152,134 |
| suspend_d | 5/16 | 4 | 0 | 3 | 0 | 263 |
| fund_daily | 3/23 | 3 | 0 | 2 | 0 | 57,116 |
| fund_nav | 10/21 | 3 | 0 | 2 | 0 | 0 |
| fund_div | 17/28 | 3 | 0 | 3 | 0 | 0 |
| etf_limit | 4/19 | 3 | 0 | 2 | 0 | 57,874 |
| fund_adj | 3/15 | 3 | 0 | 2 | 0 | 57,833 |
| fund_share | 4/15 | 4 | 0 | 2 | 0 | 0 |
| index_weight | 4/16 | 4 | 0 | 2 | 0 | 2,527 |
| index_dailybasic | 4/24 | 4 | 0 | 2 | 0 | 393 |
| index_member_all | 5/23 | 4 | 0 | 3 | 0 | 23 |
| income | 88/106 | 10 | 0 | 1 | 0 | 4 |
| balancesheet | 152/170 | 4 | 0 | 1 | 0 | 4 |
| cashflow | 91/109 | 1 | 0 | 2 | 0 | 4 |
| fina_indicator | 165/179 | 2 | 0 | 2 | 0 | 0 |
| forecast | 10/24 | 2 | 0 | 2 | 0 | 0 |
| express | 30/44 | 4 | 0 | 2 | 0 | 0 |
| dividend | 18/28 | 2 | 0 | 4 | 0 | 50 |
| disclosure_date | 5/18 | 2 | 0 | 4 | 0 | 239 |
| fina_audit | 4/19 | 2 | 0 | 2 | 0 | 0 |
| fina_mainbz | 6/21 | 3 | 0 | 2 | 0 | 0 |
| moneyflow | 4/32 | 4 | 0 | 3 | 0 | 149,779 |
| margin | 5/21 | 4 | 0 | 2 | 0 | 81 |
| margin_detail | 13/23 | 4 | 0 | 4 | 0 | 119,882 |
| margin_secs | 4/16 | 4 | 0 | 3 | 0 | 120,602 |
| hsgt_top10 | 9/23 | 4 | 0 | 2 | 0 | 540 |
| top_list | 14/27 | 4 | 0 | 2 | 0 | 1,769 |
| top_inst | 8/22 | 4 | 0 | 2 | 0 | 19,025 |
| block_trade | 6/19 | 4 | 0 | 2 | 0 | 2,797 |
| repurchase | 11/21 | 3 | 0 | 2 | 0 | 906 |
| pledge_stat | 5/19 | 4 | 0 | 3 | 0 | 1,077 |
| pledge_detail | 12/26 | 3 | 0 | 2 | 0 | 0 |
| stk_holdernumber | 6/16 | 3 | 0 | 2 | 0 | 2 |
| stk_holdertrade | 9/25 | 3 | 0 | 2 | 0 | 1,372 |
| top10_holders | 6/21 | 3 | 0 | 2 | 0 | 0 |
| top10_floatholders | 6/21 | 3 | 0 | 2 | 0 | 0 |
| share_float | 5/19 | 3 | 0 | 3 | 0 | 32,710 |
| stk_rewards | 9/19 | 3 | 0 | 3 | 0 | 2,207 |
| stk_managers | 12/24 | 3 | 0 | 2 | 0 | 0 |
| stk_seasoned | 66/81 | 6 | 0 | 6 | 0 | 89 |
| shibor | 4/14 | 4 | 0 | 2 | 0 | 28 |
| shibor_quote | 4/16 | 4 | 0 | 1 | 0 | 0 |
| shibor_lpr | 4/13 | 4 | 0 | 1 | 0 | 0 |
| cn_gdp | 3/21 | 3 | 0 | 1 | 0 | 0 |
| cn_cpi | 3/25 | 3 | 0 | 1 | 0 | 1 |
| cn_ppi | 3/43 | 3 | 0 | 1 | 0 | 1 |
| cn_m | 3/22 | 3 | 0 | 1 | 0 | 1 |
| cn_pmi | 26/72 | 3 | 0 | 1 | 0 | 1 |
| sf_month | 4/16 | 3 | 0 | 1 | 0 | 1 |
| cn_schedule | 4/17 | 3 | 0 | 2 | 0 | 28 |
| wz_index | 13/25 | 4 | 0 | 2 | 0 | 27 |
| gz_index | 4/19 | 4 | 0 | 2 | 0 | 0 |
| daily_info | 14/26 | 4 | 0 | 2 | 0 | 322 |
| sz_daily_info | 9/21 | 4 | 0 | 2 | 0 | 378 |
| index_daily | 12/23 | 3 | 0 | 1 | 0 | 54 |

不同 schema 指纹可能来自 timestamp 单位/null 类型差异，不能一概称为字段丢失；每个变体字段与类型已完整列入 datasets.json，可按分区/文件回溯。未观察到的契约字段在字典标记无实际类型。业务键版本差异先保留再取 latest；上述‘重复观察’不是删除建议。缺失率仅检查 SQL NULL，未将空字符串/来源哨兵值全部归类为缺失；经济含义离群值也没有全字段阈值认证。

分区 schema 复核：8,540 个有效文件，读取错误 0，缺失/额外来源字段文件 0；各分区的字段完整类型并集见 schema_partitions.json。
全量价格/键/日期检查中的非零发现：

- `index_daily.close<=0` = 1,472 / 23785538 行。

跨表与日历全量检查（daily 逻辑行作为关联检查分母）：

```json
{
  "daily_without_adj_factor": 0,
  "daily_without_daily_basic": 90362,
  "daily_without_stk_limit": 92144,
  "daily_unknown_stock_master": 3,
  "daily_dates_outside_exchange_calendar": 349052,
  "calendar_gaps_within_observed_symbol_span": 267247,
  "gap_note": "Within first/last observed bar only; suspensions/lifecycle not subtracted; not certified missing bars."
}
```

缺口数是股票×开市日组合，起止仅为首末已见行情，尚未扣停牌，不覆盖首个观测之前/最后观测之后的遗漏。日历只覆盖已有交易所；未提供的交易所日历不能借用另一市场认证。未对所有稀疏事件、季度/月度宏观、财报逐证券应报期作完整性认证。

进一步精确拆分（relationship_details.json）：
- 本地开市日历（exchange/行数/起止）：`[['SSE', 3120, '20131227', '20261030'], ['SZSE', 3120, '20131227', '20261030']]`。日历未匹配行情（代码后缀/行数/证券数）：`[['BJ', 349052, 350]]`。没有BSE日历时，不能对BSE计算完整应有交易日分母，也不能据此称行情日期错误。
- 缺daily_basic（后缀/行数/证券数/起止）：`[['BJ', 90362, 241, '20150105', '20221230']]`；缺涨跌停：`[['BJ', 91014, 241, '20150105', '20221230'], ['SH', 1, 1, '20190722', '20190722'], ['SZ', 1129, 2, '20150105', '20191213']]`。
- 当前stock_basic未包含的代码（代码/行情行数/起止）：`[['000022.SZ', 691, '20150105', '20181220'], ['000043.SZ', 1127, '20150105', '20191213'], ['300114.SZ', 2447, '20150105', '20250214']]`。需要补证券生命周期/代码变更或退市映射，不能直接按当前主表inner join丢弃历史股票。
- 首末已见日范围内应有股票×开市日组合 11,682,934，缺行情267,247个；按市场拆分`[['SH', 82108], ['SZ', 185139]]`；其中257,115个能匹配当天`suspend_type=S`，剩余10,132个尚未解释。这里只匹配同日停牌标记，未重建连续停牌区间，剩余数不等于已确认遗漏。
- 指数日线分母23785538行；OHLC/amount/vol的NULL数：`{'open': {'nulls': 20776974, 'rows': 23785538, 'nonfinite': 0}, 'high': {'nulls': 20776974, 'rows': 23785538, 'nonfinite': 0}, 'low': {'nulls': 20776974, 'rows': 23785538, 'nonfinite': 0}, 'close': {'nulls': 35640, 'rows': 23785538, 'nonfinite': 0}, 'amount': {'nulls': 8263446, 'rows': 23785538, 'nonfinite': 0}, 'vol': {'nulls': 4496680, 'rows': 23785538, 'nonfinite': 0}}`。需要按指数类型和来源资格筛选，不可用0填补或宣称全库指数OHLC可用。

Raw 抽样错误：0 / 201 文件；抽样总解码 146,338 行。所有样本路径和 schema 保留，未抽样批次的可读性未认证。
辅助审计 CSV：365 文件，SQLite：1 文件；字段和流式行数另存 auxiliary_tables.json。它们是旧审计产物，**不并入金融样本总数**。目录中的 DuckDB 快照/恢复演练库、PDF 披露证据及 JSONP 网页证据未逐库/逐页重新解析，其历史结论仅作线索。

注册任务状态：`[['SUCCESS', 183199], ['FAILED_RETRYABLE', 80], ['PENDING', 174], ['FAILED_PERMANENT', 57]]`。存在未完成任务时，时间最大值不能代表回填完成。

## Qlib、因子与旧标签

- `E:\QuantData\40_qlib\0e4a03a042a75d520cbc52d82fa57e9f0097b4669b58ed0e3c842a4f6050f179`：54,131 个 bin，6,028,400 字节，长度异常 0 个；manifest 证券数 7733，范围 2026-08-17 至 2026-09-22。模式 `market_replay`；源版本 `e62c345c9d322da72d86f6a281b19e32d0351ca021268b05043a9dfd4f8c9ebf`。
- `E:\QuantData\40_qlib\1be752ccd0c3447847521c799e8461d39526f31c5c160812af64e52a1f0662d2`：51,716 个 bin，5,761,336 字节，长度异常 0 个；manifest 证券数 7388，范围 2026-08-17 至 2026-09-22。模式 `market_replay`；源版本 `4045db6327b0e88cbbcdcbf4b6071c5203698f37235d4dde26dde7e9a9dc9962`。

两个 Qlib export 共享同源历史，版本不同，不能拼接当新增样本。bin 为 float32 序列，首值是日历偏移；OHLC=原价×research_factor，volume=手×100/research_factor，amount=千元×1000，factor 为归一化复权比例；不得把 Qlib volume 与未复权股数混用。七个字段的实际文件名保存在 supplement.json。
factor_registry/model_registry/experiment_registry 为空，30_features 未有发布文件；有动量函数源码不等于已有因子样本。指定目录中未发现独立已发布预测标签表；Qlib 导出仅行情/因子字段，不提供可默认继承的 Y。旧项目标签未进入本研究，未来收益标签需要重新定义并验证。

## 复权、信息时钟和泄漏风险

- 原行情为提供商未复权口径。研究收益链 `close[t]*adj[t]/(close[t-1]*adj[t-1])-1`，首观测锚定指数不使用未来最新前复权基准；展示 qfq 使用最新因子，只能展示。提供商因子未独立核验为现金分红再投资总收益。Y 应明确其经济口径、交易期限和端点可得性，不给停牌自动填价。
- `_ingested_at` 是抓取观察时间；`_available_at` 至少为观察时间，若 ann_date/f_ann_date/actual_date 更晚则保守跨日；`_event_available_at` 仅白名单行情按上海23:59:59重建。这些字段不等于全部数据的真实首次公开时刻。
- 财务历史 API 可能返回今天修订后的过去报表。end_date、ann_date、f_ann_date、update_flag 不能提供完整修订公开轨迹。严格历史查询必须先过滤知识时间再挑版本；2026年首次抓取的2018年财报不能自动认证为2018年可见。
- stock_basic/行业成员是当前观察到的历史描述，上市/退市日期不代表当时所有属性已知。ST 权限缺口、历史证券生命周期和行业成员发布时间需要补证；不能只选今天仍上市股票。日历完整性仍需按交易所验证。
- 宏观 month/quarter 是统计期，不是 release date；cn_schedule 不能未经映射直接证明所有指标可得时间。缺失字段、修订和低频到日频关联均需显式门禁。
- 旧审计文档标记 index_daily BLOCKED，只作历史证据；本轮数值检查结果见上文，不将旧阻塞或旧通过自动替代当前检查，也未做独立外部报价一致性核验。
- 标签跨越训练/验证边界会泄漏；需要按最大标签期限隔离，文本也需首次公开时间与去重来源。基座可能记忆历史结果的风险需单独记录，时间切分不能消除它。

## X_state / 文本 / Y 的可用性与下一步

| 数据 | 用途 | 本轮判断 |
|---|---|---|
| daily + adj_factor + 日历 | X_state 量价、Y 候选收益链 | 可作提供商历史重建的研究起点；先解决键关联、停牌/生命周期及缺口解释，固定版本与时钟 |
| daily_basic、资金流、融资、涨跌停 | X_state 扩展 | 有实际数据；各字段 NULL、覆盖不齐，估值/资金流并非全部在 market_eod 白名单，不能随意回填严格 PIT |
| 财务/事件/宏观 | X_state、可选结构化转文本 | 需要公告可得时点与修订策略；把同一数字改写为文字不等于独立文本来源 |
| stock_basic / index_weight / industry / status | 历史样本池及关联 | 当前主数据和权限不足以认证完整历史股票池；需剔除幸存者偏差 |
| 公告/新闻正文、研报 | 文本输入 | 未发现系统化正文语料及全文发布时间索引；PDF/JSONP 只是旧审计证据，不可当全库文本 |
| Qlib / 旧审计缓存 | 快速读取/参考 | 有限复用、固定来源版本；不是独立数据源，未继承旧标签或收益 |

下一步先选择一个覆盖可解释的证券/日期小范围，固定数据版本，逐证券解释停牌与退市、关联因子和交易所日历，再讨论预测期限和收益分档。为文本实验补充可追溯的正文、首次公开时间、修订版本和去重规则。之后核验 Karpo 原生决策契约及 Xlab 资源，做小规模监督后训练；文本条件共享相同样本、标签、切分、预算与评估。

## 机器可读附件

- `inventory/datasets.json`：88个契约、有效文件/分区/schema、精确行数/范围/质量、关系检查及运行时信息。
- `inventory/fields.json`：完整来源/Canonical 字段并集，声明类型/实际类型/说明/单位或明确未知/键/每字段 NULL 与分母。
- `inventory/schema_partitions.json`：逐数据集/分区字段类型及契约字段差异文件。
- `inventory/relationship_details.json`：关联缺口按市场拆分、主表孤立代码及日历缺口分母。
- `inventory/active_files.csv`：逐文件路径、分区、登记行数与登记SHA256；本轮不宣称重新哈希。
- `inventory/filesystem_data.json` 与 `filesystem_code.json`：全目录/限定代码目录容量及遍历错误。
- `inventory/supplement.json`：Raw 样本、已记录覆盖证据、schema_registry、Qlib 与来源代码哈希。
- `inventory/auxiliary_tables.json`：审计CSV/SQLite字段和行数；`environment.json`：依赖版本。
