# CSMAR 第二轮股本与公司行动回执

2026-11-21 00:01（中国标准时间）的官方 SDK 续采记录了 39 个计划实例。服务端全部返回 `-2501`（“您目前没有访问权限”），本批有效数据页为 0。三张目标表的失败请求与此前成功的计数请求采用相同的日期及证券筛选范围。计数成功可以核对请求范围及候选源规模。当前安装和账号配置的授权原因仍待服务端确认。前一批遇到的下载额度限制使用 `-2404`，本批具体响应为 `-2501`。

| 官方表 | 可核对的历史计数 | 续采数据页 | 拟核对的字段 |
| --- | ---: | ---: | --- |
| `CD_Dividend` | 165,479 | 0 | 实施进度、公告日期、送股和转增比、税前派息、登记／除权／新股上市日、分配对象及基数 |
| `STK_HK_CapitalChange` | 2,999 | 0 | 公司及证券 ID、公告日、实际生效日、变动前后股数、变动数量及原因 |
| `STK_HK_InstitutionInfo` | 221 | 0 | 公司及证券 ID、港股代码、股份类型、上市日、ISIN |

[逐请求、日期范围及 SHA-256](/E:/Kurumi/artifacts/cn_numeric_followup/capital/csmar_day2/query_status_20261121.json)。[续采日志](/E:/Kurumi/artifacts/cn_numeric/csmar_runtime/daily_resume_20261121.log)。

当时的已发布 V5 有 2,601 个证券日缺少有效的 U 链，沪市 1,012 个、深市 1,589 个、北交所 0 个。其中 1,338 个未见带日期的既有公告档案事件，127 个已有须进一步区分范围的非现金事件，另有 595 个现金事件的价格因子比对不一致或口径不唯一。持有已验证 A 股股数和同日 H 股报价、仍缺发行人市值的范围是 24 家、21,589 个证券日，覆盖中国石化、紫金矿业、中信银行、中国国航、广汽集团等。以上是续采前的实测优先级范围，取得来源后仍须核查各时点的股类、公开和生效时间、状态以及汇率，才能计算最终能填补的数量。本批获准入的 U 事件、U 覆盖区间、股类版本均为 0。没有据此修改数据包或指针。

[已发布 V5 的 U 缺口](/E:/Kurumi/artifacts/cn_numeric_followup/capital/csmar_day2/u_baseline_priority.json)。[V5 的 A/H 同日报价缺口](/E:/Kurumi/artifacts/cn_numeric_followup/capital/csmar_day2/hk_missing_same_day_baseline.json)。

续接需要带原公告时间、实施／生效时间、完整证券范围及行数回执的官方数据导出。U 可以用实施正文与 `TRD_Cptl` 独立校准每股份额，并按实际行情复算除权。港股股本需要同时确认国内证券与港股的身份、实际发行股数、股类和公开时点。港交所规则要求披露股本变动，原始翌日披露及月报表可按实际发生日和公告可用时点逐项验证。已有月报观察能证明报告期末股数，日频连续区间仍需核对期间变动。现存 CSMAR 官方字段字典和计数无法完成这些数据核对。 [CSMAR 产品手册](https://lib.nankai.edu.cn/_upload/article/files/23/1b/e77168d14733abff9383487e10e1/3652645c-7069-4b3f-a6b2-016ebfbc6a2e.pdf) [港交所《上市规则》第 13.25A 至 13.25C 条](https://cn-rules.hkex.com.hk/entiresection/5757)

[只读回执校验脚本](/E:/Kurumi/scripts/watch_cn_csmar_capital_receipts.py)和[实际缺口交叉核查脚本](/E:/Kurumi/scripts/audit_cn_csmar_day2_capital.py)保留了续接所需入口。已在现有数据上复核未到页的分支，并用官方字段字典验证后续查询绑定；目标数据页未到，所以没有执行实际来源入库验证。
