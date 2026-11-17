# 本地参考资料

仓库保存在 `reference/`，由根目录 `.gitignore` 忽略。研究清单和论文保存在 `docs/`。

已有 Karpo 目录保留；新增仓库使用 depth=1、blob:none 的浅层部分克隆及稀疏检出，禁用 LFS。跳过权重、CSV/Parquet等数据文件及部分数据目录；StockNet数据仓库仅检出说明。按需读取被省略的Git对象可能再次联网。未运行第三方代码或下载HF权重/大数据集。

## 仓库

| 仓库 | 本地路径 | HEAD | 保存结果 |
|---|---|---|---|
| AI4Finance-Foundation/FinGPT | `reference/FinGPT` | `ac5c5443fbeeafad801e7a3c188e4f24cfaad4d8` | ok |
| SUFE-AIFLM-Lab/Fin-R1 | `reference/Fin-R1` | `06ead1e61ff77cad71dc409198b1a2575d748ecd` | ok |
| The-FinAI/PIXIU | `reference/PIXIU` | `860d6a085378ee0bd2c21287d978f00393f17aaa` | ok |
| UBC-NLP/fintral | `reference/fintral` | `18e7328b471680bc8b52bfb3fa7eca2fd8465fb5` | ok |
| Zdong104/FNSPID_Financial_News_Dataset | `reference/FNSPID_Financial_News_Dataset` | `4054842ec476953b30ee874d4b7e8eea786a21fa` | ok |
| gpleiss/temperature_scaling | `reference/temperature_scaling` | `ce1154ec7d5235eee046f28875c3dd8421f11d45` | ok |
| jmichankow/deep_learning_probability | `reference/deep_learning_probability` | `debecb2998201b426765f0f3a31e9f0eaf5971b3` | ok |
| shiyu-coder/Kronos | `reference/Kronos` | `67b630e67f6a18c9e9be918d9b4337c960db1e9a` | ok |
| yumoxu/stocknet-code | `reference/stocknet-code` | `e32147c07c1e06033fcc8f76525a0c25e8babc16` | ok |
| yumoxu/stocknet-dataset | `reference/stocknet-dataset` | `330708b5ddc359961078bef469f43f48992fd6e4` | ok |

已有基座代码：`reference/karpo-decision/`，未拉取、覆盖或重置。

## 论文

15篇PDF及逐篇页数见 [论文目录](../papers/README.md)。FinGPT-Forecaster没有在原清单中列出单独论文，保留其源码和模型链接；其余15个条目各保存一篇。

- [研究筛选与适配建议](../research_references.md)
- [机器可读研究清单](research_catalog.json)
- [检索时GitHub版本](research_revisions.json)
- [实际下载与克隆记录](download_manifest.json)：下载URL、实际提交、PDF字节数、页数、SHA-256和首页文本核验。

## 复现

从项目根目录运行：

```powershell
& E:\quant\.venv\Scripts\python.exe scripts/fetch_references.py
```

需允许访问GitHub、arXiv和ACL，并有git、curl.exe、pdfinfo和pdftotext。已有目录与PDF默认保留，只读核验；源网站更新不会覆盖已有本地文件。未指定版本的arXiv链接首次下载时取网站当前版本，以文件哈希固定实际内容。
