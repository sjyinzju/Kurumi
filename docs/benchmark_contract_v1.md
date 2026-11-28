# Kurumi 外部 benchmark 测评契约 v1

日期：2026-11-25。协议标识：kurumi-external-bench-v1。

## 1. 目标与范围

本轮在已经准备好环境与模型的 GB10 个人目录内，使用未做金融后训练的 MachinePulseAI/karpo-decision-31B 原模型 M0，完成四项冻结 benchmark 的下载、适配、全量推理、评分和结果保存。全部通过后自动进入下一阶段，不在准备完成或少量 smoke 后结束。

本协议不修改 Kurumi 现有 A 股数值契约，不启动 M1/M2/M3 训练，不重建新闻公告数据，不把 A 股数值包 NUMERIC_READY 作为外部 benchmark 的运行条件。后续模型沿用相同测试输入和评分口径，以独立 run 保存结果。

| benchmark_id | 固定来源 | 范围 | 规模 |
| --- | --- | --- | ---: |
| finben_bigdata | TheFinAI/en-sm-bigdata | 官方 test | 1472 |
| finben_acl | TheFinAI/en-sm-acl | 官方 test | 3720 |
| alphafin_test | AlphaFin/AlphaFin-dataset-v1 | test/1000_report_marketdata.json | 1000 |
| pi_round2_full | PI Trading Arena Round 2 | full 输入，pick>=0.5 官方策略 | 90 场景、2070 问题 |

本轮固定为外部零样本评测，不使用这些 benchmark 的训练/验证样本作 few-shot，不根据 test 调模板、温度、交易阈值或选择 checkpoint。最终有 6192 条方向预测和 90 个完整 PI 回答。

首次正式推理前完成必要工程修正并冻结协议。冻结后改变样本、问题、选项顺序、标签或评分含义时，必须另记协议版本并重跑受影响的基线；不覆盖旧结果。路径调整、报告格式和不改变输入输出含义的执行修复只记录代码/运行版本。

## 2. 目录与配置

仓库内保留：本契约、configs/benchmarks/v1.toml、sources.v1.lock.json、runtime.local.example.toml、src/kurumi/benchmark_adapters.py、最小运行/评分入口及小型结果摘要。

机器配置复制为 configs/benchmarks/runtime.local.toml。Codex 根据已存在的 GB10 工作区填写 repository_root、python_executable、model_dir、data_root、run_root 五个绝对路径。真实目录优先于任何示例名称；不另建第二套环境或复制模型。

同一本机配置的 model 段记录当前运行的 key、repo_id 和 checkpoint_role；本轮是 karpo-m0/original_unmodified。该身份与实际 checkpoint 进入 run_manifest，但不改变公共数据/评分协议。后续版本使用新的 model.key 和输出目录；PI 的 answers 文件名也由当前 model.key 派生，不把 M0 名称硬编码进通用执行器。

建议数据根为个人研究目录的 data/benchmarks/v1，结果根为 runs/benchmarks/v1。它们优先位于 Git 仓库外。现有模型、缓存、环境位置保持不变。只向 .gitignore 追加确实需要的本机配置和结果目录条目，不覆盖原有忽略规则。

代码优先复用仓库和已安装 karpo_decision。现有 karpo_numeric.py 的固定三题七分类封装不适合外部任务。需要时只新增一个薄的 scripts/run_benchmarks.py，完成下载、准备、检查、运行和评分；不新建 Web 服务、插件注册系统或作业数据库。

## 3. 原始数据下载与冻结

### 3.1 Hugging Face

以 sources.v1.lock.json 中的 repo_id、repo_type、完整 revision 和精确 file 下载。使用 hf_hub_download 的 revision 与 filename 参数，或者等价的已安装工具。两个 FinBen 只下载指定 test 分片，AlphaFin 只下载指定 JSON；不下载训练集和 AlphaFin 大型回测数据库。

两个 FinBen 文件需要已获准访问的 Hugging Face 账户。使用现有安全凭据；不把令牌写入仓库、命令日志或报告。不经授权绕过 gate，不改用镜像/旧版替代。实际返回 401/403 时，保留已完成材料并报告具体仓库和所需授权。

FinBen 的初始 sha256 为 null，表示尚未完成授权下载后的逐字节校验。成功下载后计算真实 SHA256，核验原文件大小、行数和必需字段，再填入锁文件并将 sha256_status 记为 verified_download。只有两项都补齐后才能冻结本轮正式协议。revision 和相对文件路径保持原值，不以更新 hash 的方式接受另一个文件。

### 3.2 PI

在云端下载官方 Round 2 ZIP，保存原始字节和实际下载日期、URL、SHA256。解压后强制核验题目、行情与 arena/simulate.py 三个核心文件的哈希。只允许在个人目录内安全解压相对路径。

ZIP 可能因追加其他模型缓存而变化；当三个核心哈希均保持一致时，记录实际 ZIP 哈希即可，无须更换协议。任一核心文件变化时，优先复用已有相同哈希快照；没有匹配快照则报告阻塞，不自动修改科学配置或锁文件。

模型读取 full/decision_points.jsonl 的 state 和 questions。完整未来行情、已有 answers、summary、事后最优路径只供离线评分和参考比较，绝不进入模型 payload。

### 3.3 原始与 prepared 文件

每个 benchmark 目录保存：

| 相对路径 | 内容 |
| --- | --- |
| raw/ | 原始文件，下载后不修改 |
| prepared/requests.jsonl | 每行 sample_id、request、metadata |
| prepared/labels.parquet | 三个方向任务的真值；PI 不伪造分类标签 |
| manifest.json | 来源版本、原文件与 prepared 哈希、行数、字段和检查结果 |

使用 Python/Arrow 原生值读取 Parquet，例如 pyarrow 的 to_pylist，避免将 numpy 标量或字符串形式的列表直接传入适配器。原始数据顺序保持不变；sample_id 是 benchmark_id:source_row_index，唯一身份由数据快照版本和 sample_id 共同确定。

请求哈希基于实际发给模型的 UTF-8 JSON：ensure_ascii=False、separators=(",", ":")、allow_nan=False。保留字典插入顺序，不排序 questions/criteria 后再传模型；不同选项顺序不能共享请求缓存。

## 4. 数据适配器与接口

适配器模块只做纯 CPU 的结构转换和回答校验，无下载、训练、模型加载或交易评分副作用。

接口如下：

    prepare_finben(row, benchmark_id, source_index) -> (prepared, label)
    prepare_alphafin(row, source_index) -> (prepared, label)
    prepare_pi(row) -> (prepared, None)
    normalize_direction(prepared, response) -> prediction
    validate_pi_answers(prepared, response) -> response

prepared 包含 sample_id、request、metadata。传给 Decider 的参数只能是 prepared["request"]，不能把 metadata、label 或完整原始行一起发送。原始标签可以与输入并存于 CPU 数据准备阶段；禁止进入实际模型请求。

### 4.1 FinBen 两项

- state 等于原始 query 全文，不重复拼接 text，不改写语言或题目。
- 一道 direction/choice 问题。criteria 为 {c0: choices[0], c1: choices[1]}，保持每行原选项顺序和文本。
- gold_label = choices[gold]，然后根据 Rise/Fall 语义映射上涨 1、下跌 0。gold 不是统一的涨跌码。
- answer/gold 只进入独立 label。原始 answer 保留供检查；有不一致时核查来源和官方 gold 规则，不静默重贴标签。
- 输出 p_up 必须按实际上涨选项取值，不能取索引 0 或 confidence。

### 4.2 AlphaFin-Test

- 固定全部 1000 行，包含相同股票月份的多份报告和第 127 行的空行情。不得去重、筛选成 999 行或用外部数据补行情。
- state 等于原始 input 全文。原 instruction 完整保留在 metadata.source_instruction。
- 原 instruction 唯一且已经核实。direction.instructions 取其已确认的“同时给出”之前的方向任务句，保留原句文字；criteria 按 {up: 涨, down: 跌} 顺序。只把响应形式适配为原生概率二选一。
- output 仅进入标签分支，按固定正则 fullmatch：这个股票的下月最终收益结果是:'([涨跌])',(上涨|下跌)概率:(极大|较大|中上|一般)。涨必须对应上涨，跌必须对应下跌。
- 四个定性强度词只保存为 source_strength，不转换为 0.9 等伪概率真值。
- 输出金标准必须有 484 涨、516 跌。任何不匹配都报告，不猜测解析。

时间口径：输入研报属于自然月 M，行情也属于 M；预测 M+1 自然月。报告日之后的同月行情属于原题已给定的信息，预测截点按月末理解。记录 stock_code（保留前导零）、report_date、asof_month、target_month、market_data_empty，不把报告日作为预测截点，不改为报告日后 30 天或本地 20 交易日任务。不得声称原文的 00:00:00 是实际发布时间。

### 4.3 PI Round 2/full

- 按原文件顺序处理 i=0..89，核对 i/t 唯一与原始顺序。
- request 只含原 state 和原 questions，保留所有插入顺序及问题文字。外层 i/t 放入记录元数据，不将外层 momentum/candidates 重复拼入 state。
- 必须完成全部 2070 题：choice 90、noul 1260、score 720。
- choice 保留 choice、probabilities、confidence；noul 保存 P(true)；score 保存等级概率、期望等级和 legend。
- PI 的三级 score 使用 0、1、2，regime_risk.score 原样与 0.5 比较，不能除以 2。
- choice 交易阈值读取 probabilities[choice]；Karpo 的 confidence 是另一种变换后的数值，不能代替选择概率。
- 此冻结版本的模型输入均为空仓初始状态。每条模型请求独立，模拟器的实际持仓不回填 state。

## 5. M0 加载与模型验收

先定位现有完整原生模型目录，确认包括 decision_config.json、readout.safetensors、tokenizer/processor、全部权重与权重索引。编码缓存目录或仅有 tokenizer 的目录不构成模型。复用现有下载清单和验收记录；不重复下载或复制 31B 权重。

M0 使用原始基座及原始 Readout，无后训练 LoRA、改动后的读出头或本地 A 股校准温度。记录实际原模型 revision、模型来源凭证、配置与 Readout 哈希，以及已有权重清单；不能仅根据文件夹名声称已经核验某个 revision。缺少可信来源时补做必要核查；无法确认原模型身份时报告。

原生调用参考（以已经安装且核实签名的版本为准）：

    from karpo_decision.decider import Decider
    decider = Decider.from_pretrained(
        model_dir, device="cuda:0", max_length=32768, token_budget=32768
    )
    response = decider.decide(prepared["request"])

不要向这一路径额外传 dtype/torch_dtype；已核实版本的 from_pretrained 会把这些不支持的参数转给构造函数。原加载器使用 BF16 backbone、配置指定的 FP32 Readout。保持已安装原生模板、选项 codes、attention 和 choice/noul/score 温度，不拟合新温度，不改成生成式采样，不静默换成量化模型。

已核查 Kurumi 固定的 karpo_decision 版本 6600011eb5cf46232d056ec0717dc726146d29de 与上游 c52d3507a254d3ad8423726c6bc6568c99113e7d 的上述加载实现相同。已安装兼容版本无需为本轮升级。环境只补当前入口实际缺少的小依赖，不批量升级 torch/transformers/CUDA。

整个模型设为 eval，并使用 inference_mode；不执行 backward、optimizer、在线学习或概率校准。原生 Decider 已实现相应推理路径，应复用。模型加载一次后可以依次跑四项，样本间无历史问答。推理 KV/前缀缓存必须遵循原生正确的请求和模型身份边界。

### 最小 preflight

1. 确认本机确为目标 GB10、GPU 可用、个人输出路径可写、当前模型身份与文件齐全，遵循已有集群运行方式。
2. 下载和适配所有样本，核验计数/标签/哈希，并使用真实原生编码器检查全部请求长度。原生按问题拆分时，每份必须保留完整 state；单个完整 state 超限时报告，不能截断。
3. 每个 benchmark 只做一条真实 smoke，优先覆盖长输入；PI 一条同时覆盖三类问题。检查真实 forward、概率、原始响应和文件写入。无须先跑大规模参数测试。
4. smoke 无故障就立即全量运行。相同最终身份下的合法 smoke 响应可计入正式结果，避免重复推理。修过输入/模型设置的 smoke 不复用。

降低外部 batch 或原生 token_budget 可用于解决打包资源问题，但不能缩短 state；降低 token_budget 不保证过大的单序列能运行。不能仅为跑通切换模型、精度或问题文本。所有性能参数在正式开始时记录，环境/精度变化不与旧结果静默混用。

## 6. 评分规则

### 6.1 三个方向任务

每个样本使用完整的两类概率；要求有限、在 [0,1] 内、和为 1（浮点容差 1e-5）。不舍入后再评分，不归一化修补错误回答。

- y_true、y_pred：上涨 1，下跌 0；原始 option index 另存。
- Accuracy：正确数 / 固定全部样本数。
- MCC：(TP*TN-FP*FN) / sqrt((TP+FP)*(TP+FN)*(TN+FP)*(TN+FN))；分母为 0 时记 0，并保存混淆计数。
- Brier：mean((p_up-y_true)^2)，固定二元正类定义。
- NLL：mean(-ln(max(p_gold,1e-12)))，自然对数；p_gold 直接取真类原始概率。只在计算 log 时取下界，保存的概率不变。
- 硬标签由原始选项概率 argmax 得到；精确平局取原 criteria 顺序第一项。

FinBen 的 Accuracy/MCC 是官方主指标。AlphaFin 的 1000 样本 native-choice 是本研究固定的可复跑口径；其论文数字只标 published_reference。论文原流程和当前后处理存在去重、无效生成回答补值等差异，不把未复现论文口径的分数标成 reproduced。M0、后续 M1/M2/M3 和在本协议重跑的其他模型可以直接比较。

只报告四个必需指标、混淆计数和有效覆盖；本轮不必增加校准搜索、显著性 bootstrap 或多次随机重复。原始概率保留后，AUROC、校准图等后续分析无需重新调用模型。

### 6.2 PI 官方评分

每个 run 建立独立回放工作目录，复用冻结原始文件；不在 raw/ 内生成新 summary。写入 rounds/round2/full/answers_karpo-m0.jsonl，每行采用：

    {
      "i": 原始i, "t": 原始t,
      "model": 实际模型标识与revision,
      "provider": "local",
      "answers": response["answers"],
      "missing": [],
      "usage": response.get("usage"),
      "latency_s": 实测耗时
    }

完成 90 条和 2070 题校验后，从回放根目录执行：

    python -m arena.simulate round2 full

模拟器自动发现 answers_*.jsonl，无须修改 MODELS、RELEASED 或冻结 scorer。M0 每次从 1000 美元开始，以官方成交价、费用和退出规则计分。不得重新获取实时行情或额外平移 bar 时间戳。

读取 summary.json 的 official_leaderboard 中 karpo-m0 条目，以及 results 中 karpo-m0 [pick>=0.5] 条目；资金曲线取 equity_curves.csv 的对应列。保存官方原始输出，再导出标准 metrics.json。必须同时记录最终净值、收益率、最大回撤、switches、steps_in_cash。

picks.csv 对应研究版 pick 策略，不能当成官方阈值策略的持仓。需要逐步官方行动时，用冻结 Track.policy("karpo-m0", k, 0.5) 读取或做等价的确定性提取，另存 official_actions.csv；不改交易撮合实现。不必自动执行 arena.analyze，因为其默认分析并非本轮新模型的官方策略。

本地 Karpo 不需要 OpenRouter 密钥。不直接 import 官方 run_selected 作为 validator，它的导入链会读取 .env；使用包内纯校验函数即可。历史其他模型的舍入缓存由官方 scorer 读取，不能套新 Karpo 的 1e-5 输出校验规则把它们误判为坏数据。

## 7. 结果保存与续跑

运行根目录：run_root/karpo-m0/RUN_ID。RUN_ID 唯一，不能覆写已完成运行。保存实际 UTC 时间；报告给用户时可同时显示北京时间。

| 文件 | 必需内容 |
| --- | --- |
| run_manifest.json | 协议和源码哈希、源文件哈希、模型身份、native配置、精度、环境/GPU、路径、开始结束时间、状态 |
| protocol/ | 本次实际使用的公共配置、补齐后的来源锁和适配器字节快照 |
| <benchmark>/responses.jsonl | sample_id、request_sha256、原始 response、状态、耗时，逐条落盘 |
| <benchmark>/predictions.parquet | 方向预测：sample_id、p_up/p_down、y_pred、原选项信息；评分后关联 y_true 和分析元数据 |
| <benchmark>/errors.jsonl | 实际异常、样本ID和恢复记录；没有异常可为空 |
| <benchmark>/metrics.json | 指标、预期/成功/失败数、协议标识、评分口径 |
| pi_round2_full/replay/ | 官方运行工作目录、M0 answers、summary、equity_curves、official_actions |
| summary.csv | 四项的汇总，交易指标与方向指标分别列出 |
| report.md | 本次结果、可比较的参考结果、耗时和真实限制 |

prepared 输入只保存一份，由 run_manifest 的路径和哈希引用；不在每个 run 中复制模型或整个数据目录。原生 usage 保留原值，包括 input_tokens、output_tokens=0、sequences；不把未发生的生成 token 或 API 花费填成实际调用。

恢复执行前核对：相同模型/Readout/tokenizer/native配置、相同输入与源快照、相同适配器与科学配置。读取现有合法成功行后只补未完成 ID，已有成功预测不重选或覆盖。无效回答保留错误，修复实际执行问题后再做一次同样请求；不以多次抽样择优，不填 0.5、默认 Fall 或借用其他模型。

JSONL 每条完成即写入并 flush。可用集群既有作业方式或用户自己的持久会话防止 SSH 断开；记录命令、任务/PID、日志路径。仅启动后台作业不算完成，应持续观察到结果完成或报告实际阻塞。

## 8. 完成、阻塞与交付

正式完成必须同时满足：

- BigData 1472/1472、ACL 3720/3720、AlphaFin 1000/1000 个有效方向输出。
- PI 90/90 场景、2070/2070 问题，官方 scorer 能读取新的 karpo-m0 缓存并产出完整结果和 91 个权益时点。
- 实际请求和模型身份可追溯，真值没有进入 payload，无静默删样本、截断输入或用参考缓存替代本模型。
- 四项均有原始响应、机器可读结果、评分与报告，可离线重算分数。

运行状态只需 RUNNING、COMPLETE、PARTIAL 或 BLOCKED。缺少授权、源数据与固定版本冲突、模型身份无法核实、完整输入无法在当前资源执行等实质阻塞应明确报告；保留已完成产物和恢复命令。常规路径、缺少小依赖、序列化等可自行解决的实现问题应修复后继续，不为 routine 操作反复询问。

代码、契约、实际补齐的锁文件、小型 summary/metrics/report 和产物清单可归档进仓库；原始受限数据、完整题目、权重、访问凭据、缓存和完整运行目录保留个人数据盘，不整体打进 Git。是否推送远端遵循当前会话已有仓库授权；没有可写凭据时不阻塞云端结果保存。

后续训练防泄漏清单应登记这些测试源及同源副本，特别是 ACL18/StockNet 关系、AlphaFin 股票目标月与自有标签窗口的重叠。本轮仅建立保留清单，不扩展成 M1 训练集构造或完整污染审计。基座的历史预训练暴露按官方披露记录，不宣称冻结参数消除了历史记忆。

## 9. 主要来源

- FinBen BigData：https://huggingface.co/datasets/TheFinAI/en-sm-bigdata
- FinBen ACL：https://huggingface.co/datasets/TheFinAI/en-sm-acl
- AlphaFin 固定文件：https://huggingface.co/datasets/AlphaFin/AlphaFin-dataset-v1/blob/09fd46494e00cfcf2d089fc4dbeb3589b969d9e0/test/1000_report_marketdata.json
- AlphaFin 论文：https://aclanthology.org/2024.lrec-main.69/
- AlphaFin 后处理：https://github.com/AlphaFin-proj/AlphaFin/blob/main/src/stage1_trend_prediction/dataprocess_stockgpt.py
- PI 说明：https://pilabs.space/trading-arena/README.md
- Karpo 模型：https://huggingface.co/MachinePulseAI/karpo-decision-31B
- Karpo 原生接口：https://github.com/machinepulse-ai/karpo-decision/blob/main/src/karpo_decision/decider.py
