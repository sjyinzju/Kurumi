# CN 数值建设的旧库回收记录

## 现行与共享引用

只读核对了 `E:\QuantData\quant.duckdb` 的 67 个业务视图、46 个注册数据版本和下游注册表。回收前有 8,540 个活跃 Canonical 分片，另有 1,068,648 个非活跃记录。非活跃标志不构成删除依据。量价、日历、股本、公司行动、财务历史版本以及 Quant 使用的原始数据和当前视图继续保留。脚本会扫描注册清单、根目录的项目和报告文本、下游注册记录与视图中的具体文件名。

## 已回收临时文件

在旧写入协调完成后，使用旧库的 ingestion 和 metadata 锁核对了两份中断写入留下的 `progress.json.<UUID>.partial`。实际删除两份文件，共 18,880 字节。`progress.json` 保留并按原 SHA-256 核验。旧审计的 64 个 UUID 临时目录为空，逐一以非递归方式移除。复查两个路径下均无这些临时项目。详细回执见仓库工作区 `artifacts/cn_numeric/legacy-scratch.receipt.json`。

## 旧恢复计划与回收边界

第一次严格检查没有找到可直接回收的分片。扩大范围后，12 个分区的 2,116 个非活跃记录全部命中文本引用。核对其中一个分区的五个具体文件，均未出现在 46 份数据库版本清单中，只命中 `reports/data_integrity/1a4434dbcc0d0ade31806efb4b1c924cef8280e6412eeaa553f8f8265a711f9a/recovery_plan.json`。

该文件是 2026-10 执行记录中拟用于未来独立全库备份的 `PLAN_ONLY` 清单，共 1,512,415 项，文件大小 432,345,081 字节，SHA-256 `3250e8232368bda01a644941ee16d6ed6cb5f2b7f3e6bf1b428044f5371e46f7`。同目录回执说明其中未被注册版本引用的非活跃 Canonical 哈希沿用登记值。清单明确记录无独立备份。恢复工具由调用者通过 `--plan` 指定文件，代码搜索找到清单的生成及历史证据复制入口，旧恢复政策文档将其作为人工恢复计划引用。

`scripts/reclaim_cn_legacy.py` 可以仅对这份校验和固定的旧备份清单作范围豁免。其余清单、引用、证据和视图仍参与锁定。每个候选还需通过本机文件哈希验证，并证明其数据行及历史知识时间等追溯字段在同端点、同分区的当前文件中保留。比较遵循既有 Quant 回收规则，允许压缩路径下的 `_batch_id` 变化。原始批次及其哈希保持原引用。实际删除调用 Quant 的回收器，由其重新核对并持久记录每组回执。

带豁免的删除必须先明确退役旧备份入口。脚本在两把旧库锁下以原字节存档旧清单，将原路径写入退役记录，并保留独立证据恢复清单与旧回执。旧文档给出的原路径将不再提供可执行的全库恢复计划。未来从保留版本恢复前须从现行目录和注册表生成新的恢复清单。已发布 DatasetVersion 和现行 DuckDB 视图均保留。

单独豁免上述历史恢复计划后，重新核验同样 12 个分区。其余来源仍锁定 14 个分片。2,102 个分片均存在、哈希一致且当前分片保留其所需行，共 65,314,535 字节。另验证了 `index_daily/2026` 的 1,024 个较大未锁定分片，共 782,589,467 字节。两份证明合计 13 个分区、3,126 个文件和 847,904,002 字节。联合计划及构成文件的 SHA-256 记录在 `artifacts/cn_numeric/legacy-canonical-combined.gc-plan`。

2026-11-19，修复旧回收器预检读取整份报告导致的内存错误后，使用同一联合计划重新执行。Quant 持锁再次验证并删除了 13 个分区中的 3,126 个分片，目录实测释放 847,904,002 字节，回执状态为 `COMPLETE`。加上前述两份临时文件，计 847,922,882 字节。旧备份清单已按原 SHA-256 存档，原入口写入退役记录。原有回收器继续记录各分区的当前替代路径、原 SHA-256 和删除状态，汇总位于 `E:\QuantData\90_metadata\gc\summary.json`。

## 低空间时的无损压缩

2026-11-19 晚间，持旧库 ingestion 和 metadata 锁，对两份诊断 CSV、Kurumi 的 `work.duckdb`、冻结审计库及退役备份清单五个文件逐一执行 NTFS 压缩。五个文件仍以原路径读取，压缩前后逻辑长度及 SHA-256 一致。两个 DuckDB 文件均完成只读打开并复核构建检查点或版本计数。文件实占合计下降 6,887,722,951 字节，E 盘实测可用空间从 13.21 GiB 增至 19.62 GiB。回执见 `artifacts/cn_numeric/ntfs_report_reclamation_20261119.json`。

## 已替代 CN 发布版本的清除

核对本机项目配置、脚本及数据注册资料后，`cn-3a8881cc…`、`cn-aaae5d69…`、`cn-d08203c1…` 三份阶段性发布只在历史审计中出现。现行训练配置和增量构建从 `latest_cn.json` 定位发布包。逐一核验了三版的冻结 PIT 和停牌输入、发布清单内的文件哈希，并将原始发布清单、字段模式和必要的小型审计文件留存在 `artifacts/cn_numeric/retired_releases/`。

持两把旧库锁清除了上述三个目录内的 261 条文件路径。扣除共享硬链接后，释放约 5.65 GiB，E 盘实测可用空间从 19.59 GiB 增至 25.24 GiB。当前指针及发布清单的 SHA-256 均与清理前一致。完整版本号、留档范围及释放字节见 `artifacts/cn_numeric/retired_releases/receipt.json`。

2026-11-20 清除两个已替代的财务归一化试算输出，文件逻辑大小合计 782,711,202 字节。删除前逐一比对文件 SHA-256、已发布清单、冻结输入及共享项目引用，并确认文件可独占打开。原始采集断点、试算覆盖摘要和本轮冻结输入仍可用于回放。本轮构建并行写盘期间，清理操作前后 E 盘可用空间净增 342,638,592 字节。 [清理回执](../artifacts/cn_numeric_followup/retired_financial_trial_streams.json)

同日清除未用于发布的财报股本试算文件。按证券、生效日、公开日、股数和生效结束日比较，试算文件的所有键值均已保留在采用的来源流中。文件逻辑大小 230,098,548 字节，删除前后 E 盘可用空间实测净增 230,100,992 字节。 [清理回执](../artifacts/cn_numeric_followup/capital/superseded_financial_capital_trial.json)

2026-11-21，第六版发布后回收五个字节完全匹配的独立工作副本，E 盘实测净增 796,721,152 字节。第七版发布后再回收三个字节完全匹配的独立工作副本和一个可按原哈希重建的单发行人财务试算，实测净增 1,252,904,960 字节。逐个核验已发布清单、保留的冻结来源及待回收路径。复查现行和既有验收引用后，`E:\QuantData\numeric` 的已发布包均保留。 [第六版回执](../artifacts/cn_numeric_followup/release6_input/working_copy_reclamation.json) · [第七版独立空间核查](../artifacts/cn_numeric_followup/release7_input/independent_disk_safety.json) · [第七版工作副本](../artifacts/cn_numeric_followup/release7_input/working_copy_reclamation.json) · [试算回执](../artifacts/cn_numeric_followup/release7_input/trial_reclamation.json)
