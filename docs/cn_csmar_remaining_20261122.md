# CSMAR 续采及历史缺口增量

2026-11-22 晚间新增 1 次普通明细下载、137 条 `ANN_Security` 原始记录。第二个范围在计数成功后收到服务端 `-2404`，当日停止采集。原有 53 个明细页的 SHA-256 逐一复用，归档现有 54 页、2,371,420 条原始记录。 [机器摘要](cn_csmar_remaining_20261122.json)

## 下载和额度

| 范围 | 实测结果 |
|---|---|
| 2025 年相关停牌公告 | 将候选日期、停牌标题和精确公开时刻合并为一次请求。服务端计数 137，归档 137。 |
| 2018 年同类公告 | 同条件等待期结束后计数 957，普通明细下载收到 `-2404`，成功明细 0。计数回执保留，额度恢复后可直接校验并续采。 |
| 其余精确年度范围 | 2019–2024 年、2026 年仍待续采。上次同条件计数 HTTP 401，未计作当日额度失败。服务端对该表实测单请求跨度至多一年，已在年度内合并。 |

本机当日累计记录 15 次普通明细成功和 3 个官方包成功。CSMAR 未公开本次包的扣次，单凭本机回执无法推算官方额度上限。2018 年有一个已确认的明细页。另七个年度的页数等成功计数后再定。 [续采范围](../artifacts/cn_numeric_followup/csmar_remaining_20261122/pending_announcement_plan.json) · [归档审计](../artifacts/cn_numeric_followup/csmar_remaining_20261122/capture_audit.json)

## 本轮实际恢复

| 数据 | 实际结果 |
|---|---|
| 停牌公开时点 | 2025 年公告直接确认 25 个证券日。复用已归档的 `TSR_Stkstat`，按当时公开日及独立日频停牌证据，确认无复牌日期记录的连续停牌片段 151 段、2,794 个证券日。按生产时点展开逐键匹配，合计补 2,819 个证券日，剩 12,062 个待证实。 |
| 北交所财务 | 对已保存的 2,131 份报告按单张合并报表校验，1,356 份有金额与 CSMAR 一致。补充 936 个已知财报版本，新增 338 个公开时点有依据的版本。用契约 v1.1 复算北交所 304 家发行人、217,747 个有效输入证券日，七项核心财务完整从 69,939 增至 109,790，新增 39,851，余 107,957。 |
| 证券股本、证券市值及发行人市值 | 对四家发行人的股类原件、CSMAR 股本变动与 TuShare 日频股本进行交叉核验，实际生成 10,569 个证券日的差量。其中截至预测截止日的 10,149 个有效输入同时补齐股本及发行人市值。差量键唯一，所有公开时点不晚于样本。 |

北交所营业收入 TTM、全部净利润 TTM、归母净利润 TTM、经营现金流 TTM 分别净增 72,040、73,233、53,402、1,242 个有效输入证券日。两次回放都非空的金额没有被改写。较新报表期生效后，资产、负债、归母权益各 49 个证券日以及上年同期资产、归母权益各 18 个证券日因新锚点组成项未取得而转为空，详情含实际样本。对 301 家发行人完成 4,547 个时点的前缀不变性验证。抽查诺思兰德 2024 年半年报第 41 页的合并利润表及当期负号。 [财务回放](E:/QuantData/numeric/.build-cn/sources/csmar-pit-remaining-20261122/finance/financial_production_replay.json) · [诺思兰德原件](https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSEBJ_STOCK/2024/2024-8/2024-08-28/10437125.PDF)

股本差量使用原件的人民币普通股及股份总数两行，原件仅有日期时从次日可用。旧股本区间以 CSMAR 能证实的下一变动日为界。报告另列 172 个缺独立日频对照的证券日，它们在本次差量范围外。 [股本回放](E:/QuantData/numeric/.build-cn/sources/csmar-pit-remaining-20261122/share/share_replay.json) · [600128 原件](https://static.cninfo.com.cn/finalpage/2012-08-31/61512020.PDF) · [600508 原件](https://static.cninfo.com.cn/finalpage/2014-03-19/63692609.PDF) · [601003 原件](https://static.cninfo.com.cn/finalpage/2013-04-25/62422190.PDF) · [601158 原件](https://static.cninfo.com.cn/finalpage/2014-04-04/63787921.PDF)

## 剩余缺口与发布状态

- 停牌仍有 12,062 个证券日要核对原公告，剩余八个年度的 CSMAR 断点已保存。北交所仍有 107,957 个有效输入证券日缺至少一项核心财务，经营现金流 TTM 缺 57,330 个。后续优先取得缺失组成期的原报表和更正公告。
- 应用本轮已核准差量后，预计有效输入仍缺 1,602,545 个证券日的证券股本和 1,636,297 个证券日的发行人市值。大的缺口仍需对应股类的早期发行或实际变更原件。多股类估值还需可用的同期跨股类报价。
- 历史申万一级行业母集、分期成员公告、U 股数单位链、历史简称和涨跌停状态本轮没有新增合格来源。CSMAR 早前取得的限价明细行中所需限价字段为空。申万和 U 链的优先证据是当时发布的成分名单与实际公司行动档案。 [上一轮缺口与来源](cn_csmar_gap_reuse_20261122.md)
- 增量已进入 `E:\QuantData\numeric\.build-cn\sources\csmar-pit-remaining-20261122`。财务增量依赖上轮已核准的现金流版本。本轮合并后的同日停牌证据覆盖此前 2015–2017 年文件的范围。正式训练读取仍指向 `cn-71132cf…`，状态 `INCOMPLETE`。80 项仓库测试通过。

额度恢复后的续采命令沿用已归档的条件与结果。

```powershell
Set-Location 'E:\Kurumi'
$sdk = 'E:\Kurumi\artifacts\cn_numeric\csmar_runtime\.venv\Scripts\python.exe'
$plan = 'E:\Kurumi\artifacts\cn_numeric_followup\csmar_remaining_20261122\pending_announcement_plan.json'
$capture = 'E:\QuantData\numeric\.build-cn\sources\csmar'
& $sdk -X utf8 scripts/csmar_acquire.py --out $capture --plan $plan --prefer-packages
```
