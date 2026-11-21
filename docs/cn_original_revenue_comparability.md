# 原始财报营业收入可比性审核

第三批财报解析找回 118 条累计合并营业收入，覆盖 8 家发行人。对全部 118 条核验了财报原件哈希、公开日、累计列和上年同期比较列，再与当时已公开的同一报告期旧版本比较。保守组合准入 98 条。留置 20 条，包括 10 条金额明确重述、6 条金额相同且报告声明进行了追溯调整、4 条缺可核对的同期旧值。第二批的 72 条在第三批均保留，金额和比较列无改动。新增报告原件使长江电力 2025 年报从“旧值未知”变为“金额相等且报告声明追溯调整”，仍然留置。

[第三批逐键审核与 PDF 页码](/E:/Kurumi/artifacts/cn_numeric_followup/industrial_revenue_originals/comparability_v3/comparability_audit.json) [准入财务记录](/E:/Kurumi/artifacts/cn_numeric_followup/industrial_revenue_originals/comparability_v3/admitted_financial_versions.jsonl) [原记录替换键](/E:/Kurumi/artifacts/cn_numeric_followup/industrial_revenue_originals/comparability_v3/review.json)

在 8 家发行人的 332 个实际公告快照上重放第三批准入记录，新增 99 个 `revenue_ttm` 和 78 个 `revenue_ttm_4q_ago`，已有财务数值和公告时钟保持一致。另独立准入工业富联 2019 年三季报，补入 1–9 月累计合并营业收入 279,895,866,000 元。该报告的同比列与 2018 年三季报原值同为 283,925,768,000 元，原件第 4.3 节确认未追溯调整前期比较数据。独立重放额外补入两项 TTM 字段各 5 个。 [财务生产回放](/E:/Kurumi/artifacts/cn_numeric_followup/industrial_revenue_originals/comparability_v3/financial_snapshot_replay.json) [工业富联补充审核与原件哈希](/E:/Kurumi/artifacts/cn_numeric_followup/industrial_revenue_originals/additional_foxconn_2019q3/comparability_audit.json)

另准入美的集团 2021 年中报和寒武纪 2021 年一季报。美的集团本期累计合并营业收入为 173,809,565,000 元，同比金额 139,067,022,000 元与 2020 年原中报一致。2021 年租赁准则变更未重列 2020 年比较报表。附注明列的当期收购属于非同一控制下合并，历史按同一控制取得的芜湖厨卫公司在 2020 年中报已有记录。寒武纪本期收入为 36,131,025.54 元，2020 年同期比较数 11,552,641.24 元与上市前招股原件的 1,155.26 万元在其披露精度内一致，之后披露的 2020 年年报复核到同一精确金额。本批只补寒武纪 2021 年正式季报值。两个本期值分别从 2021-09-01 和 2021-04-28 进入可用范围。独立回放增加寒武纪的 3 个 `revenue_ttm` 和 2 个 `revenue_ttm_4q_ago`，美的集团单条本期值尚未组成新的完整 TTM。 [补充核验、原件哈希与回放](/E:/Kurumi/artifacts/cn_numeric_followup/industrial_revenue_originals/additional_final_review/comparability_audit.json) [美的集团 2021 年中报](https://static.cninfo.com.cn/finalpage/2021-08-31/1210925570.PDF) [寒武纪 2021 年一季报](https://static.cninfo.com.cn/finalpage/2021-04-27/1209820593.PDF)

| 发行人 | 新报告期 | 被调整的同期 | 原版本金额（元） | 该报告的比较金额（元） | 首个可用交易日 |
| --- | --- | --- | ---: | ---: | --- |
| 长江电力 | 2023 Q1 | 2022 Q1 | 9,738,207,780.31 | 12,301,661,386.16 | 2023-05-04 |
| 长江电力 | 2023 Q3 | 2022 Q3 | 41,269,459,721.80 | 53,066,769,846.54 | 2023-11-01 |
| 长江电力 | 2023 年度 | 2022 年度 | 52,060,482,557.85 | 68,863,128,424.25 | 2024-05-06 |
| 长江电力 | 2024 年度 | 2023 年度 | 78,111,573,265.75 | 78,143,535,736.10 | 2025-05-06 |
| 长江电力 | 2025 Q1 | 2024 Q1 | 15,640,900,490.43 | 15,656,758,358.43 | 2025-05-06 |
| 中国石油 | 2019 Q3 | 2018 Q3 | 1,709,933,000,000 | 1,726,717,000,000 | 2019-11-01 |
| 中国石油 | 2024 年度 | 2023 年度 | 3,011,012,000,000 | 3,012,812,000,000 | 2025-04-01 |
| 中国石油 | 2025 Q1 | 2024 Q1 | 812,184,000,000 | 812,801,000,000 | 2025-05-06 |
| 中国石油 | 2025 Q2 | 2024 Q2 | 1,553,869,000,000 | 1,554,973,000,000 | 2025-08-28 |
| 中国石油 | 2025 Q3 | 2024 Q3 | 2,256,279,000,000 | 2,257,694,000,000 | 2025-11-03 |

长江电力的 5 条金额变化均由报告说明归因于同一控制下合并。中国石油 2019 年三季报同时说明实施新租赁准则及同一控制下合并大连西太平洋石化。2024 年报及 2025 年的三份季报均说明大庆油田收购中油电能，自 2024 年 10 月 29 日纳入合并并调整比较期间。中国石油同时披露国际与中国企业会计准则报表，实际更正例的营业收入已核中国准则报表或指标页。 [中国石油 2019 年第三季度报告](https://www.petrochina.com.cn/petrochina/rdxx/201910/ea530434be2341f9aaad6a86f2bb567a/files/ac140451958d4f1d99e02b99ec5e9bf8.pdf) [长江电力 2025 年第一季度报告](https://static.cninfo.com.cn/finalpage/2025-04-30/1223421165.PDF)

比较值相等但明确声明追溯的范围为长江电力 2024 年一季报、中报、三季报及 2025 年三季报、年报，以及贵州茅台 2023 年报。茅台声明对应一项递延所得税会计解释，原件的同比收入相同。缺可核对旧值的范围是美的集团 2022 年中报和三季报、新易盛 2022 年一季报、寒武纪 2022 年一季报。上述首个可用交易日根据日期级公告次日开始和实测证券交易日计算。

后续可将重述值建立为单独的原期间历史版本，生效时钟取披露它的报告，之前样本保留当时的版本。对新口径下的累计值做单季转换时，仍需证明相关前序累计、同年末和同比组成期间可统一。一条同比比较数可以确证历史修订事实，不能单独证明整个 TTM 窗口。第三批准入清单保留原始报告本期值，20 条待审记录完整留存。

## 补采收口与发布前回放

扩展索引识别后，8 家公司 128 个缺失收入的原公告时点中，123 个通过常规归档解析取得合并累计营业收入。另 5 个时点用巨潮资讯正式原件和扫描表格逐一复核。原件校验覆盖财报页、会计期、报表币种、单位、当期合并列和上一年比较列。最终准入 110 个时点，其中寒武纪 2021 年一季报用上市前官方披露和年报原件交叉核验。其余 18 个已抽取时点保留原有缺失标志，涉及待统一的重述、合并范围或比较期原值。 [常规原件比较](../artifacts/cn_numeric_followup/industrial_revenue_originals/comparability_v6/comparability_audit.json) · [寒武纪与美的专案](../artifacts/cn_numeric_followup/industrial_revenue_originals/additional_final_review/comparability_audit.json) · [五份最后核验](../artifacts/cn_numeric_followup/industrial_revenue_originals/remaining_official/verified_exact_official_revenue.json) · [扫描版财务证据](../artifacts/cn_numeric_followup/industrial_revenue_originals/scanned_residue_2021/replay.json)

冻结财务流按现行 PIT 算法连接实际有效输入日。八家公司新增 8,894 个当期 TTM 和 7,438 个一年以前 TTM，均可复查对应原公告。逐公司比对既有非空值和最早修改时点以前的快照。 [全部准入记录的股票日回放](../artifacts/cn_numeric_followup/industrial_revenue_originals/guarded_replay_all/industrial_revenue_replay.json)
