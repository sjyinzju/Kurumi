# Kurumi 沪深北新闻与公告数据契约

## 数值锚点与实验条件

文本发布绑定 E:/QuantData/numeric/cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3，状态 NUMERIC_READY。数值发布清单 SHA-256 为 b5dedb67575a45fa2203a7bac4f11ad785c1e271c187cceb1eaba8f043336637，监督样本清单 SHA-256 为 5e2052486bd1cef072135aa26f4e23ae017616ee613be4e41184d9aec2b80b5f。构建逐个核实样本分片和身份映射哈希。样本从 2015-01-05 到 2026-06-30，采集请求从 2014-07-09 开始。

原包所有候选样本均有索引，训练继续使用 NumericDataset.iter_sample_ids 的监督清单。按 sample_id、instrument_id、issuer_id 和真实 asof_utc 绑定。1、5、20 日三题七选项、60 日窗口、标签、掩码和时间切分由原加载器提供。2026 年 7 月只用于数值标签兑现。默认沿用严格时点行业配置。行业关联使用历史分类版本及行业代码。使用训练扩展行业版本时需按相同配置重建受影响的文本选择，验证、校准和测试沿用严格版本。

| 研究组 | 收益训练输入 | 验证、校准和主测试 |
| --- | --- | --- |
| G0 | 无新闻和公告 | 新闻与公告 |
| GN | 新闻 | 新闻与公告 |
| GA | 公告 | 新闻与公告 |
| GNA | 新闻与公告 | 新闻与公告 |

G0 和 GNA 保留无文本评价诊断。训练及推理条件分别记录。G0 和未启用或缺正文的槽统一使用中性占位符。GN 与 GNA 的新闻片段相同，GA 与 GNA 的公告片段相同。所有分组复用监督样本和调用方的采样顺序。辅助训练如使用原文，须单独限制训练时间并按来源文档分组。基座记忆历史的风险继续沿用数值契约独立登记。

## 原件、公开时点和归属

按发布地解释可信时钟。巨潮原版 PDF 的归档日期需与索引公开日期一致。索引内为上海当地零点的公告时刻按日期精度处理。只知日期 D 时从上海 D+1 00:00 开始可用。上海证券报、中国证券报、证券时报、证券日报以原出版者固定版次的日期为依据。统计局使用原文章发布字段或版面时间。原件下载时刻独立记录。缺少有效公开时刻、归档一致性不足、正文冲突无法确定时间的记录留供审计。入样要求 available_at <= asof_utc。

按日验证来源证券代码与上市区间。用冻结历史表处理代码切换、北交所归档别名和退市历史。公司新闻要求正文中的历史简称或明确证券代码在同一段证据中承担动作主体。相同简称在同一天匹配多家时保留待解析。多公司报道按发行人分别保存证据引用，完整原文保持共享。统计局归为宏观背景。市场版和明确点出历史行业的报道可作为背景。单样本最多选一条背景新闻。明确是发行人原样披露的正文归入公告。媒体写作与分析保留在新闻。

以相对样本本地日的自然日差计算窗口。公司新闻差值为 0 至 6 日，行业、市场和宏观为 0 至 2 日，事件公告为 0 至 29 日，定期报告为 0 至 179 日。先过滤关联、窗口和公开时点，再选当时可见版本。同报告期的完整报告按同一版本组处理。单独发布的更正、补充、澄清和进展作为有单独时钟的公告保留。定期报告每样本最多一份，优先把预算留给事件公告。

## 清洗与原生输入

PDF 解析保留原页边界。HTML 保留原页面并提取正文。完整正文及哈希在语料层保存，相同正文按哈希共用存储引用。短文近重复在同发行人和接近的发布时间内比较正文重叠，并核对金额、比例、日期、否定、条件和事件状态的字面事实。保留数字间的表格边界。同一通道去掉已由当时可见文本完整覆盖的事实。跨通道重合只进入审计统计。正文噪音、程序性套话和重复页眉页脚从候选片段中清理。

同一证据保存完整原句、字符偏移和页码。定期报告优先保留可靠的币种、单位、期间与表格行，以及经营解释和公司变化。更正、补充、终止、进展与原事件只有在同发行人和同公告主题可核时链接。独立审阅从原文抽取主要会计行和披露事实，在同一文档与样本上对照原方案、保守方案和压缩方案。分档收益、未来波动和真实标签均不进入选文。

新闻和公告各有 1,024 个独立的 Karpo 原生 token 预算，计入标题、来源、公开时间、栏目标题与分隔。候选段落整段选取，保留条件和否定。构建时复核整段渲染的 token 数。三个期限共用一个数值与文本上下文。超出完整三题上下文时显式报错。数值模板的既有调用仍支持原占位符。

## 物理表

| 表 | 粒度和主要字段 |
| --- | --- |
| documents | 按发布年份分区。每行一个 doc_version_id，保存 doc_id、原生来源 ID、URL、原始时间、available_at、retrieved_at、精度、来源证据、raw_ref、raw_hash、body_hash、解析状态、版本组和重复关系。original_version_id 连接来源版本，body_owner_ref 连接共享正文。evidence_issuer_id 和 evidence_keys 绑定入模的公司事实。input_spans 保存原文半开字符区间与页码。event_thread 和 related_prior_event 保存已证实的公告主题关系。 |
| document_entities | 按文档公开年份分区。保存 doc_version_id、entity_type、entity_id、关系及匹配方法和历史映射版本。 |
| sample_text_index | 按样本月分区。保留全部原样本键、当日时钟及历史身份。news_refs 和 announcement_refs 指向具体正文版本及其固定 input_spans。分别记录两类 token 成本、状态和 selection_hash。 |
| coverage | 每个发生过的来源请求、归档版次或外部权限检查一行。包含 query_status、分页完成标志、返回数、正文成功数、缺正文、下载失败、解析失败、原因和收据路径。声明范围与实际观察到的公开日期分别保存。 |
| manifest.json | 固定数值包及监督清单、文本版本、源码和处理规则版本、Karpo 编码器及 tokenizer 哈希、来源范围、文件 SHA-256 和实验条件。 |

覆盖可证明且窗口内有合格文本时用 present，覆盖可证明且窗口内无合格文本时用 empty。采集范围尚有缺口但窗口内有可用文本时用 partial，无可用文本且来源建设不足时用 unavailable。查询返回零条和分片失败分别留在 coverage 中。样本缺源、解析和下载状态仅出现在审计字段。验收以最终入模并匹配样本发行人的证据为准，按原监督清单及各 split 固定分母分别计算。采集目录的独立原件分母和未取得分区单独报告。发布结果见 acceptance.json。

包内外的原件和正文有哈希可核。新取原件按内容哈希放在 capture/raw，内部源按原归档路径只读引用。行业、宏观、同季报告和转载都通过引用复用。真实源正文用于本地研究，发布代码和小型说明时保留供应方与原出版方的使用条款。

## 复现与训练接入

从独立工作树执行。以下 PowerShell 使用本机已有的 Karpo 源码、tokenizer 和依赖目录。其他环境可安装文本 extra，再按数值项目的 Karpo 说明接入固定提交与编码资产。第二轮的实际采集、发布和验收命令见当轮报告。下方保留第一轮采集范围。

~~~powershell
$taskText = 'E:/Kurumi/artifacts/cn-text'
$anchorText = 'E:/QuantData/numeric/cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3'
$karpoText = 'E:/Kurumi/artifacts/karpo-b8e6fd7'
$env:PYTHONPATH = "$PWD/src;$taskText/runtime;E:/quant/.venv/Lib/site-packages;E:/Kurumi/artifacts/karpo-runtime;E:/Kurumi/reference/karpo-decision/src"
$env:TOKENIZERS_PARALLELISM = 'false'
$env:OMP_NUM_THREADS = '1'
$collectText = @('--capture', "$taskText/capture", '--start', '2014-07-09', '--end', '2026-06-30')

python -m kurumi.cn_text_sources NBS @collectText --workers 2 --interval 0.4
python -m kurumi.cn_text_sources CNSTOCK-paper @collectText --dates "$taskText/capture/paper-target-editions.txt"
python -m kurumi.cn_text_sources CNSTOCK-paper @collectText --dates "$taskText/capture/paper-target-more-company.txt" --sections '[:：·]\s*(?:公司|上市公司)(?:\s|$|[·／/])'
foreach ($keywordText in @('控制权变更', '重大合同', '终止上市决定', '业绩快报修正')) {
    python -m kurumi.cn_text_sources CNINFO @collectText --search $keywordText --workers 2 --interval 0.25
}
python -m kurumi.cn_text_sources CNINFO --capture "$taskText/capture" --start 2024-04-19 --end 2024-04-19 --exchange BSE --body-title '业绩快报|业绩预告|重大合同|更正|进展|回购|变更|延期|取消|终止' --max-pdf-kib 900
python -m kurumi.cn_text_index --numeric $anchorText --capture "$taskText/capture" --tokenizer $karpoText --output "$taskText/releases" --cache "$taskText/processing-cache" --project 'E:/Kurumi' --external-sources 'E:/QuantData/numeric/.build-cn/sources' --prior-text 'E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/issuer_reports_pit/issuer_reports_pit.parquet' --source-audit "$taskText/source_audit.json"
~~~

巨潮按月查询，遇到分页上限再拆日期。全类别极忙的单日可以传入固定包的 reference/security_history.parquet 作为 --security-history，继续按当时证券代码收集。源索引分页及正文下载分别保留断点。正文字段的权限和官方 ZIP 可由 scripts/probe_cn_text_entitlements.py 复核。报纸两份日期文件根据原样本月份内实际交易日顺序选取中位日以及四分之一与四分之三位置的日子，所选日期与版块留在采集目录。

完成构建后将命令打印的发布目录作为 text_directory。验收脚本含文件核验、逐月样本键与关系核验、全量时点和独立 token 预算检查、原件抽查与 CPU 原生短测。

~~~powershell
$textDirectory = 'E:/Kurumi/artifacts/cn-text/releases/cn-text-1f2b38f551c412f36cdb6f36'
python scripts/verify_cn_text.py --numeric $anchorText --text $textDirectory --tokenizer $karpoText --output "$taskText/verified.json" --cache "$taskText/verification-cache"
~~~

~~~python
from kurumi.encoding_cache import EncodingCache
from kurumi.karpo_numeric import KarpoNumericEncoder, packed_logits
from kurumi.text_dataset import NumericTextDataset

data = NumericTextDataset(numeric_directory, text_directory)
encoder = KarpoNumericEncoder.from_checkpoint(tokenizer_directory)
cache = EncodingCache(cache_directory, touch_interval_seconds=60)
batch = data.load_research_batch(sample_ids, group="GN", phase="train")
plans = data.plan_batch(encoder, batch, cache=cache)
logits = packed_logits(plans, packed_backbone, backbone, readout, device)
labels, mask = batch.supervision.as_torch(device)
~~~

可用 iter_sample_ids 从原监督清单取样，再按研究所选时间和共享顺序组成批次。NumericTextDataset 按月份读取样本引用，按年份批取正文片段并复用进程内缓存。确定性选段按内容和规则版本缓存。训练可按实测 token 长度组批，交给原生 pack 无 padding 打包。磁盘编码缓存键包括真实渲染请求、数值和文本版本、分组、模板、原生编码器、tokenizer、长度、运行库和序列化格式。选文和序列化在 CPU 上验证相同 Readout、mask 和标签。训练使用 Packed 与 Readout 正向和反向，参数变化后重新计算受影响模型状态。

## 后续数值包迁移

样本键及其证券、发行人、截点和行业规则继续一致时，在明确核对优化包后传入 TextIndexMigration()，使用原索引稳定键连接。数值包保留子集时复用同一方式逐批连接。样本键变化时提供 TextIndexMigration(old_sample_id_by_new_id=...) 的显式新到旧映射。加载时验证实际证券、发行人、截点和历史行业。因输入截点或选文规则变化的样本需要重建对应索引。原件、正规正文和无关样本引用可继续复用。完整编码缓存由当前数值版本及请求内容决定，模板或数值内容有变化时使用新键。
