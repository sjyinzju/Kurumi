"""Audit actual text companions and exercise native Karpo with the pinned numeric loader."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from time import perf_counter

import duckdb
import pyarrow.dataset as ds

from kurumi.cn_text_corpus import FACTS, NativeBudget
from kurumi.cn_text_index import checked_anchor
from kurumi.cn_text_sources import Capture, file_hash, read_json, write_json
from kurumi.encoding_cache import EncodingCache
from kurumi.karpo_numeric import KarpoNumericEncoder, packed_logits, request_from_input
from kurumi.numeric_loader import TASK_IDS, NumericDataset
from kurumi.text_dataset import NumericTextDataset
from kurumi.text_input import BUDGET, TRAIN_CONDITIONS, section_text


def view(con, name, path, extra_sql="*"):
    con.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS SELECT {extra_sql} FROM read_parquet("
                "'" + Path(path).as_posix().replace("'", "''") + "', hive_partitioning=false)")


def document_bodies(directory, references):
    years = defaultdict(list)
    for ref in references:
        years[int(ref.split(":", 1)[0])].append(ref)
    table = ds.dataset(directory / "documents", format="parquet", partitioning="hive")
    for year, keys in sorted(years.items()):
        where = (ds.field("year") == year) & ds.field("doc_version_id").isin(keys)
        batches = table.to_batches(columns=["doc_version_id", "body_text"], filter=where,
                                   batch_size=12, batch_readahead=1, fragment_readahead=1, use_threads=False)
        for batch in batches:
            for item in batch.to_pylist():
                yield item["doc_version_id"], item["body_text"]


def census(con, numeric, text, manifest, budget):
    view(con, "docs", text / "documents/**/*.parquet")
    view(con, "entities", text / "document_entities/**/*.parquet")
    view(con, "samples", numeric / "samples/**/*.parquet",
         "sample_id,local_trade_date,asof_utc,instrument_id,issuer_id,split,"
         " classification_version || '|' || industry_code_asof AS industry_key")
    view(con, "supervision", numeric / "reports/training_samples.parquet",
         "sample_id,local_trade_date,split")
    view(con, "idx_all", text / "sample_text_index/**/*.parquet")
    view(con, "coverage", text / "coverage.parquet")
    con.execute("""
        CREATE TEMP TABLE direct_news AS SELECT DISTINCT e.doc_version_id FROM entities e JOIN docs d USING(doc_version_id)
        WHERE d.kind='news' AND d.input_text IS NOT NULL AND e.entity_type IN ('instrument','issuer')
    """)
    count_stats = []
    plans = set()
    lo, hi = [date.fromisoformat(x) for x in manifest["sample_range"]]
    capture = Capture(Path(manifest["capture_root"]))
    for shard in sorted((text / "sample_text_index").glob("month=*/part.parquet")):
        if shard.parent.name.endswith(("-03", "-06", "-09", "-12")):
            print(f"Verifying {shard.parent.name}", flush=True)
        view(con, "idx", shard)
        start, end, count, distinct = con.execute(
            "SELECT min(local_trade_date),max(local_trade_date),count(*),count(DISTINCT sample_id) FROM idx").fetchone()
        if start < lo or end > hi or count != distinct:
            raise AssertionError(f"Incorrect shard scope or duplicate keys {shard}")
        expected = con.execute("SELECT count(*) FROM samples WHERE local_trade_date BETWEEN ? AND ?",
                               [start, end]).fetchone()[0]
        invalid = con.execute("""
            SELECT count(*) FROM idx i LEFT JOIN (SELECT * FROM samples WHERE local_trade_date BETWEEN ? AND ?) s USING(sample_id)
            WHERE s.sample_id IS NULL OR i.local_trade_date IS DISTINCT FROM s.local_trade_date
              OR i.asof_utc IS DISTINCT FROM s.asof_utc OR i.split IS DISTINCT FROM s.split
              OR i.instrument_id IS DISTINCT FROM s.instrument_id OR i.issuer_id IS DISTINCT FROM s.issuer_id
              OR i.industry_key IS DISTINCT FROM s.industry_key OR i.text_version <> ?
              OR (len(i.news_refs)>0) <> (i.news_status IN ('partial','present'))
              OR (len(i.announcement_refs)>0) <> (i.announcement_status IN ('partial','present'))
        """, [start, end, manifest["text_version"]]).fetchone()[0]
        if count != expected or invalid:
            raise AssertionError(f"Sample key/identity/cutoff mismatch {shard}: {count}, {expected}, {invalid}")
        bad = con.execute("""
            WITH refs AS (
                SELECT DISTINCT local_trade_date,asof_utc,'news' AS modality,unnest(news_refs) AS ref FROM idx
                UNION ALL
                SELECT DISTINCT local_trade_date,asof_utc,'announcement',unnest(announcement_refs) FROM idx
            )
            SELECT count(*) FROM refs r LEFT JOIN docs d ON r.ref=d.doc_version_id
            LEFT JOIN direct_news n ON n.doc_version_id=d.doc_version_id
            WHERE d.doc_version_id IS NULL OR d.kind<>r.modality OR d.input_text IS NULL
              OR d.available_at IS NULL OR d.available_at>r.asof_utc OR d.published_local_day>r.local_trade_date
              OR d.published_local_day<r.local_trade_date -
                 CASE WHEN d.kind='news' THEN IF(n.doc_version_id IS NULL,2,6)
                      WHEN d.document_class='periodic' THEN 179 ELSE 29 END
        """).fetchone()[0]
        association = con.execute("""
            WITH flattened AS (
                SELECT instrument_id,issuer_id,industry_key,'news' AS modality,unnest(news_refs) AS ref FROM idx
                UNION ALL
                SELECT instrument_id,issuer_id,industry_key,'announcement',unnest(announcement_refs) FROM idx
            ), valid AS (
                SELECT DISTINCT instrument_id,issuer_id,industry_key,modality,ref FROM flattened
            )
            SELECT count(*) FROM valid f
            WHERE NOT EXISTS (
                SELECT 1 FROM entities e WHERE e.doc_version_id=f.ref AND (
                  (e.entity_type='instrument' AND e.entity_id=f.instrument_id)
                  OR (e.entity_type='issuer' AND e.entity_id=f.issuer_id)
                  OR (f.modality='news' AND e.entity_type='market' AND e.entity_id='CN')
                  OR (f.modality='news' AND e.entity_type='industry' AND e.entity_id=f.industry_key)
                ))
        """).fetchone()[0]
        if bad or association:
            raise AssertionError(f"Invalid as-of or entity refs {shard}: {bad}, {association}")
        for mode in ("news", "announcement"):
            for refs, count_value in con.execute(
                f"SELECT DISTINCT {mode}_refs,{mode}_tokens FROM idx"
            ).fetchall():
                plans.add((mode, tuple(refs), count_value))
        counts = con.execute("""
            WITH per_context AS (
                SELECT DISTINCT selection_hash,news_refs FROM idx
            ), direct_context AS (
                SELECT DISTINCT selection_hash FROM per_context,unnest(news_refs) AS n(ref)
                JOIN direct_news d ON d.doc_version_id=n.ref
            )
            SELECT i.split, count(*) AS supervised, count(*) FILTER (len(news_refs)>0) AS news,
                count(*) FILTER (len(announcement_refs)>0) AS announcement,
                count(*) FILTER (len(news_refs)>0 AND len(announcement_refs)>0) AS both,
                count(*) FILTER (direct_context.selection_hash IS NOT NULL) AS company_news
            FROM idx i INNER JOIN (SELECT * FROM supervision WHERE local_trade_date BETWEEN ? AND ?) s
                USING (sample_id,local_trade_date,split)
                LEFT JOIN direct_context ON i.selection_hash=direct_context.selection_hash GROUP BY i.split
        """, [start, end]).fetchall()
        count_stats.extend([dict(zip(("month", "split", "supervised", "news", "announcement", "both", "company_news"),
                                     (str(start)[:7], *row), strict=True)) for row in counts])
    expected_samples = con.execute("SELECT count(*) FROM samples WHERE local_trade_date BETWEEN ? AND ?",
                                   [lo, hi]).fetchone()[0]
    if con.execute("SELECT count(*) FROM idx_all").fetchone()[0] != expected_samples or (
        manifest["sample_count"] != expected_samples
    ):
        raise AssertionError("Text index does not cover the complete declared numeric sample range")
    in_docs = dict(con.execute("SELECT doc_version_id,input_text FROM docs WHERE input_text IS NOT NULL").fetchall())
    ordered = sorted(plans)
    for start in range(0, len(ordered), 192):
        chunk = ordered[start:start + 192]
        texts = [section_text(mode, [in_docs[k] for k in refs]) if refs else "" for mode, refs, _ in chunk]
        for actual, (mode, refs, count_value) in zip(budget.counts(texts), chunk, strict=True):
            if actual != count_value or actual > BUDGET:
                raise AssertionError(f"Token budget mismatch for {mode} {refs}")
    broken = con.execute("""
        WITH owners AS MATERIALIZED (
            SELECT doc_version_id, sha256(body_text) AS digest, length(body_text) AS chars
            FROM docs WHERE body_text IS NOT NULL
        )
        SELECT count(*) FROM docs d LEFT JOIN owners o ON d.body_owner_ref=o.doc_version_id
        WHERE (d.body_hash IS NOT NULL AND (o.digest IS NULL OR o.digest<>d.body_hash))
           OR EXISTS (SELECT 1 FROM unnest(d.input_spans) AS t(span)
             WHERE span.start<0 OR span."end">o.chars OR span.start>=span."end")
           OR (d.input_text IS NOT NULL AND (d.raw_ref IS NULL OR d.raw_hash IS NULL))
    """).fetchone()[0]
    if broken:
        raise AssertionError(f"Body ownership, raw references, or selected offsets invalid: {broken}")
    if "evidence" in manifest["config"]:
        invalid_evidence = con.execute("""
            SELECT count(*) FROM docs d WHERE input_text IS NOT NULL AND (
                evidence_issuer_id IS NULL AND (kind='announcement' OR relation_status<>'background')
                OR evidence_issuer_id IS NOT NULL AND (
                    len(evidence_keys)<>len(input_spans) OR len(evidence_keys)=0 OR NOT EXISTS (
                        SELECT 1 FROM entities e WHERE e.doc_version_id=d.doc_version_id
                        AND e.entity_type='issuer' AND e.entity_id=d.evidence_issuer_id)))
        """).fetchone()[0]
        invalid_versions = con.execute("""
            SELECT count(*) FROM docs d LEFT JOIN docs prior ON prior.doc_version_id=d.related_prior_event
            WHERE d.related_prior_event IS NOT NULL AND
                (prior.doc_version_id IS NULL OR prior.available_at>=d.available_at
                 OR prior.event_thread IS DISTINCT FROM d.event_thread)
        """).fetchone()[0]
        if invalid_evidence or invalid_versions:
            raise AssertionError(f"Invalid model evidence or prior-event lineage: {invalid_evidence}, {invalid_versions}")
    original_locations = con.execute(
        "SELECT DISTINCT raw_ref,raw_hash FROM docs WHERE input_text IS NOT NULL").fetchall()
    for ref, digest in original_locations:
        path = capture.root / Path(ref)
        if path.suffix == ".gz":
            capture.read({"raw_ref": ref, "raw_hash": digest})
        elif file_hash(path) != digest:
            raise AssertionError(f"Eligible original bytes changed for {ref}")
    edits = con.execute("""
        WITH chosen AS MATERIALIZED (
            SELECT doc_version_id,provider,title,published_local_day,raw_ref,raw_hash,
                   input_text,input_spans,body_owner_ref
            FROM docs WHERE input_text IS NOT NULL AND kind='announcement'
              AND (correction_or_progress OR document_class='event')
            ORDER BY correction_or_progress DESC,published_local_day DESC,doc_version_id LIMIT 12
        )
        SELECT doc_version_id,provider,title,published_local_day,raw_ref,raw_hash,
            body_owner_ref,input_text,input_spans
        FROM chosen
    """).fetchall()
    fact_audit = []
    owners = dict(document_bodies(text, {r[6] for r in edits}))
    for version, provider, title, day, ref, digest, owner, rendered, spans in edits:
        absolute = Path(ref)
        if absolute.is_absolute() and absolute.suffix != ".gz":
            if file_hash(absolute) != digest:
                raise AssertionError(f"Original evidence changed for {version}")
        else:
            capture.read({"raw_ref": ref, "raw_hash": digest})
        clean = [" ".join(owners[owner][s["start"]:s["end"]].split()) for s in spans]
        if not all(text in rendered for text in clean):
            raise AssertionError(f"Selected span is not in actual rendered context: {version}")
        fact_audit.append({"doc_version_id": version, "provider": provider, "title": title, "publication": str(day),
                           "verified_source_hash": digest, "evidence_spans": spans,
                           "number_and_qualifier_markers": len(FACTS.findall("\n".join(clean)))})
    document_report = con.execute("""
        SELECT provider,kind,parse_status,relation_status,count(*) FROM docs GROUP BY ALL ORDER BY ALL
    """).fetchall()
    yearly = con.execute("""
        SELECT year(published_local_day),kind,count(*),count(*) FILTER(input_text IS NOT NULL)
        FROM docs GROUP BY ALL ORDER BY ALL
    """).fetchall()
    eligible_summary = con.execute("""
        SELECT kind,count(*),count(DISTINCT duplicate_group),count(*) FILTER (raw_tokens_measured IS NOT NULL),
            sum(raw_tokens_measured),sum(input_tokens) FILTER (raw_tokens_measured IS NOT NULL),
            sum(body_fact_markers),sum(kept_fact_markers),median(input_tokens)
        FROM docs WHERE input_text IS NOT NULL GROUP BY kind ORDER BY kind
    """).fetchall()
    vendors = con.execute("""
        SELECT d.kind, e.entity_type, e.match_method, count(DISTINCT e.entity_id), count(*)
        FROM docs d JOIN entities e USING(doc_version_id)
        WHERE d.input_text IS NOT NULL GROUP BY ALL ORDER BY ALL
    """).fetchall()
    source_scope_counts = con.execute("""
        SELECT source,kind,query_status,count(*),sum(returned_count),sum(body_success_count),
            sum(body_missing_count),sum(download_failed_count),sum(parse_failed_count),
            min(first_publication),max(last_publication)
        FROM coverage GROUP BY ALL ORDER BY ALL
    """).fetchall()
    view(con, "security_history", numeric / "reference/security_history.parquet")
    securities = con.execute("""
        SELECT h.exchange,count(DISTINCT h.instrument_id),count(DISTINCT h.instrument_id) FILTER(h.delisting_date IS NOT NULL),
            count(DISTINCT e.entity_id) FILTER(d.kind='announcement'),count(DISTINCT e.entity_id) FILTER(d.kind='news')
        FROM security_history h
        SEMI JOIN (SELECT DISTINCT instrument_id FROM idx_all) i USING(instrument_id)
        LEFT JOIN entities e ON e.entity_type='instrument' AND h.instrument_id=e.entity_id
        LEFT JOIN docs d ON d.doc_version_id=e.doc_version_id AND d.input_text IS NOT NULL
        GROUP BY h.exchange ORDER BY h.exchange
    """).fetchall()
    return {"indexed_rows": expected_samples, "source_scope_counts": source_scope_counts, "securities": securities, "source_stats": document_report, "publication_year": yearly,
            "model_eligible_stats": eligible_summary, "associations": vendors, "supervised_monthly": count_stats,
            "distinct_native_sections_verified": len(plans),
            "distinct_eligible_original_paths_verified": len(original_locations), "fact_and_source_spot_checks": fact_audit,
            "for_all_index_rows": "numeric keys, cutoff, document versions, eligible entity and modality budgets",
            "eligible_original_bytes_sha256_checked": True}


def example_ids(con, numeric, text):
    view(con, "idx", text / "sample_text_index/**/*.parquet")
    view(con, "supervision", numeric / "reports/training_samples.parquet", "sample_id,local_trade_date,split")
    return [row[0] for row in con.execute("""
        WITH eligible AS (
            SELECT i.*, concat((len(news_refs)>0)::INT, (len(announcement_refs)>0)::INT) AS coverage
            FROM idx i SEMI JOIN supervision s USING (sample_id,local_trade_date,split)
        )
        SELECT min(sample_id) FROM eligible GROUP BY coverage
        ORDER BY coverage DESC
    """).fetchall()]


def historical_smoke(con, loader):
    retired = con.execute("""
        SELECT i.sample_id,h.delisting_date FROM idx i
        JOIN read_parquet(?) h USING(instrument_id)
        SEMI JOIN supervision s USING(sample_id,local_trade_date,split)
        WHERE h.delisting_date IS NOT NULL AND i.local_trade_date<=h.delisting_date
          AND len(i.announcement_refs)>0 ORDER BY i.local_trade_date LIMIT 1
    """, [(loader.numeric.directory / "reference/security_history.parquet").as_posix()]).fetchone()
    proof = {}
    if retired:
        sid, delisting = retired
        batch = loader.load_batch((sid,), condition="announcement")
        assert batch.model_input[0]["Xstate"]["Xtext"]["announcements"]
        proof["retired_sample"] = {"sample_id": sid, "delisting": str(delisting)}
    codes = [
        ("CN|CN-302132.SZ|2025-02-14", "300114"),
        ("CN|CN-302132.SZ|2025-02-17", "302132"),
    ]
    ids = [x[0] for x in codes]
    if con.execute("SELECT count(*) FROM idx WHERE sample_id IN (?,?)", ids).fetchone()[0] == len(ids):
        models = loader.load_model_inputs(ids, condition="both")
        for (sid, symbol), model in zip(codes, models, strict=True):
            identity = model["Xstate"]["Xstock"]["identity"]
            assert identity["symbol_asof"] == symbol
            proof.setdefault("code_switch", []).append({"sample_id": sid, "historical_symbol": symbol})
    return proof


def native_smoke(con, numeric_path, text_path, tokenizer, cache_path):
    import torch
    from karpo_decision.model.packed import pack
    from karpo_decision.model.readout import Readout

    torch.set_num_threads(1)
    numeric = NumericDataset(numeric_path)
    loader = NumericTextDataset(numeric, text_path)
    encoder = KarpoNumericEncoder.from_checkpoint(tokenizer)
    sample_ids = example_ids(con, numeric_path, text_path)
    if not sample_ids:
        raise AssertionError("No supervised samples found for native text QA")
    original = numeric.load_batch(sample_ids)
    cache = EncodingCache(cache_path, max_bytes=24 * 1024**2, touch_interval_seconds=60)
    conditions = {}
    contexts = {}
    results = {}
    device = torch.device("cpu")
    try:
        for group, mode in TRAIN_CONDITIONS.items():
            batch = loader.load_batch(sample_ids, condition=mode)
            assert original.supervision == batch.supervision
            for before, after in zip(original.model_input, batch.model_input, strict=True):
                assert before["Xchoice"] == after["Xchoice"]
                assert {k: v for k, v in before["Xstate"].items() if k != "Xtext"} == {
                    k: v for k, v in after["Xstate"].items() if k != "Xtext"
                }
                expected_prefix = request_from_input(before)["state"].removesuffix("\n[Text slot] not_built")
                assert request_from_input(after)["state"].startswith(expected_prefix + "\n[News]")
                assert len(after["Xstate"]["Xstock"]["sequence"]) == 60
            contexts[group] = [a["Xstate"]["Xtext"] for a in batch.model_input]
            start = perf_counter()
            encoded = loader.plan_batch(encoder, batch)
            cold = perf_counter() - start
            loader.plan_batch(encoder, batch, cache=cache)
            start = perf_counter()
            cached = loader.plan_batch(encoder, batch, cache=cache)
            warm = perf_counter() - start
            packed = pack([p[0] for p in encoded], None, device)
            for request, native, replay in zip(batch.model_input, encoded, cached, strict=True):
                assert len(native) == len(replay) == 1 and native[0].keys == TASK_IDS and native[0].counts == (7, 7, 7)
                assert all(torch.equal(getattr(native[0], k), getattr(replay[0], k))
                           for k in ("markers", "input_ids", "positions", "segment_ids"))
                assert set(native[0].segment_ids.unique().tolist()) == {0, 1, 2, 3}
                req = request_from_input(request)
                shared = encoder.encoder.blocks.shared(req["state"], list(req["questions"].values()))
                assert native[0].input_ids[native[0].segment_ids == 0].tolist() == shared
            assert packed.marker_cu.tolist() == list(range(0, 3 * len(sample_ids) + 1, 3))
            conditions[group] = {"effective_text_condition": mode, "packed_tokens": packed.tokens,
                                 "per_sample_tokens": [p[0].length for p in encoded],
                                 "uncached_plan_ms": round(cold * 1000, 2), "cache_hit_plan_ms": round(warm * 1000, 2)}
            results[group] = encoded
        for zero, news, ann, both in zip(*(contexts[g] for g in ("G0", "GN", "GA", "GNA")), strict=True):
            assert zero == {"news": (), "announcements": ()}
            assert news["news"] == both["news"] and not news["announcements"]
            assert ann["announcements"] == both["announcements"] and not ann["news"]
        headings = loader.load_model_inputs(sample_ids, condition="both")
        assert [x["Xstate"]["Xtext"] for x in headings] == contexts["GNA"]
        phase_batch = loader.load_research_batch([sample_ids[0]], group="G0", phase="inference")
        assert phase_batch.audit[0]["text"]["text_condition"] == "both"
        # Exercise native pack/readout and differentiation with a tiny stand-in for the 31B backbone.
        embed = torch.nn.Embedding(17, 4)
        readout = Readout.from_rows(torch.arange(28, dtype=torch.float32).reshape(7, 4) / 28)
        logits = packed_logits(results["GNA"],
                               lambda p: embed(p.input_ids[p.markers].remainder(17)),
                               None, readout, device)
        assert tuple(logits.shape) == (len(sample_ids), 3, 7)
        labels = torch.tensor(original.supervision.target_class)
        mask = torch.tensor(original.supervision.label_mask)
        torch.nn.functional.cross_entropy(logits[mask], labels[mask]).backward()
        assert readout.weight.grad.abs().sum() > 0 and embed.weight.grad.abs().sum() > 0
    finally:
        cache.close()
    return {"samples": sample_ids, "natural_empty_contexts": sum(
                not item["news"] and not item["announcements"] for item in contexts["GNA"]),
            "all_modes": conditions, "native_pack_readout_shape": list(logits.shape),
            "numerics_choices_and_supervision_identical": True,
            "cpu_readout_backprop_with_tiny_standin": True,
            "document_reader_cache_entries": len(loader.document_cache),
            "historical_identity_verified": historical_smoke(con, loader)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--numeric", type=Path, required=True)
    p.add_argument("--text", type=Path, required=True)
    p.add_argument("--tokenizer", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--native-only", action="store_true")
    args = p.parse_args()
    numeric, _, _ = checked_anchor(args.numeric)
    manifest = read_json(args.text / "manifest.json")
    if manifest["numeric_path"] != str(numeric):
        raise ValueError("Text verification must use the pinned numeric anchor")
    budget = NativeBudget(args.tokenizer)
    if manifest["config"]["tokenizer"] != budget.revision:
        raise ValueError("Tokenizer asset hashes differ")
    for key, digest in manifest.get("source_scope_receipts", {}).items():
        saved = args.text / "scope_receipts" / (digest + ".json.gz")
        actual = (saved if saved.is_file() else Path(manifest["capture_root"]) / key)
        if saved.is_file():
            from kurumi.cn_text_sources import sha

            valid = sha(gzip.decompress(actual.read_bytes())) == digest
        else:
            valid = file_hash(actual) == digest
        if not valid:
            raise AssertionError(f"Archived source scope hash mismatch {key}")
    for filename, digest in manifest.get("source_inputs", {}).items():
        if file_hash(Path(filename)) != digest:
            raise AssertionError(f"Archived source input hash mismatch {filename}")
    for key, file in manifest["files"].items():
        actual = args.text / key
        if actual.stat().st_size != file["bytes"] or file_hash(actual) != file["sha256"]:
            raise AssertionError(f"Manifest file hash mismatch {key}")
    start = perf_counter()
    args.cache.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 2, "memory_limit": "1400MB",
                               "temp_directory": str(args.cache / "duckdb")}) as con:
        data = {} if args.native_only else census(con, numeric, args.text, manifest, budget)
        data["native"] = native_smoke(con, numeric, args.text, args.tokenizer, args.cache)
    data["verified_seconds"] = round(perf_counter() - start, 2)
    data["text_version"] = manifest["text_version"]
    write_json(args.output, json.loads(json.dumps(data, default=str)))
    print(json.dumps({"text_version": data["text_version"], "indexed_rows": data.get("indexed_rows"),
                      "native_samples": data["native"]["samples"], "seconds": data["verified_seconds"]}))


if __name__ == "__main__":
    main()
