# 北交所早期财报原件核验

从第四版实际 `stock_daily` 查得，研究预测区间内有 114 家北交所发行人的 3,164 个证券日具备有效行情输入但没有财务快照。按各证券的最后缺口日定向查找此前已公开的发行人完整定期报告，同时查询上市前两年内的前序期。新旧证券代码由实际发布键连接。未进入北交所的历史行情仍不参与样本或标签。 [北交所证券新旧代码和上市日](https://www.bse.cn/service/code_mapping.html)

直接测试北交所公告索引获得 HTTP 200 但正文返回“请求参数异常”。全国股转官方两个域名的同类定向查询均返回 HTTP 403。巨潮三组历史检索请求返回零条，已知的巨潮原件链接可以读取。批量阶段沿用现有的公告档案工具按年度、上半年及两个季报类别定位发行人附件。记录实际 URL、公告日期、目录与附件 SHA-256 和取得时间。 [北交所公告入口](https://www.bse.cn/disclosure/announcement.html) · [全国股转正式公告规则](https://www.neeq.com.cn/class_c0/200011043.html) · [请求回执](../artifacts/cn_numeric_followup/bse_financial_originals/probes/official_exchange_probes.json)

新芝生物 2022 年三季报的发行人网站、巨潮和公告档案下载均为 956,782 字节且 SHA-256 相同。已核实利润表同时列当季和年初累计两对数字，营业收入取 137,979,314.23 元，归母净利润取 32,078,508.50 元。2022 年半年度报告另保存为前序组成期。卓兆点胶 2023 年三季报的巨潮原件与公告档案下载逐字节一致。合并资产、负债、权益与经营现金流合计均按报表独立勾稽。 [新芝生物发行人原件](https://www.scientz.com/uploadfile/202410/0de8e6780d735c1ded016373581edaf3.pdf) · [卓兆点胶巨潮原件](https://static.cninfo.com.cn/finalpage/2023-10-30/1218206969.PDF) · [下载回执](../artifacts/cn_numeric_followup/bse_financial_originals/probes/verified_locators.json)

从合并表取当期存量和年初累计流量，分别核对证券身份、会计期间、币种单位和公开日期。表格无法确定列顺序或合并口径时保留失败原因。财务会计口径由原件明示，或由原件确认的交易场所和正式定期报告身份对应当期规则。报告日期精度按契约处理，财务快照保持真正的可用和修订时点。 [北交所初版上市规则第 6.1.2 条](https://www.bse.cn/cxjg_list/200010908.html) · [2023 年北交所适用版本](https://www.bse.cn/cxjg_list/200018002.html) · [全国股转信息披露规则第十二条](https://www.neeq.com.cn/class_c0/200011043.html) · [采集命令](../scripts/collect_cn_bse_financial_filings.py) · [合并报表校验](../scripts/stage_cn_bse_financial_filings.py) · [历史时点回放](../scripts/verify_cn_bse_financial_filings.py)

批次实际核出 931 条历史目录记录，取回含原件的 914 条，PDF 文件共 1,694,152,097 字节。两家已独立验算的四份原件先在真实证券日回放。新恢复 262 个财务缺失证券日，其中 142 个通过模型行情输入条件。 [采集目录](../artifacts/cn_numeric_followup/bse_financial_originals/issuer_reports/collection.json) · [两家对照回放](../artifacts/cn_numeric_followup/bse_financial_originals/control_replay/bse_financial_replay_audit.json)

批量校验从 931 个已登记版本中接收 467 份，涉及 86 家发行人。用真实证券日和冻结财务流回放，7,540 个原无快照的证券日取得财务快照，其中 2,380 个原已符合预测输入条件。既有非空财务量未下降。前四财政季度资产与归母权益各增加 9,548 个证券日，经营现金流 TTM 增加 398 个证券日，收入、合并净利润、归母净利润的 TTM 各增加 193 个证券日。既有快照前缀保持一致。 [实际财报验收](../artifacts/cn_numeric_followup/bse_financial_originals/normalized_v2/bse_financial_originals_audit.json) · [全范围回放](../artifacts/cn_numeric_followup/bse_financial_originals/frozen_replay/bse_financial_replay_audit.json)

通过模型行情输入条件的原缺口还剩 784 个证券日，涉及 28 家发行人。464 个原始候选保留逐件原因，主要是合并报表区段不明确、发行人身份页不可验证、会计口径无法确认、归母权益未可靠提取及资产负债表期末列不明确。执行过附件网络失败重试。附件无原件或附件不唯一累计 19 条。 [逐件缺口记录](../artifacts/cn_numeric_followup/bse_financial_originals/normalized_v2/bse_financial_originals_audit.json)

对早期身份未连接的记录继续核对正式上市文件。六家原件封面对应新三板旧证券代码，北交所发行主体经逐家确认。追加 25 个已核验版本，和前 467 个版本的证券及公开时间键互不重合。回放再补 652 个证券日的财务快照，其中 292 个满足预测输入条件。两批累计 492 个原件版本、8,192 个新快照证券日和 2,672 个有效输入日。 [新旧发行身份与生产回放](../artifacts/cn_numeric_followup/bse_financial_originals/residue/frozen/bse_financial_replay_audit.json)

第二批旧代码核验追加 13 家发行人的 49 份正式合并报表。真实网格回放再恢复 1,002 个财务快照证券日，其中 222 个为有效模型输入日。三批累计 541 份原件、9,194 个财务快照证券日及 2,894 个有效输入日。原定向有效输入范围余 270 个证券日。 [第二批旧代码原件回放](../artifacts/cn_numeric_followup/bse_financial_originals/residue/frozen_followup/bse_financial_replay_audit.json)

最后 9 家的 52 份原始正式报表保留了合并归属项目和少数股东权益或损益。三个报表标题省略了“合并”字样。逐件用所有权归属、报表数字勾稽和原件页码确认报表范围。独立回放新增 810 个快照证券日，其中 270 个满足行情输入条件。四批共 593 份原始报告，覆盖 114 家发行人，合计 10,004 个新快照证券日。定向范围的 3,164 个原有效输入缺口全部在真实回放中恢复。 [合并范围与原件回放](../artifacts/cn_numeric_followup/bse_financial_originals/residue/frozen_unprefixed/bse_financial_replay_audit.json)
