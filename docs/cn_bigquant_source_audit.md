# BigQuant SDK 数据来源复测

2026-11-21 北京时间 19:25–19:27，以本机 Python 3.11 的 `bigquant 0.1.11` 和已有账号配置实测。SDK 可导入，身份接口成功，`bq dai schema cn_stock_capital` 可返回预期股本字段。Python 实际读取的五类目标表，以及命令行读取一条普通 A 股日线，均被服务端拒绝，提示「请先申请SDK使用权限」。 [SDK 查询回执](../artifacts/cn_numeric_followup/bigquant_20261121/access_probe/summary.json) · [命令行对照](../artifacts/cn_numeric_followup/bigquant_20261121/access_probe/cli_control.json)

| 本轮缺口 | 实测范围 | 取得明细后需验证的证据 |
| --- | --- | --- |
| 前期 A 股类权重和跨股类市值 | `cn_stock_capital`，覆盖测试用普通 A 股、A/H 股、北交所旧代码与现代码、退市证券 | 目标 A 股类股数、H 股股数、公告日、实际变动日、原始版本和修订时点。 [官方股本字段](https://v6.bigquant.com/data/datasources/cn_stock_capital) |
| 历史申万归属 | `cn_stock_industry_component`，测试了 2015 年分片及申万 2014／2021 分类 | 样本日可用的分类版本、历史发布时点、母集和北交所覆盖。 [官方行业表](https://v6.bigquant.com/data/datasources/cn_stock_industry_component) |
| 北交所合并财报组成期 | `cn_stock_financial_income_general_pit`、`cn_stock_financial_balance_general_pit`、`cn_stock_financial_cashflow_general_pit`，测试了北交所新旧代码与 2021–2026 日历区间 | 合并报表语义、首次公告、原版和各次修订、币种单位、七项金额及前序季度。 [官方 PIT 字段](https://v6.bigquant.com/data/datasources/cn_stock_financial_income_general_pit) |

本轮获取的 BigQuant 明细为 0 条，实际补齐 0 个数据键。当前发布仍是 `cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a`，状态 `INCOMPLETE`。开通本地 SDK 数据读取后，以 `cn_stock_capital` 为优先，先复测历史原始公告、已退市和北交所样本，再按实际可核验证据评估能补齐的证券日。官方 SDK 文档给出向平台「小Q」申请权限的入口。 [官方 SDK 权限说明](https://v6.bigquant.com/wiki/doc/vac4qwmQr4) · [当前读取指针](E:/QuantData/numeric/latest_cn.json)
