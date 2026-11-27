"""Measure qualified text coverage on the frozen numeric supervision population."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
from verify_cn_text import document_bodies, view

from kurumi.cn_text_corpus import IdentityHistory
from kurumi.cn_text_facts import company_facts, normal_literal
from kurumi.cn_text_index import ANCHOR, LOOKBACK, SPLIT_COUNTS, checked_anchor
from kurumi.cn_text_sources import file_hash, read_json, write_json

METRICS = (
    "eligible", "news", "announcement", "both", "company_text", "background_only", "no_company_text_in_complete_scope",
    "news_unavailable", "announcement_unavailable", "neither_mode_has_content", "periodic", "event", "periodic_only",
    "event_only", "new_original_selected", "only_new_originals", "baseline_news", "baseline_announcement",
    "baseline_both", "baseline_company_text", "gained", "lost", "exact_cross_mode_overlap",
)
SNAPSHOT_FIELDS = (
    "doc_version_id", "kind", "provider", "publisher", "title", "published_local_day", "rendered", "owner", "instrument",
    "method", "document_class",
)


def baseline_qualification(con, numeric, baseline):
    view(con, "old_docs", baseline / "documents/**/*.parquet")
    view(con, "old_entities", baseline / "document_entities/**/*.parquet")
    identity = IdentityHistory(con, numeric)
    originals = defaultdict(list)
    for item in con.execute("""
        SELECT d.doc_version_id,d.kind,d.provider,d.publisher,d.title,d.published_local_day,d.input_text,
               d.body_owner_ref,e.entity_id,e.match_method,d.document_class
        FROM old_docs d
        JOIN old_entities e ON e.doc_version_id=d.doc_version_id AND e.entity_type='instrument'
        WHERE d.input_text IS NOT NULL AND d.available_at IS NOT NULL AND d.body_owner_ref IS NOT NULL
    """).fetchall():
        row = dict(zip(SNAPSHOT_FIELDS, item, strict=True))
        originals[row["owner"]].append(row)
    qualifies = []
    for owner, body in document_bodies(baseline, originals):
        for row in originals[owner]:
            actor = row["instrument"]
            issuer = identity.issuers[actor]
            relation = [("instrument", actor, "direct", row["method"])]
            facts = company_facts(row, body, identity, row["published_local_day"], relation)
            rendered = normal_literal(row["rendered"])
            if any(normal_literal(span[-1]) in rendered for (instrument, _), spans in facts.items() if instrument == actor
                   for span in spans):
                qualifies.append((row["doc_version_id"], issuer, row["kind"]))
    con.register("baseline_facts", pa.table({
        "ref": pa.array([x[0] for x in qualifies], pa.string()),
        "issuer": pa.array([x[1] for x in qualifies], pa.string()),
        "mode": pa.array([x[2] for x in qualifies], pa.string()),
    }))
    return len(set(qualifies))


def publication_inventory(con, manifest, raw_audit):
    declaration = {
        "CNSTOCK-paper": (date.fromisoformat(manifest["sample_range"][0]) - timedelta(days=6),
                         date.fromisoformat(manifest["sample_range"][1]), (None,)),
        "STCN-paper": (date.fromisoformat(manifest["sample_range"][0]) - timedelta(days=6),
                      min(date(2022, 12, 31), date.fromisoformat(manifest["sample_range"][1])), (None,)),
        "CS-paper": (date.fromisoformat(manifest["sample_range"][0]) - timedelta(days=6),
                     date.fromisoformat(manifest["sample_range"][1]), (None,)),
        "ZQRB-paper": (max(date(2020, 1, 1), date.fromisoformat(manifest["sample_range"][0]) - timedelta(days=6)),
                       date.fromisoformat(manifest["sample_range"][1]), (None,)),
        "CNINFO": (*map(date.fromisoformat, manifest["requested_capture_range"]), ("SSE", "SZSE", "BSE")),
    }
    directories = []
    for provider, (lo, hi, venues) in declaration.items():
        for exchange in venues:
            start = max(lo, date(2021, 11, 15)) if exchange == "BSE" else lo
            if start > hi:
                continue
            status = Counter()
            day_status = {}
            for begin, end, state, complete in con.execute("""
                SELECT start_at,end_at,query_status,pagination_complete FROM coverage WHERE
                directory_scope AND source=? AND exchange IS NOT DISTINCT FROM ?
            """, [provider, exchange]).fetchall():
                status[state] += 1
                for i in range((min(end, hi) - max(start, begin)).days + 1):
                    day = max(start, begin) + timedelta(days=i)
                    rank = 2 if complete else 1
                    day_status[day] = max(day_status.get(day, 0), rank)
            days = (hi - start).days + 1
            valid = sum(rank == 2 for rank in day_status.values())
            directories.append(dict(provider=provider, exchange=exchange, start=str(start), end=str(hi),
                                    natural_days=days, reconciled_days=valid, failed_or_partial_days=len(day_status)-valid,
                                    unobserved_days=days-len(day_status), partition_outcomes=dict(status)))
    # Count original documents across repeated categories and carriers with observed duplicates reconciled.
    # Rows without bytes cannot be merged across publishers based solely on their headlines.
    inventory = con.execute("""
        WITH per_doc AS (
            SELECT CASE WHEN provider='CNINFO' THEN 'announcement' ELSE 'news' END AS catalogue,
                coalesce(min(duplicate_group) OVER (PARTITION BY doc_id),doc_id) AS identity,
                parse_status='ok' AND available_at IS NOT NULL
                  AND (evidence_issuer_id IS NOT NULL OR relation_status='background') AS processed,
                raw_hash IS NOT NULL AS fetched, available_at IS NULL AND parse_status='ok' AS bad_time,
                parse_status='ok' AND available_at IS NOT NULL AS parsed_with_clock,
                parse_status IN ('download_failed') AS failed_download,
                parse_status NOT IN ('ok','download_failed','body_missing','outside_anchored_listing') AS failed_parse,
                parse_status='ok' AND available_at IS NOT NULL
                  AND evidence_issuer_id IS NULL AND relation_status<>'background' AS association_open
            FROM all_docs WHERE directory_member
        ), groups AS (
            SELECT catalogue,identity,
                bool_or(processed) AS processed,bool_or(fetched) AS fetched,bool_or(bad_time) AS bad_time,
                bool_or(failed_download) AS failed_download,bool_or(failed_parse) AS failed_parse,
                bool_or(parsed_with_clock) AS parsed_with_clock,
                bool_or(association_open) AS association_open
            FROM per_doc GROUP BY ALL
        )
        SELECT catalogue,count(*),count(*) FILTER(processed),count(*) FILTER(fetched),count(*) FILTER(parsed_with_clock),
            count(*) FILTER(NOT processed AND bad_time),count(*) FILTER(NOT processed AND failed_download),
            count(*) FILTER(NOT processed AND failed_parse),count(*) FILTER(NOT processed AND association_open),
            count(*) FILTER(NOT fetched AND NOT failed_download)
        FROM groups GROUP BY ALL ORDER BY 1
    """).fetchall()
    by_kind = [dict(zip(("modality", "known_unique_directory_docs", "processed", "acquired", "parsed_with_clock",
                       "unresolved_publication", "failed_download", "failed_parse", "association_unresolved",
                       "no_attempted_body"), row, strict=True)) for row in inventory]
    source = con.execute("""
        SELECT provider,doc_kind,count(DISTINCT doc_id),count(DISTINCT doc_id) FILTER(raw_hash IS NOT NULL),
               count(DISTINCT doc_id) FILTER(parse_status='ok'),count(DISTINCT doc_id) FILTER(evidence_issuer_id IS NOT NULL),
               count(DISTINCT coalesce(duplicate_group,doc_id)) FILTER(is_new AND parse_status='ok'),
               min(published_local_day) FILTER(parse_status='ok'),max(published_local_day) FILTER(parse_status='ok'),
               min(published_local_day) FILTER(is_new AND parse_status='ok'),
               max(published_local_day) FILTER(is_new AND parse_status='ok')
        FROM all_docs GROUP BY ALL ORDER BY ALL
    """).fetchall()
    return {"directories": directories, "observed_catalogue_counts": by_kind, "source_originals": source,
            "publication_probes": raw_audit}


def check_month(con, current, old):
    view(con, "current", current)
    view(con, "previous", old)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE current_context AS
        WITH paths AS (
           SELECT DISTINCT selection_hash,news_refs,announcement_refs FROM current
        ), refs AS (
            SELECT selection_hash,unnest(news_refs) AS ref FROM paths
            UNION ALL SELECT selection_hash,unnest(announcement_refs) FROM paths
        ), active AS (
            SELECT r.selection_hash,d.* EXCLUDE(doc_version_id)
            FROM refs r JOIN doc_facts d ON r.ref=d.doc_version_id
        ), flags AS (
            SELECT selection_hash,any_value(evidence_issuer_id) AS issuer,
                bool_or(doc_kind='news' AND evidence_issuer_id IS NOT NULL) AS news,
                bool_or(doc_kind='announcement' AND evidence_issuer_id IS NOT NULL) AS ann,
                bool_or(doc_kind='news' AND evidence_issuer_id IS NULL) AS bg,
                bool_or(document_class='periodic' AND evidence_issuer_id IS NOT NULL) AS periodic,
                bool_or(document_class='event' AND evidence_issuer_id IS NOT NULL) AS event,
                bool_or(is_new AND evidence_issuer_id IS NOT NULL) AS new_body,
                bool_or(NOT is_new AND evidence_issuer_id IS NOT NULL) AS old_body,
                list_distinct(flatten(list(evidence_keys) FILTER(doc_kind='news'))) AS news_keys,
                list_distinct(flatten(list(evidence_keys) FILTER(doc_kind='announcement'))) AS ann_keys
            FROM active GROUP BY selection_hash
        )
        SELECT * EXCLUDE(news_keys,ann_keys),coalesce(list_has_any(news_keys,ann_keys),false) AS overlap FROM flags
    """)
    if con.execute("""
        SELECT count(*) FROM current i JOIN current_context c USING(selection_hash)
        WHERE (c.news OR c.ann) AND c.issuer IS DISTINCT FROM i.issuer_id
    """).fetchone()[0]:
        raise AssertionError("Selected final text is attributed to a different issuer")
    lo, hi = con.execute("SELECT min(local_trade_date),max(local_trade_date) FROM current").fetchone()
    con.execute("""
        CREATE OR REPLACE TEMP TABLE eligibility AS
        SELECT i.*,h.exchange,
            CASE WHEN h.delisting_date IS NOT NULL THEN 'historically_delisted' ELSE 'not_delisted_in_anchor' END AS listing,
            coalesce(t.special_treatment_state,'unknown') AS special
        FROM current i
        SEMI JOIN (SELECT * FROM supervision WHERE local_trade_date BETWEEN ? AND ?) s USING(sample_id,split,local_trade_date)
        JOIN security h USING(instrument_id)
        LEFT JOIN (SELECT instrument_id,local_trade_date,special_treatment_state FROM stock_daily
                   WHERE local_trade_date BETWEEN ? AND ?) t USING(instrument_id,local_trade_date)
    """, [lo, hi, lo, hi])
    con.execute("""
        CREATE OR REPLACE TEMP TABLE with_coverage AS
        WITH old_context AS (
            SELECT DISTINCT b.selection_hash,b.issuer_id,b.news_refs,b.announcement_refs FROM previous b
        ), old_refs AS (
            SELECT selection_hash,issuer_id,unnest(news_refs) AS ref FROM old_context
            UNION ALL SELECT selection_hash,issuer_id,unnest(announcement_refs) FROM old_context
        ), old_flags AS (
            SELECT selection_hash,issuer_id,bool_or(f.mode='news') AS old_news,bool_or(f.mode='announcement') AS old_ann
            FROM old_refs r JOIN baseline_facts f ON r.ref=f.ref AND r.issuer_id=f.issuer
            GROUP BY ALL
        )
        SELECT i.*, coalesce(c.news,false) AS news,coalesce(c.ann,false) AS ann,coalesce(c.bg,false) AS bg,
            coalesce(c.periodic,false) AS periodic,coalesce(c.event,false) AS event,
            coalesce(c.new_body,false) AS new_body,coalesce(c.old_body,false) AS old_body,
            coalesce(c.overlap,false) AS overlap,coalesce(o.old_news,false) AS old_news,coalesce(o.old_ann,false) AS old_ann
        FROM eligibility i LEFT JOIN current_context c USING(selection_hash)
        JOIN previous b USING(sample_id,issuer_id) LEFT JOIN old_flags o ON b.selection_hash=o.selection_hash
            AND i.issuer_id=o.issuer_id
    """)
    if con.execute("SELECT count(*) FROM with_coverage").fetchone() != con.execute(
        "SELECT count(*) FROM eligibility"
    ).fetchone():
        raise AssertionError("Baseline and round two have different anchored keys")
    measures = """count(*), count(*) FILTER(news), count(*) FILTER(ann), count(*) FILTER(news AND ann),
        count(*) FILTER(news OR ann),count(*) FILTER(bg AND NOT news AND NOT ann),
        count(*) FILTER(NOT news AND NOT ann AND news_status IN ('empty','present')
                        AND announcement_status IN ('empty','present')),
        count(*) FILTER(news_status='unavailable'),count(*) FILTER(announcement_status='unavailable'),
        count(*) FILTER(len(news_refs)=0 AND len(announcement_refs)=0),
        count(*) FILTER(periodic),count(*) FILTER(event),
        count(*) FILTER(periodic AND NOT event),count(*) FILTER(event AND NOT periodic),
        count(*) FILTER(new_body),count(*) FILTER(new_body AND NOT old_body),
        count(*) FILTER(old_news),count(*) FILTER(old_ann),count(*) FILTER(old_news AND old_ann),
        count(*) FILTER(old_news OR old_ann),count(*) FILTER((news OR ann) AND NOT (old_news OR old_ann)),
        count(*) FILTER((old_news OR old_ann) AND NOT (news OR ann)),count(*) FILTER(overlap)"""
    stratified = con.execute(f"""
        SELECT split,year(local_trade_date),exchange,listing,special,coalesce(industry_key,'unknown'),
               grouping_id(split,year(local_trade_date),exchange,listing,special,coalesce(industry_key,'unknown')),
               {measures}
        FROM with_coverage GROUP BY GROUPING SETS
           ((),(split),(year(local_trade_date)),(exchange),(listing),(special),(coalesce(industry_key,'unknown')))
    """).fetchall()
    detail = con.execute("""
        WITH chosen_refs AS (
            SELECT local_trade_date,unnest(news_refs) AS ref FROM with_coverage
            UNION ALL SELECT local_trade_date,unnest(announcement_refs) FROM with_coverage
        )
        SELECT document_class,date_diff('day',published_local_day,local_trade_date),count(*)
        FROM chosen_refs r JOIN doc_facts d ON r.ref=d.doc_version_id
        WHERE d.evidence_issuer_id IS NOT NULL GROUP BY ALL
    """).fetchall()
    source_gain = con.execute("""
        WITH chosen_refs AS (
            SELECT sample_id,unnest(news_refs) AS ref FROM with_coverage WHERE new_body
            UNION ALL SELECT sample_id,unnest(announcement_refs) FROM with_coverage WHERE new_body
        )
        SELECT provider,doc_kind,count(DISTINCT sample_id),count(DISTINCT original_version_id) FROM chosen_refs r
        JOIN doc_facts d ON r.ref=d.doc_version_id
        WHERE d.is_new AND d.evidence_issuer_id IS NOT NULL GROUP BY ALL
    """).fetchall()
    return stratified, detail, source_gain


def audit(numeric, text, baseline, cache):
    root, _, _ = checked_anchor(numeric)
    manifest, previous = (read_json(p / "manifest.json") for p in (text, baseline))
    if any(m["numeric_version"] != ANCHOR for m in (manifest, previous)):
        raise ValueError("Coverage cannot be compared between different numeric anchors")
    totals = defaultdict(Counter)
    ages, sources = Counter(), Counter()
    with duckdb.connect(config={"threads": 3, "memory_limit": "2400MB", "temp_directory": str(cache)}) as con:
        count = baseline_qualification(con, root, baseline)
        view(con, "current_docs", text / "documents/**/*.parquet")
        view(con, "coverage", text / "coverage.parquet")
        view(con, "supervision", root / "reports/training_samples.parquet", "sample_id,local_trade_date,split")
        view(con, "security", root / "reference/security_history.parquet", "instrument_id,exchange,delisting_date")
        view(con, "stock_daily", root / "stock_daily/**/*.parquet",
             "instrument_id,local_trade_date,special_treatment_state")
        con.execute("""
            CREATE TEMP TABLE all_docs AS SELECT c.* EXCLUDE(body_text),c.kind AS doc_kind,
                o.doc_id IS NULL AND h.body_hash IS NULL AS is_new
            FROM current_docs c
            LEFT JOIN (SELECT DISTINCT doc_id,raw_hash FROM old_docs WHERE parse_status='ok') o
                ON o.doc_id=c.doc_id AND o.raw_hash=c.raw_hash
            LEFT JOIN (SELECT DISTINCT body_hash FROM old_docs WHERE parse_status='ok') h
                ON h.body_hash=c.body_hash
        """)
        con.execute("""
            CREATE TEMP TABLE doc_facts AS SELECT doc_version_id,original_version_id,doc_kind,provider,
                document_class,evidence_issuer_id,evidence_keys,is_new,published_local_day
            FROM all_docs WHERE input_text IS NOT NULL
        """)
        inventory = publication_inventory(con, manifest, read_json(Path(manifest["source_audit"]))
                                          if manifest.get("source_audit") else None)
        parts = sorted((text / "sample_text_index").glob("month=*/part.parquet"))
        for part in parts:
            month = part.parent.name
            if month.endswith(("-03", "-06", "-09", "-12")):
                print(f"Qualified coverage through {month}", flush=True)
            levels, age, gains = check_month(con, part, baseline / "sample_text_index" / month / part.name)
            for row in levels:
                labels = ("split", "year", "exchange", "listing", "special_treatment", "industry")
                grouping = row[len(labels)]
                key = next(((label, str(value)) for idx, (label, value) in enumerate(zip(labels, row, strict=False))
                            if not (grouping & (1 << (len(labels)-1-idx)))), ("overall", "all"))
                totals[key].update(dict(zip(METRICS, row[len(labels)+1:], strict=True)))
            ages.update({(mode, delta): n for mode, delta, n in age})
            sources.update({(provider, mode): n for provider, mode, n, _ in gains})
    for split, expected in SPLIT_COUNTS.items():
        if totals[("split", split)]["eligible"] != expected:
            raise AssertionError(f"Frozen eligible split denominator changed for {split}")
    for stats in totals.values():
        stats["target_sample_count"] = (4 * stats["eligible"] + 4) // 5
        stats["gap_to_target"] = max(0, stats["target_sample_count"] - stats["company_text"])
    return {"text_version": manifest["text_version"], "baseline_text_version": previous["text_version"],
            "sample_manifest_sha256": manifest["sample_manifest_sha256"],
            "new_manifest_sha256": file_hash(text / "manifest.json"),
            "strict_baseline_document_issuer_facts": count, "lookback": LOOKBACK,
            "strata": [{"dimension": d, "value": k, **v} for (d, k), v in sorted(totals.items())],
            "final_company_text_age_histogram": [{"class": c, "days": age, "sample_document_refs": n}
                                                 for (c, age), n in sorted(ages.items())],
            "new_body_selected_by_source": [{"source": provider, "modality": mode, "samples": n}
                                             for (provider, mode), n in sorted(sources.items())],
            **inventory}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("numeric", "text", "baseline", "cache", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    a = p.parse_args()
    write_json(a.output, json.loads(json.dumps(audit(a.numeric, a.text, a.baseline, a.cache), default=str)))
    print(a.output)


if __name__ == "__main__":
    main()
