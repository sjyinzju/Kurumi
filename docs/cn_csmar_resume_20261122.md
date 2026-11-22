# CSMAR 续采和时点增量核验

2026-11-22（北京时间）。当前账号在官方 Windows SDK 上成功取得 **3 个打包文件和 9 个非空 `query()` 页**，新增 **894,257 条原始记录**。全部进入现有 `E:\QuantData\numeric\.build-cn\sources\csmar`。连同已验证历史归档，共 **48 页、2,362,122 条、24 张有明细的表**。旧 36 页逐页 SHA-256 复用。另核实历史运行目录中的 20 个同哈希副本及 4 个小范围对照页。 [机器摘要](cn_csmar_resume_20261122.json) · [全量归档审计](../artifacts/cn_numeric_followup/csmar_20261122/capture_audit.json)

## 剩余分页和官方打包

原 39 个范围中，16 个已有归档，余下 23 个范围按原切片逐一用 `query()` 需要 **23 次成功明细请求**。股本附注原先缺失的 5 个分段计数由本轮完整包按报表期复核，分别为 110,730、108,184、178,677、134,481、64,898，每段均低于 200,000。仅合并已确认可请求的连续财报期间，整份原范围折算为 **22 次** `query()`。本轮实际缩小跨股类报价范围并复用已齐汇率，最终的 16 个目标范围中有 4 个经计数确认为零行。其余范围单走 `query()` 需 15 次，实用 12 次成功明细传输。

核对了 SDK `getPackResultExt`、`pack` 和结果状态实现。SDK 用 `pack` 提交条件，经官方 WebSocket 获取同一任务的结果，再从官方文件域名下载 ZIP。本轮沿用协议，在现有项目内存令牌和来源归档中保留包提交、完成回执及 ZIP SHA-256。现金流正式测试采用 2017-01-01 至 2026-07-31 的合并报表，字段描述、CSV 列名、日期边界、ZIP CRC 和 **221,566/221,566** 行与计数一致。归档同时保存原始 ZIP 和用于现有适配器的 JSONL gzip。 [官方 SDK 包](https://data.csmar.com/static/packages/domestic/Python/csmarapi.rar) · [正式打包回执](../artifacts/cn_numeric_followup/csmar_20261122/package_probe.json)

SDK 回执没有展示剩余额度或包扣次。本轮没有遇到 `-2404`，因此只记录 3 次打包与 9 次普通成功请求，打包是否占同一个每日额度仍未证实。另有两次港股明细请求返回 HTTP 504，改查明确开市日期的 66 个证券键后完成计数核验，均无正成交量报价。此次没有 `-2501`。采集器支持按范围和页数选择打包，重用已有包覆盖的同条件子范围，遇 `-2404` 记录当天的断点并停止。 [查询日志](../artifacts/cn_numeric_followup/csmar_20261122/quotes.log) · [收窄范围的日志](../artifacts/cn_numeric_followup/csmar_20261122/exact_quotes.log)

## 下载范围与实际恢复

| 来源 | 新增行数及范围 | 准入及恢复 |
|---|---:|---|
| `FS_Comscfd` | 221,566 行，2017–2026 年 7 月合并现金流 | 新增 3,534 个可绑定已核验财报的历史对照证据。对北交所 217,747 个有效输入重放，已核准版本全集新增与补记均为 0，七项完整仍为 66,966 个证券日。其余金额需要原始版本证据。 |
| `AIQ_LCFinRestatY` | 17,023 行，2013–2026 年 7 月 | 含 3,490 条标为涉及财务值变更的重述。已归档为原公告索引，恢复 0 个财务值。 |
| `FN_Fn044` | 596,970 行，2013–2019 和 2020–2026 年 7 月 | 已核对报表类型、股票种类、期初和期末余额字段。档案缺该金额版本的首次公开时间，恢复 0 个股本证券日。 |
| `TSR_Stkstat` | 18,595 行，2014–2026 年 7 月 | 独立对照旧版停牌记录和实际无报价，按公告日期次日零时生效。完成 12 个年度分区 **246,774 个证券日**的停牌状态增量复算，形成 9,246 条按区间压缩的补充证据。原 271,267 个供应商已报停牌而未认证的证券日剩 24,493 个。 |
| 港股身份、股本、分配 | 221／2,999／8,554 行，按原证券过滤 | 与现有行情及国内股本交叉定位 22 家发行人的 4,305 个候选估值日。仍需核定 H 股类发行股数、完整股类集合及历史公告版本，已准入的发行人市值新增为 0。 |
| 跨股类报价和汇率 | 港股 96 行、B 股 15 行，两类均为缩窄范围的原始返回 | 本地精确键交集新增报价为 0。26,821 个涉及缺失估值的证券日×币种键均已有当时可用汇率，复用 6,116 条已有港币与美元汇率。 |
| `IDX_Idxcop` | 28,218 行，2015–2024 和 2025–2026 年 6 月 | 两次请求补齐旧计划中的三个连续区间。历史指数成分数量可以做覆盖旁证，仍待取得当时发布的证券名单，恢复 0 个历史行业归属。 |

停牌增量位于 `E:\QuantData\numeric\.build-cn\sources\csmar-pit-20261122`。逐个区间用现有时点函数重新展开，证券日键与目标分区完全一致。预测截止日前恢复 246,651 个证券日，这些停牌日期均在有效个股输入之外。发布指针继续指向 `cn-71132cf…`，状态 `INCOMPLETE`，增量文件待后续发布纳入。没有执行全量重建或模型训练。 [停牌增量审计](E:/QuantData/numeric/.build-cn/sources/csmar-pit-20261122/suspension_incremental_audit.json) · [北交所财务复算](../artifacts/cn_numeric_followup/csmar_20261122/bse_incremental_replay.json) · [港股股本对照](../artifacts/cn_numeric_followup/csmar_20261122/hk_capital_audit.json)

## 后续范围与续采

本轮有必要采集的 16 个范围已经闭合。旧计划的七个宽口径港股、B 股报价范围由实际缺失键的窄范围替代。3,834 个港股候选键所在日期在既有港股行情中均没有实际成交，需要用港交所历史交易日和股数单位证据判断能否使用此前报价。`FE_Exrated` 的旧范围不再整表提取。当前授权的历史现金流和股本附注已可通过 SDK 打包完整取得，无需为这些表申请人工批量导出。剩余 PIT 工作需要可核验的历史版本，包括重述原件、历史股类和公告、申万历史成员原始发布档案。若向官方申请，所需交付应包含这些版本身份和公开日期。

从已核验计划续采时，程序会核对并跳过完好归档。已用拒绝任何新 SDK 数据调用的测试对象实跑这份计划，确认 16 个范围均可直接读取断点。仓库 78 项测试通过。

```powershell
Set-Location 'E:\Kurumi'
$runtime = 'E:\Kurumi\artifacts\cn_numeric\csmar_runtime'
$run = 'E:\Kurumi\artifacts\cn_numeric_followup\csmar_20261122'
$capture = 'E:\QuantData\numeric\.build-cn\sources\csmar'
& "$runtime\.venv\Scripts\python.exe" -X utf8 scripts/csmar_acquire.py --out $capture --plan "$run\resume_plan.json" --prefer-packages
& 'E:\quant\.venv\Scripts\python.exe' -X utf8 scripts/csmar_capture_audit.py --capture $capture --report "$run\capture_audit.json"
```
