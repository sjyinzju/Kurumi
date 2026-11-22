# CSMAR 来源采集记录

2026-11-22 已用官方 SDK 打包和定向查询接续下列历史断点。当天完成 [批量续采](cn_csmar_resume_20261122.md)、[缺口定向补采和本地复算](cn_csmar_gap_reuse_20261122.md) 以及 [停牌、股本和北交所财务增量](cn_csmar_remaining_20261122.md)。当日晚间实测收到 `-2404`，已保存续采断点。

2026-11-20 以本机 CSMAR 账号通过官方 Windows SDK 1.0.2 登录成功，实际取得 207 个数据库条目和相关表、字段字典。在 `artifacts/cn_numeric/csmar_runtime/.venv` 单独使用 Python 3.11.9，保留后训练环境原有依赖。官方 SDK 包含可直接运行的源码。其 `__init__.py` 会导入 `prettytable`，因此隔离环境也安装了这个包。程序仅在本次会话内存保留登录令牌。来源证据保留请求参数、服务端计数、观察时间和归档页 SHA-256。采集的 gzip 页是官方 API 记录的序列化归档。 [官方 SDK 包](https://data.csmar.com/static/packages/domestic/Python/csmarapi.rar)

## 已下载与验证

| 源表 | 成功页 | 原始记录数 | 范围 |
| --- | ---: | ---: | --- |
| `TRD_Capchg` | 1 | 142,626 | 1990 年至 2026-07-31 股本生效记录 |
| `TRD_Cptl` | 1 | 71,506 | 1990 年至 2026-07-31 实施分配记录 |
| `TRD_Co` | 1 | 6,061 | 证券代码与候选 A/B/H 交叉码 |
| `TRD_Exchange` | 1 | 3,058 | 2014 年至 2026-07-31 日汇率 |
| `STK_INDCLASSIFYVERSION` | 1 | 23 | 分类版本说明 |
| `STK_INDCLASSIFYSETS` | 1 | 7,024 | 分类代码及层级 |
| `FS_Combas` | 5 | 75,539 | 2013–2017 合并资产负债表 |
| `FS_Comins` | 5 | 75,539 | 2013–2017 合并利润表 |
| `FS_Comscfd` | 4 | 57,453 | 2013–2016 合并现金流量表 |
| 合计 | 20 | 438,829 | 压缩记录页共 11,150,434 字节 |

归档位于 `E:\QuantData\numeric\.build-cn\sources\csmar`。首日落地核对包含字段元数据、请求状态和 `capture_audit.json` 在内的 210 个文件，合计 11,490,285 字节。

这些计数包含源表代码、日期和报告类型范围。财务原始下载含非标准季度末，用于契约时须再按标准季末、正式财报、历史发行人和财报币种等口径验证。`IfCorrect` 表示是否发生差错更正，`DeclareDate` 是更正公开日期。抽查 2013 年合并资产负债表的 13,022 个键均只有一行，其中 1,610 行带更正日期。对应原始报表需从原版或可验证的历史快照补证。文件获取日期保留在观察时间。

`TRD_Capchg.Shrchgdt` 记录股本实际变动日期。该表缺少公告时间，且 `Nshra` 为 A 股流通股数。混合股类与目标 A 股股本须在统一适配层按历史公开证据核验。`TRD_Cptl.Annodt` 为分配方案公告日期，`Amount` 为每股分配比例。`CA` 为现金红利、`SD` 为送红股、`DS` 为拆细。`Paydt` 对股数事件记录新增股份实际流通日，接入时保留 `Exdistdt`、`Paydt` 及不同动作的语义。标为北京市场的真实数据也包含在该表内。 [CSMAR 中国股票市场交易数据库字段手册](https://file.csmar.com/group1/M00/AA/99/CuIKV2XAnKiABeLbAB4nDGC5Ano840.pdf)

## 剩余下载

第 21 个非空数据请求收到 CSMAR `-2404`，服务端提示当日下载额度已用完、次日再试。之后同一服务限制阻断了尚未下载的请求。字段元数据和行计数仍可用，因而继续核实了余下表的查询范围。配置支持原条件续跑，成功归档复用哈希已验证的结果，失败请求保留状态并遵守 30 分钟同条件间隔。采集后应再按数据契约路线验证历史版本才能进入发布。

| 待取得来源 | 服务端实测行数或限制 |
| --- | --- |
| `STK_INDUSTRYCLASS` 申万 2014/2021 成员变更 | 13,337 行。字段有实施日期，公开日期证据需在适配阶段核实 |
| `IDX_Idxinfo`、`IDX_Chgsmp` 代码 `801` 开头的公开指数信息和变更 | 元数据 178 行；按 2014 至 2026-06-30 的 5 个不相交窗口共 7,620 行，`Chgsmp06` 字段为公告日期。样本股数量、指数适用范围和个股行业归属仍需与分类表核对 |
| `CD_Dividend` 实施公告与送股、转增、现金明细 | 165,479 行 |
| `IAR_Rept` 正式公布日与 `IAR_Forecdt` 实际披露日 | 219,777 行、215,669 行 |
| 三张财务基础表余下期间 | 资产负债表 203,483 行，利润表 203,492 行，现金流量表 221,566 行 |
| H 股身份、股本变动、分配事件 | 221 行、2,999 行、8,554 行 |
| 跨股类实际行情、基准汇率 | 筛选的港股 442,538 行、内地 B 股 271,477 行。港股行情查询最长四年，内地个股行情最长五年。基准汇率 30,548 行 |
| 原始财报股本附注 | 596,970 行。财报期、合并口径和股类在适配层核验 |
| 财报重述索引和停复牌 | 17,023 行、18,595 行 |

当日追加核对的指数样本权重表 `IDX_Smprat` 对相同指数前缀、全研究期的三个窗口均返回零行。指数成分变更公告用于核验证券与版本，行业分类仍按股票历史归属和分类标准判定。

20:15 至 20:16 通过官方 SDK 追加取得 `IDX_Idxstk` 的 10 个字段和 `IDX_Idxcop` 的 8 个字段。前者的主键为证券、交易日期，字段无指数代码，股数区分总股数和股类流通股数。后者有指数代码、交易日、样本数量和样本总市值。对 `801` 前缀实测三个窗口分别为 28、5,429、22,761 条，列入次日续采，用于外部核对指数样本的范围和数量。指数汇总值和交易所分类全母集的前期股类资本权重分别核验。程序已安排在 2026-11-21 00:01 续采实际明细，同一份已核定请求清单沿用成功断点。 [补充计数计划](../artifacts/cn_numeric_followup/csmar_industry_metadata/idx_aggregate_count_plan.json)

21:49 使用 SDK 仅查询两个合并区间的行数。服务端对 `IDX_Chgsmp` 给出最长三年，对 `IDX_Idxcop` 给出最长十年，均明确拒绝超长请求。续采清单保留原有已核定区间。优先队列前 20 项安排申万个股分类、指数变更、分派实施、真实财报公开日、三张基础财务表与港股股本和证券身份。用于旁证的指数日度汇总顺延至这些请求之后。 [官方计数回执](../artifacts/cn_numeric_followup/csmar_industry_metadata/compact_count/probe.log)

## 11 月 21 日续采实测

北京时间 00:01，39 个续采范围全部执行。11 个范围止于行数查询，28 个范围止于明细查询，服务端均返回 `-2501 No permission to access`。本批新增 0 页、0 条明细。既有 20 页、438,829 条源记录重新通过压缩内容及行数校验。首日 `-2404` 已记录为日额度限制，次日 `-2501` 登记为权限拒绝。 [39 项精确范围、阶段和回执哈希](../artifacts/cn_numeric_followup/csmar_control_20261121/csmar_daily_status_20261121.json) · [续采日志](../artifacts/cn_numeric/csmar_runtime/daily_resume_20261121.log)

另用昨天实际下载过 23 行的 `STK_INDCLASSIFYVERSION` 做独立对照。现有账号能通过 SDK 会话认证，首次刷新数据库目录收到 `-2501`，其后直测该已知范围也在计数阶段收到 `-2501`。服务端没有说明权限变化的原因。后续批量补采须在账号或机构数据查询权限恢复后从原清单断点重跑。 [目录对照](../artifacts/cn_numeric_followup/csmar_control_20261121/control.log) · [表范围对照](../artifacts/cn_numeric_followup/csmar_control_20261121/control_known_scope.log)

本批未取得申万分类、指数变动、实施分派、港股股本及后续合并报表等明细。第五版研究样本有 10,291,962 个有效输入证券日缺历史行业，2,074,690 个前一日市场成员记录缺已验证 A 股类股数，2,601 个证券日缺股数单位链。这里的影响计数是发布实测，供应商旧计数仅用于描述已尝试范围。公开财报、交易所公告和可核验历史归属继续独立补齐。 [行业回执](cn_industry_source_audit.md) · [股本和单位链回执](cn_csmar_day2_capital_evidence.md) · [市场分母](cn_market_denominator_audit.md)

## 11 月 21 日校园网复测与续采

切换到校园网后，官方 SDK 从对照表 `STK_INDCLASSIFYVERSION` 成功计数并下载 23 行。申万历史分类、分红送转和合并资产负债表的三个小样各返回 3 行。北京时间 14:36 按原清单续采，新增 16 页、1,029,036 行。逐页复核 SHA-256 和解压行数后，原归档累计 36 页、1,467,865 行。首批 20 页与既有哈希一致。 [校园网复测](../artifacts/cn_numeric_followup/csmar_control_20261121/campus_recheck_20261121_1434/summary.json) · [全量页核验](../artifacts/cn_numeric_followup/csmar_control_20261121/campus_recheck_20261121_1434/capture_integrity.json)

新增明细含 13,337 条申万历史分类、7,620 条指数样本变更、165,480 条分红明细、435,446 条财报披露记录，以及 406,975 条合并资产负债表和利润表记录。分红表比旧计数多 1 行，刷新服务端计数后与归档对齐，旧计数另存证据。`IDX_Idxinfo` 额外取得 178 行指数资料，响应缺少原请求中的 `Idxinfo04`，逐页审计保留字段警告。 [逐表数量和原清单断点](../artifacts/cn_numeric_followup/csmar_control_20261121/campus_recheck_20261121_1434/resume_result.json)

原清单 39 个范围中，15 个完整下载，1 个已归档但有字段警告，23 个尚未取得明细。本轮在 `FS_Comscfd` 的 2017–2022 年合并现金流量表收到 `-2404` 日下载额度限制。额度刷新后沿用原清单续采。 [运行日志](../artifacts/cn_numeric/csmar_runtime/campus_resume_20261121_1435.log)

## 命令

以下为 `E:\Kurumi` PowerShell 命令。`capture` 为已纳入构建来源区的归档目录，`r` 为 SDK 独立环境和运行文件目录。官方下载的 `csmarapi.rar` 只解压 SDK 源码和 `config.ini`。项目 `.env` 支持 `CSMAR_ACCOUNT`／`CSMAR_PASSWORD`，也支持 `CSMAR账号：`／`CSMAR密码：`。

```powershell
$r = 'E:\Kurumi\artifacts\cn_numeric\csmar_runtime'
$capture = 'E:\QuantData\numeric\.build-cn\sources\csmar'
$env:UV_CACHE_DIR = "$r\uv-cache"
7z x -aos "-o$r\sdk" 'C:\Users\shiju\Downloads\csmarapi.rar' 'csmarapi\*.py' 'csmarapi\config.ini'
uv venv "$r\.venv" --python 3.11
uv pip install --python "$r\.venv\Scripts\python.exe" pandas urllib3 websocket-client python-dotenv prettytable
python scripts/csmar_plan_cn.py remaining --capture $capture --plan "$r\remaining_cn_plan.json"
& "$r\.venv\Scripts\python.exe" -X utf8 scripts/csmar_acquire.py --out $capture --plan "$r\remaining_cn_plan.json"
python scripts/csmar_capture_audit.py --capture $capture --report "$capture\capture_audit.json"
```
