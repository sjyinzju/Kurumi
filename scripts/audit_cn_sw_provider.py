"""Quantify SW member coverage without using effective dates as public release dates."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
from fetch_cn_financial_versions import digest
from normalize_cn_financial_versions import identities


def audit(root, checkpoint):
    aliases = identities(root / "numeric")
    with duckdb.connect(str(root / "quant.duckdb"), read_only=True) as con:
        dictionary = defaultdict(set)
        for version, code, label in con.execute("""
            SELECT src, index_code, industry_name
            FROM canonical_index_classify WHERE level='L1' AND src IN ('SW2014', 'SW2021')
        """).fetchall():
            dictionary[code, label].add(version)
    source = sqlite3.connect(checkpoint.resolve().as_uri() + "?mode=ro", uri=True)
    groups, members = Counter(), defaultdict(set)
    seen, pages = set(), []
    with source:
        for params, fields, records, observed, checksum in source.execute("""
            SELECT parameters, fields, rows, observed_at, response_sha256
            FROM requests WHERE endpoint='index_member_all' AND error IS NULL ORDER BY parameters
        """):
            params, fields, records = tuple(map(json.loads, (params, fields, records)))
            if digest([fields, records]) != checksum:
                raise ValueError("TuShare membership page checksum did not match its receipt")
            pages.append({"parameters": params, "rows": len(records), "observed_at": observed, "sha256": checksum})
            for record in records:
                row = dict(zip(fields, record, strict=True))
                key = tuple(record)
                groups[row["is_new"], "rows"] += 1
                if key in seen:
                    groups[row["is_new"], "duplicate"] += 1
                    continue
                seen.add(key)
                if row["ts_code"] not in aliases:
                    groups[row["is_new"], "unlinked_security"] += 1
                    continue
                code, _, _, exchange = aliases[row["ts_code"]]
                versions = dictionary[row["l1_code"], row["l1_name"]]
                taxonomies = ",".join(sorted(versions)) if versions else "unmapped_l1"
                groups[row["is_new"], taxonomies] += 1
                year = row["in_date"][:4] if row["in_date"] else "unavailable"
                members[exchange, row["is_new"], year].add(code)
    count = {venue: len({info[0] for info in aliases.values() if info[3] == venue})
             for venue in {info[3] for info in aliases.values()}}
    return {
        "source": "https://tushare.pro/document/2?doc_id=335", "pages": pages,
        "row_counts": [{"scope": scope, "count": n} for scope, n in sorted(groups.items())],
        "unique_linked_codes_by_exchange_and_inclusion_year": [
            {"scope": scope, "count": len(codes)} for scope, codes in sorted(members.items())
        ],
        "universe_by_exchange": count,
        "use": "candidate_evidence_only_missing_publication_version",
        "available_fields": ["in_date", "out_date", "is_new"],
        "missing_fields": ["published_at", "source_version_id", "classification_version"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.data_root, args.checkpoint)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages": len(result["pages"]), "row_counts": result["row_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
