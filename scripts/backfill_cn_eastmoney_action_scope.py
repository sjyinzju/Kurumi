"""Fetch exact stock-scoped Eastmoney candidate archives for missing CN action scope."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from kurumi.cn_equity_candidates import historical_events

CUTOFF = "2026-07-31"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_atomic(path, payload):
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_bytes(payload)
    partial.replace(path)


def write_json(path, value):
    write_atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def fetch_code(code, store):
    receipt = store / f"{code}.receipt.json"
    events_file = store / f"{code}.events.jsonl"
    if receipt.exists() and events_file.exists():
        prior = json.loads(receipt.read_bytes())
        if (prior.get("complete") and prior["events_sha256"] == sha256(events_file)
                and all(sha256(store / p["raw_file"]) == p["source_sha256"] for p in prior["pages"]
                        if (store / p["raw_file"]).is_file())
                and all((store / p["raw_file"]).is_file() for p in prior["pages"])):
            return prior
    pages = []

    def capture_page(page, response, payload):
        original = store / f"{code}.page-{page}.json"
        write_atomic(original, response.content)
        result = payload.get("result") or {}
        pages.append({
            "page": page, "source_url": response.url, "source_sha256": sha256(original),
            "raw_file": original.name, "observed_at": datetime.now(timezone.utc).isoformat(),
            "source_version_id": str(payload.get("version") or "response_sha256"),
            "http_status": response.status_code, "provider_success": payload.get("success"),
            "provider_code": payload.get("code"), "provider_rows_expected": result.get("count"),
            "provider_pages_expected": result.get("pages"), "page_rows": len(result.get("data") or []),
        })

    report = {"query_code": code, "publication_through": CUTOFF, "complete": False, "pages": pages}
    try:
        events = historical_events(code, on_page=capture_page)
        by_hash = {p["source_sha256"]: p for p in pages}
        if any(row["SECUCODE"] != code or row["NOTICE_DATE"] is None or row["NOTICE_DATE"][:10] > CUTOFF
               or row["END_DATE"] is None for row in events):
            raise ValueError("Provider returned events outside the exact query security or publication bound")
        if not pages or any((p["provider_rows_expected"], p["provider_pages_expected"])
                            != (pages[0]["provider_rows_expected"], pages[0]["provider_pages_expected"]) for p in pages):
            raise ValueError("Provider scope changed across requested pages")
        expected_pages = pages[0]["provider_pages_expected"]
        if expected_pages is not None and len(pages) != max(1, expected_pages):
            raise ValueError("Page count does not match completed response sequence")
        retained = [row for row in events if row["END_DATE"][:10] <= CUTOFF]
        evidence = []
        for row in retained:
            meta = by_hash[row["source_sha256"]]
            evidence.append(row | {
                "observed_at": meta["observed_at"], "source_version_id": meta["source_version_id"],
                "knowledge_quality": "unverified_version", "source_page": meta["page"],
                "source_rows_expected": len(events),
            })
        write_atomic(events_file, b"".join((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8") for row in evidence))
        report.update(complete=True, status=("events_present" if retained else
                                            "no_effective_events_through_cutoff" if events else "empty_complete"),
                      rows_returned=len(events), rows_retained=len(retained),
                      rows_pre_2014=sum(row["END_DATE"][:10] < "2014-01-01" for row in retained),
                      earliest_effective=min((row["END_DATE"][:10] for row in retained), default=None),
                      latest_effective=max((row["END_DATE"][:10] for row in retained), default=None),
                      events_file=events_file.name, events_sha256=sha256(events_file))
    except requests.HTTPError as exc:
        response = exc.response
        report.update(status="http_error", http_status=response.status_code if response is not None else None,
                      source_url=response.url if response is not None else None)
    except requests.RequestException as exc:
        report.update(status="transport_error", error=type(exc).__name__)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        report.update(status="provider_or_integrity_error", error=type(exc).__name__, reason=str(exc))
    write_json(receipt, report)
    return report


def source_targets(gaps, history):
    missing = [r["ts_code"] for r in gaps["securities"] if not r["eastmoney_rows"]]
    with duckdb.connect() as con:
        con.read_parquet(history.as_posix()).create_view("security_history")
        aliases = con.execute("""
            WITH candidates AS (
                SELECT DISTINCT ts_code AS source_code, ts_code FROM security_history
                UNION SELECT DISTINCT prior_code, ts_code FROM security_history WHERE prior_code IS NOT NULL
            ), stable AS (
                SELECT * FROM candidates QUALIFY count(*) OVER(PARTITION BY source_code)=1
            )
            SELECT ts_code,source_code FROM stable WHERE ts_code IN (SELECT unnest(?)) ORDER BY 1,2
        """, [missing]).fetchall()
    by_code = {code: [] for code in missing}
    for canonical, alias in aliases:
        by_code[canonical].append(alias)
    if any(not codes for codes in by_code.values()):
        raise ValueError("A targeted issuer lacks an unambiguous published security mapping")
    return by_code


def export_candidates(base, out, store, captures):
    files = [str(store / r["events_file"]) for r in captures if r.get("complete") and r["rows_retained"]]
    stage = out.with_suffix(".partial")
    with duckdb.connect() as con:
        prior = con.read_parquet(str(base))
        schema = {name: str(dtype) for name, dtype in zip(prior.columns, prior.types, strict=True)}
        rows = con.read_json(files, columns=schema, format="newline_delimited") if files else prior.limit(0)
        rows.write_parquet(str(stage), compression="zstd")
        exported = con.read_parquet(str(stage))
        if exported.columns != prior.columns or exported.types != prior.types or len(exported) != sum(
                r.get("rows_retained", 0) for r in captures):
            raise ValueError("Typed supplement did not preserve the candidate archive schema and exact row count")
    stage.replace(out)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--gap-audit", required=True, type=Path)
    cli.add_argument("--release", required=True, type=Path)
    cli.add_argument("--base-archive", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--workers", type=int, choices=range(1, 6), default=4)
    args = cli.parse_args()
    gaps = json.loads(args.gap_audit.read_bytes())
    if gaps["dataset_version"] != args.release.name:
        cli.error("Issuer-gap audit must match the release identity reference")
    targets = source_targets(gaps, args.release / "reference" / "security_history.parquet")
    codes = sorted({alias for aliases in targets.values() for alias in aliases})
    raw = args.output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        captures = list(pool.map(lambda code: fetch_code(code, raw), codes))
    path = args.output / "eastmoney_equity_action_scope_extension.parquet"
    export_candidates(args.base_archive, path, raw, captures)
    receipts = {receipt["query_code"]: receipt for receipt in captures}
    outcomes = {
        code: ("incomplete_source_query" if not all(receipts[a]["complete"] for a in aliases) else
               "complete_with_events" if any(receipts[a]["rows_retained"] for a in aliases) else
               "complete_zero_in_scope") for code, aliases in targets.items()
    }
    write_json(args.output / "eastmoney_action_scope_manifest.json", {
        "dataset_version": gaps["dataset_version"], "publication_through": CUTOFF,
        "candidate_extension": path.name, "candidate_sha256": sha256(path),
        "securities": len(targets), "query_codes": len(codes),
        "candidate_rows": sum(r.get("rows_retained", 0) for r in captures),
        "pre_2014_rows": sum(r.get("rows_pre_2014", 0) for r in captures),
        "outcomes": outcomes, "exact_aliases": targets, "query_receipts": captures,
    })
    print(len(targets), "issuers", len(codes), "aliases", {status: list(outcomes.values()).count(status)
                                                           for status in sorted(set(outcomes.values()))})


if __name__ == "__main__":
    main()
