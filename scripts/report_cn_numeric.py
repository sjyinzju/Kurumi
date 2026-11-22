"""Collect measured storage and render the CN dataset report from a built release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import duckdb


def inventory(root):
    counts = Counter()
    sizes = Counter()
    errors = []
    stack = [(root, "")]
    while stack:
        directory, group = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    key = group or entry.name
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((entry.path, key))
                    elif entry.is_file(follow_symlinks=False):
                        counts[key] += 1
                        sizes[key] += entry.stat(follow_symlinks=False).st_size
        except OSError as error:
            errors.append({"path": str(directory), "errno": error.errno})
    return {"files": dict(counts), "bytes": dict(sizes), "errors": errors,
            "free_bytes": shutil.disk_usage(root).free}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def legacy_reference_check(root):
    with duckdb.connect(str(root / "quant.duckdb"), read_only=True) as con:
        active = {path for (path,) in con.sql("SELECT path FROM canonical_parts WHERE active").fetchall()}
        inactive = con.sql("SELECT count(*) FROM canonical_parts WHERE NOT active").fetchone()[0]
        versions = con.sql("SELECT manifest FROM dataset_versions").fetchall()
        historical = {
            path for (record,) in versions for paths in json.loads(record)["paths"].values() for path in paths
        }
    missing = sorted(path for path in active | historical if not Path(path).is_file())
    return {"active_paths": len(active), "registered_versions": len(versions),
            "historically_pinned_paths": len(historical), "inactive_registry_rows": inactive, "missing": missing}


def optional_json(path):
    return read_json(path) if path.is_file() else None


def matching_review(path, version):
    value = optional_json(path)
    return value if value and value.get("dataset_version") == version else None


def matching_prefix(paths, manifest):
    hashes = manifest["pit_evidence_sha256"]
    for path in paths:
        check = optional_json(path)
        if check and all(hashes.get(f"{name}.jsonl") == digest
                         for name, digest in check["frozen_source_sha256"].items()):
            return check
    return None


def feature_counts(release):
    path = release / "reports" / "feature_coverage.parquet"
    with duckdb.connect() as con:
        return con.execute("""
            SELECT dataset_table, field, sum(n_rows)::BIGINT AS observed_rows,
                   sum(n_valid)::BIGINT AS valid_rows
            FROM read_parquet(?) GROUP BY 1,2 ORDER BY 1,2
        """, [str(path)]).fetchall()


def source_impact(release):
    fields = ("candidates", "input_valid", "security_shares_missing", "issuer_cap_missing",
              "split_chain_missing", "fundamentals_missing", "industry_missing")
    by_split = {}
    with duckdb.connect() as con:
        con.execute("SET threads=3; SET memory_limit='3GB'")
        for partition in sorted((release / "samples" / "market_id=CN").glob("year=*")):
            stock = release / "stock_daily" / "market_id=CN" / partition.name
            rows = con.execute("""
                SELECT s.split, count(*), count_if(s.input_valid),
                       count_if(d.shares_outstanding_security IS NULL),
                       count_if(d.issuer_market_cap_reporting IS NULL),
                       count_if(NOT coalesce(d.split_chain_known, false)),
                       count_if(s.fundamental_snapshot_id IS NULL),
                       count_if(s.industry_code_asof IS NULL)
                FROM read_parquet(?, hive_partitioning=false) AS s
                LEFT JOIN read_parquet(?, hive_partitioning=false) AS d
                    USING (instrument_id, local_trade_date)
                GROUP BY s.split
            """, [str(partition / "*.parquet"), str(stock / "*.parquet")]).fetchall()
            for split, *counts in rows:
                by_split.setdefault(split, Counter()).update(dict(zip(fields, counts, strict=True)))
        aggregates = {}
        for table in ("market_daily", "industry_daily"):
            rows = con.execute("""
                SELECT coverage.return_1d.status, count(*), count_if(return_1d IS NOT NULL),
                       count_if(coverage.return_1d.membership_complete),
                       count_if(coalesce(coverage.return_1d.cap_coverage >= 0.99, false)),
                       count_if(coverage.return_1d.cap_coverage IS NULL)
                FROM read_parquet(?, hive_partitioning=false) GROUP BY 1 ORDER BY 1
            """, [str(release / table / "**/*.parquet")]).fetchall()
            aggregates[table] = [dict(zip(("status", "rows", "return_1d_valid", "membership_complete",
                                          "cap_coverage_at_least_99pct", "cap_coverage_unavailable"), row, strict=True))
                                 for row in rows]
        fields = ("revenue_ttm", "net_income_total_ttm", "net_income_parent_ttm", "operating_cashflow_ttm",
                  "assets", "liabilities", "parent_equity", "assets_4q_ago", "parent_equity_4q_ago",
                  "revenue_ttm_4q_ago", "net_income_parent_ttm_4q_ago")
        count_columns = ", ".join(f"count({field})" for field in fields)
        total, *counts = con.execute(f"SELECT count(*), {count_columns} FROM read_parquet(?)",
                                     [str(release / "stock_fundamental_asof" / "**/*.parquet")]).fetchone()
    return {"by_split": by_split, "aggregate_return_coverage": aggregates,
            "fundamental_snapshots": {"rows": total, "fields_available": dict(zip(fields, counts, strict=True))}}


def gib(size):
    return f"{size / 2**30:,.3f}"


def render(release, before, after, additional):
    manifest = read_json(release / "manifest.json")
    quality = read_json(release / "reports/quality_summary.json")
    schema = read_json(release / "schema.json")
    validation = read_json(release / "reports/validation_results.json")
    status = quality["status"]
    frozen = manifest["source_snapshot"]["suspension_evidence_sha256"]
    pit_hashes = manifest["pit_evidence_sha256"]
    followup = additional.get("followup")
    evidence_options = [
        (Path("artifacts/cn_numeric/suspension_augmented_input.json"), Path("artifacts/cn_numeric/pit_corrected_input")),
        (Path("artifacts/cn_numeric/suspension_augmented_input.json"), Path("artifacts/cn_numeric/pit_augmented_input")),
        (Path("artifacts/cn_numeric/suspension_final_input.json"), Path("artifacts/cn_numeric/pit_final_input")),
        (Path("artifacts/cn_numeric/suspension_release_input.json"), Path("artifacts/cn_numeric/pit_release_input")),
    ]
    proof, pit = next(((p, d) for p, d in evidence_options if p.is_file() and d.is_dir()
                      and hashlib.sha256(p.read_bytes()).hexdigest() == frozen
                      and {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in d.glob("*.jsonl")} == pit_hashes),
                      (Path("configs/cn_suspension_evidence.json"), Path("artifacts/cn_pit_evidence")))
    if followup:
        proof = Path(followup["suspension_evidence"])
        pit = Path(followup["pit_evidence"])
    build_options = (f"--calendar-prehistory artifacts/cn-calendar/trade_cal "
                     f"--suspension-evidence '{proof.as_posix()}'")
    doc = [
        "# CN 数值数据集报告",
        f"`{status}`。版本 `{manifest['dataset_version']}`。数据目录为 `{release}`。",
        "包含沪、深、北普通 A 股。价格及监督观察截至 2026-07-31，样本截至 2026-06-30。Xtext 记录为 `not_built`。",
        "## 存储和清理",
        "| 目录 | 迁移前文件 | 迁移前 GiB | 迁移后文件 | 迁移后 GiB |\n|---|---:|---:|---:|---:|",
    ]
    for key in sorted(set(before["files"]) | set(after["files"])):
        doc.append(f"| `{key}` | {before['files'].get(key,0):,} | {gib(before['bytes'].get(key,0))} | "
                   f"{after['files'].get(key,0):,} | {gib(after['bytes'].get(key,0))} |")
    doc.append(f"全盘可用空间由 {gib(before['free_bytes'])} GiB 变为 {gib(after['free_bytes'])} GiB。"
               f"发布清单内文件大小合计 {gib(sum(x['bytes'] for x in manifest['files'].values()))} GiB。")
    if followup:
        doc.append(f"本轮开始时 E 盘剩余约 {followup['start_free_gib']:.2f} GiB。"
                   "目录对比以首轮建设前保存的清单为基线。")
        doc.extend(followup.get("storage_observations", []))
    cleanup = additional.get("cleanup") or {}
    gc = additional.get("canonical_gc") or {}
    removed_files = cleanup.get("deleted_files", [])
    removed_dirs = cleanup.get("deleted_directories", [])
    removed_bytes = sum(item["bytes"] for item in removed_files)
    doc.append(f"已删失效进度临时文件 {len(removed_files):,} 个和空审计目录 "
               f"{len(removed_dirs):,} 个，释放 {removed_bytes:,} 字节。"
               f"经等价性验证的 Canonical 回收 {gc.get('deleted_files',0):,} 个文件，"
               f"释放 {gc.get('reclaimed_bytes',0):,} 字节。")
    staged = additional.get("abandoned_staging") or []
    if staged:
        doc.append(f"本轮另清理了 {len(staged)} 个未发布的旧导出目录，涉及 {sum(r['files'] for r in staged):,} 个文件和 "
                   f"{sum(r['bytes'] for r in staged):,} 字节。")
    link_receipt = additional.get("release_storage") or {}
    if link_receipt.get("hardlinked_unchanged_parquets"):
        doc.append(f"当前发布复用了旧版本中逐字节一致的 {link_receipt['hardlinked_unchanged_parquets']:,} 个 Parquet 文件。")
    peak = additional.get("sampled_peak")
    if peak:
        doc.append(f"构建阶段定时观测的 numeric 最大占用 {gib(peak['numeric_peak_bytes'])} GiB，"
                   f"E 盘最少剩余 {gib(peak['minimum_drive_free_bytes'])} GiB。"
                   "抽样按文件身份合并硬链接。目录清单按路径统计。")
    doc.append("当前 quant 注册表、活跃视图及仍被实际版本引用的源分片供原项目使用。训练包读取以本版本的 Parquet 清单为入口。")
    legacy = additional["legacy_reference_check"]
    doc.append(f"回收后检查了 {legacy['active_paths']:,} 个当前分片和 {legacy['registered_versions']:,} 个注册版本的引用。"
               f"历史版本共引用 {legacy['historically_pinned_paths']:,} 个不同分片，缺失 {len(legacy['missing']):,} 个。"
               f"另有 {legacy['inactive_registry_rows']:,} 个非活跃注册分片，等价性或引用证据并未全部核实。")
    doc.append("旧全库备份计划已按回收范围归档并退役，原哈希及回收判据留档。见 [旧库回收记录](cn_legacy_reclamation.md)。")
    doc.extend(["## 六张核心表", "| 表 | 主键 | 行数 | 起止日期 | Parquet GiB |\n|---|---|---:|---|---:|"])
    for table, table_schema in schema["tables"].items():
        parts = [v for k, v in manifest["files"].items() if k.startswith(table + "/")]
        first = min((v["date_min"] for v in parts if v["date_min"]), default="—")
        last = max((v["date_max"] for v in parts if v["date_max"]), default="—")
        doc.append(f"| `{table}` | {', '.join(table_schema['primary_key'])} | {sum(v['rows'] for v in parts):,} | "
                   f"{first} 至 {last} | {gib(sum(v['bytes'] for v in parts))} |")
    doc.extend(["完整字段、Arrow 类型、单位和主键见发布包 `schema.json`。"
                "按交易所、年份、字段和原因的分布见 `reports/field_coverage.parquet`，"
                "30 个因子、市场及行业字段的分母、有效项与覆盖见 `reports/feature_coverage.parquet`。", "## 全量覆盖",
                "| 交易所 | 证券日 | 实际收盘 | 复权有效 | 输入有效 | 停牌事实 | 停牌时点证据 | 股数 | 发行人市值 | U 链 | 财务快照链接 | 行业 |"
                "\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for coverage in quality["exchange_coverage"]:
        fields = ["security_days", "actual_quotes", "adjustment", "valid_inputs", "reported_suspensions", "verified_suspensions",
                  "share_verified", "issuer_cap_verified", "unit_chain_verified", "finance_verified", "industry_verified"]
        doc.append(f"| {coverage['exchange']} | " + " | ".join(f"{(coverage[k] or 0):,}" for k in fields) + " |")
    if prior_coverage := additional.get("baseline_exchange_coverage"):
        origins = {r["exchange"]: r for r in prior_coverage}
        doc.extend(["### 本轮前后对比",
                    "| 交易所 | 实际收盘 | 股数 | 发行人市值 | U 链 | 财务快照链接 | 行业 |\n|---|---:|---:|---:|---:|---:|---:|"])
        comparable = ("actual_quotes", "share_verified", "issuer_cap_verified", "unit_chain_verified",
                      "finance_verified", "industry_verified")
        for current in quality["exchange_coverage"]:
            old = origins[current["exchange"]]
            doc.append("| " + current["exchange"] + " | " + " | ".join(
                f"{old[k] or 0:,} → {current[k] or 0:,}" for k in comparable
            ) + " |")
    doc.extend(["## 因子与市场状态覆盖",
                "下表分母为各表实际发布行数。行业表只列已有可核验归属线索的行业和时段，完整母集门槛独立核查。",
                "| 表 | 字段 | 上版有效值 | 有效值 | 发布行数 |\n|---|---|---:|---:|---:|"])
    old_feature_counts = {(table, field): valid for table, field, _, valid in additional.get("baseline_features", [])}
    for table, field, physical, valid in additional["feature_counts"]:
        old = old_feature_counts.get((table, field))
        doc.append(f"| `{table}` | `{field}` | {f'{old:,}' if old is not None else '—'} | {valid:,} | {physical:,} |")
    doc.extend(["## 样本与监督",
                "| Split | 期限 | 候选 | 有效 | 无效 | 七档计数（0 至 6） |\n|---|---:|---:|---:|---:|---|"])
    invalid_by_split = []
    for split in ("train", "validation", "calibration", "test"):
        for horizon in (1, 5, 20):
            rows = [r for r in quality["supervision"] if r["split"] == split and r["horizon"] == horizon]
            total = sum(r["samples"] for r in rows)
            classes = [sum(r["samples"] for r in rows if r["label_valid"] and r["class_id"] == cls)
                       for cls in range(7)]
            doc.append(f"| {split} | {horizon} | {total:,} | {sum(classes):,} | {total-sum(classes):,} | "
                       + " / ".join(f"{n:,}" for n in classes) + " |")
            reasons = Counter()
            for row in rows:
                if not row["label_valid"]:
                    reasons[row["invalid_reason"] or "missing_reason"] += row["samples"]
            invalid_by_split.append((split, horizon, reasons))
    doc.extend(["### 监督无效原因", "| Split | 期限 | 无效原因及数量 |\n|---|---:|---|"])
    for split, horizon, reasons in invalid_by_split:
        body = "、".join(f"`{reason}` {n:,}" for reason, n in reasons.most_common()) or "—"
        doc.append(f"| {split} | {horizon} | {body} |")
    doc.append("各 split 的实际训练清单和期限掩码见 `reports/training_samples.parquet`。"
               "按交易所、年份、行业、期限、分档和排除原因的全量统计见 `reports/coverage.parquet`。")
    doc.append("至少有一个有效期限的实际清单行数为 " + "、".join(
        f"`{r['split']}` {r['samples']:,}" for r in quality["training_sample_counts"]
    ) + "。")
    if quality.get("quote_gaps"):
        doc.extend(["| 交易所 | 涉及证券 | 无报价且未解释 | F 缺失 | 缺口日期范围 |\n|---|---:|---:|---:|---|"])
        for row in quality["quote_gaps"]:
            doc.append(f"| {row['exchange']} | {row['affected_instruments']:,} | {row['open_without_quote'] or 0:,} | "
                       f"{row['factor_missing'] or 0:,} | {row['earliest']} 至 {row['latest']} |")
        doc.append("逐证券逐日缺键见 `reports/quote_gaps.parquet`。停牌披露原版可得证据与供应商事后记录分别计数。")
    doc.extend(["## 补采与证据",
                "日历、补采请求、证据原件来源、公开时间及版本哈希见 `reference/`。"
                "每日实际收盘与经证实停牌的市场估值分开保存。停牌填估值的规则只适用于市场与行业聚合。"])
    if followup:
        doc.extend(followup.get("sources", []))
    for endpoint, summary in additional.get("backfill", {}).items():
        doc.append(f"- `{endpoint}` 完成 {summary['completed_scopes']:,}/{summary['scopes']:,} 个证券范围，"
                   f"覆盖计划 {summary['requested_keys']:,} 个缺键，源响应匹配 {summary['filled_keys']:,} 个键。"
                   f"错误统计为 `{summary['errors']}`。")
    if additional.get("ttm_recovery"):
        doc.append("冷却后重新取得东方财富和宁波银行 2024Q1–2026Q1 各九期原始合并财报。"
                   "126 个原件数值均与独立同发行人、同会计期数据在披露精度下一致。"
                   "合入新增 11 个报告版本并核准 7 个已有版本，两家 2026Q1 均形成四项当期 TTM 和经济口径可比的上年同期收入与归母 TTM。")
    if semantics := additional.get("financial_semantics"):
        latest_ttm = semantics["eastmoney_target_q1_2026"]
        actions = semantics["actions"]
        doc.append("东方财富的财务收入采用原件合并利润表中的经营收入合计口径。"
                   f"2026Q1 收入 TTM 复算为 {latest_ttm['revenue_ttm']:,.2f} 元，"
                   f"净利率为 {latest_ttm['net_margin_ttm']:.2%}。"
                   f"证据涵盖 {actions['remapped_consolidated_operating_total']} 期合并收入。"
                   f"另按原件累计列修正 {actions['corrected_legacy_quarter_to_ytd']} 个早期银行财报字段，"
                   f"{actions['aggregate_scope_unverified']} 个早期财报版本的合并收入保留为缺失。"
                   "见 [2025 年年报](https://static.cninfo.com.cn/finalpage/2026-03-20/1225019509.PDF) 和 "
                   "[2026 年一季报](https://static.cninfo.com.cn/finalpage/2026-04-25/1225185763.PDF)。")
    if manifest["source_snapshot"].get("reported_suspension_policy"):
        doc.append("六条只在事后档案中证实的全日停牌用于监督原因和审计。该来源提供可核查的实际状态，历史公开时间缺失。"
                   "见 [剩余报价键来源核查](cn_suspension_residual_sources.json)。")
    doc.extend(["## 验收",
                "| 全量检查 | 违规数 |\n|---|---:|"])
    for check, errors in validation["full_sql_violation_counts"].items():
        doc.append(f"| `{check}` | {errors:,} |")
    sampled = additional.get("independent") or {}
    native = additional.get("native") or {}
    independent_features = additional.get("independent_features") or {}
    doc.append(f"独立分区哈希与页脚校验核对 {sampled.get('files_verified',0)} 个文件。"
               f"按交易所和 split 抽样复算 {len(sampled.get('window_and_label_recalculation',[]))} 条真实样本。"
               f"原生编码状态为 `{native.get('native_check','not_run')}`， "
               f"检查 {len(native.get('native_evidence',[]))} 条样本。")
    if masks := sampled.get("independent_training_mask_by_year"):
        doc.append(f"按 {len(masks)} 个年份独立从标签重建并逐行核对 "
                   f"{sum(year['rows'] for year in masks.values()):,} 条实际训练清单，期限掩码及 split 全部一致。")
    if independent_features:
        doc.append("真实量价因子独立复算的样本及数值差异保存在对应的机器可读验收结果中。")
    if additional.get("pit_prefix"):
        doc.append("真实披露和行业证据的前缀截断及扰动检查另存机器可读结果，包括时间、数值和原版引用的对比。")
    if additional.get("native_cache_check"):
        doc.append("真实样本的编码缓存命中返回相同 token 和标记。数据版本、样本、文本版本及文本条件在验收中形成独立条目。"
                   "缓存命名空间还包含模板、编码器及 tokenizer 版本，上限为 8 GiB。")
    if field_check := additional.get("independent_field_coverage"):
        doc.append(f"独立 Arrow 扫描核实 {field_check['groups']:,} 个字段原因分组及 "
                   f"{field_check['reason_entries']:,} 个稀疏原因记录，和发布表逐组一致。")
    doc.append("## 阻塞和训练影响")
    if followup:
        doc.extend(followup.get("blockers", []))
        if "structural_dependencies" in quality:
            doc.append(f"自动判定识别 {len(quality['structural_dependencies']):,} 个结构性依赖范围。"
                       "逐项原因见 `reports/quality_summary.json`。"
                       "各 split、年份、交易所及已核验行业的 PIT 分母见 `reports/pit_coverage_by_stratum.parquet`，"
                       "同口径的因子覆盖见 `reports/stock_factor_coverage_by_stratum.parquet`，"
                       "前置期和其余上市会计期的七项证据覆盖见 `reports/financial_period_coverage.parquet`。")
    else:
        doc.append("原始财务表的本地严格可知时间晚于样本截止。可证实的公告版本进入 PIT 快照，其余历史金额保留为未验证。"
                   "跨股类的股数、股本生效版本、拆合股与送转动作全集以及历史申万分类是主要依赖缺口。"
                   "市场和行业缺少可核实的完整前期分母时，按契约将相应指标保留 NULL。")
    if additional.get("sources"):
        doc.append("TuShare `bak_basic` 实测权限拒绝。可访问的 `daily_basic` 和 `index_member_all` "
                   "能提供对照值，历史版本追溯仍需原件。巨潮原件首批请求可用，后续 36 个发行人的请求及重试返回 HTTP 403。"
                   "实际补齐的申万原始附件仅覆盖少数行业和月份，不能据此补写全行业历史。")
        if additional.get("cninfo_retry"):
            doc.append("冷却后对三个发行人复测均返回 HTTP 200。两个沪深发行人查询有公告，北交所发行人的同类查询为空。"
                       "此前 HTTP 403 为暂时故障，后续获取情况见财务来源记录。")
        doc.append("深交所试营业期的完整开休市证据仍缺，5 只早期股票的上市期龄共涉及 13,424 个候选日。"
                   "已复核的样本资格规则保留这些候选，期龄字段为 NULL。")
        doc.append("申万官方历史 XLS 获得 12,934 条记录，旧 RAR 中有 11,803 条历史记录。"
                   "两版存在同一生效键分类改写和更新日期变化，现有公开网页存档未绑定被下载的旧版原始文件。"
                   "另一路理杏仁请求返回 HTTP 401。见 [申万来源核验](cn_industry_source_audit.md)。")
    if additional.get("xbrl_source_probe"):
        doc.append("原沪市 XBRL 入口重定向至公司列表，浦发银行的经营概览未返回原始财报实例链接。"
                   "原深市实例入口实测连接失败。沪市公告传输服务列有 XBRL 实例文档，公开产品页没有历史实例下载清单。"
                   "来源核对覆盖沪深公开入口、传输服务说明及北交所定期报告指南。"
                   "见 [沪市公告服务](https://www.sseinfo.com/services/other/announcement/) 和 "
                   "[深市原平台说明](https://www.szse.cn/aboutus/trends/news/t20090213_517801.html)。")
    for blocker in quality["source_dependencies"]:
        doc.append(f"- `{blocker['dependency']}` 在 {blocker['missing_security_days']:,} 个证券日缺可用值，"
                   "涉及输入可选字段与状态覆盖，影响范围详见覆盖表。")
    impact = additional["source_impact"]
    doc.extend(["### 缺口影响的候选数",
                "各缺失列可重叠，按实际样本索引连接当日记录。财务栏统计缺少任何可用快照的候选。",
                "| Split | 候选 | 行情输入有效 | 缺证券股本 | 缺发行人市值 | 缺 U 链 | 缺财务快照 | 缺行业 |\n"
                "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for split in ("train", "validation", "calibration", "test"):
        counts = impact["by_split"][split]
        columns = ("candidates", "input_valid", "security_shares_missing", "issuer_cap_missing",
                   "split_chain_missing", "fundamentals_missing", "industry_missing")
        doc.append(f"| {split} | " + " | ".join(f"{counts[key]:,}" for key in columns) + " |")
    doc.extend(["| 1 日聚合 | 状态 | 行数 | 收益有效 | 成员完整 | 市值覆盖 ≥99% | 市值覆盖无法计算 |\n"
                "|---|---|---:|---:|---:|---:|---:|"])
    for table, rows in impact["aggregate_return_coverage"].items():
        for row in rows:
            columns = ("rows", "return_1d_valid", "membership_complete",
                       "cap_coverage_at_least_99pct", "cap_coverage_unavailable")
            doc.append(f"| `{table}` | `{row['status']}` | " + " | ".join(f"{row[key]:,}" for key in columns) + " |")
    snapshots = impact["fundamental_snapshots"]
    doc.extend([f"财务分母为 {snapshots['rows']:,} 份实际共享快照。来源公告版本及条件期保存在发布包 `reference/`。",
                "| 财务字段 | 非空快照数 |\n|---|---:|"])
    for field, count in snapshots["fields_available"].items():
        doc.append(f"| `{field}` | {count:,} |")
    loader_opt = ", allow_incomplete=True" if status == "INCOMPLETE" else ""
    cli_loader_opt = " --allow-incomplete" if status == "INCOMPLETE" else ""
    if followup:
        build_options += " --spill-dir (Join-Path $env:TEMP 'kurumi-cn-followup-spill') --memory-limit-gib 8"
    doc.extend(["## 命令",
                "```powershell\n"
                "$python = 'E:/quant/.venv/Scripts/python.exe'\n"
                "$env:PYTHONPATH = 'E:/Kurumi/src;E:/Kurumi/reference/karpo-decision/src;E:/Kurumi/artifacts/karpo-runtime'\n"
                f"& $python scripts/build_cn_numeric.py --prices-only {build_options}\n"
                "& $python scripts/backfill_cn_prices.py --endpoint daily --endpoint adj_factor --endpoint suspend_d\n"
                f"& $python scripts/build_cn_numeric.py --compute-only {build_options} --pit-evidence '{pit.as_posix()}'\n"
                f"& $python scripts/build_cn_numeric.py {build_options} --pit-evidence '{pit.as_posix()}'\n"
                f"$dataset = '{release.as_posix()}'\n"
                "& $python scripts/verify_cn_numeric.py $dataset\n"
                f"& $python scripts/check_numeric_loading.py $dataset --representative --price-prefix{cli_loader_opt} "
                "--karpo-assets artifacts/karpo-b8e6fd7"
                + (" --recovered-ttm-audit artifacts/cn_pit_finance_corrected/targeted_recovery_result.json"
                   if additional.get("financial_semantics") else "") + "\n"
                "```",
                "构建阶段按价格、PIT、监督、特征和 Parquet 分区记录断点。原生检查依赖的轻量配置和 tokenizer "
                "可由 `scripts/fetch_karpo_encoding.py artifacts/karpo-b8e6fd7` 重新获取。",
                *( ["本版示例启用显式 QA 开关。正式后训练入口会检查 `NUMERIC_READY`。"] if loader_opt else [] ),
                "训练代码使用 `kurumi.numeric_loader.NumericDataset`，通过 `iter_sample_ids(split)` 取得实际清单，"
                "通过 `load_batch(sample_ids)` 取得模型输入、监督和审计。",
                "```python\n"
                "from itertools import islice\n"
                "from kurumi.numeric_loader import NumericDataset\n\n"
                f"dataset = NumericDataset.from_config('configs/cn_numeric.toml'{loader_opt})\n"
                "batch = dataset.load_batch(list(islice(dataset.iter_sample_ids('train'), 32)))\n"
                "```"])
    return "\n\n".join(doc).replace("|\n\n|", "|\n|") + "\n", {
        **quality, "dataset_version": manifest["dataset_version"], "storage_before": before,
        "storage_after": after, "validation": validation, "observations": additional,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--before", type=Path, default=Path("artifacts/cn_numeric/before.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/cn_numeric"))
    parser.add_argument("--baseline-release", type=Path, help="Immutable predecessor for coverage comparisons")
    parser.add_argument("--followup", type=Path, help="Acquisition and remaining blockers for this increment")
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    data_root = dataset.parent.parent
    workspace = dataset.parent / ".build-cn"
    manifest = read_json(dataset / "manifest.json")
    version = manifest["dataset_version"]
    augmented = args.artifacts / "pit_augmented_input" / "financial_versions.jsonl"
    used_recovered_finance = (augmented.is_file() and hashlib.sha256(augmented.read_bytes()).hexdigest()
                              == manifest["pit_evidence_sha256"].get("financial_versions.jsonl"))
    corrected = "financial_semantic_corrections.jsonl" in manifest["pit_evidence_sha256"]
    recovery_directory = "cn_pit_finance_corrected" if corrected else "cn_pit_ttm_recovery"
    more = {
        "backfill": {name: result for name in ("daily", "adj_factor", "suspend_d")
                     if (result := optional_json(workspace / f"backfill_{name}.json"))},
        "cleanup": optional_json(args.artifacts / "legacy-scratch.receipt.json"),
        "canonical_gc": optional_json(args.artifacts / "canonical_gc.json"),
        "abandoned_staging": optional_json(args.artifacts / "abandoned_staging_cleanup.json"),
        "release_storage": optional_json(workspace / "release.json"),
        "independent": matching_review(args.artifacts / "independent_acceptance.json", version),
        "native": matching_review(Path("docs/cn_native_encoding_validation.json"), version),
        "native_cache_check": optional_json(args.artifacts / "v2_native_cache_check.json"),
        "independent_features": (matching_review(args.artifacts / "real_feature_verification_v4.json", version)
                                 or matching_review(args.artifacts / "real_feature_verification_v3.json", version)
                                 or matching_review(args.artifacts / "real_feature_verification.json", version)),
        "independent_field_coverage": matching_review(args.artifacts / "final_field_coverage_validation.json", version),
        "pit_prefix": matching_prefix([args.artifacts / "pit_corrected_prefix.json",
                                       args.artifacts / "pit_augmented_prefix.json",
                                       args.artifacts / "pit_final_prefix.json",
                                       Path("docs/cn_pit_prefix_validation.json")], manifest),
        "sampled_peak": optional_json(args.artifacts / "sampled_peak.json"),
        "sources": optional_json(args.artifacts / "source_observations.json"),
        "feature_counts": feature_counts(dataset),
        "source_impact": source_impact(dataset),
        "cninfo_retry": optional_json(Path("docs/cn_cninfo_retry.json")),
        "ttm_recovery": (optional_json(Path("artifacts") / recovery_directory / "targeted_recovery_result.json")
                         if used_recovered_finance or corrected else None),
        "financial_semantics": optional_json(args.artifacts / "financial_semantics_report.json") if corrected else None,
        "xbrl_source_probe": optional_json(args.artifacts / "xbrl_public_source_probe.json"),
        "legacy_reference_check": legacy_reference_check(data_root),
    }
    if args.followup:
        context = read_json(args.followup)
        from kurumi.cn_publish import evidence_signature, sha256

        if evidence_signature(Path(context["pit_evidence"])) != manifest["pit_evidence_sha256"] or (
            sha256(Path(context["suspension_evidence"])) != manifest["source_snapshot"]["suspension_evidence_sha256"]
        ):
            raise ValueError("Follow-up build inputs do not match the release manifest")
        more.update(followup=context, sources=None, xbrl_source_probe=None)
        more["sampled_peak"] = context.get("sampled_peak")
    if args.baseline_release:
        more["baseline_exchange_coverage"] = read_json(args.baseline_release / "manifest.json")["exchange_coverage"]
        more["baseline_features"] = feature_counts(args.baseline_release)
    actual_validation = read_json(dataset / "reports/validation_results.json").get("independent", {})
    for evidence, key in (("release_bytes_windows_labels_and_masks", "independent"),
                          ("pit_source_prefix", "pit_prefix"), ("native_karpo", "native"),
                          ("independent_stock_factor_recalculation", "independent_features")):
        if receipt := actual_validation.get(evidence, {}).get("path"):
            more[key] = read_json(dataset / receipt) | {"dataset_version": version}
    text, summary = render(dataset, read_json(args.before), inventory(data_root), more)
    report = Path("docs/cn_numeric_dataset_report.md")
    report.write_text(text, encoding="utf-8")
    report.with_name("cn_numeric_quality_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
