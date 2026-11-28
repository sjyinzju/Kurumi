# Kurumi M2 数值训练迁移包

包中保存 `v3_final_full60` 的 60,000 条训练与 3,000 条固定验证原样本。`native.sqlite` 是直接训练入口。每条包含 1、5、20 会话决策及各七个选项。`train.parquet`、`validation.parquet` 保存选中样本、监督、mask 和逆入选权重。选样、覆盖、长短分布及 CPU 验收分别记录在 `selection.json`、`coverage_report.json`、`native_audit.json` 和 `cpu_relocated_readback.json`，汇总见 `report.md`。

## Linux x86_64 校验与环境

```bash
sha256sum -c m2-v3-60k-ready.tar.gz.sha256
tar -xzf m2-v3-60k-ready.tar.gz
cd m2-v3-60k-ready
sha256sum -c SHA256SUMS
```

使用 Linux x86-64 CPython 3.12。为目标平台安装 PyTorch 2.15.0 和 torchvision 0.29.2 的兼容 CUDA 构建，随后执行 `python -m pip install -r requirements-linux.txt`。固定 Karpo 源码、原生版本清单与 Apache-2.0 许可证在 `vendor/karpo-decision/`。`requirements-linux.txt` 保留 V3 训练与数值准备版本，原生包完整依赖声明见其 `pyproject.toml`。A100 的 CUDA 安装、注意力和四卡分片在目标机器验收。Windows CPU、Linux x86-64 和 GB10 ARM64 各自构建环境，可共享 SQLite、Parquet、源码、tokenizer 与适用权重。

可选的 CPU 回读从包内真实 SQLite 读取少量原样本并检查 native packing。

```bash
CUDA_VISIBLE_DEVICES=-1 PYTHONPATH="$PWD/src:$PWD/vendor/karpo-decision/src" \
  python scripts/verify_cn_efficiency_m2.py --readback
```

## 外部模型资产与启动

- `BASE_MODEL` 指向原始 `MachinePulseAI/karpo-decision-31B@b8e6fd7463cea8662c556d6257955d7ef9c10d19` 完整快照。保持文件只读。`BASE_PROVENANCE` 指向对应的 `model-manifest.json`，也可使用 M1 迁移包里的 `base-model-manifest.json`。
- `M1_MANIFEST` 指向 `m1-finance-20261125T071740Z` 的冻结 epoch 1 `manifest.json`。可用原 `frozen/` 目录或既有 `kurumi-m1-portable.tar` 解包目录，LoRA 与 Readout 文件留在同一目录。按 `m1_source.json` 核对对应清单和迁移包 SHA-256，解包后执行 `sha256sum -c SHA256SUMS` 与 `chmod a-w manifest.json lora.safetensors readout.safetensors`。
- `RUN_DIR` 指向训练输出目录。冻结资产凭据来自 M1 交付收据和 V3 兼容性清单。本地 CPU 验收使用合成张量验证保存与加载逻辑。

从解包后的目录用目标环境的 Python 启动。下面是当前单进程接口，正式运行在新增的四卡分片接口验收后进行。

```bash
bash scripts/run_cn_efficiency_m2.sh "$BASE_MODEL" "$BASE_PROVENANCE" "$M1_MANIFEST" "$RUN_DIR"
```

当前单卡每次优化器更新 4 个原样本，一遍为 15,000 次更新，验证边界为 5,000、10,000、15,000。四卡接入时明确全局原样本批量，并据此复核更新数和损失归一化。在同一目录从 `last.pt` 恢复时，将 `--resume` 加在脚本参数末尾。

运行结束后，通过 `RUN_DIR/best.json` 的相对 `manifest` 路径找到冻结 M2。每个候选保存验证指标、逐原样本概率和独立 LoRA/Readout。`kurumi.cn_efficiency_m2.load_frozen_m2(base_dir, provenance, manifest, device)` 读取原始基座与该 M2 的完整 LoRA 和 Readout，覆盖训练更新后的完整参数。资产布局沿用 `6600011eb5cf46232d056ec0717dc726146d29de` 的原生接口。

## 重建本地视图或缓存

训练可直接读取随包交付的 SQLite。重建才需要 `FROZEN_V3` 指向冻结 V3 final 根目录，对应提交 `b5ceff6191d488557f4f804a1f4f194d1efbc4c1`。现有本机目录为 `E:/Kurumi/artifacts/cn-efficiency-v3/final/`。顶级 `manifest.json` 的文件 SHA-256 为 `0540ef90859b474aa19041ae59cd75df93ef8bd3a0a033b728b0dabc14aee36f`，池清单的文件 SHA-256 见本包 `manifest.json` 的 `source_v3_pool_manifest_sha256`。保留冻结原始数据只读。

从解包目录设置依赖路径，再指定独立的重建输出 `VIEW_DIR` 与 `REBUILT_CACHE`。

```bash
export PYTHONPATH="$PWD/src:$PWD/vendor/karpo-decision/src"
export CUDA_VISIBLE_DEVICES=-1
python scripts/select_m2_v3.py --pool "$FROZEN_V3/pool" --output "$VIEW_DIR"
python scripts/train_cn_efficiency.py --config training.json prepare \
  --pool "$FROZEN_V3/pool" --date-view "$VIEW_DIR/train.parquet" \
  --confirmation-date-view "$VIEW_DIR/validation.parquet" --tokenizer tokenizer \
  --view "$REBUILT_CACHE" --formats compact
```
