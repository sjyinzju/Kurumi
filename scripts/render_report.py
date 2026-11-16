"""Render reports only from saved audit evidence; never query the source here."""
import argparse
import json
from pathlib import Path


def load(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def cell(value):
    return str(value).replace("|", "／").replace("\n", " ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=Path("docs/inventory"))
    root = parser.parse_args().inventory
    data = load(root, "datasets.json")
    if "finished_utc" not in data:
        raise RuntimeError("Full audit has not finished")
    fs = load(root, "filesystem_data.json")
    load(root, "filesystem_code.json")  # Require the paired code census before reporting completion.
    supplement = load(root, "supplement.json")
    auxiliary = load(root, "auxiliary_tables.json")
    fields = load(root, "fields.json")
    schemas = load(root, "schema_partitions.json")
    relationships = load(root, "relationship_details.json")
    datasets = data["datasets"]
    by_name = {item["dataset"]: item for item in datasets}
    by_field = {(field["dataset"], field["field"]): field for field in fields}
    gap_count = data["cross_checks"]["calendar_gaps_within_observed_symbol_span"]
    suspend_count = relationships["gaps_matching_same_day_suspend_S"]
    active = sum(x["active_files"] for x in datasets)
    errors = sum(len(x["errors"]) for x in datasets)
    present = [x for x in datasets if x["active_files"]]
    successful = [x for x in present if "logical_rows" in x and not x["errors"]]
    logical = sum(x["logical_rows"] for x in successful)
    cap = {x[0]: x[1] for x in data["capabilities"]}
    lines = ["# 真实数据盘点报告", "", f"扫描开始（UTC）：{data['started_utc']}；查询结束：{data['finished_utc']}。",
        "用户本地时区为 Asia/Shanghai（UTC+8）；这两个时间为本次实际执行时钟。外部数据未更新或改写。本报告不宣称研究/生产就绪。", "",
        "## 结论与口径", "",
        f"发现 {len(datasets)} 个来源契约，{len(present)} 个有当前有效 Canonical 文件；{len(successful)} 个完成全字段全行 SQL 解码与统计，逻辑行合计 {logical:,}。有效文件共 {active:,} 个，扫描错误 {errors} 项。无文件的契约不视为已拥有的数据。",
        f"股票日线实际截止：{by_name['daily']['ranges']['trade_date'][1]}，不能视为截至本次盘点日的最新行情。没有完整的独立文本正文库，也没有可直接沿用的本研究标签。",
        f"主要实质风险：日历覆盖和历史股票主表关联存在缺口；当前主表漏掉{len(relationships['master_orphan_codes'])}个有历史行情的代码；指数日线存在大量空OHLC及{by_name['index_daily'].get('value_checks', {}).get('close<=0', '未完成检查')}条非正收盘价，不能直接作为完整指数特征输入。",
        f"本次全目录文件普查：{sum(x['files'] for x in fs['groups'].values()):,} 个文件，{sum(x['bytes'] for x in fs['groups'].values()):,} 字节（逻辑文件容量，非 NTFS 实际分配空间）。目录访问问题 {len(fs['errors'])} 项。",
        "目录统计、footer 行数、逻辑行数均为明确范围内精确值；没有用抽样估算全库行数。不存在的数据不生成模拟替代。有效物理行不等于逻辑样本，旧文件与缓存不能叠加。", "",
        "## 检查方法与可复现命令", "", "```powershell",
        "cd E:\\Kurumi", "& E:\\quant\\.venv\\Scripts\\python.exe -u scripts/inventory.py",
        "& E:\\quant\\.venv\\Scripts\\python.exe scripts/supplement.py",
        "& E:\\quant\\.venv\\Scripts\\python.exe scripts/auxiliary_tables.py",
        "& E:\\quant\\.venv\\Scripts\\python.exe scripts/schema_consistency.py",
        "& E:\\quant\\.venv\\Scripts\\python.exe scripts/relationship_details.py",
        "& E:\\quant\\.venv\\Scripts\\python.exe scripts/render_report.py", "```", "",
        f"运行环境：Python `{data['python'].split()[0]}`；DuckDB `{data['duckdb']}`；其余依赖版本见 `environment.json`。未安装依赖、未加载凭证、未请求外部 API。",
        "1. `os.scandir` 递归统计 QuantData 所有普通文件的路径分组、字节、扩展名和 mtime；不跟随符号链接。空目录另在初始化时检查。quant 代码树排除环境、Git、依赖/工具缓存（排除清单在 JSON）；这些目录不作为数据源。",
        "2. 外部 DuckDB `read_only=True`，读取 active 指针并保存 `active_files.csv`，逐一读取全部有效 Parquet footer，比较每分区 schema。注册行数与 footer 行数分别保留。只读事务中的 active 列表是盘点输入，非新建数据版本。",
        "3. 复用 `quant.data.storage.lake` 的 SQL。对全部有效物理行计算物理行、不同内容观察对、不同内容数；再按原契约自然键/内容键取最新观察版本，落盘到本仓库临时审计库，统计所有字段 NULL、浮点非有限值、时间范围、代码覆盖、键空值及若干价格异常。逻辑视图用于盘点，**不能作为历史 X_state**。",
        "4. 日线与因子、daily_basic、涨跌停、主数据、交易所日历作全量关联。时间缺口以每证券首末已见日之间的开市日为分母，未扣停牌或特殊生命周期；不能直接解释为数据遗漏。",
        f"5. Raw 仅确定性抽样：每个有批次的 endpoint 按路径排序前三个文件，共 {len(supplement['raw_samples'])} 个，4096 行/批完整解码；注册表 Raw 总行数仅元数据声明，未重解码所有 Raw。非活动/孤立 Canonical 仅目录容量普查，未全量解码或重新计算 SHA256。",
        "6. Qlib 所有二进制文件只检查字节长度可被4整除且含首个 float32 日历偏移；每导出读取前三个文件的头64字节。未全量验证缓存数值/哈希或日历对齐。CSV 审计表按行流式计数；SQLite 用 mode=ro 读取 schema 和行数。旧审计快照 DuckDB 未逐库重审。",
        "7. 首轮 1GB/四线程 DISTINCT 聚合触及内存上限，已停止并改用可落盘 GROUP BY、单线程3GB后重跑。指数日线 latest 窗口仍触及上限，再按自然键含日期的事件年分区独立解析版本；补跑命令为 `scripts/inventory.py --retry-errors --skip-tree`。仅在源库 size/mtime 与前次结束一致时允许补跑，前次错误保留在 retry_history；最终表只使用最终结果。", "",
        f"源数据库前后 size/mtime 一致：`{data['source_db_before'] == data['source_db_after']}`；仅是附加观察，不替代只读连接保障。未尝试源码 Git 状态修复；`git -C E:\\quant rev-parse HEAD` 被权限限制，改保存 {len(supplement['source_hashes'])} 个非敏感来源代码/配置内容哈希。", "",
        "## 来源、链路与复用", "",
        "已读取外部 README、设置、来源适配器、字段契约、存储/校验、PIT、复权、股票池、动量和 Qlib 导出代码。主要来源是 Tushare HTTPS JSON API；本轮依据本地保存的 `official_api_schema.json` 获取字段语义和来源 URL，未在线重核官方定义，描述的真实性限于这份保存记录。Raw 不是交易所原始逐笔或原始公告正文。",
        "`fetch_tasks → raw_batches → 00_raw/tushare/<endpoint>/<抓取年>/<月>/<batch>.parquet + JSON → validate_frame → 10_canonical/<endpoint>/<事件年/月或snapshot>/<uuid或compact>.parquet → canonical_parts(active) → latest / PIT → dataset_versions manifest → Qlib`。",
        "Canonical 按契约统一数值为 double、文本为 string，附观察/可得时间、内容/版本/批次哈希；压实保留历史观察，旧文件仍存在。事件无源 ID 时用内容键，不能把两次同值事件证明为同一真实事件。`_batch_id` 连 raw_batches；Raw sidecar 连 task、请求参数及文件哈希。源财报有不同报告类型/更新标志，不能随意合并。",
        "主关联为行情/因子/估值/涨跌停的 `(ts_code,trade_date)`，主数据以 ts_code 关联，指数成分以 `(index_code,con_code,trade_date)`，行业按 in_date/out_date 映射但仍需可得时钟；宏观为 date/month/quarter，绝不能按统计期当公开日。全部自然键见下表与 datasets.json；字段及元数据含义见字段字典。",
        "仓库初始仅 AGENTS.md，无 reference 项目。新建的 reference/README.md 是只读参考索引，未复制外部代码。`Registry` 构造会写目录/DDL，禁止在盘点调用。外部旧项目评估文档提及的 E:\\AI_quantization 不在本轮实查范围。", "",
        "## 目录与容量", "", "容量按所有文件相加，含旧版和重复缓存。具体路径例子、扩展名及修改时间在 filesystem_data.json。mtime 不是信息发布时间。", "",
        "| 目录（E:\\QuantData 下） | 文件数 | 字节 | 最近文件修改 UTC |", "|---|---:|---:|---|"]
    for key, value in fs["groups"].items():
        lines.append(f"| {key} | {value['files']:,} | {value['bytes']:,} | {value['latest_mtime_utc']} |")
    lines += ["", "`20_pit/30_features/50_predictions/60_backtests/70_live` 初始化时文件遍历为空，不能把目录存在当作已拥有特征、标签或预测。quant 的 .venv/.git 和 .cache/uv 依赖缓存未统计字节；不是本轮市场数据集。其余 .cache 下的 pytest、元数据恢复和读取基准缓存单独普查，见 supplement.json 的 quant_cache_census，未将测试数据当作生产样本。", "",
        "## 全部数据集", "", "绝对路径、分区列表、物理版本行、文件数/容量和所有质量计数均见 datasets.json；有效文件逐项见 active_files.csv。以下行数为本次 latest 逻辑精确统计；‘无有效文件’不等于该接口从未有过数据。日期取契约 _event_date，主数据是上市日、财务常为公告日、宏观常为统计期末，不是统一交易日期。", "",
        "| 数据集 | 类别/频率 | 行数 | 事件时间范围 | 覆盖(ts_code数) | 自然键 | 已记录权限状态 |", "|---|---|---:|---|---:|---|---|"]
    for item in datasets:
        ranges = item.get("ranges", {}).get("_event_date", [None, None])
        lines.append("| " + " | ".join(map(cell, [item["dataset"], item["category"] + "/" + item["frequency"],
            item.get("logical_rows", "无有效文件" if not item["active_files"] else "扫描失败"),
            f"{ranges[0]} ~ {ranges[1]}", item.get("coverage", {}).get("ts_code", "不适用"),
            ",".join(item["primary_key"]) or "内容身份，无源事件ID", cap.get(item["dataset"], "未记录")])) + " |")
    lines += ["", "权限状态是 endpoint_capabilities 的历史探测值，并非本轮联网验证；例如 empty 状态与磁盘已有历史记录可以同时成立。抓取时间范围在每表 ranges._ingested_at（序列化保留显式时区偏移，如+08:00，与底层UTC时刻等价），mtime 在目录清单；没有据此承诺更新频率。", "",
        "## 质量与完整性", "", "NULL 分母均为该字段所属数据集的 latest 逻辑行数；nonfinite 只检查 float/double，NaN/Inf 不等于 SQL NULL。全部原始计数见 fields.json。以下只展示发现项，未展示项不扩展为未执行检查的通过。", "",
        "| 数据集 | NULL字段数 / 已观察字段数 | 全NULL字段数 | 浮点非有限值 | schema变体数 | 物理行−观察对（重复观察） | 观察对−内容数（重观察） |", "|---|---:|---:|---:|---:|---:|---:|"]
    for item in present:
        ff = [f for f in fields if f["dataset"] == item["dataset"] and f["quality"]]
        dup = item.get("physical_duplicate_stats", [0, 0, 0])
        lines.append(f"| {item['dataset']} | {sum(f['quality']['nulls']>0 for f in ff)}/{len(ff)} | {sum(f['quality']['nulls']==f['quality']['rows'] and f['quality']['rows']>0 for f in ff)} | {sum(f['quality'].get('nonfinite',0) for f in ff)} | {len(item['schema_variants'])} | {dup[0]-dup[1]:,} | {dup[1]-dup[2]:,} |")
    lines += ["", "不同 schema 指纹可能来自 timestamp 单位/null 类型差异，不能一概称为字段丢失；每个变体字段与类型已完整列入 datasets.json，可按分区/文件回溯。未观察到的契约字段在字典标记无实际类型。业务键版本差异先保留再取 latest；上述‘重复观察’不是删除建议。缺失率仅检查 SQL NULL，未将空字符串/来源哨兵值全部归类为缺失；经济含义离群值也没有全字段阈值认证。", "",
        f"分区 schema 复核：{schemas['files_checked']:,} 个有效文件，读取错误 {len(schemas['errors'])}，缺失/额外来源字段文件 {sum(len(x['deviations']) for x in schemas['datasets'].values())}；各分区的字段完整类型并集见 schema_partitions.json。",
        "全量价格/键/日期检查中的非零发现：", ""]
    findings = []
    for item in present:
        checks = dict(item.get("value_checks", {}))
        checks.update({k: item[k] for k in ("null_primary_key_rows", "invalid_trade_dates") if k in item})
        for key, value in checks.items():
            if value:
                findings.append(f"- `{item['dataset']}.{key}` = {value:,} / {item.get('logical_rows', '未知')} 行。")
    lines += findings or ["- 已执行的上述数值/键/日期规则未发现非零项；不代表数据没有其它经济含义异常。"]
    lines += ["", "跨表与日历全量检查（daily 逻辑行作为关联检查分母）：", "", "```json", json.dumps(data["cross_checks"], ensure_ascii=False, indent=2), "```", "",
        "缺口数是股票×开市日组合，起止仅为首末已见行情，尚未扣停牌，不覆盖首个观测之前/最后观测之后的遗漏。日历只覆盖已有交易所；未提供的交易所日历不能借用另一市场认证。未对所有稀疏事件、季度/月度宏观、财报逐证券应报期作完整性认证。", "",
        "进一步精确拆分（relationship_details.json）：",
        f"- 本地开市日历（exchange/行数/起止）：`{relationships['calendar_by_exchange']}`。日历未匹配行情（代码后缀/行数/证券数）：`{relationships['calendar_unmatched_by_exchange']}`。没有BSE日历时，不能对BSE计算完整应有交易日分母，也不能据此称行情日期错误。",
        f"- 缺daily_basic（后缀/行数/证券数/起止）：`{relationships['daily_missing_daily_basic_by_exchange']}`；缺涨跌停：`{relationships['daily_missing_stk_limit_by_exchange']}`。",
        f"- 当前stock_basic未包含的代码（代码/行情行数/起止）：`{relationships['master_orphan_codes']}`。需要补证券生命周期/代码变更或退市映射，不能直接按当前主表inner join丢弃历史股票。",
        f"- 首末已见日范围内应有股票×开市日组合 {relationships['expected_stock_sessions_within_observed_span']:,}，缺行情{gap_count:,}个；按市场拆分`{relationships['gaps_by_exchange']}`；其中{suspend_count:,}个能匹配当天`suspend_type=S`，剩余{gap_count-suspend_count:,}个尚未解释。这里只匹配同日停牌标记，未重建连续停牌区间，剩余数不等于已确认遗漏。",
        f"- 指数日线分母{by_name['index_daily'].get('logical_rows', '未完成')}行；OHLC/amount/vol的NULL数：`{ {name: by_field[('index_daily', name)]['quality'] for name in ('open', 'high', 'low', 'close', 'amount', 'vol')} }`。需要按指数类型和来源资格筛选，不可用0填补或宣称全库指数OHLC可用。", "",
        f"Raw 抽样错误：{sum('error' in x for x in supplement['raw_samples'])} / {len(supplement['raw_samples'])} 文件；抽样总解码 {sum(x.get('decoded_rows',0) for x in supplement['raw_samples']):,} 行。所有样本路径和 schema 保留，未抽样批次的可读性未认证。",
        f"辅助审计 CSV：{len(auxiliary['csv'])} 文件，SQLite：{len(auxiliary['sqlite'])} 文件；字段和流式行数另存 auxiliary_tables.json。它们是旧审计产物，**不并入金融样本总数**。目录中的 DuckDB 快照/恢复演练库、PDF 披露证据及 JSONP 网页证据未逐库/逐页重新解析，其历史结论仅作线索。", "",
        f"注册任务状态：`{data['task_status']}`。存在未完成任务时，时间最大值不能代表回填完成。", "",
        "## Qlib、因子与旧标签", ""]
    for q in supplement["qlib"]:
        lines += [f"- `{q['path']}`：{q['binary_files']:,} 个 bin，{q['bytes']:,} 字节，长度异常 {len(q['invalid_binary_lengths'])} 个；manifest 证券数 {q['manifest'].get('instrument_count')}，范围 {q['manifest'].get('start')} 至 {q['manifest'].get('end')}。模式 `{q['manifest'].get('mode')}`；源版本 `{q['manifest'].get('dataset_version')}`。"]
    lines += ["", "两个 Qlib export 共享同源历史，版本不同，不能拼接当新增样本。bin 为 float32 序列，首值是日历偏移；OHLC=原价×research_factor，volume=手×100/research_factor，amount=千元×1000，factor 为归一化复权比例；不得把 Qlib volume 与未复权股数混用。七个字段的实际文件名保存在 supplement.json。",
        "factor_registry/model_registry/experiment_registry 为空，30_features 未有发布文件；有动量函数源码不等于已有因子样本。指定目录中未发现独立已发布预测标签表；Qlib 导出仅行情/因子字段，不提供可默认继承的 Y。旧项目标签未进入本研究，未来收益标签需要重新定义并验证。", "",
        "## 复权、信息时钟和泄漏风险", "",
        "- 原行情为提供商未复权口径。研究收益链 `close[t]*adj[t]/(close[t-1]*adj[t-1])-1`，首观测锚定指数不使用未来最新前复权基准；展示 qfq 使用最新因子，只能展示。提供商因子未独立核验为现金分红再投资总收益。Y 应明确其经济口径、交易期限和端点可得性，不给停牌自动填价。",
        "- `_ingested_at` 是抓取观察时间；`_available_at` 至少为观察时间，若 ann_date/f_ann_date/actual_date 更晚则保守跨日；`_event_available_at` 仅白名单行情按上海23:59:59重建。这些字段不等于全部数据的真实首次公开时刻。",
        "- 财务历史 API 可能返回今天修订后的过去报表。end_date、ann_date、f_ann_date、update_flag 不能提供完整修订公开轨迹。严格历史查询必须先过滤知识时间再挑版本；2026年首次抓取的2018年财报不能自动认证为2018年可见。",
        "- stock_basic/行业成员是当前观察到的历史描述，上市/退市日期不代表当时所有属性已知。ST 权限缺口、历史证券生命周期和行业成员发布时间需要补证；不能只选今天仍上市股票。日历完整性仍需按交易所验证。",
        "- 宏观 month/quarter 是统计期，不是 release date；cn_schedule 不能未经映射直接证明所有指标可得时间。缺失字段、修订和低频到日频关联均需显式门禁。",
        "- 旧审计文档标记 index_daily BLOCKED，只作历史证据；本轮数值检查结果见上文，不将旧阻塞或旧通过自动替代当前检查，也未做独立外部报价一致性核验。",
        "- 标签跨越训练/验证边界会泄漏；需要按最大标签期限隔离，文本也需首次公开时间与去重来源。基座可能记忆历史结果的风险需单独记录，时间切分不能消除它。", "",
        "## X_state / 文本 / Y 的可用性与下一步", "",
        "| 数据 | 用途 | 本轮判断 |", "|---|---|---|",
        "| daily + adj_factor + 日历 | X_state 量价、Y 候选收益链 | 可作提供商历史重建的研究起点；先解决键关联、停牌/生命周期及缺口解释，固定版本与时钟 |",
        "| daily_basic、资金流、融资、涨跌停 | X_state 扩展 | 有实际数据；各字段 NULL、覆盖不齐，估值/资金流并非全部在 market_eod 白名单，不能随意回填严格 PIT |",
        "| 财务/事件/宏观 | X_state、可选结构化转文本 | 需要公告可得时点与修订策略；把同一数字改写为文字不等于独立文本来源 |",
        "| stock_basic / index_weight / industry / status | 历史样本池及关联 | 当前主数据和权限不足以认证完整历史股票池；需剔除幸存者偏差 |",
        "| 公告/新闻正文、研报 | 文本输入 | 未发现系统化正文语料及全文发布时间索引；PDF/JSONP 只是旧审计证据，不可当全库文本 |",
        "| Qlib / 旧审计缓存 | 快速读取/参考 | 有限复用、固定来源版本；不是独立数据源，未继承旧标签或收益 |", "",
        "下一步先选择一个覆盖可解释的证券/日期小范围，固定数据版本，逐证券解释停牌与退市、关联因子和交易所日历，再讨论预测期限和收益分档。为文本实验补充可追溯的正文、首次公开时间、修订版本和去重规则。之后核验 Karpo 原生决策契约及 Xlab 资源，做小规模监督后训练；文本条件共享相同样本、标签、切分、预算与评估。", "",
        "## 机器可读附件", "",
        "- `inventory/datasets.json`：88个契约、有效文件/分区/schema、精确行数/范围/质量、关系检查及运行时信息。",
        "- `inventory/fields.json`：完整来源/Canonical 字段并集，声明类型/实际类型/说明/单位或明确未知/键/每字段 NULL 与分母。",
        "- `inventory/schema_partitions.json`：逐数据集/分区字段类型及契约字段差异文件。",
        "- `inventory/relationship_details.json`：关联缺口按市场拆分、主表孤立代码及日历缺口分母。",
        "- `inventory/active_files.csv`：逐文件路径、分区、登记行数与登记SHA256；本轮不宣称重新哈希。",
        "- `inventory/filesystem_data.json` 与 `filesystem_code.json`：全目录/限定代码目录容量及遍历错误。",
        "- `inventory/supplement.json`：Raw 样本、已记录覆盖证据、schema_registry、Qlib 与来源代码哈希。",
        "- `inventory/auxiliary_tables.json`：审计CSV/SQLite字段和行数；`environment.json`：依赖版本。", ""]
    if errors:
        lines += ["## 未完成读取及原因", ""]
        for item in datasets:
            for error in item["errors"]:
                lines.append(f"- {item['dataset']}: {cell(error)}")
    if fs["errors"]:
        lines += ["目录错误：", "```json", json.dumps(fs["errors"], ensure_ascii=False, indent=2), "```"]
    (root.parent / "data_report.md").write_text("\n".join(lines), encoding="utf-8")
    dictionary = ["# 完整字段字典", "", "来源定义取本地保存的官方说明，未联网复核；未确认单位明确标注，不能从数值大小猜测。每表均覆盖契约字段和所有有效分区实际字段并集，实际类型为空表示本次未观察到。NULL分母是当前逻辑行；Raw全量schema尚未重扫，样本和schema_registry见supplement.json。", ""]
    for item in datasets:
        dictionary += [f"## {item['dataset']}", "", f"{item['title']}；路径 `{item['canonical_path']}`；自然键 `{','.join(item['primary_key']) or '内容身份'}`。", "",
                       "| 字段 | 声明类型 | 实际Arrow类型 | 含义 | 单位 | 键 | NULL/行数 |", "|---|---|---|---|---|---|---|"]
        for field in fields:
            if field["dataset"] != item["dataset"]:
                continue
            q = field["quality"]
            dictionary.append("| " + " | ".join(map(cell, [field["field"], field["declared_type"] or "元数据", ",".join(field["actual_arrow_types"]) or "未观察到",
                field["meaning"], field["unit"], "是" if field["primary_key"] else "", f"{q['nulls']}/{q['rows']}" if q else "未扫描/无文件"])) + " |")
        dictionary += [""]
    dictionary += ["## 注册表字段", "", "以下为实际 DuckDB DESCRIBE；业务含义以 registry/database.py DDL 和 lineage 为据，其余不作猜测。JSON payload 为元数据，不是原始金融特征。", ""]
    for table, values in data["registry_tables"].items():
        dictionary += [f"### {table}（{values['rows']} 行）", "", "| 字段 | 类型 | 可空 | 约束 |", "|---|---|---|---|"]
        dictionary += ["| " + " | ".join(map(cell, row[:4])) + " |" for row in values["fields"]]
        dictionary += [""]
    dictionary += ["辅助 CSV/SQLite 全字段及 SQLite 类型见 `inventory/auxiliary_tables.json`。Qlib字段及单位见数据报告，实际文件名见 supplement.json。", ""]
    (root.parent / "field_dictionary.md").write_text("\n".join(dictionary), encoding="utf-8")


if __name__ == "__main__":
    main()
