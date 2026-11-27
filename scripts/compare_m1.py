"""Verify frozen M0/M1 coverage, pair their saved outputs, and archive lightweight reports."""

import argparse
import csv
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
from archive_m1_model import package_m1
from run_benchmarks import (
    PI,
    PI_TRACK,
    read_json,
    read_jsonl,
    saved_responses,
    sha256,
    write_json,
    write_parquet,
)

REPO = Path(__file__).resolve().parents[1]
ORDER = ("finben_bigdata", "finben_acl", "alphafin_test", PI)
EXPECTED = dict(zip(ORDER, (1472, 3720, 1000, 90), strict=True))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def csv_rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def csv_write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def info(path):
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def direction_pair(a, b, directory):
    left = pq.read_table(a / "predictions.parquet").to_pylist()
    right = pq.read_table(b / "predictions.parquet").to_pylist()
    require(len(left) == len(right) == EXPECTED[a.name], f"Prediction count differs: {a.name}")
    by_id = {r["sample_id"]: r for r in right}
    require(len(by_id) == len(right), "Duplicate prediction ID")
    rows = []
    changes = Counter()
    for x in left:
        y = by_id.pop(x["sample_id"])
        for k in ("sample_id", "y_true", "gold_index", "option_keys", "up_option", "down_option"):
            require(x[k] == y[k], f"Direction labels or options differ: {a.name}/{x['sample_id']}/{k}")
        outcome = []
        for r in (x, y):
            outcome.append("correct" if r["y_pred"] == r["y_true"] else "wrong")
        changes["_to_".join(outcome)] += 1
        item = {"sample_id": x["sample_id"], "y_true": x["y_true"], "outcome": "_to_".join(outcome)}
        for k in ("p_up", "p_down", "y_pred", "prediction_option_key"):
            item["m0_" + k] = x[k]
            item["m1_" + k] = y[k]
        item["delta_p_up"] = y["p_up"] - x["p_up"]
        rows.append(item)
    require(not by_id, "Unpaired M1 prediction IDs")
    write_parquet(directory / (a.name + ".parquet"), rows)
    return dict(changes)


def pi_pair(a, b, directory):
    ta, tb = (x / "replay" / PI_TRACK for x in (a, b))

    # The scorer, market series, decision points and all original comparator answers must be byte-identical.
    def replay_sources(x, variant):
        p = x / "replay"
        inputs = [
            p / "arena/simulate.py",
            p / "arena/__init__.py",
            p / "data/bars_15m.csv",
            p / PI_TRACK / "decision_points.jsonl",
        ]
        inputs += [f for f in (p / PI_TRACK).glob("answers_*.jsonl") if f.name != f"answers_{variant}.jsonl"]
        return {f.relative_to(p).as_posix(): sha256(f) for f in inputs}

    require(
        replay_sources(a, "karpo-m0") == replay_sources(b, "karpo-m1"), "Official PI replay inputs changed"
    )
    left, right = csv_rows(ta / "official_actions.csv"), csv_rows(tb / "official_actions.csv")
    require(len(left) == len(right) == 90, "PI scenario count differs")
    rows = []
    for x, y in zip(left, right, strict=True):
        require(all(x[k] == y[k] for k in ("i", "t", "fill_mark")), "PI decision axes differ")
        r = {k: x[k] for k in ("i", "t", "fill_mark")}
        r["i"] = int(r["i"])
        for k in ("choice", "choice_probability", "regime_score", "target_position"):
            for name, record in (("m0", x), ("m1", y)):
                r[f"{name}_{k}"] = (
                    float(record[k]) if k in ("choice_probability", "regime_score") else record[k]
                )
        rows.append(r)
    write_parquet(directory / "pi_actions.parquet", rows)
    changed = sum(r["m0_target_position"] != r["m1_target_position"] for r in rows)
    equity = []
    for x, y in zip(csv_rows(ta / "official_equity.csv"), csv_rows(tb / "official_equity.csv"), strict=True):
        require(x["mark"] == y["mark"], "PI equity timeline differs")
        e0, e1 = float(x["equity_usd"]), float(y["equity_usd"])
        equity.append({"mark": x["mark"], "m0_equity_usd": e0, "m1_equity_usd": e1, "delta_usd": e1 - e0})
    require(len(equity) == 91, "Incomplete PI equity history")
    write_parquet(directory / "pi_equity.parquet", equity)
    return {"scenarios": 90, "equity_marks": 91, "different_target_positions": changed}


def assemble(root, run_id):
    tr = root / "runs/training/m1" / run_id
    ids = read_json(tr / "run_ids.json")
    m0 = root / "runs/benchmarks/v1/karpo-m0" / ids["m0_run_id"]
    m1 = root / "runs/benchmarks/v1/karpo-m1" / ids["benchmark_run_id"]
    prepared = root / "data/financial_m1/v1/prepared"
    train = read_json(tr / "training_result.json")
    frozen = read_json(Path(train["frozen_manifest"]))
    data = read_json(prepared / "data_manifest.json")
    baseline_dev = read_json(tr / "financial_dev/m0/metrics.json")
    jobs = read_json(tr / "jobs.json")
    first = read_json(tr / "first_update.json")
    h = train["history"]
    require(
        [x["epoch"] for x in h] == [1, 2] and train["state"] == frozen["state"] == "FROZEN",
        "Two frozen epochs required",
    )
    chosen = min(h, key=lambda e: (e["dev"]["all"]["mean_ce"], e["epoch"]))
    n_train = sum(s["train"] for s in data["counts"].values())
    n_dev = sum(s["dev"] for s in data["counts"].values())
    require(
        chosen["epoch"] == train["selected_epoch"] == frozen["selected_epoch"], "Selection is inconsistent"
    )
    require(
        baseline_dev["all"]["items"] == n_dev
        and all(e["train_originals"] == n_train and e["dev"]["all"]["items"] == n_dev for e in h),
        "Incomplete financial coverage",
    )
    for k, v in frozen["weights"].items():
        require(sha256(Path(v["path"])) == v["sha256"] == chosen["weights"][k]["sha256"], f"Changed {k}")
    old, new = (read_json(x / "run_manifest.json") for x in (m0, m1))
    require(
        old["state"] == new["state"] == "COMPLETE" and new["loaded_m1"]["weights"] == frozen["weights"],
        "Incomplete benchmark or wrong load identity",
    )
    manifest_key = new["identity"]["cache_identity_sha256"]
    require(new["loaded_m1"]["cache_identity_sha256"] == manifest_key, "M1 cache attestation differs")
    for k in (
        "inputs",
        "protocol_sha256",
        "adapter_sha256",
        "inference",
        "sources_lock_sha256",
        "native",
        "software",
        "device",
    ):
        require(old["identity"][k] == new["identity"][k], f"Protocol identity differs: {k}")
    paired = m1 / "paired"
    paired.mkdir(exist_ok=True)
    full_m0 = read_json(m0 / "artifact_index.json")
    compare = []
    pairs = {}
    coverage = {}
    for dataset in ORDER:
        a, b = m0 / dataset, m1 / dataset
        for entry in full_m0["benchmarks"][dataset]["outputs"].values():
            require(
                sha256(Path(entry["path"])) == entry["sha256"], f"Archived M0 output changed: {entry['path']}"
            )
        requests = list(read_jsonl(root / "data/benchmarks/v1" / dataset / "prepared/requests.jsonl"))
        c0 = saved_responses(a, requests)
        c1 = saved_responses(b, requests, cache_identity=manifest_key)
        source0, source1 = read_json(a / "metrics.json"), read_json(b / "metrics.json")
        expected = EXPECTED[dataset]
        require(
            len(c0) == len(c1) == source0["success"] == source1["success"] == expected and set(c0) == set(c1),
            f"Incomplete {dataset}",
        )
        require(
            all(c0[k]["request_sha256"] == c1[k]["request_sha256"] for k in c0),
            f"Paired request changed: {dataset}",
        )
        require(source0["scoring"] == source1["scoring"], "Scorer changed")
        coverage[dataset] = {"complete": len(c1), "expected": expected}
        if dataset == PI:
            require(source0["questions"] == source1["questions"] == 2070, "PI question count differs")
            coverage[dataset]["questions"] = 2070
            pairs[dataset] = pi_pair(a, b, paired)
            metrics = ("final_usd", "return_pct", "max_drawdown_pct", "switches", "steps_in_cash")
        else:
            pairs[dataset] = direction_pair(a, b, paired)
            metrics = ("accuracy", "mcc", "brier", "nll")
        for metric in metrics:
            x, y = source0[metric], source1[metric]
            delta = y - x
            direction = (
                -1 if metric in ("brier", "nll") else 0 if metric in ("switches", "steps_in_cash") else 1
            )
            effect = (
                "无预设优劣"
                if not direction
                else "持平"
                if delta == 0
                else "改善"
                if direction * delta > 0
                else "退化"
            )
            compare.append(
                {
                    "benchmark": dataset,
                    "metric": metric,
                    "M0": x,
                    "M1": y,
                    "M1_minus_M0": delta,
                    "accuracy_delta_pp": 100 * delta if metric == "accuracy" else "",
                    "change": effect,
                }
            )
    csv_write(m1 / "comparison.csv", compare)
    dev_table = []
    for key, orig in baseline_dev.items():
        trained = chosen["dev"][key]
        require(orig["items"] == trained["items"], "Unpaired dev source")
        for metric in ("mean_ce", "item_mean_accuracy", "exact_match"):
            dev_table.append(
                {
                    "source": key,
                    "items": orig["items"],
                    "metric": metric,
                    "M0": orig[metric],
                    "M1": trained[metric],
                    "M1_minus_M0": trained[metric] - orig[metric],
                }
            )
    csv_write(m1 / "financial_dev_comparison.csv", dev_table)
    write_json(m1 / "paired_summary.json", pairs)
    portable = package_m1(root, run_id)
    td = REPO / "docs/training" / run_id
    ed = REPO / "docs/benchmarks" / m1.name
    td.mkdir(parents=True, exist_ok=True)
    ed.mkdir(parents=True, exist_ok=True)
    for f in (
        tr / "run_ids.json",
        tr / "epoch-1.json",
        tr / "epoch-2.json",
        tr / "training_result.json",
        tr / "first_update.json",
        tr / "jobs.json",
        tr / "source_acquisition.json",
        tr / "trainable_parameters.json",
        tr / "throughput_microstep100.json",
        tr / "model_portable.json",
        prepared / "data_manifest.json",
    ):
        shutil.copyfile(f, td / f.name)
    for f in ("comparison.csv", "financial_dev_comparison.csv", "paired_summary.json", "run_manifest.json", "summary.csv"):
        shutil.copyfile(m1 / f, ed / f)
    performance_path = tr / "performance_profile.json"
    performance = read_json(performance_path) if performance_path.exists() else None
    if performance is not None:
        shutil.copyfile(performance_path, td / performance_path.name)
    refinement_path = tr / "performance_refinement.json"
    refinement = read_json(refinement_path) if refinement_path.exists() else None
    if refinement is not None:
        shutil.copyfile(refinement_path, td / refinement_path.name)
    lines = [
        "# Kurumi M1 金融后训练与冻结复测",
        "",
        "**COMPLETE**",
        "",
        "## 数据",
        "",
        "| 来源 | 原始 | 去重排除 | 总排除 | 有效 | train | dev |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s, v in data["counts"].items():
        lines.append(
            "| "
            + " | ".join(
                [s, *[str(v[k]) for k in ("raw", "deduplicated", "excluded", "valid", "train", "dev")]]
            )
            + " |"
        )
    lines += [
        "",
        f"训练集 {n_train:,} 道，开发集 {n_dev:,} 道。跨 split 重叠 group 数为 {data['group_overlap']}。"
        f"近重复分组合并记录为 {data['near_group_links']} 对。",
        "",
        "CFA 仅保留能把题干和官方材料答案自动对应的题目。逐源排除原因、来源声明及文件哈希见 data_manifest.json。",
        "",
        "## 两轮训练与金融 dev",
        "",
        "| 模型 | 训练原题均值 CE | dev 原题均值 CE | dev 原题平均准确率 | 全题正确率 |",
        "|---|---:|---:|---:|---:|",
        f"| M0 | — | {baseline_dev['all']['mean_ce']:.7f} | {baseline_dev['all']['item_mean_accuracy']:.7f} | {baseline_dev['all']['exact_match']:.7f} |",
    ]
    for e in h:
        all_dev = e["dev"]["all"]
        lines.append(
            f"| epoch {e['epoch']} | {e['train_mean_ce']:.7f} | {all_dev['mean_ce']:.7f} | {all_dev['item_mean_accuracy']:.7f} | {all_dev['exact_match']:.7f} |"
        )
    c = chosen["dev"]["all"]
    lines += [
        "",
        f"选定 epoch {chosen['epoch']}。相对 M0，金融 dev 的 CE 变化为 {c['mean_ce'] - baseline_dev['all']['mean_ce']:+.7f}。"
        f"两轮完成 {train['updates']:,} 次优化器更新、{train['tokens']:,} 个有效 token。"
        f"原计划 {train['microsteps']:,} 个 pack，实际执行 {train.get('physical_packs', train['microsteps']):,} 个。"
        f"训练计算累计 {train['compute_s']:,.0f} 秒。",
        "",
        f"冻结基座为 {frozen['identity']['repo_id']}@{frozen['identity']['base_revision']}。"
        f"原生代码为 {frozen['identity']['native_revision']}。",
        "",
    ]
    for k, v in frozen["weights"].items():
        lines.append(f"- {k} 文件位于 \x60{v['path']}\x60，SHA-256 为 \x60{v['sha256']}\x60。")
    lines += [
        "",
        f"冻结清单位于 \x60{train['frozen_manifest']}\x60。各后续分支从同一冻结清单加载基座、LoRA 和 Readout，分别保存各分支可训练副本。",
        f"已校验的迁移包位于 \x60{portable['archive']}\x60，SHA-256 为 \x60{portable['archive_sha256']}\x60。"
        "基座校验、探针复现及后续训练加载见 docs/m1_model_migration.md。",
        "",
    ]
    if performance is not None:
        before, after = performance["baseline"], performance["selected"]
        gib = 1 << 30
        execution = after["recipe"]
        lines += [
            "## GB10 训练性能",
            "",
            f"同一检查点、同一更新窗口的 {before['tokens']:,} 个有效 token，"
            f"warmup 后从 {before['usable_tokens_per_second']:.1f} 提至 "
            f"{after['usable_tokens_per_second']:.1f} token/s，"
            f"倍率为 {before['seconds'] / after['seconds']:.3f}×。"
            f"PyTorch 峰值分配显存从 {before['peak_allocated_bytes'] / gib:.2f} GiB 变为 "
            f"{after['peak_allocated_bytes'] / gib:.2f} GiB。",
            "",
            f"原配置的单窗口前向 {before['forward_gpu_seconds']:.2f} 秒、"
            f"反向 {before['backward_gpu_seconds']:.2f} 秒、读取与解码 {before['data_seconds']:.3f} 秒。"
            f"相同梯度的优化器更新耗时 {performance['optimizer_full_update_seconds']:.3f} 秒。",
            "",
            f"执行配置为 {execution['recompute']} 重计算、checkpoint_every={execution['checkpoint_every']}、"
            f"keep_every={execution['keep_every']}、long_tokens={execution['long_tokens']}、"
            f"pack 预算 {execution['pack_limit'] or 4096}、LoRA 合并缩放与加法 {execution['fused_lora_add']}。"
            f"窗口逐题 CE 最大差为 {after.get('max_item_ce_delta', 0.0):.7g}，"
            f"最低系统可用内存 {after['min_available_bytes'] / gib:.2f} GiB，"
            f"训练进程 swap 为 {after['process_swap_bytes']} 字节。",
            "",
        ]
        if refinement is not None:
            reference, refined = refinement["baseline"], refinement["selected"]
            if "seconds" in reference:
                lines.append(
                    f"第二轮在原 pack 顺序上测得 {reference['usable_tokens_per_second']:.1f} → "
                    f"{refined['usable_tokens_per_second']:.1f} token/s，"
                    f"峰值从 {reference['peak_allocated_bytes'] / gib:.2f} GiB 变为 "
                    f"{refined['peak_allocated_bytes'] / gib:.2f} GiB。"
                )
            else:
                lines.append(f"第二轮保留原执行配置，实测基线受限于 {reference['error']}。")
            for trial in refinement["trials"]:
                label = "按长度保留激活"
                if trial["recipe"].get("inplace_lora_add"):
                    label += "与 LoRA 原地加法"
                if "long_tokens" in trial["recipe"]:
                    label += f"（long_tokens={trial['recipe']['long_tokens']}）"
                if "seconds" in trial:
                    lines.append(
                        f"- {label} 实测 {trial['usable_tokens_per_second']:.1f} token/s，"
                        f"最大逐题 CE 差 {trial['max_item_ce_delta']:.7g}，"
                        f"梯度范数差 {trial['relative_grad_norm_delta']:.2%}，"
                        f"最低系统可用内存 {trial['min_available_bytes'] / gib:.2f} GiB。"
                    )
                else:
                    lines.append(f"- {label} 受限于 {trial['error']}。")
            operators = refinement.get("operator_sample", {}).get("cuda_operator_self_ms", {})
            if "aten::mm" in operators:
                lines.append(
                    f"选定路径的一次单 pack CUDA trace 中，矩阵乘法用时 {operators['aten::mm'] / 1000:.2f} 秒，"
                    f"memory-efficient 与 Flash Attention 的反向分别用时 "
                    f"{operators.get('aten::_efficient_attention_backward', 0.0) / 1000:.2f} 和 "
                    f"{operators.get('aten::_flash_attention_backward', 0.0) / 1000:.2f} 秒。"
                )
            lines.append("当前配置和选点证据见 performance_refinement.json。")
        phases = [*train.get("performance_history", []), train.get("performance")]
        for live in phases:
            if not live or not live["windows"]:
                continue
            lines.append(
                f"采用该阶段执行配置的 {live['windows']:,} 次正式更新平均 "
                f"{live['tokens'] / live['seconds']:.1f} 有效 token/s，"
                f"记录 {live.get('retry_windows', 0)} 次内存回退窗口。"
            )
        warmed = []
        seen_jobs = set()
        for item in read_jsonl(tr / "events.jsonl"):
            if item["event"] == "update" and "window_seconds" in item:
                if item["job"] in seen_jobs:
                    warmed.append(item)
                seen_jobs.add(item["job"])
        if warmed:
            lines.append(
                f"跳过每份 Slurm 作业的首次更新后，{len(warmed):,} 次正式更新平均 "
                f"{sum(x['tokens'] for x in warmed) / sum(x['window_seconds'] for x in warmed):.1f} 有效 token/s。"
            )
        lines.extend(["完整测时、候选结果和算子记录见 performance_profile.json。", ""])
    lines += [
        "## 冻结测评",
        "",
        "| 数据 | 完成 / 预期 | 指标 | M0 | M1 | 差值 | 变化 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for row in compare:
        dataset = row["benchmark"]
        desc = f"{coverage[dataset]['complete']} / {coverage[dataset]['expected']}"
        if dataset == PI:
            desc += " 场景，2070 题"
        d = f"{row['M1_minus_M0']:+.8g}"
        if row["metric"] == "accuracy":
            d += f"（{row['accuracy_delta_pp']:+.4f} 个百分点）"
        lines.append(
            f"| {dataset} | {desc} | {row['metric']} | {row['M0']:.8g} | {row['M1']:.8g} | {d} | {row['change']} |"
        )
    lines += [
        "",
        "PI 最大回撤使用官方负百分数。切换次数及空仓步数报告观察差值。各方向任务的预测翻转数见 paired_summary.json。",
        "",
        "## 作业与实际耗时",
        "",
        "| 阶段 | Job ID | 节点 | 结束状态 | 退出码 | Slurm 秒数 |",
        "|---|---:|---|---|---|---:|",
    ]
    for job in jobs:
        a = job["accounting"]
        lines.append(
            f"| {job['stage']} | {job['job_id']} | {a['nodes']} | {a['state']} | {a['exit_code']} | {a['elapsed_s']} |"
        )
    gpu_s = sum(int(j["accounting"]["elapsed_s"]) for j in jobs if j["stage"] != "prepare")
    starts = [datetime.fromisoformat(j["accounting"]["submit"]) for j in jobs]
    ends = [datetime.fromisoformat(j["accounting"]["end"]) for j in jobs]
    lines += [
        "",
        f"GPU 作业累计用时 {gpu_s:,} 秒。含排队和跨作业间隔的总历时为 {(max(ends) - min(starts)).total_seconds():,.0f} 秒。",
        "训练作业的退出码 75:0 表示已保存完整恢复状态并交给下一个作业。Slurm 将该退出码记录为 FAILED。",
        "",
        "## 运行问题与结果路径",
        "",
        "首次准备作业 4260 的默认 shell 无法执行已有激活脚本。作业 4261 改用 Bash 并完成同一批数据准备。"
        "两份 HF 原件通过已授权本地下载并经 SFTP 上传，其余四份从官方存储直接下载至 GB10。",
    ]
    issuefile = tr / "issues.json"
    if issuefile.exists():
        for x in read_json(issuefile):
            lines.append(f"- {x}")
    lines += [
        "",
        f"- 六源原件与 prepared 文件位于 \x60{prepared.parent}\x60。",
        f"- 训练、dev 逐题输出、Slurm 与恢复日志位于 \x60{tr}\x60。",
        f"- 选定模型及 last 恢复点位于 \x60{Path(train['frozen_manifest']).parents[1]}\x60。",
        f"- M0 全精度来源位于 \x60{m0}\x60。",
        f"- M1 全部响应、方向预测和 PI 官方轨迹位于 \x60{m1}\x60。",
        f"- 逐样本和逐场景配对表位于 \x60{paired}\x60。逐源金融 dev 比较见 financial_dev_comparison.csv。",
        "",
        "artifact_index.json 记录完整路径、字节数与 SHA-256。",
        "",
    ]
    for dest in (tr / "report.md", m1 / "comparison_report.md", td / "report.md", ed / "report.md"):
        dest.write_text("\n".join(lines), encoding="utf-8")
    files = {}
    for label, folder in (
        ("training", tr),
        ("model", Path(train["frozen_manifest"]).parents[1]),
        ("prepared", prepared),
        ("benchmark", m1),
    ):
        files[label] = {
            f.relative_to(folder).as_posix(): info(f)
            for f in sorted(folder.rglob("*"))
            if f.is_file()
            and not f.name.startswith(".")
            and f.name
            not in ("artifact_index.json", "coordinator_status.json", "coordinator.log", "coordinator.pid")
        }
    index = {
        "state": "COMPLETE",
        "ids": ids,
        "base_manifest": str(root / "runs/setup/model-manifest.json"),
        "frozen": train["frozen_manifest"],
        "portable_model": portable,
        "coverage": coverage,
        "training_history": str(tr / "training_result.json"),
        "jobs": jobs,
        "paths": files,
        "m0_index": info(m0 / "artifact_index.json"),
        "paired": str(paired),
        "first_update": first,
    }
    for dest in (m1 / "artifact_index.json", td / "artifact_index.json", ed / "artifact_index.json"):
        write_json(dest, index)
    print(f"COMPLETE {ed / 'report.md'}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    a = p.parse_args()
    assemble(a.root, a.run_id)
