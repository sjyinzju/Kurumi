# 申万行业历史来源核验

## 已取得的官方资料

2026-11-19 使用经过证书链校验的 HTTPS 下载了申万宏源研究现行行业历史 XLS、2021 版分类字典和冻结的旧版 RAR。站点未发送中间证书，补齐了与站点证书匹配的 DigiCert 官方中间证书。三个响应均为 HTTP 200，实际文件均符合各自二进制格式。下载及异常回执存放在 `artifacts/cn_numeric/sw_source/`。 [行业历史 XLS](https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls) · [分类字典 XLS](https://www.swsresearch.com/swindex/pdf/SwClass2021/SwClassCode_2021.xls) · [官方旧版 RAR](https://www.swsresearch.com/swindex/pdf/SwClass2021/SwClass.rar)

| 原件 | 字节 | SHA-256 | 服务器 Last-Modified（UTC） |
| --- | ---: | --- | --- |
| `StockClassifyUse_stock.xls` | 1,167,360 | `c06fae2bd4f90179daf055cf66b921115982fa485ccd484e55033932217ffaa8` | 2026-11-19 07:55:18 |
| `SwClassCode_2021.xls` | 73,728 | `2063bde1c2d4501cd5fd8d12ffc7d66029dc6befd05c0f8d78a681ec4549ff33` | 2026-11-19 07:55:15 |
| `SwClass.rar` | 1,509,530 | `7cf486a6e6de70b2d014f5b17c4dff8afeb0eebb6731dcbacb3de8b2700b70a7` | 2022-11-29 03:18:07 |

## 全量核对

现行历史表只有股票代码、计入日期、行业代码、更新日期四列。12,934 行数据涉及 5,938 个股票代码和 553 个行业代码。计入日期覆盖 1990-01-01 至 2026-11-10，其中 2,334 行的 Excel 日期值含时分秒。更新字段全部含时分秒，覆盖 2015-10-26 至 2026-11-16，工作簿未附时区或历史公开规则。12,343 行更新晚于计入，差值中位数为 1,357 日。96 行在样本终点前生效、终点后才更新。

| 核对项 | 现行 XLS | 旧 RAR 内的 2022 年 XLS |
| --- | ---: | ---: |
| 完整读出的数据行 | 12,934 | 11,803 |
| 股票代码 | 5,938 | 5,161 |
| 与发布版证券历史唯一链接的行 | 12,897 | 11,782 |
| 同时满足计入日上市区间与代码切换口径的行 | 8,221 | 7,827 |
| 匹配本地 SW2014 字典的专属代码行 | 3,235 | 3,252 |
| 匹配本地 SW2021 字典的专属代码行 | 4,184 | 3,401 |
| 两套字典均有的代码行 | 3,670 | 3,326 |
| 两套字典均未找到的代码行 | 1,845 | 1,824 |

旧 XLS 最晚更新为 2022-09-29。它与现行 XLS 有 10,219 行的股票、计入日及行业组合相同，其中 2,447 行的更新字段已改变。旧表有 1,584 个组合在现行表中消失。现行表有 30 个组合使用旧表已有的股票及计入日，行业代码发生变化。另外有 276 个现行组合的更新字段早于旧表的最大更新时间，但旧表没有该组合。这些对比证实了事后改写，且更新字段不足以确定某行已经在该时点公开。两套行业代码存在交叠，逐行归属版本还需要历史口径证据。

## 历史公开时间的边界

2022-08-12 的公开存档证实申万旧站当时提供 `pdf/SwClass2021/SwClass.rar` 下载。现行官方域名保留的 RAR 包含 2022-09 冻结的历史 XLS 和分类字典，以及 2021-08 的官方说明和 2021-09 创建的 7 月末分类 XLSX。后者读出 5,284 行，含 4,429 个不同的大陆证券代码格式和 31 个一级行业名称。网页存档证实了当时的下载入口，包内时间和 HTTP 头提供旧版身份线索。 [2022-08-12 的申万下载页存档](https://web.archive.org/web/20220812120237id_/http://www.swsindex.com/idx0530.aspx) · [申万行业分类标准 2021 版说明](https://wxweb.swsresearch.com/swsreport/2021_08/328340.pdf)

对新旧两个精确 RAR 路径，以及现行历史 XLS 路径查询了截止 2026-06-30 的 Wayback CDX，均为 HTTP 200 空数组。现行 XLS 的最近公开抓取为 2026-09-21，已过样本终点。两次 Common Crawl 历史查询返回 HTTP 504。理杏仁 `company/industries` 实测 HTTP 401 `UnauthorizedError`，官方文档要求用户 token。 [理杏仁股票所属行业接口](https://www.lixinger.com/api/open-api/html-doc/cn/company/industries)

本次保留这些官方原件及核验结果作为候选证据。未取得样本截止日前的精确文件抓取或行级公开版本证明，因此这批文件未写入 `industry_versions`。`scripts/audit_cn_sw_history.py` 可复算工作簿与证券、分类字典的链接统计。机器可读结果为 `artifacts/cn_numeric/sw_source/history_audit.json` 和 `archive_xlsx_audit.json`。

## 指数公告及备选来源复核

- 申万 801180 的指数公告接口实测返回 9 条，发布日期介于 2003-10-15 与 2014-07-01。打开最近一条原公告，可核实 50 家公司一级行业变更及 2014-07-02 的生效日。公告列出了本次变更名单，将完整样本股指向站点指数页面和资讯商，响应没有完整成分附件。成分接口重测对 801180 和对照行业 801780 均返回 HTTP 200 和空名单，附加 2020-01-31 的历史日期参数结果相同。此次核查取得的可追溯历史成分附件仍为已经使用的 2025-11、2025-12、2026-01 三个版本，未取得覆盖研究期的完整历史发布名单。 [801180 公告接口](https://www.swsresearch.com/institute-sw/api/index_publish/details/index_announcements/?swindexcode=801180&page=1&page_size=100) · [2014 调整公告原文](https://www.swsresearch.com/institute-sw/api/index_announcements/details/?id=D741B78F-98CE-4BBC-ACC3-B86C563867D5)
- CNEquity 从 2020 年起生成的月度回填直接读取上节的现行 `StockClassifyUse_stock.xls`。固定提交中的解析器只保留证券、计入日期和行业代码，按计入日期选取每月快照并应用退市过滤。它所生成的快照日期来自重建算法，未增加历史发布版本证据。 [下载实现](https://github.com/rootSunc/CNEquity/blob/05370ab722acaaf1cf4cebc8b4489aaa81d5083b/src/cnequity/adapters/sw/industry_history.py#L37-L39) · [解析及月度展开实现](https://github.com/rootSunc/CNEquity/blob/05370ab722acaaf1cf4cebc8b4489aaa81d5083b/src/cnequity/adapters/sw/industry_history.py#L155-L229)
- SSRData 的公开字段表共 11 列，含三级行业代码及名称、证券代码及名称、纳入日、剔除日和当前标志，未列公开时刻或发布版本。页面展示的范围到 2025-05-23，下载要求登录开通权限，另列高校校园网试用。本次仅核验公开字段与权限说明。 [SSRData 数据说明与下载条件](https://www.ssrdata.com/data/Index/swhycfgc/swhycfgc)

## 2026-11-20 追加核验

- 本地申万公告列表共 2,054 个条目。2021-07-31 结果发布公告明确说明个股分类当日起在官网发布并每周五更新，另行安排配套指数切换。原保存的公告正文有公告身份和 SHA-256 `2cdd979e94cc899b1efaad6d2c7c262686d0d822bd38ca33a9cef41f8721281f`，未附证券名单。2021-09-03 的旧站快照保留 9 月 2 日更新文本、官方 RAR 路径和 `2014to2021.xlsx` 路径。现存 RAR 中的 7 月底工作簿内部创建时间为 2021-09-09。Wayback 对旧／新站月度原件通配与旧站 `SwClass2021` 静态目录的 HTTP 200 查询均为空。 [申万分类结果原公告](https://www.swsresearch.com/institute-sw/api/index_announcements/details/?id=19CBFEC8-C576-4D3C-9578-A55D3CF2AFC5) · [2021-09-03 下载页存档](https://web.archive.org/web/20210903073042id_/http://www.swsindex.com/%2fidx0530.aspx)
- 两个 GitHub 提交中的 2021 年 7 月末分类文件与申万官方 RAR 中工作簿逐字节相同，均为 260,429 字节，SHA-256 为 `b242ab04e0f68357cf90772e3f15367644d3e74c08a767eb9c5edcf21467fcbb`。GitHub API 的实际仓库推送时间分别为 2026-01-12 12:24:53 UTC 和 2026-01-13 02:32:56 UTC。另有论坛下载页登记 2022-02-08 上传名称与大小相符的工作簿，实际下载需要论坛币，未核对其文件内容。现有证据无法确定 2021 年各证券记录的历史公开时点，也无法证明 2026 年仍适用这份 2021 名单。 [逐字节相同的公开提交](https://github.com/18June96/stock-analysis-system/commit/6b39be35a0b74b524a39cf47ac9e43e2ed595f4c) · [带日期的历史附件索引](https://bbs.pinggu.org/thread-10900148-1-1.html)
- 公告列表有 2015-03-20、2015-07-01、2016-06-24 和 2019-07-01 的行业指数调仓记录。本轮实际请求官方正文和静态下载均收到 HTTP 508。另试旧域名和官方公告镜像域名，分别遇到 DNS/连接、证书或 HTTP 403。已保存的 2014-07-01 调仓原文列出 50 条一级行业变更，文中引用 2011 版标准，相关证券在研究区间内的后续变化尚待核实。
- 三个已适配的月度成分工作簿实际只有 4–5 个指数标签，`申万制造`、`申万消费` 属于非 SW 一级行业组合。逐一核对原表后，`BIW2511.xlsx` 有农林牧渔 105、医药生物 477、国防军工 137，`BIW2512.xlsx` 对应 105、478、138，`BIW2601.xlsx` 有医药生物 478、国防军工 138。其余历史母集仍缺必要的时点证据。CSMAR SDK 对 `STK_INDUSTRYCLASS` 的申万 2014／2021 查询返回 13,337 行服务端计数，具体记录待下载额度恢复。 [CSMAR 采集记录](cn_csmar_source_audit.md)
- 2020-02-22 的官方“全部行业分类下载”路径有 Wayback HTTP 200 存档，原响应只有 696 字节的网页表单。2022-03-17 存档同样保留下载页和历史更新日期，未找到所链工作簿原件。TuShare `index_weight` 使用现有授权查询 `801010.SI` 和 `801150.SI` 的七个窗口，涉及 2015、2019、2021、2024、2025、2026 年，均成功响应零行。本机该端点有效数据的 11 个指数也均无 `.SI` 代码。请求状态和归档核验回执保存在 `artifacts/cn_numeric/csmar_runtime/sw_membership/`。 [2020 年下载路径存档](https://web.archive.org/web/20200222145030id_/http://www.swsindex.com:80/downloadfiles.aspx?swindexcode=SwClass&type=530&columnid=8892) · [2022 年申万下载页存档](https://web.archive.org/web/20220317143612id_/http://www.swsindex.com/idx0530.aspx) · [TuShare 指数成分和权重](https://tushare.pro/document/2?doc_id=96)

## 2026-11-20 补采

TuShare `index_member_all` 按 `is_new=N` 和 `is_new=Y` 共下载 9 页，分别取得 2,012 条历史和 5,916 条当前记录，逐页内容哈希核对一致，返回中没有完全重复行。历史行中有 1,426 条一级代码及名称同时匹配 2014、2021 两版词典，另有 586 条仅匹配 2021 版。当前行中有 18 条无法连接 A 股证券母集。接口没有逐行发布时间、源发布版本或行业标准版本，原始响应保存在来源断点，暂不计入历史可得成员。 [TuShare 字段文档](https://tushare.pro/document/2?doc_id=335)

本地 `index_weight` 只有沪、深、北交所的 11 只指数，未见 `801` 开头申万行业代码。用银行一级行业代码 `801780.SI` 向该接口查询 2020 年 12 月和 2025 年 12 月，另查询 `801780.SWI` 作为代码口径对照，三个请求均正常返回空结果。

申万 2021 年 7 月的原公告区分了分类结果公布和行业指数切换，说明分类结果在官网每周五更新。2022 年 2 月的公开论坛目录可定位到同一月末的附表，附件下载要求站内权限。它提供了核对原件的日期线索，附表具体字节仍需核验。申万现站的七个分类切换、指数成分调整公告详情及旧版压缩包重测返回 HTTP 508。 [原分类说明](https://wxweb.swsresearch.com/swsreport/2021_08/328340.pdf) · [2022 年附表目录](https://bbs.pinggu.org/thread-10900148-1-1.html)

CSMAR 账号已列出申万分类标准与历史成员表。版本元数据显示 SW2014 截止 2021-07-29，SW2021 于 2021-07-30 实施。成员表有实施日期，目录所列字段没有成员公告时间。分类标准版本和行业词典已保存，成员表的正式批量下载受到当日配额限制。截至本次核查，研究区间完整历史成员母集仍未达到验收条件。参见 [CSMAR 来源核验](cn_csmar_source_audit.md)。

另核对了 BigQuant、聚宽和国投证券数矿三种备选接口的字段。BigQuant 的日度成分日期定义为交易日，变动记录由相邻成分比较生成，其说明确认 2021 版分类回溯至 2010 年。聚宽提供按给定日期查询成分的入口，公开文档所列返回值为股票代码列表。数矿的 `get_stock_industry_change` 明确列有 `pub_date`（发布日期），涵盖沪深 SW2014 和新版。外部客户须先向业务对接人员申请 VPN 和 SDK 测试环境。现有授权范围内未取得该接口响应，其历史修订保留和北交所覆盖仍待核实。 [BigQuant 数据说明](https://bigquant.com/data/datasources/cn_stock_factors_company_profile) · [聚宽接口文档](https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf) · [数矿接口字段](https://fintech.stocke.com.cn/plat_files/upload/link/dataquant_v1.1.1.html) · [数矿开通条件](https://fintech.stocke.com.cn/main/downloadcenter/detail/index.shtml?id=3)

17:21 使用已经核验的证书链复测申万 2014 年调整公告、2021 年分类公告和官方旧 RAR，三条均返回 HTTP 508，证书校验成功。CSMAR 同日下午复测登录成功，实际取得 `STK_IndustryClassAnl` 17 个字段、`SQS_INDCLASSIFIC` 12 个字段。前者 `EndDate` 为统计截止时间，后者 `StatsDate` 为挂牌公司分类截止日期。两张表的字段列表均无成员公开日期。 [申万复测回执](../artifacts/cn_numeric_followup/sw_official_retest/retest_verified_chain.json) · [CSMAR 字段回执](../artifacts/cn_numeric_followup/csmar_industry_metadata/fields)

已从 CSMAR 归档逐级核对 SW2014 的 359 个分类代码和 SW2021 的 511 个代码。全部层级链完整，59 个一级节点的分类代码与名称逐项匹配 Quant 已归档的同版 TuShare 词典，并映射到各自的 `.SI` 代码。交叉表保存两侧来源哈希和批次，供后续成员归并使用。 [词典交叉核验](../artifacts/cn_numeric_followup/csmar_industry_metadata/sw_l1_crosswalk_receipt.json)

## CSMAR 公告日期交叉核对

已离线读取三份有原始公告身份的申万月末成分结果，并与 TuShare 九页归档的生效区间核对。2025-11-28 的 719 条、2025-12-31 的 721 条及 2026-01-30 的 616 条一级成员均同级同码。这些对照点覆盖三套行业和三个截面，分别保留原件公告日。TuShare 记录仍缺逐行公开版本，不能用这些对照点填补其他日期。 [机器核验结果](../artifacts/cn_numeric_followup/csmar_industry_metadata/sw_csmar_event_audit.json)

`scripts/audit_cn_sw_csmar_events.py` 接收已对服务端计数和归档哈希核验的 CSMAR 页。`STK_INDUSTRYCLASS` 验证证券挂牌历史、版本生效边界、实施日期和各级代码到一级代码的映射。`IDX_Chgsmp` 的 `Chgsmp01` 是成份变更日，`Chgsmp04` 中 `1` 为新增、`2` 为剔除，`Chgsmp06` 为指数公告日。脚本仅列出证券、分类版本、一级代码和确切实施日期均匹配的独立候选。公告日冲突、代码歧义及找不到指数元数据的记录单独计数。 [CSMAR 官方说明书第 9 页](https://cn.ceibs.edu/pdf/library/40032.pdf)

指数公告候选还需逐条核对原始公告确实公布该证券的行业归属，并保留公告身份、原件哈希和首次公开日。合同日期精度规则在日期级公开后下一日零时启用。2021 年官方说明明确区分分类发布和配套指数切换。范围完整性需要初始母集及对应范围连续发布记录，须单独核对北交所、新股、退市证券与指数样本筛选造成的差异。目前三张 CSMAR 表仍只有计数回执，适配器没有新增发布行。 [申万行业分类标准 2021 版说明](https://wxweb.swsresearch.com/swsreport/2021_08/328340.pdf)

## 2026-06-30 全市场公开截面

GH Archive 的 `2026-06-30-12.json.gz` 实际读取 24,314,271 字节和 162,161 个事件。唯一匹配的公开 `PushEvent` 为 `14109064360`，北京时间 `2026-06-30 20:17:48`，早于契约当日 `23:59:59` 预测时点。按该事件原文给出的 `c363ffa98f342ff87d285e5856231da875adb308` 获取 Git 树、当日方法说明和固定版本的 5,787 行分类 JSON。JSON Git blob SHA-1 为 `edf72832b7b7beb1aae0b381669b672fee5e574d`，下载字节 SHA-256 为 `887d5230a8db912a521d7ed487e7d85a7fe69acccbe0caacc577495913678b21`。事件原字节、压缩归档哈希及固定 Git 原件均有单独回执。 [原始公开事件归档](https://data.gharchive.org/2026-06-30-12.json.gz) · [公开截面对应的固定提交](https://github.com/MORECORIANDERS/sw-map/tree/c363ffa98f342ff87d285e5856231da875adb308)

与正式 V4 的 `symbol_asof + exchange` 当日证券池逐一连接。5,527 条记录均与申万原历史 XLS 中已有的证券、确切计入日期和三级代码相同，SW2021 分级代码和一级名称也一致。余下 260 行在当日证券池无法唯一连接。当前申万 XLS 仅承担交叉核对，时点来自公开归档的固定版本。这个来源覆盖 2026-06-30 当日，保留的历史计入日期只供来源复核。

| 场所 | 归属复核通过 | 当日净补 | 净补中输入有效 | 净补中实际行情 |
| --- | ---: | ---: | ---: | ---: |
| 沪 | 2,310 | 2,026 | 1,926 | 2,012 |
| 深 | 2,894 | 2,566 | 2,427 | 2,561 |
| 北 | 323 | 323 | 297 | 322 |
| 合计 | 5,527 | 4,915 | 4,650 | 4,895 |

生产 PIT 选择器重放原 2,884 个前缀段及 6 月 26 日、29 日、30 日与 7 月 1 日的 22,107 条真实证券日。所有前缀和原有归属保持一致，仅 6 月 30 日新增 4,915 个行业归属。7 月 1 日重新按原来源选择。该增量尚处独立冻结目录，供后续数据版本使用。 [净补成员版本](../artifacts/cn_numeric_followup/sw_bse_research_anchors/verified_day/incremental/industry_versions.jsonl) · [机器核验](../artifacts/cn_numeric_followup/sw_bse_research_anchors/verified_day/sw_publication_audit.json) · [下载及回放](../scripts/audit_cn_sw_published_snapshot.py)

同期尝试八个公开的申万宏源北交所研报目录，均取得带日期的原始页面。2023-06-14 与 2025-03-10 页面展示逐证券的申万一级名称，覆盖在审或注册未发行名单，2023 月报还出现旧版名称。其余六个公开预览无可读的逐证券申万一级表。早期东财报告 PDF 的本地 HTTP 200 实体验证为访问提示脚本，官网老公告和下载中心返回 HTTP 508。这些来源保留为审计线索，历史成员连续区间仍需核验。 [2023-06-14 目录](https://www.sdyanbao.com/detail/418928) · [2025-03-10 目录](https://www.sdyanbao.com/detail/860938) · [请求回执](../artifacts/cn_numeric_followup/sw_bse_research_anchors/probes/original_source_http_probe.json)

## 2023–2025 行业成分网页存档

对乐咕乐股公开成分页做 Wayback CDX 精确查询，获得 79 个独立网页摘要。按证券分类词典筛选出交易日的 55 个一级行业页面，均下载到 HTTP 200 原始正文，正文 SHA-1 的 Base32 编码与各自 CDX 摘要逐字节核对。原表给出股票代码、纳入日和申万一级名称。逐行连接证券历史日期与场所，用官方申万历史 XLS 在存档当日的归属经 SW2021 词典确认一级代码。使用 Wayback 实际抓取时刻作当天公开的最迟界限。原表的纳入日期保留供审计，模型归属有效期只覆盖所证实的交易日。 [机械设备原始网页示例](https://web.archive.org/web/20241204082350id_/https://legulegu.com/stockdata/index-composition?industryCode=801890.SI) · [食品饮料原始网页示例](https://web.archive.org/web/20241204083608id_/https://legulegu.com/stockdata/index-composition?industryCode=801120.SI)

| 实证交易日 | 一级行业页面 | 净补归属 |
| --- | ---: | ---: |
| 2023-02-07 | 4 | 359 |
| 2023-02-08 | 1 | 148 |
| 2023-11-30 | 1 | 153 |
| 2024-12-04 | 28 | 4,752 |
| 2025-05-22 | 3 | 546 |
| 2025-06-17 | 1 | 95 |
| 2025-07-10 | 3 | 537 |
| 2025-08-15 | 4 | 729 |
| 2025-09-11 | 10 | 1,993 |
| 合计 | 55 | 9,312 |

9,312 个证券日包含沪 4,131 条、深 5,181 条。9,289 条有实际行情，9,079 条输入有效。另有 1 条记录无法唯一连接当日证券。2024-12-04 覆盖 5,372 个证券日中的 4,752 个，仍缺农林牧渔、交通运输、环保的当日页面及北交所成员。实际页面价格有前一交易日收盘的例子，任何网页价格均未进入数据包。生产 PIT 选择器在 38 个交易日、203,528 个真实证券日上复验，原有归属和来源没有变化，新增限于表中的 9 日。逐日移除当日及其以后公开版本前缀保持一致。 [冻结成员增量](../artifacts/cn_numeric_followup/sw_bse_research_anchors/verified_wayback/industry_versions.jsonl) · [逐页及前缀验收](../artifacts/cn_numeric_followup/sw_bse_research_anchors/verified_wayback/sw_wayback_audit.json) · [下载及回放](../scripts/audit_cn_sw_wayback_constituents.py)

同一站点另有四个申万二级行业原始页面，分别是汽车零部件、种植业、乘用车和航空装备Ⅱ。用申万官方分类字典和 Quant 归档的同版行业代码核对二级代码及其一级父类，再与每条证券的当日官方行业历史逐项核对，净补 264 条一级归属。2023-02-07 新增 190 条，2023-09-22 新增 28 条，2025-09-15 新增 46 条。全部有实际行情，258 条输入有效，与前一批无重叠。生产时点检查覆盖 68,422 条真实证券日。 [四页归档增量](../artifacts/cn_numeric_followup/sw_bse_research_anchors/verified_wayback_level2/industry_versions.jsonl) · [分级与时点验收](../artifacts/cn_numeric_followup/sw_bse_research_anchors/verified_wayback_level2/sw_wayback_audit.json)

去除网页档案按内容摘要的去重条件后，两个域名仍各返回同样的 79 条历史记录，2026 年 1–6 月均没有该类成分页。旧申万站 2015、2016 和 2018 年的入口都有归档，成员加载依赖未归档的 POST 处理器。旧下载路径的 366 个历史记录均为 HTML，原站和现站的 `SwClass2014.rar` 精确匹配均为空。 [旧版目录核验](../artifacts/cn_numeric_followup/sw_bse_research_anchors/alternate_archive/old_official)

2019 年的沪深 300 研究仓库保留了原始 SW2014 行业 CSV。GH Archive 原事件 `9139578761` 对应 2019-02-26 北京时间 23:49:00 的公开推送，锁定的 Git 提交含该 CSV。公开原代码仅请求 2019-02-20 的 Wind 一级行业版本，公开日和有证据的截面日期未重合，保留供历史有效区间交叉核验。另取得 5,864 行的 2026 年 6 月 TuShare 行业 Parquet，其 Git 内部日期为 6 月 22 日，未核得截止前外部公开事件或存档。6 月 29 日收盘晚报的固定文件于 8 月 2 日入库，也未提供逐证券完整归属。 [2019 年公开事件](https://data.gharchive.org/2019-02-26-15.json.gz) · [2019 年原代码](https://github.com/WIFAQuant/HS300/blob/ed741da260817b52a506997fc471a9229415faec/HS300.py) · [2026 年 Parquet 核验](../artifacts/cn_numeric_followup/sw_bse_research_anchors/factor_snapshot)

| 目录 | 冻结文件 | SHA-256 |
| --- | --- | --- |
| `verified_wayback` | `industry_versions.jsonl` | `1393cece5594ad39d2c00b7976833a7d6d53caa1cc6201ed31cc2c0e478ab488` |
| `verified_wayback` | `sw_wayback_audit.json` | `83c8cf676459bf3c67741fbf8e20b665f9fa547d35b441196da951728c1bc5ab` |
| `verified_wayback_level2` | `industry_versions.jsonl` | `ec0655de5ed1811e0a6bef15d0f487b19656341121d8c32ccab3ba5fac4833a1` |
| `verified_wayback_level2` | `sw_wayback_audit.json` | `17dff2499d0ce876674e303659a1f62a6ddac3cb7e807c9356b6761fbcbea4a4` |
| `legacy_2019` | `raw_events.jsonl` | `868e43c410b6be9485af1a4dc3d1b555266cc410d2c26998d8a1b7ada793af1c` |
| `legacy_2019` | `snapshot.csv` | `7120a3590b934714d1bac77ce35ab28d6179148e0cd258b8933969ca3804975d` |

## 下一批 CSMAR 到达后的只读验收

沿旧站菜单的完整地址恢复了申万 2013-12-09 行业分类调整公告。Wayback 原件于 2014-12-30 12:27:36 UTC 抓取，8,101 字节，SHA-256 为 `7f89db9c2ec30460b949ee4813ccb942385ca63a7d4f9ead5243aa79b04ec87e`，正文 SHA-1 与对应 CDX 摘要逐字节一致。公告确认新版分类于 2014-01-01 实施，配套指数调整另行公告，逐证券归属见独立的《沪深A股一级行业分类表》。原公告未附该表，本次未据此新增成员。现站同一公告 ID 返回 HTTP 508。按该版旧站地址逐一回放 2015-03-20、2015-07-01、2016-06-24、2019-07-01 指数成份调整公告，四条均返回 HTTP 404。 [旧站原件及摘要核验](../artifacts/cn_numeric_followup/sw_bse_research_anchors/alternate_archive/old_official/dec2013_exact_identity.json) · [现站复测](../artifacts/cn_numeric_followup/sw_bse_research_anchors/alternate_archive/old_official/dec2013_notice_probe.json) · [四条存档核验](../artifacts/cn_numeric_followup/sw_bse_research_anchors/alternate_archive/old_official/historic_adjustment_exact_replay.json)

现有三套申万来源合计 15 个截面、17,159 条控制行。先以已有 TuShare 归档离线核验，17,084 条一级归属一致，另有 75 条缺记录，零冲突。控制样本包含北交所，结果保留确切场所与日期。监测脚本按已取得的数据页单独检查 `STK_INDUSTRYCLASS`、`IDX_Idxinfo` 和 `IDX_Chgsmp` 的已下载及待下载范围。全部页通过后，候选事件仍需核实与申万实际行业变更相关的原始公告。行业截面只证明其实际公开日可见的归属。指定 `--watch-until` 及带时区的结束时刻，脚本每 15 秒检查已完成的本地明细和同批成功回执，验证服务端计数、压缩原件哈希和实际行数后刷新报告。脚本不调用 CSMAR。 [读取准备及实际预检](../artifacts/cn_numeric_followup/csmar_industry_metadata/sw_csmar_event_audit_preflight.json)

```powershell
$env:PYTHONPATH = 'src'
$latest = (Get-Content E:/QuantData/numeric/latest_cn.json | ConvertFrom-Json).path
$sw = 'artifacts/cn_numeric_followup/sw_bse_research_anchors'
$audit = 'artifacts/cn_numeric_followup/csmar_industry_metadata'
$sources = 'E:/QuantData/numeric/.build-cn/sources'
$release = "E:/QuantData/numeric/$latest"
E:/quant/.venv/Scripts/python.exe scripts/audit_cn_sw_csmar_events.py `
  --capture "$sources/csmar/requests" --count-receipts "$audit/requests" `
  --crosswalk "$audit/sw_l1_crosswalk_receipt.json" `
  --security-history "$release/reference/security_history.parquet" `
  --release-root $release `
  --official-controls artifacts/cn_pit_evidence/industry_versions.jsonl `
  --additional-controls "$sw/verified_day/industry_versions.jsonl" `
  --additional-controls "$sw/verified_wayback/industry_versions.jsonl" `
  --additional-controls "$sw/verified_wayback_level2/industry_versions.jsonl" `
  --tushare "$sources/financial-v2/tushare-sw.sqlite3" --output "$audit/sw_csmar_event_audit_after_capture.json"
```

### 2026-11-21 续采结果

北京时间 00:01:13–00:01:17 的七个行业请求全部收到 CSMAR 服务码 `-2501`，服务返回当前账号没有访问权限。`STK_INDUSTRYCLASS` 的申万 2014／2021 明细被拒，旧成功计数为 13,337。`IDX_Idxinfo` 的 `801%` 计数被拒，旧成功计数为 178。`IDX_Chgsmp` 的五个计数窗口均被拒，旧成功计数分别为 1,979、1,544、2,576、1,449、72，总计 7,620。源目录三类明细均为零，因此母集覆盖、证券归属、版本和指数事件无法按这些明细交叉验证，这一批新增成员为零。机器记录逐项保留请求条件、时间和原失败回执 SHA-256。 [机器核验](../artifacts/cn_numeric_followup/csmar_industry_metadata/sw_csmar_event_audit_after_capture.json)

核查时正式指针为 `cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c`。研究期 11,618,610 个候选证券日中，89,326 个具备合规行业归属，分布在测试段的上交所 40,968 个和深交所 48,358 个。10,291,962 个输入有效证券日仍缺行业，其中北交所 217,747 个、上交所 4,335,879 个、深交所 5,738,336 个。后续发布版的实际覆盖独立统计。 [正式版本分层覆盖](../artifacts/cn_numeric_followup/csmar_industry_metadata/released_membership_baseline_v5.json)

## 第七版样本期复核

当前发布 `cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a` 的全量 `stock_daily` 检查以截至 2026-06-30 的 `input_valid=true` 证券日为分母。上交所 4,375,977 个有效输入日中有 4,329,803 个缺 `industry_code_asof`，深交所为 5,730,722／5,785,044，北交所为 217,450／217,747。三所合计 10,277,975／10,378,768。完整历史行业母集依然是 `INCOMPLETE` 的原因。 [版本清单](E:/QuantData/numeric/cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a/manifest.json)
