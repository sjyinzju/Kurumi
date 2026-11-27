"""Compare extraction profiles on the same archived originals and native numeric inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from time import perf_counter

import duckdb
import pyarrow as pa
from verify_cn_text import document_bodies, view

from kurumi.cn_text_corpus import IdentityHistory, NativeBudget, choose_spans
from kurumi.cn_text_facts import company_facts, normal_literal, pick_facts
from kurumi.cn_text_index import LOOKBACK, checked_anchor
from kurumi.cn_text_sources import Capture, read_json, write_json
from kurumi.encoding_cache import EncodingCache
from kurumi.karpo_numeric import PLAN_TENSORS, KarpoNumericEncoder, _plan_from_bytes, _plan_to_bytes
from kurumi.numeric_loader import TASK_IDS, NumericDataset
from kurumi.text_dataset import NumericTextDataset

SEED = 28339
PROFILES = ("legacy", "conservative", "compact")
AUDIT_ROWS = re.compile(r"^\s*(?:营业(?:总)?收入|归属于(?:上市公司|母公司).{0,12}净利润)"
                        r"(?:\s*[（(]元[）)])? {2,}[-+−]?\d[^\n]*", re.M)
AMOUNT = re.compile(r"[-+−]?\d[\d,.]*(?:\s*(?:亿|万|千)?(?:元|吨|股|美元|%|％|倍)|\s*个百分点)")
EVENT = re.compile(r"报告期内|业绩|净利润|营业收入|合同|订单|中标|股权|收购|发行|减值|"
                   r"违约|诉讼|处罚|终止|停牌|批复|批准|重组|风险警示|投产|交付|销量")
QUALIFIER = re.compile(r"尚未|不再|不得|未能|如果|如未|若|待批准|终止|撤销|更正|修正")
NOISE = re.compile(r"董事会.{0,30}保证|重大遗漏|误导性陈述|不构成投资建议|网络版郑重声明|"
                   r"打印本页|上一篇|下一篇|点击查看|(?:证券代码|股票代码).{0,23}公告编号")
QUOTE_SPLIT = re.compile(r"(?<=[。！？])|\n[ \t]*\n|\f")


def independent_anchors(row, body, target_name):
    """Review designated financial rows and opening transaction clauses without consulting selectors."""
    if row["document_class"] == "periodic":
        lines = [m[0].strip() for m in AUDIT_ROWS.finditer(body[:23_000])]
        if lines:
            return list(dict.fromkeys(lines))[:2]
    targets = []
    for piece in QUOTE_SPLIT.split(body[:17_000]):
        clean = " ".join(piece.split())
        if not 20 <= len(clean) <= 310 or NOISE.search(clean) or not EVENT.search(clean):
            continue
        if row["kind"] == "announcement" and not re.search(r"[。！？][”’」』）)]*$", clean):
            continue
        if row["kind"] == "news" and (not target_name or target_name not in clean[:50]):
            continue
        if AMOUNT.search(clean) or QUALIFIER.search(clean):
            targets.append(clean)
        if len(targets) == 2:
            break
    return list(dict.fromkeys(targets))


def review_pairs(con, numeric, text):
    view(con, "docs", text / "documents/**/*.parquet")
    view(con, "entities", text / "document_entities/**/*.parquet")
    view(con, "eligibility", numeric / "reports/training_samples.parquet", "sample_id,local_trade_date,split")
    view(con, "stock_samples", numeric / "samples/**/*.parquet", "instrument_id,sample_id,local_trade_date,asof_utc")
    identity = IdentityHistory(con, numeric)
    rows = con.execute("""
        WITH candidates AS (
            SELECT d.* EXCLUDE(body_text),row_number() OVER (PARTITION BY d.kind,d.provider,
                floor(year(d.published_local_day)/3),d.document_class,d.correction_or_progress,
                coalesce(d.source_exchange,'news') ORDER BY hash(d.doc_version_id,?)) AS draw
            FROM docs d WHERE doc_version_id=original_version_id AND parse_status='ok'
                AND available_at IS NOT NULL AND provider<>'NBS'
        ), quota AS (
            SELECT * FROM candidates WHERE draw<=64
            QUALIFY row_number() OVER(PARTITION BY kind ORDER BY draw,hash(doc_version_id,?))
              <= CASE WHEN kind='news' THEN 960 ELSE 440 END
        )
        SELECT q.doc_version_id,q.kind,q.provider,q.publisher,q.title,q.published_local_day,q.published_raw,
               q.available_at,q.document_class,q.source_symbol,q.source_exchange,q.source_section,
               q.raw_ref,q.raw_hash,q.body_owner_ref
        FROM quota q
        ORDER BY q.draw,hash(q.doc_version_id,?)
    """, [SEED, SEED, SEED]).to_arrow_table().to_pylist()
    bodies = dict(document_bodies(text, {x["body_owner_ref"] for x in rows}))
    proposals = []
    for row in rows:
        row["body_text"] = bodies[row["body_owner_ref"]]
        row.update(symbol=row["source_symbol"], exchange=row["source_exchange"], section=row["source_section"])
        day = row["published_local_day"]
        relations = identity.associate(row, row["body_text"], day)
        for typ, instrument, _, _ in relations:
            if typ != "instrument":
                continue
            name = identity.name_at(instrument, day)
            labels = independent_anchors(row, row["body_text"], name)
            if labels:
                proposals.append((row, relations, instrument, name, labels))
    seed = pa.table({
        "pair": list(range(len(proposals))),
        "instrument_id": [x[2] for x in proposals],
        "published": pa.array([x[0]["published_local_day"] for x in proposals], pa.date32()),
        "available": pa.array([x[0]["available_at"] for x in proposals], pa.timestamp("us", tz="UTC")),
        "window": [LOOKBACK["company_news" if x[0]["kind"] == "news" else x[0]["document_class"]]
                   for x in proposals],
    })
    con.register("review_proposals", seed)
    sample_ids = dict(con.execute("""
        SELECT p.pair,arg_min(s.sample_id,s.local_trade_date)
        FROM review_proposals p JOIN stock_samples s USING(instrument_id)
        SEMI JOIN eligibility e ON s.sample_id=e.sample_id AND s.local_trade_date=e.local_trade_date
        WHERE p.available<=s.asof_utc AND s.local_trade_date>=p.published
          AND date_diff('day',p.published,s.local_trade_date)<p.window GROUP BY p.pair
    """).fetchall())
    pairs = []
    accepted = Counter()
    seen = set()
    for i, (row, relations, instrument, name, labels) in enumerate(proposals):
        if i not in sample_ids or accepted[row["kind"]] >= 100:
            continue
        distinct = [label for label in labels if (instrument, normal_literal(label)) not in seen]
        if not distinct:
            continue
        seen.update((instrument, normal_literal(label)) for label in distinct)
        pairs.append((row, relations, instrument, name, distinct, sample_ids[i]))
        accepted[row["kind"]] += 1
    return identity, pairs, dict(accepted)


def quantiles(values):
    items = sorted(values)
    return {f"p{p}": items[(p * (len(items) - 1) + 99) // 100] for p in (50, 90, 99)} if items else {}


def noise_tokens(block, family, name, identity, day, budget):
    seen = set()
    bad = 0
    # Count explicit boilerplate, unambiguously different opening issuers, and repeated sentences.
    for part in QUOTE_SPLIT.split(block.split("\n", 2)[-1]):
        text = part.strip()
        if not text:
            continue
        key = normal_literal(text)
        actors = identity.mentions(text[:40], day) if family == "news" else []
        other = bool(actors and name and actors[0][3] != name and name not in text)
        if key in seen or NOISE.search(text) or other:
            bad += budget.count(text)
        seen.add(key)
    return bad


def original_text_check(row, capture):
    if not row["raw_ref"] or not row["raw_hash"]:
        raise AssertionError("Review evidence must have original archive bytes")
    capture.read(row)


def comparison(con, numeric, text, checkpoint):
    import torch

    torch.set_num_threads(1)
    identity, pairs, counts = review_pairs(con, numeric, text)
    manifest = read_json(text / "manifest.json")
    capture = Capture(Path(manifest["capture_root"]))
    budget = NativeBudget(checkpoint)
    encoder = KarpoNumericEncoder.from_checkpoint(checkpoint)
    numeric_dataset = NumericDataset(numeric)
    ids = sorted({x[-1] for x in pairs})
    samples = {}
    for start in range(0, len(ids), 24):
        batch_ids = ids[start:start + 24]
        batch = numeric_dataset.load_batch(batch_ids)
        samples.update(zip(batch_ids, batch.model_input, strict=True))
    metrics, checked = defaultdict(Counter), set()
    totals, marginal, audit = defaultdict(list), defaultdict(list), []
    targets = Counter()
    for row, links, instrument, name, labels, sample_id in pairs:
        if row["raw_hash"] not in checked:
            original_text_check(row, capture)
            checked.add(row["raw_hash"])
        body = row["body_text"]
        base = samples[sample_id]["Xstate"]
        mode = row["kind"]
        channel = "news" if mode == "news" else "announcements"
        empty = dict(news=(), announcements=())
        numeric_plan = encoder.plan(samples[sample_id] | {"Xstate": base | {"Xtext": empty}})[0]
        expected = [normal_literal(x) for x in labels]
        targets[mode] += len(expected)
        started = perf_counter()
        old = choose_spans(row, body, budget)
        candidates = {"legacy": (old[0], perf_counter() - started)}
        started = perf_counter()
        facts = company_facts(row, body, identity, row["published_local_day"], links)
        spans = [s for (i, _), parts in facts.items() if i == instrument for s in parts]
        extraction_time = perf_counter() - started
        for variant in PROFILES[1:]:
            started = perf_counter()
            selected, *_ = pick_facts(row, spans, identity.issuers[instrument], name or "", budget, variant)
            candidates[variant] = (selected, perf_counter() - started + extraction_time)
        picked = {}
        for variant, (block, elapsed) in candidates.items():
            model_input = samples[sample_id] | {"Xstate": base | {"Xtext": empty | {
                channel: (block,) if block else ()}}}
            plan = encoder.plan(model_input)[0]
            assert plan.keys == TASK_IDS and plan.counts == (7, 7, 7)
            model_tokens = plan.length - numeric_plan.length
            kept = sum(label in normal_literal(block) for label in expected)
            noise = noise_tokens(block, mode, name, identity, row["published_local_day"], budget)
            key = (variant, mode)
            stats = metrics[key]
            stats.update(kept=kept, native_text_tokens=model_tokens, noise_tokens=noise, missing_block=int(not block),
                         selection_ms=round(elapsed * 1000, 4))
            totals[key].append(plan.length)
            marginal[key].append(model_tokens)
            picked[variant] = {"anchors_kept": kept, "native_tokens": plan.length}
        audit.append(dict(doc_version_id=row["doc_version_id"], sample_id=sample_id, source=row["provider"],
                          modality=mode, original_sha256=row["raw_hash"], anchors=len(labels), results=picked))
    return {"pairs": counts, "seed": SEED, "unique_originals": len(checked), "review": audit,
            "profiles": [{"profile": v, "modality": mode, "independent_anchors": targets[mode], **stats,
                          "native_total_tokens": quantiles(totals[v, mode]),
                          "marginal_native_tokens": quantiles(marginal[v, mode]),
                          "anchors_per_1000_native_text_tokens": round(1000 * stats["kept"] /
                                                                      max(1, stats["native_text_tokens"]), 4),
                          "explicit_noise_share": round(stats["noise_tokens"] / max(1, stats["native_text_tokens"]), 6)}
                         for (v, mode), stats in sorted(metrics.items())]}


def old_payload(plan):
    row = {name: None if (value := getattr(plan, name)) is None else value.tolist() for name in PLAN_TENSORS}
    return zlib.compress(json.dumps([dict(row, keys=plan.keys, counts=plan.counts)],
                                    separators=(",", ":")).encode(), level=1)


def benchmark(con, numeric, text, checkpoint, cache_dir):
    import psutil
    import torch

    torch.set_num_threads(1)
    process = psutil.Process()
    view(con, "supervision", numeric / "reports/training_samples.parquet", "sample_id,local_trade_date,split")
    view(con, "idx_all", text / "sample_text_index/**/*.parquet")
    ids = [r[0] for r in con.execute("""
        SELECT sample_id FROM idx_all i SEMI JOIN supervision s USING(sample_id,split,local_trade_date)
        QUALIFY row_number() OVER(PARTITION BY split,len(news_refs)>0,len(announcement_refs)>0,
            (news_tokens+announcement_tokens>=512) ORDER BY hash(i.sample_id,?))<=28
        ORDER BY local_trade_date,sample_id
    """, [SEED]).fetchall()]
    loader = NumericTextDataset(numeric, text)
    encoder = KarpoNumericEncoder.from_checkpoint(checkpoint)
    sampling = [(ids[start:start + 32]) for start in range(0, len(ids), 32)]

    def counters():
        mem = process.memory_info()
        io = process.io_counters()
        return mem.rss, getattr(mem, "peak_wset", mem.rss), io.read_bytes, io.write_bytes

    before_load = counters()
    started = perf_counter()
    batches = [loader.load_batch(ids, condition="both") for ids in sampling]
    load_seconds = perf_counter() - started
    begin = counters()
    start = perf_counter()
    encoded = [plan[0] for batch in batches for plan in loader.plan_batch(encoder, batch)]
    cold_seconds = perf_counter() - start
    after_cold = counters()
    counters_by_profile = {}
    with_cache = EncodingCache(cache_dir, max_bytes=120 * 1024**2, touch_interval_seconds=60)
    try:
        for strategy, serializer in (("legacy_json", old_payload), ("binary", lambda plan: _plan_to_bytes([plan]))):
            start = perf_counter()
            raw = [serializer(plan) for plan in encoded]
            serialized = perf_counter() - start
            before_write = counters()
            for key, payload in zip(ids, raw, strict=True):
                with_cache.put(strategy, "fixed", key, "native", payload)
            after_write = counters()
            # Time warm SQLite access and decoding separately from equivalence assertions.
            times = []
            for _ in range(3):
                start = perf_counter()
                restored = [_plan_from_bytes(with_cache.get(strategy, "fixed", key, "native"))[0] for key in ids]
                times.append(perf_counter() - start)
            after_warm = counters()
            for a, b in zip(encoded, restored, strict=True):
                assert a.keys == b.keys and a.counts == b.counts
                for name in PLAN_TENSORS:
                    x, y = getattr(a, name), getattr(b, name)
                    assert x is y if x is None else y is not None and x.dtype == y.dtype and torch.equal(x, y)
            counters_by_profile[strategy] = dict(serialize_seconds=serialized, warm_seconds=median(times),
                warm_samples_per_second=len(ids) / median(times), payload_bytes=sum(map(len, raw)),
                io_read_bytes=after_warm[2] - after_write[2], io_write_bytes=after_write[3] - before_write[3],
                peak_rss_bytes=after_warm[1])
        for batch in batches[:1]:
            first = loader.plan_batch(encoder, batch, cache=with_cache)
            second = loader.plan_batch(encoder, batch, cache=with_cache)
            for a, b in zip(first, second, strict=True):
                for field in PLAN_TENSORS:
                    x, y = getattr(a[0], field), getattr(b[0], field)
                    assert x is y if x is None else y is not None and torch.equal(x, y)
    finally:
        with_cache.close()
    return dict(samples=len(ids), seed=SEED, sample_ids_sha256=hashlib.sha256("\n".join(ids).encode()).hexdigest(),
                load_seconds=load_seconds, uncached_native_seconds=cold_seconds,
                load_read_bytes=begin[2] - before_load[2], load_write_bytes=begin[3] - before_load[3],
                uncached_samples_per_second=len(ids) / cold_seconds, load_and_encode_native_tokens=quantiles(
                    [p.length for p in encoded]), cold_read_bytes=after_cold[2] - begin[2],
                cold_write_bytes=after_cold[3] - begin[3], cold_peak_rss_bytes=after_cold[1],
                cache=counters_by_profile, tensor_equality=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("numeric", "text", "tokenizer", "cache", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    numeric, _, _ = checked_anchor(args.numeric)
    args.cache.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 2, "memory_limit": "2400MB", "temp_directory": str(args.cache)}) as con:
        checks = comparison(con, numeric, args.text, args.tokenizer)
        print(f"Compared {sum(checks['pairs'].values())} shared document/sample pairs", flush=True)
        checks["native_cpu_benchmark"] = benchmark(con, numeric, args.text, args.tokenizer, args.cache)
    checks["text_version"] = read_json(args.text / "manifest.json")["text_version"]
    write_json(args.output, checks)
    print(args.output)


if __name__ == "__main__":
    main()
