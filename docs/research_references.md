# Karpo 金融后训练研究参考

检索日期：2026-11-17，Asia/Shanghai。目标是让 `karpo-decision-31B` 接收自然文本及其他金融信息，在给定股票、决策时点和预测期限后，输出未来收益方向与幅度的概率信息。

本次筛选了16项参考。最值得先读的是 **FinGPT-Forecaster、AURA-4B、Newsflow 收益预测、收益分布 CNN/LSTM、温度校准和历史前视偏差研究**。它们分别解决样本组织、结果监督后训练、文本到收益、分布目标、概率质量和历史评价问题，组合起来比照搬单一金融聊天模型更贴近本项目。

用户提供的[分享页](https://chatgpt.com/share/6afb2a23-63a4-83e8-8eda-e33bc47ebb18)网页抓取返回 cache miss，浏览器访问超时，本次未读到正文。任务解释依据用户本条描述、根目录 AGENTS.md 和现有本地 Karpo 源码，不将分享页内容当作已验证证据。

## 与 Karpo 原生结构的关系

Karpo 的 `state` 可携带文本、JSON和图像，`questions` 指定待回答的选择问题；模型通过原生读出头给选项打分，无需生成回答文本。这与“自由组织证据、固定收益问题”的接口相容。[官方模型卡](https://huggingface.co/MachinePulseAI/karpo-decision-31B)、[官方代码](https://github.com/machinepulse-ai/karpo-decision)和本地 `reference/karpo-decision/src/karpo_decision/protocol.py`、`model/readout.py` 支持这一判断。

建议保留 `X_state` 的输入自由度，将股票、决策时点、交易日/自然日期限、收益口径明确到 `X_choice`。新闻段落、表格描述、杂乱笔记、行情摘要或图表可以有不同呈现，但系统仍需可靠识别它们属于哪一时点。传输接口使用JSON不要求用户把金融内容先整理为固定特征字段。

以互斥、穷尽的收益区间作为一个 `choice` 问题，可以从同一概率向量汇总方向和幅度。若按零收益划分，正区间概率之和为上涨概率，负区间之和为下跌概率；零收益的归属单独定义。跨越零的区间无法精确拆出正负概率，开放尾区间也没有天然中点，不能把区间中点加权结果称为精确期望收益。具体期限和分档仍待实验确定。

以下“可复用”均为本项目的适配判断。论文结果没有在本机复现；未下载模型权重或数据集，也没有执行第三方训练代码。7B/8B聊天模型的 LoRA 权重不能直接接到 Karpo 的不同骨干和读出结构上。

## 最接近目标的后训练与输入参考

| 编号 | 工作与原始入口 | 规模 | 值得参考 | 与本目标的距离 |
|---|---|---|---|---|
| R01 | [FinGPT-Forecaster 仓库](https://github.com/AI4Finance-Foundation/FinGPT/tree/master/fingpt/FinGPT_Forecaster)、[7B LoRA](https://huggingface.co/FinGPT/fingpt-forecaster_dow30_llama2-7b_lora)、[中文样本](https://huggingface.co/datasets/FinGPT/fingpt-forecaster-sz50-20230201-20240101) | Llama-2 7B | 新闻、历史行情、可选财务→未来一周涨跌区间；有训练和数据组织实现 | 生成预测说明，未直接提供校准收益分布；教师解释存在已知标签条件化 |
| R02 | [Can Language Models Learn to Forecast Stock Prices](https://arxiv.org/abs/2609.36914) | Qwen3 4B，AURA | SFT→PPO；按真实未来收益监督方向和幅度 | 工具调用与数值预测，非概率分布；官方实现/权重未确认，基准有结果筛选 |
| R03 | [Fine-Tuning Large Language Models for Stock Return Prediction Using Newsflow](https://arxiv.org/abs/2407.18103) | Mistral 7B、Llama3 8B、DeBERTa | 文本表征+预测头联合训练；LoRA；比较表征聚合 | MSE连续收益回归；数据为供应商新闻；官方公开训练仓库未确认 |
| R04 | [PIXIU 仓库](https://github.com/The-FinAI/PIXIU)、[论文](https://arxiv.org/abs/2306.05443)、[FinMA-7B-full](https://huggingface.co/TheFinAI/finma-7b-full) | 选7B分支 | 金融指令混合、预测任务与语言任务的组织 | 分类/文本答案，不等同于收益概率质量；不采用更大的分支 |
| R05 | [Open-FinLLMs 论文](https://arxiv.org/abs/2408.11878)、[FinLLaMA-instruct](https://huggingface.co/TheFinAI/FinLLaMA-instruct)、[FinLLaVA](https://huggingface.co/TheFinAI/FinLLaVA) | 8B系列 | 金融文本、表格、序列及图像的适配思路 | 任务面广；不建议复现其大规模持续预训练；未直接解决收益概率校准 |
| R06 | [FinTral 论文](https://arxiv.org/abs/2402.10986)、[官方仓库](https://github.com/UBC-NLP/fintral) | Mistral 7B | 文本/数值/表格/图像和DPO、检索工具的组合 | 当前仓库仅有标题式README，按论文参考处理 |
| R07 | [Fin-R1 论文](https://arxiv.org/abs/2503.16252)、[仓库](https://github.com/SUFE-AIFLM-Lab/Fin-R1)、[模型](https://huggingface.co/SUFE-AIFLM-Lab/Fin-R1) | Qwen2.5 7B | 财务问题筛选和分阶段SFT/GRPO | 主要是财务推理QA；公开根目录以文档/图片/报告为主，未见完整训练器 |

### 三项优先核读结论

**R01 FinGPT-Forecaster：优先借鉴样本构造和工程入口。** 已检查 `prompt.py`、`train_lora.py` 和目录。前者有把已知下一期区间标签提供给教师、再生成支持解释的流程。这可用于监督目标或解释蒸馏，`answer/label` 应留在 Y/训练目标侧；不能把这些事后解释作为当时可得的 `X_state`，或将教师解释当作独立预测验证。中文查看器可见 `prompt/answer/period/label/symbol`，适合讨论本项目样本契约，但未证明其全部样本满足历史财务可得性。Forecaster README 也明确发布的是监督 LoRA，未提供经过验证的 RLSP 训练器。[源码依据](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/fingpt/FinGPT_Forecaster/prompt.py)、[说明](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/fingpt/FinGPT_Forecaster/README.md)

**R02 AURA：优先读任务定义和评价限制。** 论文用4B模型做SFT和PPO，预测方向与幅度，且让训练标签的实现窗口早于测试决策窗口。其任务保留过程使用了实现结果，398个测试任务中240个进入最终幅度门槛评分，不能把其分数解释为未经选择的全市场表现。模型输出是数值收益预测，不能据该论文声称获得了校准的上涨概率。本次没有确认作者的完整训练仓库或可下载权重，同名GitHub结果未当作官方实现。[方法及限制](https://arxiv.org/html/2609.36914v1)

**R03 Newsflow：最贴近“文本表征直接学习未来收益”的方法参考。** 论文用LoRA适配LLM并训练稠密预测层，对比末端表征和全token平均聚合，以MSE监督收益。可借鉴这一研究设计，再围绕Karpo原生选择读出构造分布监督。其月度收益任务是论文设置，本项目不据此锁定预测期限；供应商新闻及未确认的公开训练代码限制了直接复现。[方法与实验设置](https://arxiv.org/html/2407.18103v1)

## 数据 对照与概率评价参考

| 编号 | 工作与原始入口 | 用途 | 关键限制 |
|---|---|---|---|
| R08 | [FinBen 论文](https://arxiv.org/abs/2402.12659)、[实现所在PIXIU](https://github.com/The-FinAI/PIXIU) | 分开衡量金融语言理解、预测和决策任务 | 总榜分数不替代本地收益分布评价；与R04共用仓库 |
| R09 | [FinMultiTime 论文](https://arxiv.org/abs/2506.05019)、[HF数据](https://huggingface.co/datasets/Wenyan0110/Multimodal-Dataset-Image_Text_Table_TimeSeries-for-Financial-Time-Series-Forecasting) | 中英新闻、表格、图表、序列的时间对齐及模态覆盖清单 | 论文称112.6GB；不同页面覆盖数字不一致，未下载认证 |
| R10 | [FNSPID 仓库](https://github.com/Zdong104/FNSPID_Financial_News_Dataset)、[论文](https://arxiv.org/abs/2402.06698)、[HF数据](https://huggingface.co/datasets/Zihan1004/FNSPID) | 新闻与价格数据管线；数据抓取、处理、对照实验模块 | 停止维护、说明授权矛盾；HF查看器有类型解析错误 |
| R11 | [StockNet 论文](https://aclanthology.org/P18-1183/)、[代码](https://github.com/yumoxu/stocknet-code)、[数据](https://github.com/yumoxu/stocknet-dataset) | 较小的文本+价格方向预测对照；随机性建模 | 2018年技术栈、特定历史股票池；标签不能直接继承 |
| R12 | [Kronos 仓库](https://github.com/shiyu-coder/Kronos)、[论文](https://arxiv.org/abs/2508.02739)、[small模型](https://huggingface.co/NeoQuasar/Kronos-small) | 仅行情输入的轻量对照；金融序列微调管线 | mini 4.1M、small 24.7M、base 102.3M；无自由文本输入，生成采样频率仍需校准 |
| R13 | [收益分布CNN/LSTM论文](https://arxiv.org/abs/2508.18921)、[代码](https://github.com/jmichankow/deep_learning_probability) | 直接预测Normal/t/偏t分布，用NLL、CRPS等评价幅度和尾部 | 指数序列任务，不含自由文本；未核实精确参数量 |
| R14 | [Dutch Books for Language Models](https://arxiv.org/abs/2609.02797) | 以股票收益构造关联事件，检查概率逻辑相容性 | 逻辑相容性、校准和预测准确率是不同指标；官方实现未确认 |
| R15 | [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599)、[代码](https://github.com/gpleiss/temperature_scaling) | 用独立验证集拟合temperature，校准选择概率 | 原论文不是金融时序实验；需检验市场漂移，禁止用测试标签调温度 |
| R16 | [Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis](https://arxiv.org/abs/2309.17322) | 具名/匿名文本对照，检查预训练知识与前视偏差 | 匿名化是敏感性检查，不能证明基座没有记忆历史 |

R13 的代码入口为 `SCRIPTS/prob_nn.ipynb` 和 `prob_nn_var_es.R`，适合学习连续分布损失及风险评价。该文中的 PIT 指 **probability integral transform（概率积分变换）**，与本仓库数据工程中的 point-in-time 可得性是两个概念。[作者仓库](https://github.com/jmichankow/deep_learning_probability)

## 可获得性与复用边界

- **可检查的训练入口**：FinGPT有 `train_lora.py`；Kronos README给出 `finetune/config.py`、tokenizer和predictor微调入口。StockNet和收益分布项目有代码目录，但旧依赖及数值实现仍需后续验证。这里只确认入口存在及所读内容，未认定所有实现可直接运行。
- **公开仓库不等于完整训练复现**：FinTral根目录仅README；Fin-R1根目录是README、图片和技术报告；AURA和Newsflow的官方完整训练实现未确认。它们保留为论文参考。
- **Open-FinLLMs版本需要固定**：FinLLaMA-instruct模型卡要求接受访问条件，并记录过错误上传其他骨干checkpoint、随后恢复8B模型的事件。将来使用应固定revision并检查config和权重结构，不能只凭仓库名称判断。[模型卡说明](https://huggingface.co/TheFinAI/FinLLaMA-instruct)
- **FinMultiTime不是已经导入的数据**：摘要、HTML和HF卡的股票覆盖数字不同，HF默认查看器只显示9条图像验证样本，这不足以认证完整多模态语料。本地原始文件、首次公开时间和修订版本尚未检查。[论文HTML](https://arxiv.org/html/2506.05019v2)、[数据卡](https://huggingface.co/datasets/Wenyan0110/Multimodal-Dataset-Image_Text_Table_TimeSeries-for-Financial-Time-Series-Forecasting)
- **FNSPID需先小范围解析**：README日期为2025-07-24的说明称停止维护并放开使用，旧段落却仍限制商业使用；HF查看器报Arrow类型转换错误。后续需明确权限并对文件显式指定schema，查看器失败不能直接推断所有原始CSV损坏。[README](https://github.com/Zdong104/FNSPID_Financial_News_Dataset)、[HF状态](https://huggingface.co/datasets/Zihan1004/FNSPID)
- **权重与代码分开核对**：仓库或adapter页面的MIT/Apache标记不能替代基础Llama模型条款。此次只记录入口和明显限制，未作全面许可审查，也未接受门禁或下载权重。

## 面向本项目的建议

1. **先做分布监督的最小研究闭环。** 参考R01组织证据和收益标签、R03设计直接收益监督、R13设计概率评价，围绕Karpo原生readout输出收益区间概率。保留仅训练读出与进一步适配骨干的对照，不先扩大到工具调用RL。
2. **分别验证输入内容和呈现形式的增量。** 在同一证券—时点—标签上，比较结构化数据、有/无新闻、不同文本来源；再对同一信息生成段落、表格、顺序变化等表述版本，单独测格式鲁棒性。数据内容或信息时点改变的样本不能算纯格式扰动。
3. **同一分布派生方向和阈值概率。** 参考R14检查上涨/下跌互补、尾概率随阈值单调、区间可加性。不同期限不是同一事件，跨期限不随意施加单调约束。R15的校准只在历史验证窗拟合，最终测试窗保持独立。
4. **结果监督与概率质量匹配。** SFT可从真实区间标签的交叉熵起步；若后续尝试R02式结果反馈，再评估其是否改善log loss、Brier或分布评分。方向正确率、解释流畅度和交易收益分别报告，不能相互替代。
5. **先解释现有数据缺口再迁移外部数据。** [本地盘点报告](data_report.md)已记录历史主表关联、BSE日历、指数异常和文本缺口。R09/R10作为补充语料候选，不把数据卡或旧基准标签直接视为本项目已通过PIT检查的数据。
6. **保留历史记忆风险的独立结论。** 参考R16做具名/匿名、不同时间窗和前向留出对照；匿名化会改变输入含义，也可能仍可识别公司。时间切分和标签隔离有必要，但不能消除基座预训练记忆的可能性。

建议阅读顺序：R01与R03 → R13与R15 → R16与R14 → R02 → 根据文本/图像需求补读R04/R05/R09。R06/R07作为扩展阅读；R11/R12用于限制计算量的对照。

## 检索记录

机器可读的逐项链接、规模、复用点、限制和检查范围见 [research_catalog.json](references/research_catalog.json)。10个不同GitHub仓库的检索时提交元数据见 [research_revisions.json](references/research_revisions.json)；FinBen与PIXIU共仓，StockNet代码与数据分仓，资源条目数不等于独立仓库数。

检索阶段GitHub通过连接器读取，论文和HF通过网页读取；论文摘要、README和代码检查深度已逐项标注。未将检索到的同名非官方项目当作作者实现，也未将论文性能数字当作本项目实测结果。随后按用户要求克隆仓库并保存论文，本地路径、版本、哈希与保存结果见 [本地资料索引](references/README.md)。`reference/`不再由本项目Git跟踪，目录中的现有Karpo参考项目保留。
