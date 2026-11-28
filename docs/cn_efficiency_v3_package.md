# Kurumi V3 数值训练包

`pool/` 包含 10,376,684 个证券日的完整列式数据，包括逐日行情、个股因子、时点财务、市场和行业背景，以及 1、5、20 日的有效监督。目标日期、mask 和双精度真实收益与 r1 底表一致。`pool/training.json` 固定推荐输入配方和每条完整原生请求 3199 tokens 的验收上限。`tokenizer/` 和 `vendor/karpo-decision/` 分别保存锁定的 tokenizer 文件和带许可证的原生源码。

应整体迁移目录。数据、编解码工具及 Windows CPU 依赖可在目标目录内直接使用。`manifest.json` 记录各文件的 SHA-256 和字节数、数据谱系及冻结 M1 的兼容标识。验证文件时只需 Python 3.11 或更新版本。

```powershell
python scripts/verify_cn_efficiency_package.py
```

## 在 Windows 上本地生成训练视图和缓存

用 x86-64 CPython 3.11，在包根目录设置环境。运行时的版本清单在 `runtime/windows-cp311.lock.json`。

```powershell
$pkg = (Get-Location).Path
$env:PYTHONPATH = "$pkg/src;$pkg/vendor/karpo-decision/src;$pkg/runtime/windows-cp311"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CUDA_VISIBLE_DEVICES = '-1'
python -S scripts/verify_cn_efficiency_package.py --smoke
```

按实验决定设置 `$start`、`$end`、`$labelEnd` 和 `$budget`。`--budget` 是原样本数，也可用 `--token-budget` 按配置中的实测均长估算预算。可选 `--split` 保留原分区及其 mask。以下 `$view` 和 `$cache` 指向用户选定的新文件。CPU 验收目录里的 48 条 fit 和 8 条 confirm 仅用于安装和 packing 验证。

```powershell
python -S scripts/select_cn_efficiency_view.py --pool pool --output $view --start $start --end $end --label-end $labelEnd --budget $budget
python -S scripts/train_cn_efficiency.py --config pool/training.json prepare --pool pool --date-view $view --tokenizer tokenizer --view $cache --formats compact
```

可传入 `--confirmation-date-view` 单独准备确认视图。它的第一天须晚于拟合样本日和所有参与拟合的目标日期。每次缓存构建使用真实 Karpo Encoder 验收每条完整原样本，再把 token、标签、mask、权重及 packing 所需位置写入 SQLite。超限时构建报错，附带样本 ID。

## 在 Linux 训练环境中衔接冻结 M1

使用 Python 3.12 或更新版本和适配目标设备的 CUDA PyTorch 2.15.0 及 torchvision 0.29.2。数值输入准备依赖为 duckdb 1.5.5、pyarrow 23.0.1、numpy 2.4.6、transformers 5.23.0、tokenizers 0.23.3、jinja2 3.1.6、safetensors 0.8.0、pillow 13.0.0、pybase64 1.5.2。原生包的完整依赖声明在 `vendor/karpo-decision/pyproject.toml`。确保训练和缓存生成使用兼容的 tokenizer、模板及原生源码。

在有正式训练授权和设备资源时使用以下入口。传入原始 Karpo 基座目录和其 provenance、独立封存的冻结 M1 manifest、有明确预算的训练缓存及新运行目录。原始基座与 M1 权重是外部初始化资产，`manifest.json` 记录兼容版本及保护摘要。

```bash
export PYTHONPATH="$PWD/src:$PWD/vendor/karpo-decision/src"
python scripts/train_cn_efficiency.py --config pool/training.json train \
  --view "$CACHE" --model "$BASE_MODEL" --provenance "$BASE_PROVENANCE" \
  --m1-frozen "$M1_MANIFEST" --output "$RUN_DIR" --device "$DEVICE" \
  --format compact --max-updates "$MAX_UPDATES" --baseline-execution
```

CPU 验收复跑日期视图、监督和原生 packing，并导入冻结 M1 训练依赖。真实冻结权重加载和模型前后向需要已有训练设备及受保护资产。
