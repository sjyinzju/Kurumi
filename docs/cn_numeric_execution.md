# CN 数值数据建设执行记录

执行起点为 2026-11-19，契约为同日定稿的 v1.0。数据写入分区使用 `E:\QuantData\numeric`，代码和发布报告位于本仓库。

| 阶段 | 产物与核验点 |
| --- | --- |
| 依赖识别 | 现行 quant 快照、活跃分片、历史清单、源原件、历史生命周期和磁盘清单 |
| 清理迁移 | 分区按列读取与压缩，新旧哈希分别登记。旧分片须无消费者引用且有已验证的等价源数据才进入回收 |
| 定向补采 | 从生命周期日历母集得到缺键，逐端点按证券补采，保存请求摘要、时间和实际结果 |
| 特征与标签 | 历史日历展开、实际价格窗口、PIT 财务及股本、市场和行业聚合、三个期限独立监督 |
| 验收与发布 | 核验分区、时间窗口、标签数值和覆盖，使用内容清单标识版本，并用真实样本验证 Karpo |

## 保留依赖

| 范围 | 必要源及证据 |
| --- | --- |
| 证券身份和日期 | 股票主表、历史更名、北交所新旧代码和实际切换日、上市退市、交易所日历 |
| 实际量价、状态、sigma、Xchoice、Y | 日线 OHLC、真实股数/成交额、独立价格复权 F、停复牌、涨跌停；保留 2015 年价格预热与 2026 年 7 月结果缓冲 |
| 成交单位链 U | 拆股、合股、送转原始公告、生效时间和查验覆盖；现金分配仅进入价格复权链 |
| 个股换手、证券权重及发行人估值 | 当时股类股数、普通股类历史、报价/汇率及币种；日指标原值作为核对线索；股本公告及关联公司行动 |
| 财务与估值因子 | 正式合并收入、利润、归母利润、经营现金流、资产、负债、归母权益，以及连续前序组成期、历史公开版本及原件 |
| 市场、行业、相对状态 | 生命周期母集、历史申万一级归属和版本、已核实停牌估值、前期证券资本基数、原始量价与有效覆盖 |
| 复现与质量 | 源批次及查询时间、原件身份和身份哈希、旧注册表引用、衍生 SHA-256、schema、质量原因与各阶段检查点 |

已核对 quant 提交 `0e885f181bc0db433bfd69572523a327d6216e49`。旧注册表含 46 个版本、8,540 个当前活跃分片、1,068,648 个未活跃记录。计划任务 `PersonalQuant-Resume` 已禁用，旧进程 ID 已不在任务表，注册表运行抓取数为零。共享引用扫描涵盖 quant、Kurumi 和 E 盘已知的研究与数据项目。

价格阶段记录在 `.build-cn/work.duckdb` 的 `build_checkpoints`。补采按请求保存确认、空响应与可恢复异常。发布准备目录以输入、代码、来源证据的哈希标识，每张已导出表核对 Parquet 行数和 SHA-256 后写入进度。

首轮价格网格发现 11,222 个无实际收盘且尚无停牌证据的证券日。定向 TuShare 请求覆盖行情、价格因子和停复牌。另按交易所公告及北交所成交日期核实 1,143 个开市日，取得 1990／1991 年起的沪深早期日历。北交所日历核验见 [机器可读验收](cn_bse_calendar_validation.json)。

补采及身份修正后，价格检查点包含 11,745,773 个证券日，其中 6,206 个仍无收盘且未被源端和本轮公告解释。纠正财报 PDF 脚注列误取金额后，从已保存的价格检查点重新启动下游构建。发布构建使用冻结的备查输入并核验哈希一致。供应商事后可见的停牌事实仅供监督和审计，市场估值使用有当时可得证据的停牌状态。

首版写出 1,161.86 万候选样本和 3,485.58 万标签记录。逐年导出在价格和因子连接两侧按日期裁剪。全量字段覆盖先统计相同原因映射的出现次数，再展开不同映射，并与独立 Arrow 扫描逐组核对。

原地回收已移除 3,126 个经源哈希、引用及逐行等价性核验的 Canonical 旧分片。随后增量合入另六段已核实停牌公告和最终股数单位链区间。增量入口使用首版清单核对来源快照，并确认新公告包含原有记录。实际更新 1,613 个证券日的停牌证据，未解释的无报价证券日剩 4,891 个。重新计算监督审计及依赖状态，随后独立验收增量发布。

复测巨潮目录恢复后，按缺失会计组成期取得东方财富、宁波银行的连续季度原件。原件同会计期数据逐项核对后，财务冻结输入增至 194 个报告版本。再合入原始公告和六条独立保留的事后停牌事实，更新 4,883 个证券日的停牌证据；当前价格检查点剩 14 个未解释无报价证券日和 161 个停牌日复权因子缺口。

二次复核明确了东方财富合并利润表的收入合计口径，并从原始季度报告的累计列核正了平安银行、浦发银行的早期金额。最终重建仍使用 194 个报告版本，冻结财务流 SHA-256 为 `a597423df70558badb4756199defef7413e489143c064379370d1869a11f0a03`。修复脚本和原件定位支持复核字段语义，来源前缀验收绑定同一冻结流。

2026-11-19 最终重建发布 `cn-8dfdd9db8a90fd88e132e3675fd31e311e02b5a50ad437cca7f8bdff7198e03b`，`latest_cn.json` 已指向该目录。上一阶段版本 `cn-d08203c1f3b86fda76ce197f5493e675ad130c422bdc9d3f68134814b1280983` 已由包含收入语义修正的版本替代。发布目录实测复用 39 个逐字节相同的 Parquet，独立核验 86 个清单文件及 10,360,815 条训练索引的分段和期限掩码。市场和行业聚合缺少可核验的历史资本基数及完整行业名单，发布状态为 `INCOMPLETE`。见 [数据报告](cn_numeric_dataset_report.md) 和 [质量摘要](cn_numeric_quality_summary.json)。

## 2026-11-20 增量补齐

本轮从现有发布与 `numeric/.build-cn/work.duckdb` 的五个检查点开始。开工时 E 盘可用约 28.71 GiB。新采集以请求回执、原件哈希和统一证据流记录，构建沿用相同六张表和时间切分。

| 阶段 | 核验依据 |
| --- | --- |
| 依赖定位与实现修复 | 以证券日历母集核对当前缺口，回归检查官方股本无供应商对照、股类口径、公司行动及发布状态 |
| 证据采集和归并 | 核验 TuShare、CSMAR 和交易所披露的渠道权限、字段口径、历史版本与已采集分区，合入原有冻结证据 |
| 增量重算 | 使用价格和已验证的监督检查点，重算来源变更影响的时态字段、市场和行业统计、因子与关联索引 |
| 验收发布 | 分区独立核验、历史前缀和真实原生编码测试，汇总结构性缺口后由构建器决定状态 |

已通过现有凭据登录 CSMAR 官方 SDK。首日完成 20 批、438,829 行，并核对源行数与文件 SHA-256。第 21 批返回官方日下载限额。已取得的完整股本事件和分配档案进入核对，其余查询以实际已下载清单为准。见 [CSMAR 来源核验](cn_csmar_source_audit.md)。

BaoStock 和东方财富在 14 个早期深市缺价日的开、高、低、收一致，且 BaoStock 返回正成交量和正常成交状态。恢复的分片只包含实际成交，没有引入停牌估值。此前遗留的 F 缺口另按独立公司行动档案验证，和股数单位链分别处理。

首次增量构建发布 `cn-1778218fa1d94642379210bd3438e987cef73a84925f5e8442d23f2f23d2d6`。清单覆盖 110 个文件，合计 3,608,242,803 字节。生命周期与交易日网格中的未解释行情缺口和 F 缺口均为零，候选样本 11,618,610 条，标签 34,855,830 条。23 项全量违例计数均为零，发布后也独立核查了清单、窗口、标签及训练掩码。股本证据尚不足以恢复完整前期市值分母，历史行业成员也没有完整证据，自动判定 `INCOMPLETE`。

TuShare 财务定向预热、新上市公司前序会计期和更正前版本采集均已实际完成，分别处理 8,445、1,995 和 5,889 个请求。归一化财务流包含 219,414 个版本，抽样复算了 259 条原始源记录。官方股本第二次冻结含 13,470 条公告版本。股本锚点仍使用原来独立交叉验证的 138,827 条，更新的财务流没有提供不同或新增的股本锚点。第二次构建沿用相同价格证据，复核监督检查点后重新计算其他受影响表。

18:14 完成第二次增量发布 `cn-20796d534b7d3ba59a8054c95d4341bac4e0212ee3b50219d4f78282d5910790`。111 个清单文件共 3,630,683,863 字节，20 个 Parquet 与前版共享硬链接，其中 12 个标签分片的 SHA-256 全部一致。财务时点快照增至 197,612 份，合格股本、发行人市值和股数单位链分别增加 602,447、612,005 和 11,952 个证券日。23 项全量违例计数均为零，4 项独立验收通过。独立全量扫描核对 2,813 个市场日和 363 个行业日均未构成有效覆盖收益。最新指针和构建器状态为 `INCOMPLETE`。 [数据报告](cn_numeric_dataset_report.md) · [质量摘要](cn_numeric_quality_summary.json)

进一步使用本版真实量价复算 U 链。101 只证券原有归档只扫描研究期，实际历史档案含 1,311 条 2014 年前的股本事件，逐证券完整分页重取后恢复 268,521 个证券日。修复日历映射把北交所开市前事件聚到首个开市日的问题，原始候选逐项核对后恢复 43 个开市日证券键。中航成飞按深交所原公告补录 300114 至 302132 的换码日期，并通过两个代码定向取回 87 条 TuShare 分派记录。三方证据已能核定其全部 2,813 个证券日的 U 档案。上述均为第三次构建备查证据。 [U 链完整缺口复算](../artifacts/cn_numeric_followup/capital/action_reconciled_full_extension/full_extension_gap_audit.json) · [深交所换码公告原件](https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF)

18:46 冻结第三次增量输入 `cn-pit-f1e6893601e4cda1bdb881a8` 并启动全量构建。深交所全部 40,165 个候选公告日已处理，上交所全部 22,045 个候选公告日已处理。原件去重后纳入 15,628 个沪深股本版本。中航成飞的两个代码另外完成 18 份 TuShare 财务查询，净增 46 个财务版本，沿用原稳定证券 ID。三家发行人的 A+H 有效区间在 2,152 个实际证券日上通过生产代码和独立算式核对，并通过三次时点截断。 [股本和汇率核验](cn_mainland_capital_intervals_audit.json) · [冻结输入](../artifacts/cn_numeric_followup/release3_input/frozen_path.txt)

第三次构建期间另冻结 134 家发行人的官方年报或上市公告股本证据，另含 28 份原件确认的多股类版本。在第二版实际行情上识别了 282,123 个可核对的缺股类市值证券日，待重算后核计净增。北交所余下 82 个 U 缺口均取得范围明确的原始证据，含 4 个原始送转或拆股事件。逐日回放另核对 726 个此前只有事后记录的停牌日及其原始披露，最后两个开市日附可信的同日事实公开时刻。三家公司交易简称的 5 条主源版本已通过真实 Parquet 回放，补 2,818 个空值及纠正 611 个过早启用的简称。 [停牌与 U 核验](cn_bse_source_residual_audit.md) · [历史简称核验](cn_security_name_audit.md)

19:43 发布第三版 `cn-27e5ff0cbcccc52e25e4fe03e8f8ac7da7662b480ed3753e6523e62de69f65b6`，125 个清单文件共 3,634,986,866 字节。财务时点快照 197,657 份。相比上一版，合格股类股本增加 121,325 个证券日，发行人市值增加 121,254 日，合格 U 链增加 271,553 日。全量测试、真实输入编码和独立核验通过。2,812 个有前一交易日的市场日均缺部分母集前期资本，构建器自动发布 `INCOMPLETE`。 [第三版独立验收](../artifacts/cn_numeric_followup/release3_input/independent_release_verification.json) · [市场权重审计](../artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-27e5ff0cbcccc52e25e4fe03e8f8ac7da7662b480ed3753e6523e62de69f65b6.json)

19:47 冻结第四版输入 `cn-pit-3f84b262593dc2ad07c20f49` 并启动重算。首阶段在原价格网格追加验证了 726 个北交所停牌证券日，北交所核验停牌总数达 731。实际价格及 F 缺口仍为零。输入同时含 210 家新核验股本原件，5 家退市 B 股历史股类及 8,852 条实际报价，5 条历史简称版本，82 个北交所和 702 个沪深 U 链可复算证券日。收益、样本及最终覆盖以第四版重新验收结果为准。 [第四版冻结点](../artifacts/cn_numeric_followup/release4_input/frozen_path.txt) · [退市 B 股独立核验](cn_retired_b_siblings_audit.md)

冻结检查发现历史脚本可将可重写的工作文件和存档接成同一硬链接。新冻结命令先将新字节归档到按 SHA-256 命名的对象，再在冻结版本之间复用相同对象。增量入口校验父版 Manifest 的完整源哈希后再追加记录。验证覆盖重写原工作文件、重复冻结以及使用父版清单追加新流；冻结结果和版本名均按预期保持。 [冻结命令](../scripts/stage_cn_pit_evidence.py)

第四版重算期间已实际核验北交所 29 家 IPO 原件，覆盖 1,190 个原缺证券市值的实际报价日。沪深另一批现金分配档案在双源、原始报价和发行人折算复核后已有 2,269 个证券日可冻结。128 个非首发日简称缺口检索取得 126 份沪深原件，21 个同日简称空值通过媒体公开时刻与原件生效日交叉验证。九家科创板公司另由 27 份原件证实旧称存在，实际试算复原 12 个空值并纠正 105 个提前更名证券日。以上结果作为下一版候选，发布总量以重算和验收统计为准。 [北交所原件核验](../artifacts/cn_numeric_followup/capital/residual_bse_ipo_anchors/final_review/bse_ipo_freeze_audit.json) · [沪深现金档案核验](../artifacts/cn_numeric_followup/capital/mainland_cash_gaps/frozen_2024_2026/) · [科创板简称核验](../artifacts/cn_security_name_audit/sse_proposed_names/verified/sse_proposed_names_audit.json)

21:12 发布第四版 `cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc`，140 个清单文件共 3,672,747,391 字节。四项独立检查均通过，股类股本净增 362,893 个证券日，发行人估值增 218,532 日，U 链增 784 日。北交所 246,184 个证券日全部具备有效 U，731 个非报价日全部取得停牌证据。四个 split 的实际样本数与第三版一致，标签分片的字节哈希均已变化。2,812 个有前一期的市场日仍缺完整资本分母。发布状态为 `INCOMPLETE`。 [发布与实际差额](../artifacts/cn_numeric_followup/release4_input/actual_release_delta.json) · [市场权重核验](../artifacts/cn_numeric_followup/market_denominator/market_weight_blockers_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

21:13 冻结第五版输入 `cn-pit-8c326f55439a40e121fc0cde`。首个构建进程在第四版写锁释放前退出，待第四版正常退出后以同一冻结输入恢复。实测进入 PIT 重算，价格源版本沿用第四版。冻结新增沪深 2,533 个现金分配 U 证据和核验股本原件，同时纳入同所改码、跨所发行人链接、1,243 个限价状态和招商港口 2017 年正式年报。 [冻结输入](../artifacts/cn_numeric_followup/release5_input/frozen_path.txt) · [锁交接回执](../artifacts/cn_numeric_followup/release5_input/initial_lock_handoff.log) · [来源归并](../artifacts/cn_numeric_followup/release5_input/v5_originals_audit.json)

21:23 以同一冻结输入重新启动第五版。样本索引从 PIT 表同步发行人、财务及行业引用。影响目标日来源编号的简称、限价与价格事实流发生变化时，构建器重算监督分片。全量验收新增样本引用和目标日来源编号的对照检查。57 项本地测试通过。第四版 34,855,830 个标签也已逐行比对，其中 13,299 个标签的简称来源和 2,073 个标签的停牌来源更新；收益、目标日期、监督掩码和无效原因完全一致。 [第四版标签差额复算](../artifacts/cn_numeric_followup/label_release_diff_cn-9603ec85aed8295eccad357b9c70f19201bf944ede1cbbdb87033b1a502017cc.json)

21:28 查明第四版构建入口漏传了已写出的股类报价分片。第五版修正冻结为 `cn-pit-15a56149b92f88d511563b2c`。640,659 个真实股类报价和 6,116 行汇率均有冻结哈希。股类版本存在时，冻结与运行时均核对报价及汇率分片。第五版随后完成 PIT，进入监督和特征重算。 [修正后的输入](../artifacts/cn_numeric_followup/release5_input/frozen_path.txt) · [退市 B 股来源](cn_retired_b_siblings_audit.md)

第五版运行期间，新增两批七家 A/H 股发行人共 15 个历史普通股股类版本。对第五版冻结报价及 PIT 算法的回放净恢复 15,959 个证券市值和 15,484 个发行人市值，已核实旧市值保持一致。另从发行人原公告中冻结 115 个股数单位日期和 219 个停牌会话。2026-06-30 的申万当日公开快照新增 4,915 个此前缺失的行业证券日，其中北交所 323 个。独立前缀回放确认其当日生效，既有版本和相邻日期不受影响。 [A/H 复算一](../artifacts/cn_numeric_followup/capital/residual_multi_cap/frozen/v5_merge_delta.json) · [A/H 复算二](../artifacts/cn_numeric_followup/capital/residual_multi_cap/extra_frozen/v5_merge_delta.json) · [停牌及单位链](../artifacts/cn_numeric_followup/capital/mainland_cash_gaps/frozen_suspended_cash_2018_2026_final/suspended_cash_followup_audit.json)

22:23 开始归并第六版候选。两批 492 个北交所正式财报版本，实际回放可新增 8,192 个财务快照证券日及 2,672 个已有有效行情输入的证券日。申万三批实际来源合计 14,491 个互不重叠的证券日，覆盖 12 次历史截面。新增停牌原件为 222 个，全部通过无实际成交的交叉核对。 [北交所原件](cn_bse_financial_originals_audit.md) · [申万历史原件](cn_industry_source_audit.md)

Windows 系统日志显示 22:33:46 进入待机，22:57:10 唤醒。第五版从已核验的标签分片断点继续写入。后续构建期间使用进程级的系统空闲休眠请求，结束后释放。 [Microsoft Windows API](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)

23:40 第五版 `cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c` 通过四项独立验收并更新读取指针。143 个清单文件共 3,676,634,932 字节，状态 `INCOMPLETE`。相对第四版新增 36,354 个股本证券日、165,470 个发行人市值证券日和 2,533 个股数单位链证券日。164,057 个跨股类估值证券日均成功连接来源，七家公司 14 条实际样本用原件、实际股价与汇率独立复算。全量 34,855,830 个标签中 17,279 个更新了目标日来源编号，其他字段逐键一致。 [真实成果与差额](../artifacts/cn_numeric_followup/release5_input/actual_release_delta.json) · [真实标签对照](../artifacts/cn_numeric_followup/label_release_diff_cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c.json)

23:41 核验第五版 Manifest 及冻结对象哈希后，清理 Kurumi 内三个可重建、未被读取方引用的生成副本，合计 778,885,687 字节。E 盘净回升 778,891,264 字节。 [回收回执](../artifacts/cn_numeric_followup/release5_input/working_copy_reclamation.json)

23:43 冻结第六版 `cn-pit-080b8785d26fdc673a1bdad7`。四批共 593 份北交所正式财报版本，源回放补齐定向范围内全部 3,164 个有效模型输入日的财务快照。将 14,491 个有公开时点的申万归属、7 家跨股类股本和 115 个股数单位链补证同时纳入本版。运行入口实测已加上 222 个有公开证据的停牌日，真实报价和价格复权无未解释缺口，进入 PIT 重算。 [第六版冻结点](../artifacts/cn_numeric_followup/release6_input/frozen_path.txt) · [北交所财报逐发行人核验](cn_bse_financial_residue_audit.md)

11 月 21 日 00:01，CSMAR 续采实际完成。39 个范围均返回权限码 `-2501`，新增 0 页，旧 438,829 条源记录再次通过哈希与行数检查。会话认证继续成功，前一日曾下载 23 条的已知对照范围当夜也无法查询行数。第六版继续计算特征。 [CSMAR 续采及对照](cn_csmar_source_audit.md)

00:55，第七版来源审核完成。财务准入 215 个原公告时点和 16 个单独披露的比较期补证，均可回到正式合并报表及公告时钟。其中八家普通行业发行人的定向回放新增 8,894 个当期 TTM 证券日。观典防务的三份原件修复 7 个有效输入日的七项核心财务量。六家 A/H 发行人股本按同日价格和汇率复算，独立来源回放增加 4,318 个发行人市值证券日。第六版仍在写出全量监督分片，待实际发布后归并这批来源。 [财务公司说明](cn_original_revenue_comparability.md) · [证券公司原件](cn_securities_revenue_audit.md) · [A/H 股本证据](cn_v7_ah_capital_recovery.md)

01:33，第六版 `cn-beb5e8af76b5b11a604f69eacc0418bccc1aedc664ba3a6913bae3addf2cdcf9` 发布，读取指针已更新。146 个清单文件共 3,678,476,389 字节，四项独立验收通过，状态 `INCOMPLETE`。相对第五版新增 16,033 个核验股本、15,637 个发行人市值、115 个股数单位链、10,004 个财务快照链接、14,491 个申万归属及 222 个确证停牌证券日。首次发布版之外的标签观察区间、预测期、三个期限和训练清单保持相同。 [实际差额](../artifacts/cn_numeric_followup/release6_input/actual_release_delta.json)

第六版发布后，独立逐键比对 34,855,830 条标签的 14 个字段。666 条原本无效的监督记录更新停牌来源，其余字段一致。北交所有效输入日中 3,164 个空快照引用已全部补齐，仍只有 29 个有效输入日有七项财务量。核对五份归一化工作副本与已发布清单所指冻结对象的 SHA-256 后回收工作副本，E 盘实测增加 796,721,152 字节。 [发布后独立复核](../artifacts/cn_numeric_followup/release6_input/independent_v6.json) · [回收证据](../artifacts/cn_numeric_followup/release6_input/working_copy_reclamation.json)

01:36，第七版冻结为 `cn-pit-45a7a89e77f38280e50fbe39` 并实际启动主构建。财务同公告时点修复 215 条，另保留 16 条各自首次公开的较晚或上市前历史组成事件。修复保护既有非空财务量。当收入版本口径不一致时，单季及 TTM 收入继续写入明确的缺失原因。第六版独立验收结束后应用修复，Ruff 和 67 项测试通过。 [第七版原版本配对](../artifacts/cn_numeric_followup/release7_input/v7_financial_version_audit.json)

03:10，第七版 `cn-369dd922bdcab942f77d959223921a4391200693282df980e321c7e946f90c5a` 发布。当前读取指针与清单同为 `INCOMPLETE`，157 个清单文件合计 3,679,160,738 字节。24 项全量 SQL 违例计数均为零，四项独立发布检查通过。实际复算后与第六版逐文件独立核对，12 个标签分片的全部 SHA-256 一致，覆盖 34,855,830 条监督记录。新增 4,318 个发行人市值证券日、264 个合格股本证券日及 24 个财务快照链接。按最终 Parquet 复核，目标发行人恢复了 13,641 个当期 TTM 营收证券日和 11,975 个一年以前 TTM 营收证券日。原件确认新增 243 个 A 股证券市值证券日并纠正 1,401 个旧值。 [实际发布差额](../artifacts/cn_numeric_followup/release7_input/actual_release_delta.json) · [实际逐字段和标签复核](../artifacts/cn_numeric_followup/release7_input/independent_v7.json)

03:11，回收发布后可重建的三个工作副本和一个独立财务试算，E 盘实测净增 1,252,904,960 字节。已发布版本、现行入口与原始来源证据通过路径和 SHA-256 核对。 [独立空间清单](../artifacts/cn_numeric_followup/release7_input/independent_disk_safety.json) · [工作副本](../artifacts/cn_numeric_followup/release7_input/working_copy_reclamation.json) · [试算回执](../artifacts/cn_numeric_followup/release7_input/trial_reclamation.json)

03:14，同步核对读取指针、数据报告和机器摘要的版本及状态。统一加载器按 `INCOMPLETE` 拦截正式入口，显式 QA 读取实测加载 32 个训练清单样本。E 盘实测剩余 25.95 GiB，构建进程的临时防休眠请求已释放。

### 来源断点的复算

以下命令从实际采集断点复算财务来源层，新目录用于归并结果检查。`tushare-sw.sqlite3` 单独用于行业来源核验。

```powershell
Set-Location 'E:\Kurumi'
$python = 'E:\quant\.venv\Scripts\python.exe'
$source = 'E:\QuantData\numeric\.build-cn\sources'
$project = 'E:\Kurumi\artifacts\cn_numeric_followup'
$financial = Join-Path $source 'financial-v2'
$checkpoints = @()
Get-ChildItem -LiteralPath $financial -File -Filter 'tushare-*.sqlite3' |
    Where-Object Name -ne 'tushare-sw.sqlite3' |
    ForEach-Object { $checkpoints += @('--checkpoint', $_.FullName) }
$csmar = Join-Path $source 'csmar\requests'
$normalized = Join-Path $financial 'normalized-replay'
& $python scripts/normalize_cn_financial_versions.py --output $normalized --csmar-capture $csmar `
    --originals 'E:\Kurumi\artifacts\cn_numeric\pit_corrected_input\financial_versions.jsonl' `
    --originals (Join-Path $project '002591_verified_originals.jsonl') @checkpoints
& $python scripts/verify_cn_financial_sources.py --input (Join-Path $normalized 'financial_versions.jsonl') `
    --csmar $csmar --report (Join-Path $project 'financial_replay_lineage.json') @checkpoints
```
