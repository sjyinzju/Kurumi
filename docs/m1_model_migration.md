# Kurumi M1 模型保存与迁移

后续训练从按两轮金融 dev 平均 CE 选定的 M1 初始化。训练产物目录中的 `model_portable.json` 记录迁移包路径、完整 SHA-256、逐文件哈希和选中 epoch。GB10 上的 `frozen/` 保留选定权重，`last.pt` 保留本轮最后一个优化器边界的训练恢复状态。

## 迁移与校验

将 `kurumi-m1-portable.tar` 复制到目标机器并与 `model_portable.json` 中的 SHA-256 核对。在 Linux 上解包和检查。

```bash
sha256sum kurumi-m1-portable.tar
mkdir -p /destination/kurumi-m1
tar -xf kurumi-m1-portable.tar -C /destination/kurumi-m1
cd /destination/kurumi-m1
sha256sum -c SHA256SUMS
chmod a-w manifest.json lora.safetensors readout.safetensors
```

迁移包内的 `manifest.json` 用相对路径引用 LoRA 和完整 Readout。基座使用 `MachinePulseAI/karpo-decision-31B@b8e6fd7463cea8662c556d6257955d7ef9c10d19`，原生代码使用 `6600011eb5cf46232d056ec0717dc726146d29de`。通过 `base-model-manifest.json` 核对目标机上原始基座的文件大小和哈希。清单中 `sha256` 直接对文件字节计算，`git_blob_sha1` 对 Git blob 头和文件字节计算。通过 `native-identity.json` 核对原生代码版本和源文件哈希。

## 加载与探针

从 Kurumi 仓库根目录、使用目标节点的 Karpo 环境运行。将示例路径替换为目标机上的精确基座目录和已解包的迁移包目录。

```bash
PYTHONPATH=src python - /destination/karpo-decision-31B /destination/kurumi-m1 <<'PY'
import sys
from pathlib import Path

import torch
from karpo_decision.decider import Decider
from kurumi.karpo_numeric import _plan_from_bytes
from kurumi.m1_model import frozen_identity, load_frozen, sha256
from kurumi.m1_probe import verify_frozen_probe

base, bundle = map(Path, sys.argv[1:])
manifest = frozen_identity(bundle / "manifest.json")
probe = bundle / manifest["portable_probe"]["path"]
assert sha256(probe) == manifest["portable_probe"]["sha256"]
ckpt = load_frozen(base, manifest, torch.device("cuda:0"))
decider = Decider(ckpt, max_length=32768, token_budget=32768)
sequences = _plan_from_bytes(probe.read_bytes())
print(verify_frozen_probe(lambda: torch.cat(decider.logits(sequences)[0]), manifest["fixed_logits"]))
PY
```

这个严格阈值用于本轮加载校验。换卡时记录 CUDA、PyTorch、实际注意力和矩阵乘法路径以及探针误差，核验通过后再启动后续训练。

后续分支复用加载时已经挂载的 LoRA。在自己的模型实例中为 LoRA 的 A、B 和 Readout 开放梯度，并构造该分支的优化器、调度器和数据清单。原始参数保持冻结，分支权重与日志保存到独立目录。
