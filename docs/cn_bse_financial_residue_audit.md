# 北交所早期财务快照补齐复核

从第四版实际发布的行情输入清单出发，114 家发行人共 3,164 个有效输入证券日缺财务快照。逐发行人用生产时点逻辑重放四批正式原件，全部 3,164 个缺口均得到快照。新增快照共 10,004 个证券日，593 个财务发布版本与旧流合并后共改进 39,808 个证券日。既有非空财务量没有下降。以下是冻结片段的真实数据回放，正式训练包另按第六版发布验收结果记录。 [逐发行人合并回放](../artifacts/cn_numeric_followup/bse_financial_originals/residue/combined_bse_financial_residue_audit.json)

| 冻结片段 | 原件版本 | 发行人 | 新有财务快照的证券日 | 其中有效输入日 |
|---|---:|---:|---:|---:|
| 原财报批次 | 467 | 86 | 7,540 | 2,380 |
| 已核实旧证券代码第一批 | 25 | 6 | 652 | 292 |
| 已核实旧证券代码第二批 | 49 | 13 | 1,002 | 222 |
| 三表题头未标注合并 | 52 | 9 | 810 | 270 |
| 合计 | 593 | 114 | 10,004 | 3,164 |

前两批补充使用正式上市资料与原财报上的法人名称、旧代码建立连接。旧代码仅用于定位财报和确认同一法人。财报有效时间仍由实际公告日确定，上市前旧市场行情未加入北交所输入。原财报 PDF、公告目录和详细页的哈希继续使用采集原值。北交所域名下的直接二进制下载实验收到 HTTP 403，官方文本检索可读。另保留实取的巨潮官方佐证与请求回执。 [第一批发行人证据](../artifacts/cn_numeric_followup/bse_financial_originals/residue/issuer_identity_proof.json) · [第二批发行人证据](../artifacts/cn_numeric_followup/bse_financial_originals/residue/issuer_identity_proof_followup.json) · [直接读取回执](../artifacts/cn_numeric_followup/bse_financial_originals/residue/identity_sources/issuer_identity_capture.json)

第三批的三张表题头分别为资产负债表、利润表和现金流量表。审核确认原件同一财务报表节中有唯一有序的一套三表，并逐份核对归属母公司的资本与损益、少数股东权益与损益表项、原币单位和对应年月。泰鹏智能 2023 年半年度原件在简表明列两期归属于挂牌公司股东的净资产，逐分核对同一原件的所有者权益合计后保留简表原行作为归母权益来源。方盛股份 2022 年第三季度报告的巨潮直取版和既有存档逐字节一致。 [北交所新旧码公告](https://www.bse.cn/code_mapping/200025792.html) · [方盛原季报](https://static.cninfo.com.cn/finalpage/2022-11-07/1215045005.PDF) · [题头复核配置](../artifacts/cn_numeric_followup/bse_financial_originals/residue/issuer_unprefixed_review.json) · [方盛复核配置](../artifacts/cn_numeric_followup/bse_financial_originals/residue/issuer_920662_review.json)

核验覆盖财务版本第一次可得日、每个受影响证券日的历史前缀、七项原始财务量的来源行，以及快照新增和既有字段损失。四批的发行人、来源版本 ID 和财务发布键均无交集。失于正式合并属性、明确期间列、金额核算或主体对应的个别原件仍保留逐件理由。 [原批次](../artifacts/cn_numeric_followup/bse_financial_originals/frozen_replay/bse_financial_replay_audit.json) · [第一批](../artifacts/cn_numeric_followup/bse_financial_originals/residue/frozen/bse_financial_replay_audit.json) · [第二批](../artifacts/cn_numeric_followup/bse_financial_originals/residue/frozen_followup/bse_financial_replay_audit.json) · [第三批](../artifacts/cn_numeric_followup/bse_financial_originals/residue/frozen_unprefixed/bse_financial_replay_audit.json)
