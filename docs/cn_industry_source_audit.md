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
