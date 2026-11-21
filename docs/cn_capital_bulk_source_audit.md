# A 股历史股本批量来源核验

2026 年 11 月 20 日以已发布 V4 为基线。预测日期范围内有 2,094,073 个证券日缺精确目标股类股本，其中 370,986 个落在 TuShare 盘前股本接口声明的起始日之后。其余 1,723,087 个早于 2024-05-01。370,986 是日期交集上限，仍需逐股核实股类、更新时点及回修。市场位于历史母集的前一期股本缺口为 2,110,997 个成员日，使用的日期键与证券日统计不同。 [证券日范围](../artifacts/cn_numeric_followup/capital/daily_authoritative_probe/v4_capital_gap_scope.json) · [前一期市场母集](../artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

| 路线 | 实际核验与可用边界 |
|---|---|
| 上交所公开股本变动查询 | 实取 600522、600028、601328、603605 合计 83 条，四只证券均达到服务端分页总数。返回精确到股的 A 股、B 股、总股数和记录编号。返回的 `realDate` 没有配套公告字段。中国石化原件载为 2015-02-11 股本变化，接口显示 `2015-02-16`，逐日时点需以具体原件核对。按 `seq` 再请求仍返回相同的 33 条。正式站和繁体镜像明细链接均为 HTTP 404。可做独立股数核对，未新增可入库时点行。 [接口响应](../artifacts/cn_numeric_followup/capital/daily_authoritative_probe/sse_capital_event_response_probe.json) · [明细复测](../artifacts/cn_numeric_followup/capital/daily_authoritative_probe/sse_detail_yearbook_audit.json) |
| 上交所公开统计年鉴 | 实取 2020 年鉴原件，2019 年变动表列股票代码、简称、变动后总股本、变动原因和变动日期。表内缺公告日期，而且股数显示尺度比精确到股的事件接口粗。 [年鉴原件](https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061074/files/4ea3a8b53f144e69879a56b3bc4569c9.pdf) |
| 北交所与中国结算 | 北交所公开个股列表实测提供最新业务日期及当日总股本。正式技术文档描述下发给市场参与者的每日静态文件，未找到可公开历史下载的完整目标股类股本。中国结算股本结构实时查询面向发行人，采用 PROP 或发行人网上业务系统。 [北交所公开接口证据](../artifacts/cn_numeric_followup/market_denominator/official_live_probe.json) · [北京市场静态数据文档](https://www.bse.cn/uploads/6/file/public/202508/20250812182648_1tic2qew12.pdf) · [中国结算发行人入口](https://m.chinaclear.cn/zdjs/std/plat_zindex.shtml) |
| TuShare 盘前股本 | 使用现有账号实际请求 2026-06-30，服务端明确拒绝 `stk_premarket` 权限。官方定义从 2024-05-01 开始，09:00 和 18:10 更新，有总股本及流通股本。开通后先核对历史返回属于哪次发布及当时是否有独立的 B/H 股类，再接入合格行。 [权限回执](../artifacts/cn_numeric_followup/capital/daily_authoritative_probe/tushare_stk_premarket_live_probe.json) · [官方接口](https://tushare.pro/document/2?doc_id=329) |
| 巨潮和理杏仁 | 巨潮 `p_stock2215` GET 和 POST 均返回业务码 003。理杏仁正式 API HTTP 401。公开页面可以在检索索引中看到公告日与变动日，股数按显示精度缩写。四个股票页面的本机直连均为 HTTP 403，浏览器未取得可核验的 CSV。未用展示数值与网页发布时间进行回填。 [实测回执](../artifacts/cn_numeric_followup/capital/daily_authoritative_probe/public_source_initial_result.json) · [理杏仁授权接口](https://www.lixinger.com/api/open-api/html-doc/cn/company/equity-change) · [页面实测](../artifacts/cn_numeric_followup/capital/daily_authoritative_probe/lixinger_public_rows.json) |
| CSMAR 已取字段与预定续采 | `TRD_Capchg.Shrchgdt` 为变动日，无公告时间。`IDX_Idxstk` 有证券交易日、总股数和 A/B/H 流通股数，无独立公告时点和各股类完整发行股数。现有权限计划包含 `CD_Dividend.Ddadt`、`Annocont`、`DistributionBaseShares` 和登记生效日期，实取后可验证具体已实施股本事件。分红基数须区分总发行量与扣掉库存股后的参与分红数量。本次核验未发起新的 CSMAR SDK 请求。 [CSMAR 字段与续采](cn_csmar_source_audit.md) |

## 可以申请的批量数据

- 上证所信息网络的主参考数据包含日频 `YYYYMMDD_SHARECAPITAL_CCC.txt`，有证券、数据日、最近变动日、总股数、非流通股和 H 股数。官方表列更新时间为 T+1 08:45，采购前应确认 2014 年预热至 2026-07 的原始逐日留档、当日发布批次及 A/B 类别的完整定义。T 文件可以随后实际可用时点使用。由 T 当日晚首次发现的变化仍需要当晚证据或正式版本时间。申请入口提供主参考数据和历史数据服务。 [产品规格](https://www.sseinfo.com/services/assortment/document/product/c/10010538/files/5322996.pdf) · [发布时点及字段](https://bsp.sseinfo.com/admin/static/public/2024-06-07/163dba54e4334131b2d953ede8a8368c/%E4%B8%8A%E6%B5%B7%E8%AF%81%E5%88%B8%E4%BA%A4%E6%98%93%E6%89%80LDDS%E7%B3%BB%E7%BB%9F%E4%B8%BB%E5%8F%82%E8%80%83%E6%95%B0%E6%8D%AE%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E%E4%B9%A6%E6%8A%80%E6%9C%AF%E5%BC%80%E5%8F%91%E7%A8%BF.pdf) · [服务入口](https://www.sseinfo.com/services/sseai/aidata/)
- 深交所授权深圳证券信息有限公司提供 `End-of-day Data`，官方说明含日终 A/B 证券股本及收盘。采购前须从样本文件核对是完整发行股数还是流通股，确认历史区间和当时日终发布版本。 [深交所官方数据服务](https://www.szse.cn/English/services/dataServices/)
- BigQuant `cn_stock_capital` 文档提供公告日、实际变动日、A/B 类别总数、各类流通与限售、香港上市股数。下载需 DAI 数据授权及本地 SDK API Key，当前环境没有可用授权。目录标示的起始字段不能证明实际覆盖 2015 年。理杏仁 `cn/company/equity-change` 提供公告和生效日期、流通及限售 A，单次日期跨度不超过十年。对两者都应先取得旧样本、退市、北交所、历史修订与单位的实际受许可记录，再评估剩余全历史缺口的覆盖。 [BigQuant 字段](https://bigquant.com/data/datasources/cn_stock_capital) · [BigQuant SDK 授权](https://aistudio.bigquant.com/wiki/doc/vac4qwmQr4) · [理杏仁字段](https://www.lixinger.com/api/open-api/html-doc/cn/company/equity-change)

本次探查没有产生可冻结的额外大批次股本版本。现有来源确认多数缺口需要能重放具体历史时点和股类的逐日档案，或可以对应发行人原始披露的结构化事件记录。保留既有数据质量掩码。

```powershell
$dataRoot = 'E:\QuantData\numeric'
$pointer = Get-Content (Join-Path $dataRoot 'latest_cn.json') -Raw | ConvertFrom-Json
python .\scripts\audit_cn_capital_feed_scope.py --release (Join-Path $dataRoot $pointer.path) --output .\artifacts\cn_numeric_followup\capital\daily_authoritative_probe\latest_capital_gap_scope.json
```
