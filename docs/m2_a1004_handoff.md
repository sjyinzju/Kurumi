# M2 检查点备份与 GB10 交接

## A100 上的 HF 发布

脚本使用 `huggingface_hub` 和 `hf_xet` 访问既有模型仓库 `sjyinzju/Kurumi-Research`。A100 与 GB10 各自读取任务专用的权限为 `0600` 的纯 token 文件。控制机运行协调器时不需要访问 token 内容。将发布状态与凭据放在训练输出目录之外。

在 M1 迁移完成前，可用 `probe` 子命令验证仓库写权。用实际值设置下列路径和本轮训练 ID。

```bash
python scripts/m2_hf_artifacts.py probe --run-id "$RUN_ID" \
  --state-dir "$HF_STATE_DIR" --token-file "$HF_TOKEN_FILE"
python scripts/m2_hf_artifacts.py prepare --run-id "$RUN_ID" \
  --state-dir "$HF_STATE_DIR" --token-file "$HF_TOKEN_FILE" \
  --data "$SEALED_M2_ARCHIVE" --m1 "$FROZEN_M1_ARCHIVE"
```

`hf-write-verified.json` 记录小型准备清单的 HF commit。`prepared.json` 同时记录两个原始迁移包的发布 commit。发布进程随训练一起在 A100 的独立 tmux 会话中运行，标准输出保留在发布状态目录。重启同一命令会校验已上传内容并继续处理未上传的快照。

```bash
python -u scripts/m2_hf_artifacts.py watch --run-id "$RUN_ID" \
  --state-dir "$HF_STATE_DIR" --token-file "$HF_TOKEN_FILE" --run-dir "$TRAIN_RUN_DIR"
```

发布进程仅处理包含 `READY.json` 的原子检查点目录。训练进程写出 `TRAINING_COMPLETE.json` 后，发布进程检查训练封存清单与所有已备份快照的一致性，验证 HF 路径、大小和对象摘要，最后单独提交 `COMPLETE.json`。`published.json` 记录包含该标记的 HF 固定 commit。

## 写入凭据留在控制机时的异地检查点

在控制机的持久进程中启动以下拉取程序。它只读取准确指定的 A100 运行目录，每个 `READY.json` 检查点按远端文件 SHA256 校验，传输中断后从现有临时文件长度继续。全部文件校验后原子公开该检查点目录。正式训练封存后才拉取模型、验证、日志和来源文件，并写出本地 `TRAINING_COMPLETE.json`。拉取过程只需要经核对的 SSH 接入，无需 HF token。

```powershell
python -u scripts/m2_checkpoint_spool.py --ssh-helper $SshHelper --run-id $RunId `
  --source $A100TrainRunDir --spool $LocalTrainRunDir
```

控制机获准保存训练恢复点到 HF 时，可在相同本地运行目录上启动 `watch --checkpoints-only`。该模式复用不可变检查点路径与对象摘要验证，凭据留在控制机。它仅生成 `checkpoint-archive.json`，完整发布流程可复用已上传的恢复点。该回执不触发 GB10 接收或租赁释放。

## 控制机与 GB10

本地配置使用 JSON。以下是字段清单，具体值来自实际 SSH、目录和凭据准备记录。

| 位置 | 字段与用途 |
| --- | --- |
| 根 | `run_id` 为训练 ID，`eval_run_id` 为独立测评 ID |
| `a100` | `ssh_host`、可选 `ssh_args` 数组、`python`、`state_dir`、`instance_id` |
| `a100.identity` | `hostname` 与 `boot_id` 取自已登录的目标实例 |
| `gb10` | `ssh_host`、可选 `ssh_args` 数组、独立 `checkout`、`python`、`activate`、`runtime`、`state_dir`、`receive_dir`、`benchmark_dir`、`hf_token_file` |
| `gb10` 可选 | `data_archive`、`m1_archive` 指向可复用的已封存归档。缺少本地归档时由 GB10 从同一 HF commit 下载 |

`a100.state_dir` 对应发布命令的 `--state-dir`。`gb10.runtime` 使用 M2 单独的 TOML，`[m2].frozen_manifest` 为 `<receive_dir>/m2/<run_id>/model/manifest.json`，`benchmark_dir` 为 runtime 中 `<run_root>/karpo-m2/<eval_run_id>`。`gb10.python` 用于登录节点下载、校验和提交作业。模型加载由 `scripts/m2_gb10.slurm` 在 GPU 节点执行。

直接访问 HF 失败时，`scripts/m2_hf_ssh_relay.py` 可在控制机建立经授权 SSH 的反向回环转发。中继仅接受经认证的 CONNECT 到 Hugging Face 官方域名的 443 端口，保留终端 TLS 校验，并使用控制机现有 HTTPS 路由。`--ssh-helper` 指向本轮经核对的本地 SSH 接入模块；其中 `a100_client()`、`gb10_client()` 返回已校验宿主密钥的客户端。用 `--state-dir` 保留每台机器的中继凭据，重启时复用端口和凭据。远端发布命令用 `--proxy-file` 读取对应的私有中继配置，GB10 配置使用 `gb10.hf_proxy_file`。需要沿用本地 SSH 模块时，在 `a100` 和 `gb10` 下分别设置 `ssh_helper` 为文件路径，`ssh_connector` 为对应的连接函数。控制机失联期间，A100 训练仍可保存检查点，HF 发布和接收会在中继恢复后继续。

先将租赁实例和 GB10 的主机密钥加入当前账户的可信 SSH 主机记录，并确保 SSH 密钥在后台进程中可用。训练前运行以下现场检查。

```powershell
python scripts/m2_handoff.py preflight --config $HandoffConfig
```

在控制机的持久后台进程中运行下列命令。Windows 可用隐藏的 `Start-Process` 运行，并将标准输出和错误重定向至本轮日志。控制机或 VPN 恢复后以同一配置与状态文件重启协调器。A100 的训练与上传进程以及已经提交的 Slurm 作业会继续运行。

```powershell
python -u scripts/m2_handoff.py watch --config $HandoffConfig --state $HandoffState `
  --release-confirmation $ReleaseReceipt
```

协调器从发布回执获取固定 commit，从 GB10 获取 SHA256 校验回执，再提交正式测评。HF 持久保存全部恢复点。GB10 接收模型、全部验证、日志、来源记录、原始归档及最终恢复点。测评的首条有效预测回执绑定训练 ID、HF commit、模型摘要、测评 ID 与 Slurm job ID。只有该作业仍为 `RUNNING` 且有效预测文件存在时，协调器才在身份匹配的 A100 目标内调用矩池云释放命令。Slurm 超时、抢占或节点故障后的续跑复用同一测评 ID 和逐样本落盘。完成后的四项结果上传到训练目录下独立的 `benchmark/` 路径。

释放请求与计费终态分别记录。若已接入矩池云的鉴权状态查询，可将其命令参数数组写入 `a100.platform_status_command`。协调器在数组末尾添加实例 ID，读取该命令输出的 JSON。使用官方控制台观察终态时，将实际页面证据写成 `--release-confirmation` 指定的 JSON，包含 `provider`（`matpool`）、`instance_id`、`state`（`RELEASED` 或 `STOPPED`）、`billing_active`（`false`）、`checked_at` 与 `source`。SSH 断开后继续查平台状态。
