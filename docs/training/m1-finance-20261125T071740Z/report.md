# Kurumi M1 金融后训练与冻结复测

**COMPLETE**

## 数据

| 来源 | 原始 | 去重排除 | 总排除 | 有效 | train | dev |
|---|---:|---:|---:|---:|---:|---:|
| cflue | 30907 | 20 | 56 | 30851 | 29309 | 1542 |
| finqa | 6251 | 48 | 68 | 6183 | 5872 | 311 |
| fpb | 2264 | 5 | 5 | 2259 | 2146 | 113 |
| convfinqa | 11104 | 32 | 34 | 11070 | 10512 | 558 |
| cfa | 2946 | 3 | 2828 | 118 | 112 | 6 |
| fineval | 1321 | 83 | 90 | 1231 | 1169 | 62 |

训练集 49,120 道，开发集 2,592 道。跨 split 重叠 group 数为 0。近重复分组合并记录为 255 对。

CFA 仅保留能把题干和官方材料答案自动对应的题目。逐源排除原因、来源声明及文件哈希见 data_manifest.json。

## 两轮训练与金融 dev

| 模型 | 训练原题均值 CE | dev 原题均值 CE | dev 原题平均准确率 | 全题正确率 |
|---|---:|---:|---:|---:|
| M0 | — | 0.3709736 | 0.8538130 | 0.7924383 |
| epoch 1 | 0.2854231 | 0.2806892 | 0.8857382 | 0.8310185 |
| epoch 2 | 0.1876132 | 0.2851158 | 0.8961741 | 0.8414352 |

选定 epoch 1。相对 M0，金融 dev 的 CE 变化为 -0.0902845。两轮完成 1,030 次优化器更新、59,243,168 个有效 token。原计划 16,459 个 pack，实际执行 16,459 个。训练计算累计 193,689 秒。

冻结基座为 MachinePulseAI/karpo-decision-31B@b8e6fd7463cea8662c556d6257955d7ef9c10d19。原生代码为 6600011eb5cf46232d056ec0717dc726146d29de。

- lora 文件位于 `/home/shijunyu/kurumi-research/models/kurumi-m1/m1-finance-20261125T071740Z/frozen/lora.safetensors`，SHA-256 为 `a182cc9b865e7f8fb99eceb8bb829c786c2b35ad7448e84ecc31dba1d83e7f8e`。
- readout 文件位于 `/home/shijunyu/kurumi-research/models/kurumi-m1/m1-finance-20261125T071740Z/frozen/readout.safetensors`，SHA-256 为 `dcc862d86220cb3044a8e20a829575974fd259da700fb5ce9f8ad0922b0eb8cf`。

冻结清单位于 `/home/shijunyu/kurumi-research/models/kurumi-m1/m1-finance-20261125T071740Z/frozen/manifest.json`。各后续分支从同一冻结清单加载基座、LoRA 和 Readout，分别保存各分支可训练副本。
已校验的迁移包位于 `/home/shijunyu/kurumi-research/models/kurumi-m1/m1-finance-20261125T071740Z/kurumi-m1-portable.tar`，SHA-256 为 `7ebb637dc53b25ec092492900a5cdfecd4cedd68ab35d33aa8e56122805fcada`。基座校验、探针复现及后续训练加载见 docs/m1_model_migration.md。

## GB10 训练性能

同一检查点、同一更新窗口的 60,922 个有效 token，warmup 后从 264.6 提至 320.3 token/s，倍率为 1.211×。PyTorch 峰值分配显存从 64.05 GiB 变为 97.77 GiB。

原配置的单窗口前向 65.83 秒、反向 159.78 秒、读取与解码 4.618 秒。相同梯度的优化器更新耗时 0.402 秒。

执行配置为 selective 重计算、checkpoint_every=2、keep_every=0、long_tokens=0、pack 预算 4096、LoRA 合并缩放与加法 True。窗口逐题 CE 最大差为 0，最低系统可用内存 11.57 GiB，训练进程 swap 为 0 字节。

第二轮在原 pack 顺序上测得 306.1 → 306.1 token/s，峰值从 97.73 GiB 变为 97.73 GiB。
- 按长度保留激活（long_tokens=2112） 实测 324.1 token/s，最大逐题 CE 差 0，梯度范数差 1.12%，最低系统可用内存 10.33 GiB。
- 按长度保留激活与 LoRA 原地加法（long_tokens=2112） 实测 322.9 token/s，最大逐题 CE 差 0，梯度范数差 2.15%，最低系统可用内存 9.73 GiB。
选定路径的一次单 pack CUDA trace 中，矩阵乘法用时 7.79 秒，memory-efficient 与 Flash Attention 的反向分别用时 0.81 和 0.36 秒。
当前配置和选点证据见 performance_refinement.json。
采用该阶段执行配置的 956 次正式更新平均 308.0 有效 token/s，记录 7 次内存回退窗口。
跳过每份 Slurm 作业的首次更新后，941 次正式更新平均 310.6 有效 token/s。
完整测时、候选结果和算子记录见 performance_profile.json。

## 冻结测评

| 数据 | 完成 / 预期 | 指标 | M0 | M1 | 差值 | 变化 |
|---|---:|---|---:|---:|---:|---|
| finben_bigdata | 1472 / 1472 | accuracy | 0.54144022 | 0.55978261 | +0.018342391（+1.8342 个百分点） | 改善 |
| finben_bigdata | 1472 / 1472 | mcc | 0.040208002 | 0.072496722 | +0.03228872 | 改善 |
| finben_bigdata | 1472 / 1472 | brier | 0.24942768 | 0.24732278 | -0.0021048952 | 改善 |
| finben_bigdata | 1472 / 1472 | nll | 0.69255343 | 0.68807459 | -0.0044788417 | 改善 |
| finben_acl | 3720 / 3720 | accuracy | 0.48870968 | 0.48924731 | +0.00053763441（+0.0538 个百分点） | 改善 |
| finben_acl | 3720 / 3720 | mcc | -0.025635811 | -0.027959864 | -0.0023240538 | 退化 |
| finben_acl | 3720 / 3720 | brier | 0.27004914 | 0.26364012 | -0.0064090122 | 改善 |
| finben_acl | 3720 / 3720 | nll | 0.74083387 | 0.72293675 | -0.017897122 | 改善 |
| alphafin_test | 1000 / 1000 | accuracy | 0.483 | 0.477 | -0.006（-0.6000 个百分点） | 退化 |
| alphafin_test | 1000 / 1000 | mcc | -0.021305145 | -0.035033422 | -0.013728276 | 退化 |
| alphafin_test | 1000 / 1000 | brier | 0.36685618 | 0.35520909 | -0.01164709 | 改善 |
| alphafin_test | 1000 / 1000 | nll | 1.1105513 | 1.0380208 | -0.072530492 | 改善 |
| pi_round2_full | 90 / 90 场景，2070 题 | final_usd | 816.38 | 836.02 | +19.64 | 改善 |
| pi_round2_full | 90 / 90 场景，2070 题 | return_pct | -18.36 | -16.4 | +1.96 | 改善 |
| pi_round2_full | 90 / 90 场景，2070 题 | max_drawdown_pct | -20.88 | -20.48 | +0.4 | 改善 |
| pi_round2_full | 90 / 90 场景，2070 题 | switches | 43 | 46 | +3 | 无预设优劣 |
| pi_round2_full | 90 / 90 场景，2070 题 | steps_in_cash | 13 | 16 | +3 | 无预设优劣 |

PI 最大回撤使用官方负百分数。切换次数及空仓步数报告观察差值。各方向任务的预测翻转数见 paired_summary.json。

## 作业与实际耗时

| 阶段 | Job ID | 节点 | 结束状态 | 退出码 | Slurm 秒数 |
|---|---:|---|---|---|---:|
| prepare | 4260 | pgx02 | FAILED | 127:0 | 1 |
| prepare | 4261 | pgx02 | COMPLETED | 0:0 | 288 |
| diagnostic | 4262 | pgx04 | COMPLETED | 0:0 | 1770 |
| train | 4264 | pgx04 | FAILED | 75:0 | 3031 |
| train | 4266 | pgx04 | FAILED | 75:0 | 13706 |
| train | 4278 | pgx02 | CANCELLED by 1013 | 0:0 | 2351 |
| train | 4288 | pgx02 | FAILED | 75:0 | 13305 |
| train | 4305 | pgx02 | FAILED | 75:0 | 13352 |
| train | 4311 | pgx02 | FAILED | 75:0 | 13295 |
| train | 4313 | pgx02 | FAILED | 75:0 | 13241 |
| train | 4320 | pgx02 | FAILED | 75:0 | 13223 |
| train | 4328 | pgx02 | FAILED | 75:0 | 13315 |
| train | 4351 | pgx02 | FAILED | 75:0 | 13272 |
| train | 4362 | pgx02 | FAILED | 75:0 | 13301 |
| train | 4367 | pgx02 | FAILED | 75:0 | 13386 |
| train | 4368 | pgx02 | FAILED | 75:0 | 13301 |
| train | 4373 | pgx03 | FAILED | 75:0 | 13377 |
| train | 4379 | pgx02 | FAILED | 75:0 | 13248 |
| train | 4392 | pgx02 | FAILED | 75:0 | 13346 |
| train | 4403 | pgx02 | FAILED | 75:0 | 13311 |
| train | 4413 | pgx02 | COMPLETED | 0:0 | 5495 |
| benchmark | 4414 | pgx02 | FAILED | 1:0 | 686 |
| benchmark | 4415 | pgx02 | COMPLETED | 0:0 | 10539 |

GPU 作业累计用时 223,851 秒。含排队和跨作业间隔的总历时为 229,583 秒。
训练作业的退出码 75:0 表示已保存完整恢复状态并交给下一个作业。Slurm 将该退出码记录为 FAILED。

## 运行问题与结果路径

首次准备作业 4260 的默认 shell 无法执行已有激活脚本。作业 4261 改用 Bash 并完成同一批数据准备。两份 HF 原件通过已授权本地下载并经 SFTP 上传，其余四份从官方存储直接下载至 GB10。
- 训练作业 4264 按上一轮暂停请求收到 SIGTERM 后保存至第 1 轮 pack 176、优化器更新 11，以恢复码 75 退出。接手后由协调器提交 4266，从同一 run 的该检查点继续。
- GB10 的 Nsight Systems 硬件计数器查询返回权限不足，无法直接测统一内存带宽。性能对照使用 CUDA 事件、算子采样和 Slurm 内的实际内存记录。
- 作业 4278 已完成性能短测，但切换后 GPU 进程一度占用约 109.4 GiB，系统可用内存降至约 1.9 GiB且正规更新未提交。确认完整第 74 次更新检查点字节一致后结束该作业。原 run 加入生产 allocator 上限、高分支 pack 的全层重计算及未提交窗口的 OOM 原样重放。
- 复测作业 4414 在首次加载探针中拦截并退出，尚未写入样本响应。冻结时 Dynamo 对原生 _norm_rope 触发了重编译上限，冷启动的融合路径与冻结探针最大 logit 差为 0.0203704833984。4415 仅在加载探针中复现该原生 eager 回退，严格比对误差为 0。探针结束后恢复正式推理的原融合函数并复查冷启动输出。M0/M1 的数据、适配器与协议身份字段逐项一致。正式复测使用两份 M1 权重哈希组成的独立缓存身份。

- 六源原件与 prepared 文件位于 `/home/shijunyu/kurumi-research/data/financial_m1/v1`。
- 训练、dev 逐题输出、Slurm 与恢复日志位于 `/home/shijunyu/kurumi-research/runs/training/m1/m1-finance-20261125T071740Z`。
- 选定模型及 last 恢复点位于 `/home/shijunyu/kurumi-research/models/kurumi-m1/m1-finance-20261125T071740Z`。
- M0 全精度来源位于 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z`。
- M1 全部响应、方向预测和 PI 官方轨迹位于 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m1/m1-eval-20261125T071740Z`。
- 逐样本和逐场景配对表位于 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m1/m1-eval-20261125T071740Z/paired`。逐源金融 dev 比较见 financial_dev_comparison.csv。

artifact_index.json 记录完整路径、字节数与 SHA-256。
