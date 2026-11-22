# CN 数值数据来源补齐及剩余缺口

## 来源处理

- **CSMAR**　已按回执、SHA-256 和解压行数核对 15 张表的 36 个已下载页，共 1,467,865 条。财务原始行逐页对照已证实的历史报表，`IAR_Rept` 与 `IAR_Forecdt` 用于核对披露日期。股本、公司行动及分派用实际证券日回放。行业归档中，13,337 条分类、7,620 条指数变更和 178 条指数资料均已归并审核，424 个精确事件候选仍需原公告确认。`IDX_Idxinfo` 的 `Idxinfo04` 确认未返回。 [归档审核](../artifacts/cn_numeric_followup/gap_batch/csmar_capture_audit.json) · [行业审核](../artifacts/cn_numeric_followup/gap_batch/csmar_industry_audit.json)
- **TuShare**　以旧发布缺失键生成范围。完成 151 个简称公告月份、1,467 个限价证券区间、560 个公司行动日期、三类北交所财务表各 552 个证券代码区间，以及 71 个补充核对请求。现金流量表一次网络失败已从断点恢复。早期简称候选另取得 87 份沪深正式公告。限价回放在 4,963 个原先未知的证券日确认了不设涨跌幅限制，并核对其余已知限价类型。TuShare、CSMAR 分派和股本动作交叉核验取得 29 个可补 U 日期。 [限价与简称审核](../artifacts/cn_numeric_followup/gap_batch/market-stage/tushare_market_gap_stage.json) · [公司行动审核](../artifacts/cn_numeric_followup/gap_batch/market-stage/tushare_csmar_units_audit.json)
- **北交所**　正式财报目录覆盖 304 家发行人，6,463 个候选，6,440 个取得 PDF 附件。3,468 份通过发行人、会计期、合并范围、币种单位、列位置和会计等式检查，2,995 个候选保留拒收原因。两种 PDF 解析方法对 36 份已验证原件作对照，23 份均成功且金额一致，13 份保留原解析路径。 [来源构建与时点核验](../scripts/stage_cn_bse_financial_gaps.py) · [北交所全样本复算命令](../scripts/check_cn_bse_gap_batch.py)

## 冻结来源复算

生成 7,372 个与已验证历史报表绑定的 CSMAR 原始行证据，保留 1,113 个金额差异核查条目。北交所合并流新增 851 个报表版本，补充 2,270 个已有版本。`920339.BJ` 的同日现金流差异保留已采信版本及两侧哈希。另核实 4 个历史股本版本，并复算 3,058 个原始汇率日期，未发现已采信汇率变化。新冻结来源为 `cn-pit-a67a51789e5e2d1e0837ecd0`。

候选源覆盖北交所全部 217,747 个有效输入证券日。七项当期财务量完整的证券日从仅应用 v1.1 公式时的 4,556 个增至 66,966 个。营收 TTM 和经营现金流 TTM 分别达到 73,636 和 102,853 个。与仅修公式的回放比较，已有值后来缺失的案例均发生在取得新公告、财务锚点前进后。按契约使用新锚点并保留暂缺的组成项。 [冻结源复算](../artifacts/cn_numeric_followup/gap_batch/bse_batch_financial_replay.json) · [锚点差额原因](../artifacts/cn_numeric_followup/gap_batch/bse_anchor_changes_audit.json)

## 剩余缺口和解决路径

下表的有效输入口径截至 2026-06-30，共 10,378,768 个证券日，同一证券日可能涉及多个字段。全包口径另含 7 月标签观察日。

| 数据缺口 | 剩余数量和影响 |
|---|---|
| 历史申万行业 | 10,277,975 个有效输入缺行业归属。2,813 条市场日状态和 13,987 条行业日状态已有行，按契约验证的一日聚合收益均为 0 条。 |
| 股本及发行人市值 | 1,612,694 个有效输入缺证券股本，1,646,446 个缺发行人市值，影响估值类因子与市值权重。 |
| 北交所财务 | 217,747 个有效输入中，150,781 个尚缺至少一项核心财务量。营收 TTM 缺 144,111 个，经营现金流 TTM 缺 114,894 个，上年营收与归母净利 TTM 各缺 159,194 个。 |
| 历史简称 | 55 个有效输入仍缺，全包共 3,280 个证券日缺。名称回放无合格新增。 |
| U 股数单位链 | 1,499 个有效输入缺 U，全包共 2,457 个证券日缺，影响需要拆股一致口径的量价特征。 |
| 涨跌停价 | 全包仍有 9,242 个证券日的限价状态未知，均在有效输入之外。其中 1,809 个有有效报价。 |
| 停复牌公开时点 | 全包 271,267 个证券日有供应商停牌状态、仍缺同期可验证的公告时间。行情和监督口径按现有证据和掩码处理。 |

| 类别 | 可继续采用的来源和证据 |
|---|---|
| 历史申万行业及市场状态 | 取得申万的完整历史一级成分初始母集及连续调整公告，逐条保留实际公告时间。使用 CSMAR 指数变更匹配确定的证券、版本和有效日查找原件，区分行业归属与指数入选。现行官方历史 XLS 和 TuShare 接口适合定位变更，仍需有公开日期的历史版本。 [申万历史来源审计](cn_industry_source_audit.md) |
| 股本和发行人市值 | 继续取得交易所、登记结算或许可供应商的股类发行数量及其生效与公开时间。A/H、A/B 多股类还需同期各股类报价和汇率。先核验老股、退市股和跨股类样本，再按契约复算前期市值权重分母。 [许可数据和字段口径](cn_capital_bulk_source_audit.md) |
| 北交所财务 | 优先处理影响当期及上年 TTM 的报告组成期。取得历史正式现金流量表及更正公告，利用 CSMAR 现金流和重述索引定位原文，与交易所原件校验报告准则、首发时间和修订顺序。布局无法确定的报告可按表级证据拆解核验。 [北交所定期报告指引](https://www.bse.cn/cxjg_list/200025675.html) |
| 历史简称 | 对有效输入证券日优先寻找带实际公开时刻的更名或风险警示实施公告。上市首日历史简称由有日期的上市公告书和原证券代码确认。 |
| 限价与 U | 对尚未知的限价索取逐日开盘前的交易所限价档案，或用当年有效交易规则、上市／复牌事件及当时的价格基准核算。U 的剩余区间用原始送转、拆并股和实际实施公告确认乘数及有效日。 |
| 停复牌状态 | 按已知证券及生效日定位交易所的原公告、披露时间和恢复交易日期，优先覆盖影响市场连续估值的停牌区间。 |

限价剩余候选中，7,432 个证券日没有精确的 TuShare 供应商记录，1,810 个供应商值为占位值或与实际行情不符。U 的 29 个新增覆盖日期由现有公司行动和公开时间支持，新增股数单位乘数为 0。简称按截至输入时点的公告判断，此轮 TuShare 和已取得的原公告合计新增合格简称 0 条。 [市场来源拒收原因](../artifacts/cn_numeric_followup/gap_batch/market-stage/tushare_market_gap_stage.json)

现有 CSMAR 校园网续采最后在 `FS_Comscfd` 2017–2022 年范围收到日额度码 `-2404`，旧范围另存有 `-2501` 权限拒绝回执。对于当前未下载范围，额度刷新可沿用原查询清单续采，`-2501` 需由授权方确认。TuShare 盘前股本和 BigQuant SDK 明细读取已有实际权限拒绝。开通服务后仍需核查发行股类、历史发布时间及覆盖年份。 [CSMAR 回执](cn_csmar_source_audit.md) · [TuShare 盘前股本](cn_capital_bulk_source_audit.md) · [BigQuant 回执](cn_bigquant_source_audit.md)

在仍缺证券股本的有效输入中，341,865 个证券日落入 TuShare 盘前股本声明的日期范围。这是开通后可查的日期交集上限。更早的 1,270,829 个证券日需要历史档案，例如交易所授权主参考数据、经核实的 BigQuant 股本变动或发行人原始披露。北交所候选中拒收最多的两类是表中归母权益无法唯一辨认（996 份）和合并范围无法确认（729 份）。可优先从有明确合并标识的单表提取 TTM 组成项，逐字段审核原件。 [TuShare 盘前股本接口](https://tushare.pro/document/2?doc_id=329) · [北交所附件核验回执](../artifacts/cn_numeric_followup/gap_batch/bse-originals-final/bse_financial_originals_audit.json)

## 发布及全量验收

2026-11-21 23:32（北京时间）已发布 `cn-71132cf836bd63c14a85bbb71cbbd607a3372d4c7f0b91e359382d359ecc6d45`，读取指针已切换，契约版本 `1.1`，状态 **`INCOMPLETE`**。发布文件清单合计 3,692,211,264 字节（3.44 GiB），与旧版共享 24 个字节相同的 Parquet 文件。发布时 E 盘剩余约 10.76 GiB。北交所原始 PDF 归档与预览缓存另占约 10.43 GiB。 [机器可读摘要](cn_numeric_gap_batch_quality.json) · [当前读取指针](E:/QuantData/numeric/latest_cn.json) · [发布清单](E:/QuantData/numeric/cn-71132cf836bd63c14a85bbb71cbbd607a3372d4c7f0b91e359382d359ecc6d45/manifest.json)

| 核心表 | 实际行数 | 分区日期范围 |
|---|---:|---|
| `stock_daily` | 11,745,773 | 2015-01-05 至 2026-07-31 |
| `stock_fundamental_asof` | 198,799 | 2012-03-09 至 2026-05-15（快照公开日期） |
| `market_daily` | 2,813 | 2015-01-05 至 2026-07-31 |
| `industry_daily` | 13,987 | 2023-02-08 至 2026-07-31 |
| `samples` | 11,618,610 | 2015-01-05 至 2026-06-30 |
| `labels` | 34,855,830 | 2015-01-05 至 2026-06-30（样本日期） |

- 全量 SQL 检查零违规。按样本与期限逐键比较了全部 34,855,830 条新旧标签，目标日期、简单收益、对数收益、Z、类别和监督掩码均一致。3,967 条无效标签仅更新了目标日证据 ID，逐条追溯到目标日从限价未知改为不设限。全部候选样本的键和非财务引用字段一致，3,094 条候选样本更新了财务快照引用。至少一个期限有效的样本数为 train 7,209,690、validation 608,311、calibration 651,003、test 1,891,977。样本截止于 6 月 30 日，7 月用于标签观察。
- 独立复验四项通过。真实样本检查覆盖 60 个证券日的 PIT 前缀、150 个证券日的 22 项可独立复算因子，以及 16 个 Karpo 原生编码样本。原生样本保持三题、每题七项和完整 60 日数值窗口。仓库测试 76 项通过。 [发布校验结果](E:/QuantData/numeric/cn-71132cf836bd63c14a85bbb71cbbd607a3372d4c7f0b91e359382d359ecc6d45/reports/validation_results.json)
- 财务原始字段和依赖财务的因子通过结构性全空检查。仍有六项市场和行业相对个股因子在全部 32 个交易所 × 年份 × split 分组全空，分别为两项市场超额收益、两项行业超额收益、市场 beta 和残差波动率。市场权重分母和历史行业母集仍是通过验收的首要阻塞。 [财务与因子分层覆盖](E:/QuantData/numeric/cn-71132cf836bd63c14a85bbb71cbbd607a3372d4c7f0b91e359382d359ecc6d45/reports/financial_factor_coverage.parquet)

## 复查和重建

以下命令从读取指针获取发布目录，检查发布文件并用本机 Karpo tokenizer 和原生代码抽查编码。`--allow-incomplete` 用于质量检查，正式训练入口按发布状态控制。

```powershell
Set-Location 'E:\Kurumi'
$python = 'E:\quant\.venv\Scripts\python.exe'
$numeric = 'E:\QuantData\numeric'
$version = (Get-Content (Join-Path $numeric 'latest_cn.json') -Raw | ConvertFrom-Json).path
$release = Join-Path $numeric $version
$env:PYTHONPATH = 'E:\Kurumi\src;E:\Kurumi\reference\karpo-decision\src;E:\Kurumi\artifacts\karpo-runtime'
& $python scripts/verify_cn_numeric.py $release
& $python scripts/check_numeric_loading.py $release --representative --price-prefix --allow-incomplete --karpo-assets artifacts/karpo-b8e6fd7
```

重建可复用 `E:\QuantData\numeric\.build-cn\sources\pit-releases\cn-pit-a67a51789e5e2d1e0837ecd0`。`scripts/build_cn_numeric.py` 接受该目录作为 `--pit-evidence`，并接受 `--calendar-prehistory artifacts/cn-calendar/trade_cal` 和 `--suspension-evidence $release/reference/official_suspensions.json`。读取配置用 `configs/cn_numeric.toml`，以 `dataset_version` 固定某个发布版。 [构建命令](../scripts/build_cn_numeric.py) · [根目录读取配置](../configs/cn_numeric.toml) · [来源归并发布命令](../scripts/publish_cn_gap_batch.ps1) · [新旧发布复查命令](../scripts/audit_cn_gap_release.py)
