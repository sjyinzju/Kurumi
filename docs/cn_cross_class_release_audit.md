# CN 跨股类估值与标签独立验收

实际发布版本 `cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c` 的 Manifest 绑定了 640,659 行兄弟股类报价以及汇率输入和发行人股类版本。股票日表包含 124 只 A 股的 164,057 个可用跨股类发行人估值，其中沪市 97 只、136,682 行，深市 27 只、27,375 行。全量 164,057 行的股本来源均可解析到样本时点前公开的原件记录。 [机器可读跨股类验收](E:/Kurumi/artifacts/cn_numeric_followup/capital/v5_class_crosscheck/class_release_crosscheck_cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c.json)

| A 股 | 兄弟股类 | 已发布发行人估值行数 | 第一日 | 最后一日 |
|---|---|---:|---|---|
| 600958.SH 东方证券 | 03958.HK | 2,001 | 2018-01-02 | 2026-07-31 |
| 600999.SH 招商证券 | 06099.HK | 2,192 | 2017-03-30 | 2026-07-31 |
| 000418.SZ 小天鹅 A | 200418.SZ | 1,026 | 2015-01-05 | 2019-05-07 |
| 000613.SZ 大东海 A | 200613.SZ | 1,652 | 2015-01-05 | 2022-06-28 |
| 600190.SH 锦州港 | 900952.SH | 2,497 | 2015-01-05 | 2025-07-18 |
| 600555.SH 海航创新 | 900955.SH | 1,681 | 2015-01-05 | 2022-07-06 |
| 600680.SH 上海普天 | 900930.SH | 805 | 2015-01-05 | 2018-04-27 |

七家各抽取首末两个实际同日报价值，共 14 行。逐行用 A 股与兄弟股类的实际未复权收盘分别乘股数，再用当时可得的港元或美元汇率换算成人民币并相加。另行核对 A 股股类市值。东方证券第一行复算约 901.26 亿元，招商证券第一行约 1,039.88 亿元。五个 B 股摘牌日及以后无跨股类估值。7 月末日期属于股票日表观测范围。 [券商 12 份原件](E:/Kurumi/artifacts/cn_numeric_followup/capital/v5_class_crosscheck/ah_broker_original_class_amounts.json) · [五家退市材料](E:/Kurumi/docs/cn_retired_b_siblings_audit.md)

重新取得四个公开兄弟股类源响应，其中 8,055 条日期、实际收盘和成交量均与冻结时留存的提取记录一致。新响应保留自己的字节哈希。其余三个已退市 B 股的同址请求各遇到两次代理连接错误，复算使用已留存的实际日线提取记录及冻结时登记的响应哈希。汇率复算直接读取有原始捕获哈希的 3,058 行 CSMAR 档案。[重新取得报价的请求回执](E:/Kurumi/artifacts/cn_numeric_followup/capital/v5_class_crosscheck/raw_quote_reacquisition_audit.json) · [三条同址重试](E:/Kurumi/artifacts/cn_numeric_followup/capital/v5_class_crosscheck/raw_quote_reacquisition_retry.json)

相对 V4，全量 34,855,830 条标签的键和物理行序一致。17,279 条更新了目标来源标识，其中 13,586 条仅更新简称来源，3,595 条同时更新简称及价格限制来源，98 条仅更新价格限制来源。5,800 对对应的原始来历标识均已解析。实际收益、目标日期、标准化收益、分档、监督掩码、无效原因及其他字段逐项一致。 [全量标签逐字段核验](E:/Kurumi/artifacts/cn_numeric_followup/label_release_diff_cn-e22d9ca02b9d2602eb7e095e9b1e1330452ce6109437f673a08d924f50aced9c.json)

验收入口为 `scripts/audit_cn_class_release.py --help` 和 `scripts/audit_cn_label_release_diff.py --help`。前者按发布 Manifest 校验冻结来源文件，读取原始汇率捕获、已注册日线批次和公告 PDF。两项均可对已发布版本单线程复验。
