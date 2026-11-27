# Kurumi 新闻与公告第二轮发布

## 交付结果

发布 cn-text-ecb74813f733f84b62389770，状态 PARTIAL_RESEARCH_READY，生产代码提交为 5434a4245017。文件清单共 950,571,193 字节，含 11,618,610 条原样本索引及 60,000 条可用于构造输入的证据版本。按四个 split 与全部监督样本严格核验后，公司事实覆盖为 **14.43%**，距 80% 还缺 **6,793,608** 个合格样本。新闻与公告目录均有未对账日期，采集目标未通过。原生训练加载验收通过。 [发布清单](<E:/Kurumi/artifacts/cn-text/round2/releases/cn-text-ecb74813f733f84b62389770/manifest.json>) · [计算后的验收门槛](<E:/Kurumi/artifacts/cn-text/round2/releases/cn-text-ecb74813f733f84b62389770/acceptance.json>) · [仓库轻量统计](cn_text_round2_stats.json)

| 监督分组 | 固定分母 | 上轮公司事实 | 本轮公司事实 | 本轮覆盖 | 距 80% 缺口 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 总体 | 10,360,981 | 230,117 | 1,495,177 | 14.43% | 6,793,608 |
| 训练 | 7,209,690 | 129,929 | 1,324,676 | 18.37% | 4,443,076 |
| 验证 | 608,311 | 15,765 | 29,957 | 4.92% | 456,692 |
| 校准 | 651,003 | 25,014 | 39,676 | 6.09% | 481,127 |
| 测试 | 1,891,977 | 59,409 | 100,868 | 5.33% | 1,412,714 |

## 覆盖与原件验收

| 监督样本指标 | 数量 | 比例 |
| --- | ---: | ---: |
| 公司新闻 | 36,050 | 0.35% |
| 公司公告 | 1,467,052 | 14.16% |
| 新闻与公告同时存在 | 7,925 | 0.08% |
| 仅背景 | 1,719,642 | 16.60% |
| 含定期报告 | 1,363,387 | 13.16% |
| 含事件公告 | 151,549 | 1.46% |
| 含定期报告且无事件公告 | 1,315,503 | 12.70% |
| 含事件公告且无定期报告 | 103,665 | 1.00% |
| 新闻槽无正文且来源不完整 | 8,047,354 | 77.67% |
| 公告槽无正文且来源不完整 | 8,893,929 | 85.84% |
| 两个通道均无入模片段 | 7,146,162 | 68.97% |
| 声明检索已证实完整且无公司事件 | 0 | 0.00% |
| 新闻公告含相同规范化字面事实 | 0 | 0.00% |

扩源后在旧版未覆盖的母集中新增有效公司事实 1,265,060 条，旧版有而本轮未入选 0 条。有 1,182,228 个样本实际选入去重后新增原件。年份、交易所、历史退市、当时风险警示、行业及 split 的完整分层，以及最终引用按年龄逐日计数，保存在仓库统计与本机覆盖审计。 [覆盖审计](<E:/Kurumi/artifacts/cn-text/round2/releases/cn-text-ecb74813f733f84b62389770/coverage-audit.json>)

| 来源 | 新增去重正文 | 新增可解析正文最早与最晚公开日 | 有该来源新增原件的入模样本 |
| --- | ---: | --- | ---: |
| CNINFO · 公告 | 27,148 | 2014-07-15 至 2026-03-20 | 1,159,692 |
| CNSTOCK-paper · 公告 | 86 | 2015-01-07 至 2021-01-07 | 253 |
| CNSTOCK-paper · 新闻 | 18,937 | 2014-07-09 至 2026-02-13 | 12,888 |
| CS-paper · 公告 | 88 | 2016-01-08 至 2024-02-02 | 917 |
| CS-paper · 新闻 | 5,744 | 2015-01-05 至 2024-02-02 | 5,808 |
| CSMAR-CAIN · 新闻 | 0 | — 至 — | 0 |
| NBS · 新闻 | 0 | — 至 — | 0 |
| STCN-paper · 公告 | 2 | 2015-11-13 至 2016-01-08 | 13 |
| STCN-paper · 新闻 | 1,603 | 2014-12-30 至 2016-07-20 | 1,249 |
| Sina-original-filings · 公告 | 2 | 2025-04-28 至 2025-10-30 | 0 |
| ZQRB-paper · 公告 | 10 | 2021-02-08 至 2022-01-20 | 92 |
| ZQRB-paper · 新闻 | 5,134 | 2020-01-02 至 2026-04-13 | 9,018 |

| 声明目录 | 自然日 | 已对账 | 失败或未完整 | 未取得分区 |
| --- | ---: | ---: | ---: | ---: |
| CNSTOCK-paper | 4,201 | 827 | 263 | 3,111 |
| STCN-paper | 2,924 | 240 | 2,684 | 0 |
| CS-paper | 4,201 | 251 | 152 | 3,798 |
| ZQRB-paper | 2,373 | 546 | 179 | 1,648 |
| CNINFO · SSE | 4,375 | 459 | 33 | 3,883 |
| CNINFO · SZSE | 4,375 | 447 | 9 | 3,919 |
| CNINFO · BSE | 1,689 | 155 | 0 | 1,534 |

| 已观测唯一目录 | 已知条目 | 原件取得 | 通过解析、时点和关联 | 下载失败 | 解析失败 | 时点待核 | 关联待核 | 无正文尝试记录 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 公告 | 461,688 | 28,537（6.18%） | 25,981（5.63%） | 25（0.01%） | 398（0.09%） | 0（0.00%） | 2,158（0.47%） | 433,126（93.81%） |
| 新闻 | 31,464 | 29,792（94.69%） | 14,106（44.83%） | 1,480（4.70%） | 867（2.76%） | 0（0.00%） | 14,819（47.10%） | 192（0.61%） |

巨潮已观测目录合并全类别分区与已实际取得的分类目录，按原始 ID 及可确认的原件重复归并。未取得分区的总原件数未知。两类的 80% 验收均为未通过。表内未采集、下载、解析和关联原因依据目录行，无法从未覆盖日期判定某个样本确实没有事件。供应方权限受限另见来源探测记录。拒绝访问的供应方缺少可对账目录，其文档总数与关联到样本的比例未知。

| 入模事实类别 | 年龄 P50 / P90 / P99，自然日 |
| --- | --- |
| 公司新闻 | 4 / 6 / 6 |
| 事件公告 | 15 / 27 / 29 |
| 定期报告 | 87 / 161 / 178 |

## 主要分层

| 分层 | 分组 | 监督样本 | 上轮覆盖 | 本轮覆盖 |
| --- | --- | ---: | ---: | ---: |
| 交易所 | BSE | 217,032 | 49.96% | 83.39% |
| 交易所 | SSE | 4,368,676 | 0.86% | 16.78% |
| 交易所 | SZSE | 5,775,273 | 1.46% | 10.06% |
| 上市历史 | 锚点内历史退市证券 | 334,848 | 1.98% | 20.26% |
| 上市历史 | 锚点内未退市证券 | 10,026,133 | 2.23% | 14.24% |
| 当日风险状态 | 正常 | 10,130,679 | 2.24% | 14.55% |
| 当日风险状态 | 风险警示 | 230,302 | 1.31% | 9.37% |
| 年份 | 2015 | 269,271 | 1.48% | 78.51% |
| 年份 | 2016 | 513,582 | 1.50% | 76.32% |
| 年份 | 2017 | 626,014 | 1.59% | 37.35% |
| 年份 | 2018 | 734,420 | 1.54% | 1.93% |
| 年份 | 2019 | 840,652 | 1.39% | 1.70% |
| 年份 | 2020 | 891,212 | 1.52% | 10.14% |
| 年份 | 2021 | 1,000,246 | 1.37% | 9.36% |
| 年份 | 2022 | 1,119,877 | 1.97% | 11.61% |
| 年份 | 2023 | 1,214,416 | 2.97% | 11.94% |
| 年份 | 2024 | 1,259,314 | 3.24% | 5.53% |
| 年份 | 2025 | 1,277,242 | 3.33% | 5.49% |
| 年份 | 2026 | 614,735 | 2.75% | 5.00% |
| 行业 | 未知 | 3,451,184 | 4.25% | 24.64% |
| 行业 | SW2021 / 801890.SI | 443,869 | 1.00% | 3.35% |
| 行业 | SW2021 / 801150.SI | 403,708 | 0.51% | 2.63% |
| 行业 | SW2014 / 801890.SI | 389,303 | 1.97% | 20.98% |
| 行业 | SW2021 / 801080.SI | 387,335 | 0.57% | 3.13% |
| 行业 | SW2021 / 801030.SI | 338,493 | 0.69% | 3.32% |

行业列出监督样本最多的六组，名称对应历史分类版本和行业编码。全部行业分层保存在统计文件。

## 同语料的质量与 CPU 对比

用种子 28339 选取新闻 100 对、公告 100 对，逐对读取原件并核对原始哈希。三方案使用同一原文和样本。关键事实来自独立的原文规则审阅，覆盖主要报告表行及完整的披露句。训练期另对 7 份原件作定向复查，断行片段、复述市值、并列主体误入以及带币种表行的检查均按预期通过。完整逐对记录包含原件哈希和实际选文结果。 [证据对比](<E:/Kurumi/artifacts/cn-text/round2/releases/cn-text-ecb74813f733f84b62389770/evidence-comparison.json>)

| 模态 · 方案 | 保留关键事实 | 每千边际原生 token 的事实数 | 可识别重复、无效 token 占比 | 边际原生 token P50 / P90 / P99 |
| --- | ---: | ---: | ---: | --- |
| 公告 · 再压缩 | 85/169（50.30%） | 4.77 | 0.00% | 206 / 246 / 282 |
| 新闻 · 再压缩 | 72/139（51.80%） | 7.72 | 0.00% | 84 / 222 / 247 |
| 公告 · 保守 | 104/169（61.54%） | 3.44 | 0.27% | 378 / 406 / 601 |
| 新闻 · 保守 | 73/139（52.52%） | 6.89 | 0.00% | 84 / 282 / 420 |
| 公告 · 原方案 | 40/169（23.67%） | 0.73 | 4.47% | 388 / 877 / 889 |
| 新闻 · 原方案 | 128/139（92.09%） | 1.64 | 15.81% | 864 / 879 / 896 |

保守方案用于本次发布。保留率按原文锚点未出现的个数计缺失。噪声占比仅统计独立规则能识别的模板、重复句和其他主体，细小改写及全部事实单位错误尚无完整标注。新闻遗漏 66 个独立锚点，公告遗漏 65 个独立锚点，各自的保留率均低于 95%。新闻和公告每千边际原生 token 的事实密度分别较原方案提高 319.0% 和 371.8%。显性噪声相对下降 100.0% 和 93.9%，这项统计仅适用于指定检测口径。

固定 781 个真实监督样本的读取耗时 12.62 秒，进程读取 7.00 GiB。冷原生编码 4.48 秒，174.4 样本/秒。计划热读取和反序列化取三次中位数，JSON 为 1.470 秒，二进制为 0.346 秒，吞吐为 531.1 与 2258.3 样本/秒（4.25 倍）。峰值进程工作集 4.08 GiB。完整输入 P50/P90/P99 为 7806/8422/8765 token。缓存回放等价。正式 31B 训练时长和收益准确率待实测。

全量核验覆盖 11,618,610 条索引和 78,966 种原生通道组合，并逐个校验 55,276 个入模原件定位的 SHA-256。实际 CPU Readout 形状为 4 × 3 × 7，可用轻量层反传。98 项仓库测试通过，Windows 运行使用较短的测试临时根目录。 [原生验收](<E:/Kurumi/artifacts/cn-text/round2/releases/cn-text-ecb74813f733f84b62389770/verify.json>)

## 固定比较基线

沿用原始沪深北数值包 `cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3`。本机核对了 4,137,510,674 字节、11,618,610 个候选样本及 10,360,981 个有监督样本。数值清单 SHA-256 为 `b5dedb67575a45fa2203a7bac4f11ad785c1e271c187cceb1eaba8f043336637`，监督清单为 `5e2052486bd1cef072135aa26f4e23ae017616ee613be4e41184d9aec2b80b5f`。结构化优化 V2 和 V3 的监督母集为 10,376,684。本轮按原数值版本建立索引，迁移时仍使用现有显式映射和逐批身份核验。

公司新闻、背景、事件公告和定期报告保留原 7、3、30、180 自然日窗口。可信精确时钟及日期精度公告分别按原规则核对。旧版覆盖重新核对已入模片段中的发行人事实。旧报告中只按引用计的覆盖与这里的严格重算含义不同。标签、历史股票池、60 日数值输入和四个 split 保持原版本的定义。

## 来源范围与限制

- 巨潮全类别目录的声明范围是 2014-07-09 至 2026-06-30。北交所从 2021-11-15 纳入分区验收。按市场和自然日期对账，分区溢出时拆分。2024-04-23 的升页实测中，沪、深、北三路设置 100 或 200 仍只返回 30 条，第二页重复第一页。采集保留 30 条页长，并记录无法对账的分区。正文优先取第一、三季报及已有目录中的业绩、经营、控制权和风险公告。未取得的正文保留在缺口里。 [巨潮目录](https://www.cninfo.com.cn/new/commonUrl?url=disclosure%2Flist%2Fnotice)
- 上海证券报与中国证券报从 2014-12-30 起按自然日取相关版面。证券时报旧档从同日声明到 2022-12-31，证券日报从 2020-01-01 声明到 2026-06-30。其余两个来源结束于 2026-06-30。目录已识别的报道去重纳入应采分母。404、405、版次导航缺失和分页失败单列。尚未对账的日数与已知唯一目录条目分别报告。 [上海证券报](https://paper.cnstock.com/) · [中国证券报历史版次](https://epaper.cs.com.cn/zgzqb/html/2015-01/05/nbs.D110000zgzqb_A01.htm) · [证券时报历史版次](https://epaper.stcn.com/paper/zqsb/html/2015-01/05/node_2.htm) · [证券日报版次](https://epaper.zqrb.cn/html/2026-05/27/node_1232.htm)
- BigQuant 登录、行情对照和配额查询成功。公告目录、专题公告和快讯最小字段查询返回 `FlightUnauthorizedError`。当时周配额为 5,000 万，已用 7,911,979。部分正文候选表的元数据未解析。CSMAR 三个日期的实测只返回新闻元数据，其中上轮正式 ZIP 同样不含正文。本轮也核对了 CSMAR 公告目录和 AI 新闻情绪表的字段。CNRDS、慧科和 TuShare 继续沿用已有访问结果。FinCorpus 的 60 条真实样本只有正文和来源分类，原始版本及公开时点未得到独立核对。 [可核对的探测记录](cn_text_round2_source_probes.json) · [BigQuant SDK](https://v6.bigquant.com/wiki/doc/vac4qwmQr4) · [FinCorpus](https://huggingface.co/datasets/Duxiaoman-DI/FinCorpus)
- 对 12 份初次解析失败的真实公告做了定向检查。8 份检查范围内没有符合条件的扫描页，4 份由 Tesseract 5.4.0 试取到字符。数字、单位及表格边界仍需独立复核。OCR 结果没有进入输入。 [官方简体中文识别模型](https://github.com/tesseract-ocr/tessdata_fast)

## 选文与训练

新闻以段内动作主体绑定历史发行人，多主体稿件共用一份原文并分别索引片段。公告保留原发行人代码、表格单位与期间、否定、修正和条件。原文偏移与页码可追溯。相同事实在同通道已完整覆盖时去重，跨通道相同事实保留审计。更正、补充、终止和进展在可匹配同主体及同主题时记录较早公告。分开控制新闻和公告的原生 token 预算，GN 与 GNA 保持相同新闻，GA 与 GNA 保持相同公告。

训练继续通过 `NumericTextDataset.load_research_batch` 和 `plan_batch` 进入原生 Karpo。编码计划以只含文本张量的二进制序列保存，旧 JSON 解码兼容保留，缓存键带格式版本。交付分支的选文缓存键另记录规范正文摘要，应对相同原件的不同上游提取版本。冷编码及磁盘热读取在相同样本上比较，断言 token ID、位置、分段和原生标记一致。原时间切分、监督掩码、三期限七选项及 Readout 都保留。CPU 短测用轻量层验证了反传。

## 复现

下列命令从仓库工作树执行。发布验收时替换 `$release` 为构建命令打印的实际不可变目录。依赖版本、tokenizer 和实现哈希记录在该目录的 manifest；同一捕获目录可以按已保存分区续传。

~~~powershell
$base = 'E:/Kurumi/artifacts/cn-text'
$round = "$base/round2"
$anchor = 'E:/QuantData/numeric/cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3'
$tokenizer = 'E:/Kurumi/artifacts/karpo-b8e6fd7'
$python = 'E:/quant/.venv/Scripts/python.exe'
$env:PYTHONPATH = "$PWD/src;$base/runtime;E:/quant/.venv/Lib/site-packages;E:/Kurumi/artifacts/karpo-runtime;E:/Kurumi/artifacts/efficiency-runtime;E:/Kurumi/reference/karpo-decision/src"
$archive = @('--capture', "$round/capture", '--prior-capture', "$base/capture")

& $python -m kurumi.cn_text_sources CNINFO @archive --start 2014-07-09 --end 2026-06-30 --parallel-scopes 5 --interval .27 --interleave-years --skip-bodies
& $python -m kurumi.cn_text_sources CNINFO @archive --start 2014-07-09 --end 2026-06-30 --category 'category_yjdbg_szsh;category_sjdbg_szsh;' --body-title '(?:第一季度|第三季度|一季度|三季度|一季|三季)报' --security-history "$anchor/reference/security_history.parquet" --parallel-scopes 7 --workers 2 --interval .21
& $python -m kurumi.cn_text_sources CNINFO @archive --start 2014-07-09 --end 2026-06-30 --directory-bodies --parallel-scopes 5 --workers 2 --interval .63
& $python -m kurumi.cn_text_sources CNSTOCK-paper @archive --start 2014-07-09 --end 2026-06-30 --parallel-scopes 7 --workers 2 --interval .23
& $python -m kurumi.cn_text_sources STCN-paper @archive --start 2014-12-29 --end 2022-12-31 --parallel-scopes 6 --workers 2 --interval .22 --interleave-years
& $python -m kurumi.cn_text_sources CS-paper @archive --start 2014-12-30 --end 2026-06-30 --parallel-scopes 6 --workers 2 --interval .35 --interleave-years
& $python -m kurumi.cn_text_sources ZQRB-paper @archive --start 2020-01-01 --end 2026-06-30 --parallel-scopes 6 --workers 2 --interval .36 --interleave-years

Copy-Item -LiteralPath 'docs/cn_text_round2_source_probes.json' -Destination "$round/source-audit.json"
& $python -m kurumi.cn_text_index --numeric $anchor @archive --output "$round/releases" --cache "$round/processing-cache" --prior-cache "$base/processing-cache" --tokenizer $tokenizer --project 'E:/Kurumi' --external-sources 'E:/QuantData/numeric/.build-cn/sources' --prior-text 'E:/Kurumi/artifacts/cn_numeric_followup/expanded-sources-20261125/issuer_reports_pit/issuer_reports_pit.parquet' --source-audit "$round/source-audit.json" --profile conservative

$baseline = "$base/releases/cn-text-1f2b38f551c412f36cdb6f36"
& $python scripts/verify_cn_text.py --numeric $anchor --text $release --tokenizer $tokenizer --output "$release/verify.json" --cache "$round/temporary/native"
& $python scripts/audit_cn_text_coverage.py --numeric $anchor --text $release --baseline $baseline --output "$release/coverage-audit.json" --cache "$round/temporary/coverage"
& $python scripts/compare_cn_text_evidence.py --numeric $anchor --text $release --tokenizer $tokenizer --output "$release/evidence-comparison.json" --cache "$round/temporary/comparison"
& $python scripts/accept_cn_text_round2.py --text $release --coverage "$release/coverage-audit.json" --comparison "$release/evidence-comparison.json" --native "$release/verify.json" --output "$release/acceptance.json"
~~~

出刊前置与完整采集范围分开计数。较新年份的巨潮和上海证券报另有较慢并行队列，用 `--interleave-years` 从 2020-03-01 和 2017-01-01 起推进。全量验收使用实际发布快照，快照以后到达的原件可在续传重建时纳入。

## 剩余缺口与清理

捕获断点保留 27,689 个独立 PDF 字节对象，共 13.09 GiB。停止采集时 E 盘剩余 11.37 GiB。连续季报和报纸目录在公开接口条件下仍有多年份缺口。优先补齐需要能批量导出的公告全文及完整公司新闻目录，并保留原始 ID、公开时点、有效版本与稳定证券归属。现有公开采集命令支持从已落盘分区续接，新闻需补主体跨段证据并独立复核缺失锚点。

已核对路径并清除 16 个本任务临时位置，其中有 6,276 个文件留有逐文件计数。正式语料、原件、回执、发布清单、复用处理缓存及精简验收记录位于 E 盘。Git 交付生产代码、契约和轻量汇总。
