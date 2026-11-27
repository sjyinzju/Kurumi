# Kurumi M1 金融领域训练与测评执行方案

版本：m1-finance-v1 · 2026-11-25

## 1. 本轮目标与固定范围

在已完成 M0 测评的 Karpo Decision 31B 上，使用下列六个金融监督数据源完成一次连续的 M1 训练：混合训练 2 个 epoch，原始骨干冻结，只训练一套共享 LoRA 和原生 Readout。选定 M1 后冻结，完整重跑原有四项 benchmark，并与现有 M0 配对比较。

本轮不增加 CPT、RL、其他模型、独立专家头、第二套 adapter 或超参数搜索。训练效果据实报告；不根据 benchmark 成绩重选 checkpoint、改阈值或追加训练。M1 为后续 M2、新闻、公告、新闻＋公告四个训练分支的共同初始化。

## 2. 复用现有环境与存储

已核对的 M0 归档为 `docs/benchmarks/m0-20261125T034500Z/`，对应仓库提交 `9ff2d161a0ddbcec6abfd26688d330dea5fab18a`。云端实际路径如下；执行时读取现有文件，不覆盖未提交工作。

| 对象 | 路径或约定 |
|---|---|
| 研究根目录 | `/home/shijunyu/kurumi-research` |
| 云端仓库 | `/home/shijunyu/kurumi-research/Kurumi` |
| 已有环境 | 根目录下 `.venv`，入口 `activate.sh` |
| 基座路径与来源 | 从 `runs/setup/model-manifest.json` 读取；复用现有权重 |
| M0 运行 | `runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z` |
| 四项测评数据 | `data/benchmarks/v1`，复用已冻结的 raw/prepared 文件 |
| 新增 M1 数据 | `data/financial_m1/v1/{raw,prepared}` |
| 新增训练记录 | `runs/training/m1/<train_run_id>` |
| 新增检查点 | `models/kurumi-m1/<train_run_id>`，保存 adapter、Readout 和恢复状态 |
| 新增 M1 测评 | `runs/benchmarks/v1/karpo-m1/<benchmark_run_id>` |
| 仓库轻量报告 | `docs/training/<train_run_id>/`、`docs/benchmarks/<benchmark_run_id>/` |

除仓库内路径外，表中相对路径均相对于研究根目录。原始数据、模型、缓存和完整日志留在 GB10 存储盘；仓库保存代码、配置、轻量报告和产物索引。模型身份固定为：

- 基座：`MachinePulseAI/karpo-decision-31B@b8e6fd7463cea8662c556d6257955d7ef9c10d19`。
- 原生代码：`6600011eb5cf46232d056ec0717dc726146d29de`。
- 保留 M0 已跑通的 PyTorch/Transformers/CUDA 环境，只补必要依赖并记录版本。
- 复用 M0 已解决的 Python.h 编译修复：`cache/native-build/python-3.12.3-1ubuntu0.17-arm64/usr/include`，沿用成功 Slurm 入口中的 `CPATH`。

M0 的实际 runner 为云端仓库 `scripts/run_benchmarks.py`；其协议、适配器、来源锁及运行脚本快照位于 M0 运行目录的 `protocol/`。这些实现可能未完整上传 GitHub，必须先检查云端再做最小扩展。

## 3. 六个数据来源与下载

| 来源 ID | 固定 revision | 仅下载和使用的部分 | 原始记录参考数 |
|---|---|---|---:|
| `DianJin/CFLUE` | `adcf2643b83dfaed79d43ed916716ac57e88544a` | `train.json` | 30,907 |
| `Salesforce/FinTrain` | `8c458402abbbaba013a344e8365ded7699b3f0bf` | `flare_finqa_sup/train-*.parquet` | 6,251 |
| `takala/financial_phrasebank` | `8d3fe0c36d5feec6b3cc5e455b0fcb4820fb9964` | `data/FinancialPhraseBank-v1.0.zip` 中的 `FinancialPhraseBank-v1.0/Sentences_AllAgree.txt` | 2,264 |
| `FinGPT/fingpt-convfinqa` | `130ed6276b6ba5cc188eb4eafa558f3312f5bc4d` | `data/train-00000-of-00001-7acaa8cc8803a6e9.parquet` | 11,104 |
| `Salesforce/FinTrain` | `8c458402abbbaba013a344e8365ded7699b3f0bf` | `cfa_exercise_sup/train-*.parquet` | 2,946 |
| `SUFE-AIFLM-Lab/FinEval` | `ab300028f8836f14c28e80d4e96984bca9902a85` | `FinEval.zip` 中 `dev` 和 `val` | 1,321 |

合计 54,793 条为清洗前参考规模，不强行凑数。六个来源一次性准备，全部处理完成后进入正式训练；不把 FinTrain 整包下载，也不加入任何来源的官方 test。

直接在云端使用已有网络、代理及授权下载，保存原文件、SHA-256、来源 URL、revision 和许可证。HF 文件名先查询固定 revision 的文件列表；不猜测分片名。FPB 按 `iso-8859-1` 解码，以每行最后一个 `@` 分割原句和标签，无需启用旧版远程 dataset script。

如需要登录或接受协议，明确告诉用户需要完成的网页操作。云端访问确实不可用时，允许通过已授权本地浏览器下载同一官方版本，上传至对应 raw 目录并核对哈希；执行侧没有浏览器能力时给出准确下载链接和上传目标。不得绕过访问控制、记录令牌到仓库或静默缺少某一来源。

## 4. 统一数据处理

### 4.1 任务转换

| 数据/题型 | 原生表达与标签 |
|---|---|
| CFLUE、FinEval、CFA 单选 | `choice`，保留原候选，target 为正确选项 key |
| 判断题 | `noul`，使用原始真假答案 |
| CFLUE 多选 | 同一 state 下逐选项建立 `noul`，问“该选项是否应被选为本题答案”；选中即 true，兼容否定题干 |
| FinQA、ConvFinQA 数值题 | `choice`，1 个正确数值＋3 个确定性干扰项；统一单位与精度，候选不等价 |
| FinQA、ConvFinQA 明确真假题 | `noul` |
| FPB | `choice`：negative / neutral / positive；不改写成未来收益标签 |

数值答案优先用原始运算程序和执行结果核验；干扰项按固定规则产生，如错误分母、符号、单位/百分数尺度，并去除与正确答案等价的值。无法形成四个唯一有效候选的题目排除并记录。仅核验训练源的原程序，不调用外部模型猜答案。

必要时同时获取 FinQA 官方仓库的 `dataset/train.json`、ConvFinQA 官方仓库的 `data.zip`（按实际归档成员路径仅读取其中 `train_turn.json`），记录其 commit/文件哈希；仅用于恢复六个既定来源的 ID、报告分组和计算监督，不扩充训练来源。FinGPT ConvFinQA 镜像缺原始 ID，可按官方渲染规则生成输入指纹并核对答案回连，不能仅按两份文件的行号假定一致。

具体字段规则：

- CFLUE 的 `choices` 可为 Python 字典字符串，使用安全解析，不执行 `eval`；`analysis` 留作核验，不输入模型。
- FinQA 的输入只保留报告、表格和问题；不整列拼入可能已包含答案的 `text`。
- ConvFinQA 保留预测当前问题之前已给出的历史问答；当前问题的答案、程序和解析只放监督侧。
- CFA 使用题干、`scenario`、`exhibit` 和候选；仅保留 `answer` 可唯一对应候选且能够自动回连原材料中当前题答案的记录。无法自动核验的排除计数，不要求人工逐题审核；不得用 `gpt4_answer` 或 assistant messages 补答案。
- FinEval 合并公开 `dev＋val`；ID 包含学科、原 split 和原 ID，避免不同 CSV 编号冲突。两者不再单独作为未见过的验证集。

### 4.2 清洗、分组与隔离

1. 删除空题、缺标签、单选/数值 choice 无唯一正确候选、判断/多选标签无效、必要证据缺失和重复记录；原文保留数值、单位、否定词及表格结构。相同输入对应冲突标签的记录隔离，不任意选标签。
2. 以原题/报告/对话为 group，FinQA 与 ConvFinQA 同源报告跨库归为同组；普通考试题按规范化题干和候选识别同题。完全相同记录保留一份并保留来源列表；明显同题改写同组，不混入训练与开发两侧。
3. 在六个指定监督池中按 group 固定约 95% train、5% dev，seed=17；按来源/题型尽量保持覆盖，不追求精确行比例。分组和样本 ID 写入清单后锁定。
4. 在云端定位既有 `holdout_v1.md` 并沿用；若未落盘，则按 M0 `protocol/benchmark_contract_v1.md` 的保留规则补齐简明清单。四项 benchmark 的输入、答案、结果、复盘和同源改写均不作为训练/开发材料；数据准备仅使用冻结测试输入的指纹和来源信息排重，不将其内容写进训练样本。
5. 使用原始 ID、规范化题干/原文指纹及明显近重复检测排除交叉。排除规则针对具体来源与样本，不把整个 `TheFinAI` 组织禁用：本轮 FinQA 来源允许使用。
6. 金标、解释和当前答案不进入 `state/questions`；教师标签、未来结果、文件名中的答案提示不得混入输入。元数据中的 source、split、gold 只供数据管理。

### 4.3 可直接训练的产物

prepared 下输出 `train.jsonl`、`dev.jsonl`、`data_manifest.json`、`excluded.jsonl`。每条有效记录包含 `id/source/original_id/group_id/task/state/questions/targets`，训练器仅把 `state/questions` 交给原生编码器。

训练候选按 seed 与样本 ID 确定性打乱，同步重映射 targets；dev 顺序固定。原生编码后的单条总长不超过 4096 tokens，包含共享材料、全部问题、候选和标记；完整内容无法放入时整条排除，不截掉题干或证据。

数据准备完成条件：六源均完成解析，逐源原始/去重/排除/有效/train/dev 数量已记录；group 不跨 train/dev；与固定测试源没有已发现的重叠；原生布局和 target 映射有效。某一整源失败或有效数量为零，先修复实际映射问题，仍不可用则明确报告，不能悄悄按五源启动并宣称六源完成。

## 5. 原生训练配方

| 配置 | 固定值 |
|---|---|
| 数据与轮数 | 六源自然比例混合，每轮打乱；每条有效原题每轮使用一次；连续 2 epochs |
| 随机种子 | 17 |
| 原始参数 | 显式冻结整个原始 backbone |
| LoRA 范围 | 文本层实际存在的 q/k/v/o、gate/up/down 线性投影；排除视觉层及不存在的模块 |
| LoRA 参数 | r=16、alpha=32、dropout=0、bias=none |
| Readout | 使用已有初始化，完整保留 255 行及 soft-cap，FP32 更新 |
| 学习率 | LoRA 5e-5；Readout 5e-6 |
| 优化器 | AdamW，betas=(0.9,0.999)、eps=1e-8 |
| weight decay | LoRA 0.01；Readout 0 |
| 调度/裁剪 | warmup 3% 更新步＋cosine；gradient clip=1.0 |
| 精度 | Backbone BF16；Readout/关键损失 FP32 |
| 批量 | microbatch=1 个原生 pack，总长≤4096 tokens；累积 16 个 pack 更新一次 |
| 重计算 | checkpoint_every=1，recompute="layer" |
| 损失 | 交叉熵；原题内各子问题平均，再按有效批次原题平均 |
| 验证/选点 | 每 epoch 末验证一次，以整个 dev 的原题平均 CE 选较低者；同分选较早者 |

接入顺序：加载现有检查点 → `backbone.requires_grad_(False)` → 在同一 backbone 对象原位注入 LoRA → 开放原生 Readout → 构造 Packed。原生加载器默认开放部分原始参数，所以冻结必须显式执行。

训练前向采用 `Encoder.plan → pack → Packed → Readout → 每题有效 K 个 logits → CE → backward`，gold 对齐原生题目 key、候选编码和读出顺序。不能调用带 `inference_mode` 的推理入口；冻结基座不等于对整个前向使用 `no_grad`。复用已有底层前向，增加可变题目数/候选数的 M1 入口，不能强套现有“3 个期限×7 档”的收益包装。

一个 pack 可容纳多条独立原题，必须使用原生注意力隔离。每次累积中先累计原题 loss 总和，更新前按这 16 个 pack 的实际原题总数归一化梯度，再 clip/step；epoch 尾部按实际数量处理。不要把每个 pack 的平均 loss 简单除以 16。scheduler 总更新步数按两轮实际 pack 计划和累积 16 计算，包含尾部更新，不能直接用原题数除以 16。

正式训练首个实际更新确认 LoRA/Readout 有有限有效梯度、原始骨干没有梯度、更新影响原生 logits；标准 LoRA 首步 A 梯度为零可能正常。保存并重新加载后检查固定输入 logits 一致。仅做这些必要集成检查，不开额外实验轮次。训练前在同一 dev 上记录一次 M0 诊断，供最终金融能力比较；不重跑 M0 四项正式测评。

## 6. 新 Slurm 作业与长任务恢复

先读取现有 Slurm 配置和 M0 成功脚本，再提交本任务的新作业。M0 已成功使用 `partition=gpu / nodes=1 / ntasks=1 / cpus-per-task=4 / mem=108G / gres=gpu:1`；沿用资源形式，读取实际 partition/QOS 的时间上限，不照抄 M0 的 4 小时 walltime。训练与测评全部在本任务 GPU allocation 内运行，下载使用集群允许的联网入口。

主流程自动衔接：准备数据 → 连续训练 → 选点保存 → 重新加载并冻结 M1 → 四项测评 → M0/M1 比较与报告。数据已准备完成时从清单恢复，不重复下载；不止步于提交 job。

每 60 分钟在最近的 optimizer 更新边界、每个 epoch 末及调度器终止预告时保存恢复点。保存 LoRA、Readout、optimizer、scheduler、随机状态、epoch、打乱顺序/pack 游标及有效样本进度；保留可恢复的 last 和 epoch 候选即可。若单次时限不足，通过 Slurm 续跑同一 train_run_id，累计只完成原定 2 epochs，不能从头再加两轮。暂停恢复从最近完整边界重放未提交进度。

记录提交命令、Job ID、节点和日志路径；只管理本任务自己的作业。需要人工登录或上传时明确报告阻塞点和恢复方式，不空占 GPU 等待。普通依赖、路径、下载、解析和可恢复作业错误自行修复；需要改变训练方法、数据范围或精度时报告具体问题，不擅自缩成小样本训练。

训练预算为单台 GB10 约 2–6 天，按 4 天排期；前 100 个正式 microstep 后用实际有效 token 吞吐更新 ETA 并继续。M0 四项推理实测合计 2:10:09，M1 复测暂按约 3 小时安排；实际时间写入报告。

## 7. 定版、共享与四项复测

M1 保存“原基座引用＋选定 LoRA＋选定 Readout＋编码/配置/数据版本”，不覆盖 M0 权重、不另复制整套 31B 基座。保留一份只读 M1 基线；后续 M2 和三个 M3 分支各自复制该 LoRA/Readout 继续训练，原始骨干仍冻结。

测评加载必须实际恢复选定 LoRA 和更新后的 Readout，并记录实际载入文件哈希。最小扩展云端已有 runner 的模型加载与身份识别，不臆造尚不存在的 CLI 参数。仅改 model_variant/run_id 不算加载 M1。

定版后全部参数冻结，使用 `eval()` 和 `inference_mode`。沿用 M0 的数据版本、requests、适配器、候选顺序、温度 1.0、max_length/token_budget=32768、指标和 PI scorer；训练 4096 预算不带入测评。各请求独立，不携带其他 benchmark 的上下文。

| Benchmark | 固定规模/评分 |
|---|---|
| TheFinAI/en-sm-bigdata test | 1472；Accuracy/MCC/二元 Brier/NLL |
| TheFinAI/en-sm-acl test | 3720；同上 |
| AlphaFin-Test | 1000；同上 |
| PI Round2/full | 90 场景、2070 问题；官方 pick>=0.5 策略与冻结行情/scorer |

M1 使用独立运行目录和 PI 模型标识 `karpo-m1`。恢复缓存 key 包含基座、LoRA、Readout 和协议身份；M0 响应仅用于比较，绝不作为 M1 缓存。PI 沿用同一官方比较模型快照，不在线更新榜单。

从 M0 的全精度 `predictions.parquet/metrics.json` 读取基线，方向任务按相同 sample_id 对齐；PI 按相同场景与时间轴比较。输出 `M0 / M1 / M1−M0`：Accuracy 另列百分点差，MCC 越大越好，Brier/NLL 越小越好；PI 比较最终净值、收益率、最大回撤、切换次数和空仓步数。不把四项异构指标合成一个总分，不因结果下降而改协议重跑。

## 8. 必须交付与完成标准

完整产物保留于上述 GB10 目录，轻量报告和索引进入仓库：

- 数据：来源锁、六源处理统计、train/dev、排除记录、分组及去重结果。
- 训练：实际配置、模块挂载/可训练参数数、train/dev loss、两轮验证指标、所选 epoch、恢复记录和耗时。
- 模型：可重新加载的 LoRA/Readout、精确基座引用、模型身份与哈希、后续分支使用说明。
- 测评：四项完整原始响应、逐样本概率/预测、指标、PI 权益/交易轨迹及运行元数据。
- 比较：逐样本或逐场景配对表、汇总 comparison.csv 和 report.md；同时附金融 dev 的 M0/M1 诊断。
- 总报告：Job ID、节点、全部路径、有效样本数、是否完成两轮、选中 checkpoint、四项完成数、M0/M1 改善或退化、实际问题。

只有两轮训练完成、checkpoint 选定并可加载、四项样本全部评分且对比文件落盘，才报告 `COMPLETE`。`sbatch` 成功、正在运行或仅有训练 loss 均不能作为完成依据。存在真实阻塞时报告已完成部分、具体错误、所需用户操作和准确恢复命令。

## 来源

- [Kurumi M0 归档](https://github.com/sjyinzju/Kurumi/tree/9ff2d161a0ddbcec6abfd26688d330dea5fab18a/docs/benchmarks/m0-20261125T034500Z)
- [既有后训练规划](https://github.com/sjyinzju/Kurumi/blob/88e316c4873ee92c88ba0e9bd1565eacab5db3ae/docs/kurumi_post_training_plan.md)
- [Karpo 模型](https://huggingface.co/MachinePulseAI/karpo-decision-31B) · [原生代码](https://github.com/machinepulse-ai/karpo-decision/tree/6600011eb5cf46232d056ec0717dc726146d29de)
- [CFLUE](https://huggingface.co/datasets/DianJin/CFLUE) · [FinTrain](https://huggingface.co/datasets/Salesforce/FinTrain) · [Financial PhraseBank](https://huggingface.co/datasets/takala/financial_phrasebank)
- [ConvFinQA](https://huggingface.co/datasets/FinGPT/fingpt-convfinqa) · [FinEval](https://huggingface.co/datasets/SUFE-AIFLM-Lab/FinEval)

