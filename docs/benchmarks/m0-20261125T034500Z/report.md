# Kurumi M0 外部 benchmark v1

**COMPLETE** · 6,192 条方向预测 · 90 个 PI 场景 · 2,070 道 PI 问题。

## 模型与运行

- 原始模型为 `MachinePulseAI/karpo-decision-31B@b8e6fd7463cea8662c556d6257955d7ef9c10d19`，原生代码提交为 `6600011eb5cf46232d056ec0717dc726146d29de`。
- NVIDIA GB10，计算能力 12.1，PyTorch 2.14.1+cu130，Transformers 5.17.0。 原生骨干为 BF16，Readout 为 FP32。
- 模型使用 `karpo-blocks-v1` 模板和 `bidirectional` attention，保留 255 个原生答案代码。choice、noul、score 温度均为 1.0。每个请求独立运行，batch size 为 1，随机种子为 17，max length 和 token budget 均为 32,768。
- 原生编码器检查了全部请求。各项最大 token 数依次为 822、2,085、4,390 和 13,147，每个完整请求均为一条序列。
- 北京时间 2026-11-25 11:41:54 到 14:13:38，含恢复间隔共 2 小时 31 分 44 秒。成功作业 4253 在 pgx03 运行 2 小时 19 分 52 秒，PID 1691032。四项已保存响应的实测耗时合计 2 小时 10 分 09 秒，含首次原生内核编译。
- 首次作业 4252 因 Triton 编译缺少 Python.h 中止。将匹配的 Ubuntu arm64 Python 3.12 头文件解包到个人缓存后，用同一运行 ID 恢复。PI scorer 使用新增的 pandas 2.3.3。
- 两个受限 FinBen 分片使用已授权的浏览器账户下载后传到 GB10。AlphaFin 通过现有代理直接写入 GB10，PI 从官方源直下。正式适配、推理和评分均在 GB10。

## 方向预测

| Benchmark | 成功 / 预期 | Accuracy | MCC | Brier | NLL | TP | TN | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FinBen BigData | 1,472 / 1,472 | 54.14% | 0.040208 | 0.249428 | 0.692553 | 603 | 194 | 465 | 210 |
| FinBen ACL | 3,720 / 3,720 | 48.87% | -0.025636 | 0.270049 | 0.740834 | 1037 | 781 | 1031 | 871 |
| AlphaFin-Test | 1,000 / 1,000 | 48.30% | -0.021305 | 0.366856 | 1.110551 | 353 | 130 | 386 | 131 |

Accuracy、MCC、二元 Brier 和自然对数 NLL 已从原始响应和独立标签复算。机器可读产物保留全精度概率。

## PI Round 2/full

使用官方策略 `pick>=0.5`，从 USD 1,000 开始回放。完成 90/90 个场景、2,070 道问题和 91 个权益时点。最终净值 USD 816.38，收益率 -18.36%，最大回撤 -20.88%，切换 43 次，空仓 13 步。

在同一行情、题目与策略的 15 个模型中排第 14。同次回放中 morph-reflex 为 USD 1,065.77，买入持有 QQQ 为 USD 1,038.06，现金为 USD 1,000.00。其他模型使用官方快照中的缓存。 [PI Round 2 回放说明](https://pilabs.space/trading-arena/README.md)

## 论文参考

FinBen 论文附录 G 中 SLOT 的 Accuracy／MCC 在 BigData22 为 0.55／0.10，在 ACL18 为 0.59／0.21。论文的 BigData22 统计为 1,470 条，本轮固定 Hugging Face 版本为 1,472 条。ACL18 样本数相同，输入接口与论文评测方式仍有差异。 [FinBen 论文表 2 与表 14](https://arxiv.org/html/2402.12659)

AlphaFin 论文表 2 中 Stock-Chain 的 Accuracy 为 55.7%，记为 published_reference。公开后处理包含去重和无效文本回答替代，本轮对全部 1,000 行执行原生二选一。 [AlphaFin 论文](https://aclanthology.org/2024.lrec-main.69.pdf) · [公开后处理](https://github.com/AlphaFin-proj/AlphaFin/blob/main/src/stage1_trend_prediction/dataprocess_stockgpt.py)

原始基座对历史测试记录的暴露仍待核实。后续训练的保留范围记录在 Kurumi 仓库的 holdout_v1.md。

## 产物与复跑

- 运行目录 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z`
- 原始文件与独立 prepared 数据 `/home/shijunyu/kurumi-research/data/benchmarks/v1`
- 绝对路径及 SHA-256 索引 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z/artifact_index.json`
- 原生配置、来源锁和代码快照 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z/protocol`
- PI 官方回放 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z/pi_round2_full/replay/rounds/round2/full`
- 两次作业的日志 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z/slurm-4252.log` 和 `/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z/slurm-4253.log`

恢复此运行 ID 的 Slurm 命令如下。入口按模型、源输入和协议校验已保存响应。该运行已完成，重复提交会返回 COMPLETE。

```bash
run="/home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z"
sbatch --parsable --partition=gpu --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=108G \
  --gres=gpu:1 --time=04:00:00 --job-name=kurumi-m0-v1 --export=NONE \
  --open-mode=append --output="$run/slurm-%j.log" "$run/slurm.sh"
```

在已分配 GB10 的作业里启动一份新的完整运行。

```bash
source /home/shijunyu/kurumi-research/activate.sh
headers=/home/shijunyu/kurumi-research/cache/native-build/python-3.12.3-1ubuntu0.17-arm64/usr/include
export CPATH="$headers/python3.12:$headers:$headers/aarch64-linux-gnu/python3.12"
cd /home/shijunyu/kurumi-research/Kurumi
/home/shijunyu/kurumi-research/.venv/bin/python -u scripts/run_benchmarks.py run \
  --run-id "m0-$(date -u +%Y%m%dT%H%M%SZ)"
```

PI 原执行命令在独立 replay 根目录运行。

```bash
cd /home/shijunyu/kurumi-research/runs/benchmarks/v1/karpo-m0/m0-20261125T034500Z/pi_round2_full/replay
/home/shijunyu/kurumi-research/.venv/bin/python -m arena.simulate round2 full
```
