"""Audit official SW history objects without assigning undocumented publication clocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median

import duckdb

HISTORY_FILENAME = "StockClassifyUse_stock.xls"
DICTIONARY_FILENAME = "SwClassCode_2021.xls"
HISTORY_HEADER = ("股票代码", "计入日期", "行业代码", "更新日期")
DICTIONARY_HEADER = ("行业代码", "一级行业名称", "二级行业名称", "三级行业名称")
SAMPLE_END = date(2026, 6, 30)
CODE = re.compile(r"\d{6}\Z")


def workbook_rows(xlrd, path, expected_header):
    with path.open("rb") as source:
        source_hash = hashlib.file_digest(source, "sha256").hexdigest()
    book = xlrd.open_workbook(path, on_demand=True)
    if book.sheet_names() != ["Sheet1"]:
        raise ValueError(f"Expected a single Sheet1 in {path.name}")
    sheet = book.sheet_by_name("Sheet1")
    if tuple(sheet.row_values(0)) != expected_header:
        raise ValueError(f"Unexpected columns in {path.name}")
    return book, sheet, {"bytes": path.stat().st_size, "sha256": source_hash, "columns": list(expected_header)}


def inspect_history(xlrd, path):
    book, sheet, metadata = workbook_rows(xlrd, path, HISTORY_HEADER)
    rows = []
    malformed = []
    include_intraday_rows = 0
    for i in range(1, sheet.nrows):
        stock, effective, industry, updated = sheet.row_values(i)
        if (not CODE.fullmatch(str(stock)) or not CODE.fullmatch(str(industry))
                or sheet.cell_type(i, 1) != xlrd.XL_CELL_DATE or sheet.cell_type(i, 3) != xlrd.XL_CELL_DATE):
            malformed.append(i + 1)
            continue
        include_at = xlrd.xldate_as_datetime(effective, book.datemode)
        include_intraday_rows += include_at.time() != datetime.min.time()
        updated_at = xlrd.xldate_as_datetime(updated, book.datemode)
        rows.append((stock, include_at.date(), industry, updated_at))
    dates = [row[1] for row in rows]
    clocks = [row[3] for row in rows]
    lag_days = [(u.date() - d).days for _, d, _, u in rows]
    value_sets = defaultdict(set)
    for stock, effective, code, _ in rows:
        value_sets[stock, effective].add(code)
    metadata.update({
        "rows": sheet.nrows - 1, "malformed_excel_rows": malformed,
        "stock_codes": len({row[0] for row in rows}), "industry_codes": len({row[2] for row in rows}),
        "effective_from": min(dates), "effective_to": max(dates), "provider_update_from": min(clocks),
        "provider_update_to": max(clocks), "provider_update_distinct_dates": len({t.date() for t in clocks}),
        "inclusion_has_time_of_day_rows": include_intraday_rows,
        "update_has_time_of_day_rows": sum(t.time() != datetime.min.time() for t in clocks),
        "update_before_effective": sum(n < 0 for n in lag_days), "update_same_effective_day": sum(n == 0 for n in lag_days),
        "update_after_effective": sum(n > 0 for n in lag_days), "update_lag_calendar_days_median": median(lag_days),
        "update_lag_calendar_days_max": max(lag_days), "rows_effective_by_sample_end": sum(d <= SAMPLE_END for d in dates),
        "rows_with_post_sample_updates_for_pre_end_effective_dates": sum(
            d <= SAMPLE_END < u.date() for _, d, _, u in rows
        ),
        "repeated_security_effective_keys": len(rows) - len(value_sets),
        "conflicting_industry_security_effective_keys": sum(len(v) > 1 for v in value_sets.values()),
        "rows_by_provider_update_year": dict(sorted(Counter(u.year for u in clocks).items())),
        "sample_000001": [row for row in rows if row[0] == "000001"],
    })
    book.release_resources()
    return rows, metadata


def inspect_dictionary(xlrd, path):
    book, sheet, metadata = workbook_rows(xlrd, path, DICTIONARY_HEADER)
    rows = {str(row[0]): tuple(map(str, row[1:])) for row in (sheet.row_values(i) for i in range(1, sheet.nrows))}
    if len(rows) != sheet.nrows - 1 or any(not CODE.fullmatch(k) for k in rows):
        raise ValueError(f"Duplicate or malformed taxonomy key in {path.name}")
    metadata.update(rows=len(rows), codes_by_level=dict(Counter(sum(bool(n) for n in labels) for labels in rows.values())))
    book.release_resources()
    return rows, metadata


def catalog_ids(registry, release):
    with duckdb.connect(str(registry), read_only=True) as con:
        taxonomy = {src: set() for src in ("SW2014", "SW2021")}
        for src, code in con.sql("SELECT src,industry_code FROM canonical_index_classify WHERE src IN ('SW2014','SW2021')").fetchall():
            taxonomy[src].add(code)
        with (release / "manifest.json").open(encoding="utf-8") as manifest:
            dataset_version = json.load(manifest)["dataset_version"]
        aliases = defaultdict(list)
        for identity, current, prior, exchange, listed, delisted, switched in con.read_parquet(
            str(release / "reference" / "security_history.parquet")
        ).project("instrument_id,ts_code,prior_code,exchange,listing_date,delisting_date,code_switch_date").fetchall():
            aliases[current.split(".")[0]].append((identity, exchange, listed, delisted, switched, False))
            if prior and prior.split(".")[0] != current.split(".")[0]:
                aliases[prior.split(".")[0]].append((identity, exchange, listed, delisted, switched, True))
    return dataset_version, aliases, taxonomy


def resolve_rows(rows, aliases, taxonomy, dictionary):
    alias_codes, alias_ids, valid_ids = set(), set(), set()
    counts = Counter()
    venue_stock_ids = defaultdict(set)
    for stock, effective, code, _ in rows:
        matches = aliases.get(stock, [])
        if len({row[0] for row in matches}) == 1:
            alias_codes.add(stock)
            alias_ids.add(matches[0][0])
            counts["uniquely_linked_by_alias_rows"] += 1
        elif len(matches):
            counts["ambiguous_alias_rows"] += 1
        else:
            counts["unmatched_alias_rows"] += 1
        correct_lifecycle = [(ident, venue) for ident, venue, start, end, change, prior in matches
                             if start is not None and start <= effective and (end is None or effective <= end)
                             and (change is None or (effective < change if prior else change <= effective))]
        if len({item[0] for item in correct_lifecycle}) == 1:
            ident, venue = correct_lifecycle[0]
            valid_ids.add(ident)
            venue_stock_ids[venue].add(ident)
            counts["unique_lifecycle_and_code_regime_rows"] += 1
        if code in dictionary:
            counts["official_2021_dictionary_rows"] += 1
        versions = [key for key, codes in taxonomy.items() if code in codes]
        bucket = "_and_".join(versions or ("neither",))
        counts[f"local_taxonomy_{bucket}_rows"] += 1
    return {**counts, "distinct_unique_alias_codes": len(alias_codes), "distinct_unique_alias_instruments": len(alias_ids),
            "distinct_instruments_with_verified_identity_lifecycle": len(valid_ids),
            "lifecycle_instruments_by_exchange": {k: len(v) for k, v in sorted(venue_stock_ids.items())}}


def compare_versions(current, prior):
    current_rows = {(sid, effective, code): clock for sid, effective, code, clock in current}
    prior_rows = {(sid, effective, code): clock for sid, effective, code, clock in prior}
    common = current_rows.keys() & prior_rows.keys()
    cutoff = max(prior_rows.values())
    new = current_rows.keys() - prior_rows.keys()
    old_keys = {(sid, e) for sid, e, _ in prior_rows}
    return {"archive_max_provider_update": cutoff,
            "common_security_effective_industry_rows": len(common),
            "same_assignment_different_provider_update": sum(current_rows[k] != prior_rows[k] for k in common),
            "archive_assignments_missing_in_current": len(prior_rows.keys() - current_rows.keys()),
            "current_assignments_missing_in_archive": len(new),
            "current_assignments_at_existing_effective_key": sum((sid, e) in old_keys for sid, e, _ in new),
            "current_assignments_not_archived_with_update_before_archive_max": sum(current_rows[k] <= cutoff for k in new)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("release", type=Path)
    parser.add_argument("--quant-db", type=Path, default=Path("E:/QuantData/quant.duckdb"))
    parser.add_argument("--xlrd-path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.xlrd_path:
        sys.path.insert(0, str(args.xlrd_path.resolve()))
    import xlrd

    version, aliases, taxonomy = catalog_ids(args.quant_db, args.release)
    current, source = inspect_history(xlrd, args.source_dir / HISTORY_FILENAME)
    dictionary, codes = inspect_dictionary(xlrd, args.source_dir / DICTIONARY_FILENAME)
    prior, archive = inspect_history(xlrd, args.source_dir / "archive_2022" / HISTORY_FILENAME)
    prior_dictionary, archive_codes = inspect_dictionary(xlrd, args.source_dir / "archive_2022" / DICTIONARY_FILENAME)
    result = {"dataset_identity_reference": version, "source": source, "dictionary": codes, "official_2022_archive": archive,
              "official_2022_archive_dictionary": archive_codes,
              "current_identity_and_taxonomy_linkage": resolve_rows(current, aliases, taxonomy, dictionary),
              "archive_identity_and_taxonomy_linkage": resolve_rows(prior, aliases, taxonomy, prior_dictionary),
              "archive_current_comparison": compare_versions(current, prior),
              "provider_update_timezone": None, "provider_update_is_verified_publication_time": False}
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
