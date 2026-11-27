# A 股数值池 V2

**CPU_READY · GPU_VALIDATION_PENDING**

## 输入与本地准备

`configs/training/cn_efficiency_v2.json` 给出的默认配方是 `basis_points_delta` 和按证券、交易日排列的等距概率抽样 `security_first`。日期和预算由调用方提供。 [配方配置](../configs/training/cn_efficiency_v2.json)

`basis_points_delta` 保留全部 60 个交易会话、六个历史通道、金融字段及原生七档边界。OHLC 相对值和日对数收益按基点显示，成交量相对值以 0.001 为显示单位。近零非零值以带符号四分之一单位表示。差分可精确还原已经量化的价格序列，缺失掩码保持一致。波动率在原生任务中保留一次数值，因子区引用同一量，行情和财报底表精度仍由正式发布保管。 [模板与编码](../src/kurumi/cn_efficiency_recipes.py) · [576 条逐样本 token](cn_efficiency_v2_evidence/native_token_samples.csv) · [差分与显示精度](cn_efficiency_v2_evidence/token_price_deltas.json)

| 同一批样本的测量 | V1 紧凑 | V2 `basis_points_delta` |
| --- | ---: | ---: |
| 平均原生输入 token，576 条 | 6,359.52 | 4,390.91 |
| P95 原生输入 token，576 条 | 6,534 | 4,517 |
| 端到端准备中位耗时，1,024 条，每臂三次 | 32.92 秒 | 11.67 秒 |
| 进程 CPU 时间中位数 | 27.72 秒 | 12.30 秒 |
| 进程峰值 RSS 中位数 | 2.73 GB | 1.78 GB |
| 小视图 SQLite 字节 | 18,456,576 | 13,340,672 |

端到端包括读取、渲染、原生分词、缓存封装与落盘。三项有效监督数同为 1,024、997、938，类标、掩码和权重的输出摘要一致。V2 直接读取列式日期视图，按年复用价格数组，按交易日复用渲染后的市场和行业段，复用重复的原生短文本 token，并批量查询组包长度及缓存对象。全历史只保存列式数据，编码缓存属于独立训练视图。 [准备计时和字节](cn_efficiency_v2_evidence/cpu_prepare.json) · [同输入分词](cn_efficiency_v2_evidence/cpu_tokenizer_trials.json) · [日内段复用](cn_efficiency_v2_evidence/cpu_context_reuse.json)

## 构建与原生验收

旧构建器的审计字典原先被排序字符串覆盖。修复后，独立全量重跑生成了审计及清单，并重放 34,855,830 条期限记录。旧渲染入口对恢复后的监督应用视图掩码。V2 的直接入口逐条核对池内类标、目标日、视图截止、旧切分和权重，再把启用期限写入准备缓存。 [V1 重跑审计](cn_efficiency_v2_evidence/v1_replay.json)

真实跨界夹具包含 97 条记录、14 条带恢复监督的样本、66 项被日期视图屏蔽的池内有效监督，训练缓存包含 97、88、40 项三个期限的监督。原生 Request、编码、类标、掩码和权重逐项核对，还验收了 24 个多样本组包和一条真实请求的三期限拆包。另用 CLI 生成两个独立开发日期视图，验证 113 条拟合和 72 条确认记录的全部三期限监督和时序。 [原生 CPU 收据](cn_efficiency_v2_evidence/cpu_native_acceptance.json) · [CLI 收据](cn_efficiency_v2_evidence/cpu_cli_smoke.json)

## 范围和数据版本

V2 复用正式发布的行情、财务、时点市场与行业数据，以及 V1 的审计和标签恢复证据。原始发布 `cn-612cc6625177eb8619e452f4f1de659a6177c0c449deb0c721c38b6f020172e3` 的清单 SHA-256 为 `b5dedb67575a45fa2203a7bac4f11ad785c1e271c187cceb1eaba8f043336637`。V1 清单为 `726add8ea11e84ccacd47125c9d942e8f350cef253410e8d1a725b9ef28c174d`。构建逐文件核验实际读取的 77 个正式发布文件、11 个 V1 文件的字节数和 SHA-256。V2 交付前复核 26 个 Parquet 文件的 SHA-256。 正式发布和 V1 的本地路径记录在 V2 清单。 [代码、数据和运行时校验值](cn_efficiency_v2_evidence/version_lock.json)

证据目录保留实验输出的原始字节。`version_lock.json` 记录实验执行时的代码与运行时，发布版本将 GPU 支持模块的导入延迟到训练阶段。 [验收收据](cn_efficiency_v2_evidence/release_receipt.json)

V2 保留 2015–2026 年 10,376,684 条合格原样本，1、5、20 日有效监督分别为 10,369,918、10,347,081、10,310,226，共 31,027,225 项。原始池的资格和隔离理由可在本地 V1 的 `quarantine.parquet` 追溯。全历史保留 446,768 项零收益以及 1,658,595 项绝对对数收益至少为 `ln(1.2)` 的监督，另有 148,619 条低波动、1,041,298 条低流动性、3,191 条距已核实退市不超过 90 日的样本。 [V2 清单](cn_efficiency_v2_evidence/v2_pool_manifest.json) · [全量核验](cn_efficiency_v2_evidence/data_quality.json)

| 文件 | 字节 | 用途 |
| --- | ---: | --- |
| `pool.parquet` | 51,567,569 | 日期、证券、监督类标、目标日、资格与覆盖索引 |
| `security_index.parquet` | 23,917 | 稳定证券整数键 |
| `history/*.parquet` | 340,138,584 | 11,745,773 条基础行情，每个证券交易日单存一次 |
| `points/*.parquet` | 1,301,457,553 | 日点状态和财务指针，波动率与原生任务共用 |

原收益、收益纠正依据、来源版本与财务修订记录继续由发布和 V1 覆盖层定位。V2 对合格样本索引的掩码、目标日及类标做逐期限核对。开发区复核了 8,092,673 条有效行情和 7,042,856 条可复算净利率，所查 OHLC、复权、成交量、财务时钟、市场和行业时钟冲突数均为 0。真实涨跌停、微小正营收、负权益和实测极端收益保留。钉住的证券会话键允许按尾随位置恢复 60 日窗口，成交量继续按可得拆并股链换算。 [金融和行情核对脚本](../scripts/audit_cn_efficiency_v2.py)

## 前推实验口径

三个验证窗为 2020、2021、2022–2023。每窗拟合从 2015 年开始，止于该验证窗前一日。样本日与用于拟合的目标日均在验证开始前，验证目标日止于该窗末日。所有选型指标只用截至 2023 年的数据。跨 2023 年末的恢复标签样例只用于接口正确性验收。

- 主代理沿用 `HistGradientBoostingClassifier`，各臂使用同等的 18 轮、15 叶、63 分箱、0.55 特征抽样比例和其他正则。初筛使用含额外覆盖字段的扩展矩阵。最终复核仅使用原生显示范围内的日历史、财务、因子、市场、行业和覆盖数值。字符串身份字段在原生渲染中保留。
- 每个期限独立拟合七类，测试样本及其期限掩码在同窗各臂间固定。逐期限输出 CE、Brier、RPS 和准确率，主指标为三个有效期限等权的 `CE + 0.5 Brier + 0.5 RPS`。RPS 使用六个累计概率边界的均方误差。
- 表中损失差为候选减对照，越低越好。置信区间由同一评估月成对重抽样 2,000 次得到。三个种子先按共同评估样本平均逐样本损失。筛选参考门槛为每窗上界至多增加 0.01，且任一期限点估计至多增加 0.02。
- 预算视图对合格总体做随机相位等距采样，各记录具有已知且相等的入选概率，训练保留逆概率权重。邻近曝光用同一证券相邻抽中记录之间的交易会话距离和共享历史行数度量。去重、覆盖、样本数、监督数和 token 各自计量。

正则多项逻辑回归复核在各拟合段内完成缺失填充、稳健尺度变换、单调 `asinh` 变换、标准化和 64 维 PCA 白化。初次拟合达到迭代上限。排查另一轮的单条极端损失发现，辅助覆盖字段 `known_count_coverage` 在训练中近乎常量，验证样例的偏离超过训练标准差 1,000 倍。最终复核对齐原生覆盖字段，交叉熵从稳定的对数概率直接计算，保留该样本的真实 20 日监督。 [数字与收敛迭代数](cn_efficiency_v2_evidence/model_metrics.csv)

## 推荐组合与预算对照

以下比较以 V1 紧凑输入和月度 `security` 排序为基线。三窗均用 17、29、43 三个种子，且每窗使用相同的 12,000 条评估样本。

| 验证窗 | 同样本只换输入，10 万条 | 同样本数换输入和采样，10 万条 | 同预期 token 换输入和采样，144,833 条 |
| --- | ---: | ---: | ---: |
| 2020 | −0.00079 | −0.00095 | −0.00445 |
| 2021 | +0.00145 | +0.00123 | +0.00045 |
| 2022–2023 | +0.00158 | +0.00293 | +0.00185 |

三种对照的各窗聚合损失差都通过了相应质量门槛。推荐组合按同预期预算增加了 44.83% 的样本，三个拟合窗的有效期限监督从约 29.5 万–29.6 万增到 42.7 万–42.9 万。月份×市场状态覆盖维持在 131、167、190 组。使用月度 `security` 填满同等预期预算的对照中，2021 窗口的损失差上界为 +0.01889，超过门槛。 [同样本与同预算结果](cn_efficiency_v2_evidence/forward_comparisons.json)

同规模换为 `security_first` 时，三窗原先平均 2,431、1,861、1,520 对的五会话内同证券相邻样本归零。共享的 60 日历史行分别减少约 6%、21%、51%。确认窗拟合样本的月份×行业组合从平均 2,172 降至 2,129，覆盖证券从 4,465 增到 4,501。逻辑回归的三个期限都在迭代上限前收敛，推荐组合三个前推窗的主损失相对差分别为 −0.021%、−0.030%、−0.337%。 [抽样覆盖](cn_efficiency_v2_evidence/sample_coverage.csv) · [逻辑回归](cn_efficiency_v2_evidence/model_metrics.csv)

20 万条对照也通过了三窗的质量门槛。2020 窗口种子 17 的损失差区间上界为 +0.01013，补跑 29 和 43 后，聚合上界为 +0.00860。2021 与 2022–2023 使用种子 17，上界分别为 −0.00114 和 +0.00912。 [20 万样本复核](cn_efficiency_v2_evidence/forward_comparisons.json)

## 附加探索与停止依据

初筛覆盖 30,000 样本、三窗和十个 HGB 臂。完整输入扩大至 100,000 与 200,000，较短历史及采样组合也扩大到有区分力的规模。等样本实验拆开显示精度和抽样顺序。等预期 token 实验比较两种抽样顺序。收益区间目标、验证样本和评分函数在同窗对齐。

| 探索轮 | 实测结果 |
| --- | --- |
| 价格差分与本地准备 | 价格差分相对非差分基点布局再省 2.80%，量化值可精确回放。原生短文本采用等值分词复用。按日复用市场和行业段的整条读入、渲染、原生编码、序列化路径中位时间下降 8.60%。 |
| 共享边界与较宽历史分块 | 原生边界表逐档可回放，平均每条多约 41 tokens。较宽历史分块省 token，2020 年原生字段口径 10 万同样本的损失差区间上界为 +0.01047。该轮没有新增符合质量门槛的实质改进。 |
| 成交量量纲和精度 | 无损居中节省 0.73%。0.01 精度节省 1.38%，三种子扩展代理的 2020 年上界为 +0.01227，原生字段口径的 2021 年上界为 +0.01035。0.1 精度在 2020 年初筛的损失差为 +0.03016。该轮没有新增符合质量门槛的实质改进。 |

搜索涵盖字段和时点对账、八位及六位有效数字、基点与十分之一基点、价格差分、边界别名、三档成交量精度、可复算因子、近期 20/30 日与均值及因果中位数分块、随机及覆盖采样、候选上下文预读、批量尺寸和原生短串分词。结果适用于这些候选、预算和开发期，连续两轮在既定门槛下没有新增实质改进。 [附加 token 测量](cn_efficiency_v2_evidence/token_volume_precision.json) · [预测对照](cn_efficiency_v2_evidence/forward_comparisons.json)

## 本地复现

以下路径从仓库根目录运行。CPU 环境是独立 venv，通过 `.pth` 只读引用现有的数据科学依赖、CPU Torch 和固定修订的 Karpo 源码。可用磁盘缓存目录是 `E:/Kurumi/artifacts/cn-efficiency-v2-work`。

```powershell
$venv = 'E:/Kurumi/artifacts/cn-efficiency-v2-work/venv'
if (-not (Test-Path "$venv/Scripts/python.exe")) {
  python -m venv --without-pip $venv
  @('E:/quant/.venv/Lib/site-packages','E:/Kurumi/artifacts/karpo-runtime','E:/Kurumi/reference/karpo-decision/src','E:/Kurumi/src') |
    Set-Content -LiteralPath "$venv/Lib/site-packages/kurumi-cpu.pth" -Encoding ascii
}
$py = 'E:/Kurumi/artifacts/cn-efficiency-v2-work/venv/Scripts/python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CUDA_VISIBLE_DEVICES = '-1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:TOKENIZERS_PARALLELISM = 'false'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '3'
$previous = 'E:/Kurumi/artifacts/cn-efficiency-v1'
$pool = 'E:/Kurumi/artifacts/cn-efficiency-v2'
$tokenizer = 'E:/Kurumi/artifacts/karpo-b8e6fd7'
$work = 'E:/Kurumi/artifacts/cn-efficiency-v2-reproduction'

$source = (Get-Content "$previous/manifest.json" -Raw | ConvertFrom-Json).source_directory
& $py scripts/build_cn_efficiency_pool.py --source $source --output "$work/v1-replay" --threads 2 --memory-limit 2GB
& $py scripts/build_cn_efficiency_v2.py --previous $previous --output "$work/pool"
& $py scripts/audit_cn_efficiency_v2.py --pool "$work/pool" --output "$work/data-audit.json"
& $py scripts/probe_cn_efficiency_tokens_v2.py --pool $pool --tokenizer $tokenizer --output "$work/tokens"
& $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/screen" --coverage-profile augmented
foreach ($window in '2020','2021','2022_2023') {
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/expanded-$window" --windows $window --seeds 17 29 43 --train-budget 100000 --eval-budget 12000 --threads 3 --coverage-profile augmented --token-report "$work/tokens/report.json" --arms basis_points:security recent20:security recent20:security_first recent20:security_first:tokens
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/deep-$window" --windows $window --seeds 17 --train-budget 200000 --eval-budget 12000 --threads 3 --coverage-profile augmented --token-report "$work/tokens/report.json" --arms basis_points_delta:security basis_points_delta:security_first
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-paired-$window" --windows $window --seeds 17 29 43 --train-budget 100000 --eval-budget 12000 --threads 3 --feature-run "$work/expanded-$window" --token-report "$work/tokens/report.json" --arms basis_points_delta:security
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-sampler-$window" --windows $window --seeds 17 29 43 --train-budget 100000 --eval-budget 12000 --threads 2 --feature-run "$work/expanded-$window" --reference-run "$work/native-paired-$window" --reference-arm basis_points_delta:security --token-report "$work/tokens/report.json" --arms basis_points_delta:security_first
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-token-$window" --windows $window --seeds 17 29 43 --train-budget 100000 --eval-budget 12000 --threads 3 --reference-run "$work/native-paired-$window" --token-report "$work/tokens/report.json" --arms basis_points_delta:security:tokens
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-token-sampler-$window" --windows $window --seeds 17 29 43 --train-budget 100000 --eval-budget 12000 --threads 2 --reference-run "$work/native-paired-$window" --token-report "$work/tokens/report.json" --arms basis_points_delta:security_first:tokens
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-deep-$window" --windows $window --seeds 17 --train-budget 200000 --eval-budget 12000 --threads 3 --feature-run "$work/deep-$window" --token-report "$work/tokens/report.json" --arms basis_points_delta:security
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-deep-sampler-$window" --windows $window --seeds 17 --train-budget 200000 --eval-budget 12000 --threads 4 --feature-run "$work/deep-$window" --reference-run "$work/native-deep-$window" --token-report "$work/tokens/report.json" --arms basis_points_delta:security_first
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-refine-$window" --windows $window --seeds 17 --train-budget 100000 --eval-budget 12000 --threads 3 --feature-run "$work/expanded-$window" --reference-run "$work/native-paired-$window" --reference-arm basis_points_delta:security --token-report "$work/tokens/report.json" --arms basis_points_volume100:security recent20_wide:security
  & $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-logistic-$window" --windows $window --seeds 17 --train-budget 100000 --eval-budget 12000 --threads 2 --feature-run "$work/expanded-$window" --token-report "$work/tokens/report.json" --arms basis_points_delta:security basis_points_delta:security_first --estimator logistic
}
& $py scripts/probe_cn_efficiency_forward_v2.py --pool $pool --output "$work/native-deep-followup-2020" --windows 2020 --seeds 29 43 --train-budget 200000 --eval-budget 12000 --threads 5 --token-report "$work/tokens/report.json" --arms basis_points_delta:security_first
& $py scripts/bench_cn_efficiency_cpu_v2.py --pool $pool --previous $previous --tokenizer $tokenizer --output "$work/cpu"
& $py scripts/bench_cn_efficiency_cpu_v2.py --pool $pool --previous $previous --tokenizer $tokenizer --output "$work/cpu-e2e" --recipe basis_points_delta --end-to-end-only --samples 1024
```

正式日期由用户指定，`--end` 默认兼作最晚目标日期。`--label-end` 显式覆盖目标日期截止。`--split` 继续使用旧切分的掩码。`--budget` 是样本上限。`--token-budget` 与 `--tokens-per-sample` 换算样本上限，以实测均值作估计时会有实际偏差。两个预算同时提供时取较紧的限制。原生准备的 SQLite 清单报告实际编码 token、各期限监督数、抽样权重与源视图校验值。 [视图入口](../scripts/select_cn_efficiency_view.py) · [原生准备入口](../scripts/train_cn_efficiency.py)

```powershell
$config = 'configs/training/cn_efficiency_v2.json'
$recipe = Get-Content $config -Raw | ConvertFrom-Json
& $py scripts/select_cn_efficiency_view.py --pool "$pool/pool.parquet" --output "$work/fit.parquet" --start $fitStart --end $fitEnd --label-end $lastTarget --token-budget $tokenBudget --tokens-per-sample $recipe.expected_input_tokens_per_original --coverage-order $recipe.sampling_order
& $py scripts/train_cn_efficiency.py --config $config prepare --pool $pool --date-view "$work/fit.parquet" --tokenizer $tokenizer --view "$work/fit.sqlite" --formats compact
```

## GPU 验收清单

1. 使用用户指定的隔离烟测视图，在固定的原始 Karpo checkpoint 上检查 native forward、loss、backward、LoRA/Readout 更新、基座冻结，以及三期限含空目标的训练梯度。
2. 对同样本、同掩码和同权重分别检查单请求、多个请求组包和超长拆包的分数与梯度。验证带 optimizer、scheduler 和游标的重启能重放下一步。
3. 使用相同配置和原始样本比较上版紧凑输入与推荐输入，记录首步和热态有效样本/小时、监督/小时、显存峰值及端到端 I/O，再用开发前推窗核对 native 概率质量。

在已有的隔离训练环境中手动执行下列命令。GPU 阶段使用该环境中的 `run_benchmarks.py`、`benchmark_adapters` 和 `kurumi.m1_*` 训练支持模块，入口有 GB10 设备检查，原生 GPU 模块需要 Python 3.12 或更新版本。CPU 准备入口可以在本发布分支独立运行。分别为上版紧凑和推荐配方准备不同的 SQLite，使用同一小型日期视图和不同的输出路径。

```bash
python scripts/train_cn_efficiency.py --config configs/training/cn_efficiency_v2.json train --view "$CPU_PREPARED_VIEW" --model "$ORIGINAL_LOCAL_MODEL" --provenance "$ORIGINAL_PROVENANCE" --output "$GPU_SMOKE_RUN" --format compact --max-updates 2
python scripts/train_cn_efficiency.py --config configs/training/cn_efficiency_v2.json train --view "$CPU_PREPARED_VIEW" --model "$ORIGINAL_LOCAL_MODEL" --provenance "$ORIGINAL_PROVENANCE" --output "$GPU_SMOKE_RUN" --format compact --max-updates 3 --resume
```
