# 参考实现索引

## 金融后训练研究参考

2026-11-17：已筛选16项相关资源，见 [研究参考与适配建议](../docs/research_references.md)、[机器可读清单](research_catalog.json) 和 [GitHub提交元数据](research_revisions.json)。本轮未克隆额外仓库、下载权重或数据集、执行训练。已有 `karpo-decision/` 保留，作为原生接口与读出头参考；目录出现不代表已验证金融预测能力。

## 本地数据实现

初始化时仓库没有参考项目；未复制外部项目或数据库。

只读参考 `E:\quant`：

- `src/quant/data/schemas/catalog.py`、`config/official_api_schema.json`：88 个来源契约、字段说明、自然键。
- `data/storage/lake.py`：Raw/Canonical 版本链及 `parquet_sql`、`revision_sql`、`latest_sql`。盘点直接复用 SQL 生成函数。
- `data/pit/service.py`：先按可得时间过滤，再选择版本；后续适配时需固定 manifest。
- `data/adjustment/service.py`：原价×因子收益链，不能把展示前复权价直接作为历史特征。
- `data/universe/service.py`：生命周期、ST、停牌、历史成员校验；历史主数据仍有修订限制。
- `data/qlib_export/exporter.py`：分批 SQL 和逐证券导出；Qlib 缓存非独立来源。
- `factors/builtin/momentum.py`：带信息滞后的动量；未发现已发布因子时不可声称有因子数据。
- `risk/research_readiness.py`：按用途认证的概念可复用。现有 `Registry` 初始化会写库，盘点禁止调用。

`docs/legacy_assessment.md` 提及的 `E:\AI_quantization` 不在本轮指定范围，未据该文档宣称已检查旧数据或标签。
