"""Verify published multishare-class capitalization against retained original evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from audit_cn_bse_factor_discrepancies import dict_rows, digest, get_batch

SIBLINGS = {
    "000418.SZ": "200418.SZ", "000613.SZ": "200613.SZ", "600190.SH": "900952.SH",
    "600555.SH": "900955.SH", "600680.SH": "900930.SH", "600958.SH": "03958.HK", "600999.SH": "06099.HK",
}
LOCAL = ZoneInfo("Asia/Shanghai")
RETIRED = {"000418.SZ": "2019-05-27", "000613.SZ": "2022-06-29", "600190.SH": "2025-07-25",
           "600555.SH": "2022-07-13", "600680.SH": "2019-05-23"}
RETIRED_AMOUNT_PAGES = {"000418.SZ": 32, "000613.SZ": 24, "600190.SH": 23, "600555.SH": 34, "600680.SH": 25}
EXTRACT_PAGE = """
import io
import sys
import pdfplumber
with pdfplumber.open(io.BytesIO(sys.stdin.buffer.read())) as report:
    text = report.pages[int(sys.argv[1]) - 1].extract_text()
sys.stdout.buffer.write(text.encode('utf-8'))
"""


def availability(value):
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value) + timedelta(days=1), time.min, LOCAL)
    clock = datetime.fromisoformat(value)
    if clock.tzinfo is None:
        raise ValueError("Exact share-publication clock is missing a zone")
    return clock


def class_versions(path):
    result = defaultdict(list)
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record["ts_code"] not in SIBLINGS:
                continue
            contents = [record["source_url"], record["source_sha256"], record["source_version_id"]]
            ref = "issuer_class_versions-" + hashlib.sha256(json.dumps(contents, ensure_ascii=False).encode()).hexdigest()[:24]
            result[ref].append(record)
    return result


def source_quote_series(code, capital, retired):
    folder = capital / "class_quotes_public" / "class_quote_receipts" if code.endswith(".HK") else retired / "quote_receipts"
    archive = folder / f"{code}.json.gz"
    with gzip.open(archive, "rt", encoding="utf-8") as stream:
        capture = json.load(stream)
    if capture["code"] != code or "fqt=0" not in capture["source_url"]:
        raise ValueError(f"The retained sibling quote differs from its expected unadjusted identity: {code}")
    decisions = {"archived_response_sha256": capture["source_sha256"], "extracted_receipt_sha256": digest(archive),
                 "extracted_receipt": archive.as_posix(), "source_url": capture["source_url"],
                 "archived_quote_rows": len(capture["rows"]), "available_reacquired_response": False}
    raw_path = capital / "v5_class_crosscheck" / f"{code}_vendor_response.json"
    if raw_path.is_file():
        raw = json.loads(raw_path.read_bytes())
        payload = raw.get("data") or {}
        raw_rows = [(parts[0], float(parts[2]), float(parts[5]))
                    for text in payload.get("klines", []) if (parts := text.split(","))]
        archived_rows = [(r["d"], r["close"], r["volume"]) for r in capture["rows"]]
        if raw.get("rc") != 0 or payload.get("code") != code.split(".")[0] or raw_rows != archived_rows:
            raise ValueError(f"Reacquired sibling date/close/volume fields conflict with the archived extracts: {code}")
        decisions |= {"available_reacquired_response": True, "reacquired_response_path": raw_path.as_posix(),
                      "reacquired_raw_response_sha256": digest(raw_path), "all_archived_close_and_volume_rows_equal": True}
    else:
        logs = (capital / "v5_class_crosscheck" / name for name in
                ("raw_quote_reacquisition_audit.json", "raw_quote_reacquisition_retry.json"))
        decisions["same_address_raw_response_attempts"] = [
            {"receipt": log.as_posix(), "failure": row["response"].get("error"),
             "http_status": row["response"].get("http_status")}
            for log in logs if log.is_file() for row in json.loads(log.read_bytes()) if row["class_id"] == code
        ]
    return decisions, {date.fromisoformat(row["d"]): row for row in capture["rows"]}


def original_fx_rows(pit, source_directory):
    audit = json.loads((pit / "class_fx_audit.json").read_bytes())
    source_hashes = {record["sha256"]: record for record in audit["receipts"]}
    rows, archives = [], []
    for path in sorted(source_directory.glob("*.jsonl.gz")):
        checksum = digest(path)
        if checksum not in source_hashes:
            continue
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = [json.loads(line, parse_float=Decimal) for line in stream]
        if len(data) != source_hashes[checksum]["rows"]:
            raise ValueError("Original CSMAR FX response has a different row count")
        archives.append({"file": path.as_posix(), "sha256": checksum, "rows": len(data)})
        rows.extend(data)
    if {row["sha256"] for row in archives} != set(source_hashes):
        raise ValueError("Could not replay each archived CSMAR FX request")
    rows.sort(key=lambda r: r["Exchdt"])
    return archives, [availability(r["Exchdt"]) for r in rows], rows


def original_share_pdf(record, pdf_lookup, broker_audit, pdf_python):
    checksum = record["source_sha256"]
    path = pdf_lookup.get(checksum)
    if path is None:
        return None
    if record["ts_code"] not in RETIRED:
        arithmetic = next((row for row in broker_audit["versions"]
                           if (row["ts_code"], row["source_version_id"], row["published_at"], row["effective_from"])
                           == (record["ts_code"], record["source_version_id"], record["published_at"], record["effective_from"])), None)
        if arithmetic is not None:
            originals = [broker_audit["documents"][name] for name in arithmetic["available_by_version_publication"]]
            for proof in originals:
                if digest(Path(proof["path"])) != proof["source_sha256"] or availability(proof["published_at"]) > availability(record["published_at"]):
                    raise ValueError("Broker quantity source is changed or was not available by the asserted version date")
            named = {record["ts_code"]: arithmetic["a_shares"], arithmetic["h_class_id"]: arithmetic["h_shares"]}
            if (named != {part["class_id"]: part["shares"] for part in record["classes"]}
                    or arithmetic["issuer_total_shares"] != sum(named.values())):
                raise ValueError("Verified broker original PDF pages disagree with the frozen class amounts")
            return {"source_sha256": checksum, "source_url": record["source_url"], "published": record["published_at"],
                    "verified_public_original_pdfs": originals, "issuer_document_class_arithmetic": arithmetic["arithmetic_basis"],
                    "share_literals": named}
        return None
    parts = {r["class_id"]: int(r["shares"]) for r in record["classes"]}
    a = parts[record["ts_code"]]
    others = {shares for code, shares in parts.items() if code != record["ts_code"]}
    number = RETIRED_AMOUNT_PAGES[record["ts_code"]]
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != checksum:
        raise ValueError(f"A retained original share document changed during evidence verification: {path}")

    def read_page(page):
        result = subprocess.run([str(pdf_python), "-c", EXTRACT_PAGE, str(page)], input=original,
                                capture_output=True, check=True, timeout=20)
        return result.stdout.decode("utf-8")

    text = read_page(number)
    identity = read_page(record["class_link_pdf_page"])
    if any(class_id.split(".")[0] not in identity for class_id in parts):
        raise ValueError(f"The retained PDF cannot independently establish both class identities: {path}")
    amounts = {expected for expected in others | {a, sum(parts.values())} if
               str(expected) in text or f"{expected:,}" in text}
    if not (others <= amounts and (a in amounts or sum(parts.values()) in amounts)):
        return None
    return {"pdf": path.as_posix(), "source_sha256": checksum, "source_url": record["source_url"],
            "published": record["published_at"], "source_version_id": record["source_version_id"],
            "share_literals": parts, "original_share_amounts_page": number,
            "original_class_link_page": record["class_link_pdf_page"],
            "target_A_derivation": "printed" if a in amounts else "printed_total_minus_sibling_shares"}


def release_rows(con, release):
    path = (release / "stock_daily/market_id=CN/year=*/*.parquet").as_posix()
    con.read_parquet(path).create_view("stock_release", replace=True)
    grouped = dict_rows(con.sql("""
        SELECT exchange,count(*) AS stock_sessions,count(*) FILTER(WHERE issued) AS cross_class_valued_days,
               count(DISTINCT ts_code) FILTER(WHERE issued) AS cross_class_securities
        FROM (SELECT exchange,ts_code,issuer_class_provenance_id IS NOT NULL AND
                   issuer_market_cap_reporting>0 AND isfinite(issuer_market_cap_reporting) AS issued FROM stock_release)
        GROUP BY exchange ORDER BY exchange
    """))
    watched = dict_rows(con.execute("""
        SELECT ts_code,local_trade_date,symbol_asof,asof_utc,close_raw,shares_outstanding_security,security_market_cap_local,
               issuer_market_cap_reporting,issuer_class_provenance_id,issuer_quote_age_days,provenance_id,fundamental_snapshot_id
        FROM stock_release WHERE ts_code IN (SELECT unnest(?)) ORDER BY ts_code,local_trade_date
    """, [list(SIBLINGS)]))
    return grouped, watched


def recompute_sample(con, release, stock, record, sibling, archived, quoted, fx, batch, currency):
    report_day, asof = stock["local_trade_date"], stock["asof_utc"]
    if availability(record["published_at"]) > asof:
        raise ValueError("Released issuer valuation used a class publication after the stock sample clock")
    if date.fromisoformat(record["effective_from"]) > report_day or (record.get("effective_to") and
            report_day >= date.fromisoformat(record["effective_to"])):
        raise ValueError("Released issuer class source conflicts with the evaluation day")
    parts = {part["class_id"]: part for part in record["classes"]}
    target = parts[stock["ts_code"]]
    other = parts[sibling]
    if target["currency"] != "CNY" or target["shares"] != stock["shares_outstanding_security"]:
        raise ValueError("A-share valuation is not using the actual same-class quantity")
    if quoted["source_sha256"] != archived["archived_response_sha256"] or quoted["available_at"] > asof:
        raise ValueError("Released sibling quote does not resolve to the contemporaneously available archived observation")
    quote_day = quoted["quote_date"]
    if quote_day != report_day or stock["issuer_quote_age_days"] != 0:
        raise ValueError("The targeted original source proof requires a same-day positive sibling quote")
    # Resolve the stock's A-share close to the registry-held daily response bytes.
    raw_key = (stock["symbol_asof"] + stock["ts_code"][-3:], report_day.strftime("%Y%m%d"))
    a_receipt, values = get_batch(con, batch, {raw_key})
    original_close = values[raw_key][2]
    if original_close != stock["close_raw"]:
        raise ValueError("The released target price does not match original source bytes")
    clocks, source_fx = fx
    index = bisect_right(clocks, asof) - 1
    if index < 0:
        raise ValueError("No contemporaneously available FX fixing")
    fixing = source_fx[index]
    side = archived["dates"][quote_day]
    if side["close"] != quoted["price"] or not side["volume"] > 0 or other["currency"] != quoted["currency"]:
        raise ValueError("Sibling quotation differs from the original outgoing unadjusted archive")
    cny_rate = Decimal(1) / fixing["Hkdrmb"] if other["currency"] == "HKD" else fixing["Rmbusd"]
    declared = con.execute("SELECT cny_per_unit FROM class_fx WHERE rate_date=? AND currency=?",
                           [fixing["Exchdt"], other["currency"]]).fetchone()[0]
    if not math.isclose(float(cny_rate), declared, rel_tol=1e-14):
        raise ValueError("Frozen FX rate differs from its original quote and orientation")
    if currency not in ("CNY", None) or record.get("reporting_currency") != "CNY":
        raise ValueError("This representative row requires CNY issuer financial reporting")
    a_value = Decimal(str(original_close)) * Decimal(str(target["shares"]))
    sibling_value = Decimal(str(side["close"])) * Decimal(str(other["shares"])) * cny_rate
    observed = stock["issuer_market_cap_reporting"]
    if not math.isclose(float(a_value + sibling_value), observed, rel_tol=1e-12) or not math.isclose(
        float(a_value), stock["security_market_cap_local"], rel_tol=1e-12
    ):
        raise ValueError(f"Independent original-price × share-count × FX values disagree for {stock['ts_code']} {report_day}")
    return {"symbol": stock["ts_code"], "date": report_day, "asof_utc": asof, "a_close": original_close,
            "a_close_original_receipt": a_receipt, "sibling": sibling, "sibling_raw_price": side["close"],
            "sibling_currency": other["currency"], "sibling_quote_available_at": quoted["available_at"],
            "fx_raw_fields": fixing, "fx_available_at": clocks[index], "fx_cny_per_unit": str(cny_rate),
            "security_market_cap_cny": float(a_value),
            "recomputed_sibling_cap_cny": str(sibling_value), "recomputed_issuer_cap_cny": str(a_value + sibling_value),
            "published_issuer_cap_cny": observed, "issuer_provenance_id": stock["issuer_class_provenance_id"],
            "stock_shard": (release / f"stock_daily/market_id=CN/year={report_day.year}/part-000.parquet").as_posix()}


def output_counts(previous, current):
    history = {code: [] for code in SIBLINGS}
    base = {(r["ts_code"], r["local_trade_date"]): r for r in previous}
    for row in current:
        if row["issuer_class_provenance_id"] and (row["issuer_market_cap_reporting"] or 0) > 0:
            history[row["ts_code"]].append(row)
    output = []
    for code, observations in history.items():
        observed_days = [r["local_trade_date"] for r in observations]
        active, removed = RETIRED.get(code), []
        prior = [r for r in previous if r["ts_code"] == code and r["issuer_class_provenance_id"]
                 and (r["issuer_market_cap_reporting"] or 0) > 0]
        keys = set(observed_days)
        counts = {"cross_class_days_v4": len(prior), "cross_class_days_v5": len(observations),
                  "new_cross_class_days": sum((code, day) not in base or
                                               not base[code, day]["issuer_class_provenance_id"] for day in keys),
                  "first_actual_class_cap": min(keys) if keys else None, "last_actual_class_cap": max(keys) if keys else None,
                  "prior_class_days_missing": sum(r["local_trade_date"] not in keys for r in prior)}
        if active:
            # B-share delisting is outcome evidence and is not a valuation premise.
            removed = [day for day in observed_days if day >= date.fromisoformat(active)]
        output.append({"ts_code": code, "sibling": SIBLINGS[code], "retired_sibling_date": active,
                       "valuation_at_or_after_retirement": removed, **counts})
    return output, history


def inspect_sources(con, args, releases, current):
    capital = args.work_root / "artifacts" / "cn_numeric_followup" / "capital"
    retired = args.work_root / "artifacts" / "cn_b_sibling_rates"
    manifest = json.loads((args.release / "manifest.json").read_bytes())
    if manifest["dataset_version"] != args.release.name:
        raise ValueError("Release identity differs from its immutable manifest")
    proof = {}
    quotes_file = args.pit / "class_quotes.parquet"
    for name in ("class_quotes.parquet", "class_fx.parquet", "issuer_class_versions.jsonl"):
        path = args.pit / name
        sha = digest(path)
        if manifest["pit_evidence_sha256"].get(name) != sha:
            raise ValueError(f"The published source fingerprint does not bind the audited PIT file: {name}")
        proof[name] = {"path": path.as_posix(), "sha256": sha}
    proof["class_quotes.parquet"]["rows"] = con.read_parquet(str(quotes_file)).aggregate("count(*)").fetchone()[0]
    bindings = replace_references(con, args.pit, args.release, list(SIBLINGS.values()))
    linkage = full_source_links(con)
    if linkage["source_links_checked"] != sum(r["cross_class_valued_days"] for r in releases["release"]):
        raise ValueError("A positive cross-class observation resolves to multiple published source versions")
    quote_lookup = {(row["class_id"], row["quote_date"]): row for row in bindings}
    if len(quote_lookup) != len(bindings):
        raise ValueError("Multiple frozen quotes occupy a representative sibling/date key")
    archives, fx_at, fx_rows = original_fx_rows(args.pit, args.csmar_fx)
    versions = class_versions(args.pit / "issuer_class_versions.jsonl")
    pdf_files = [*retired.joinpath("originals").glob("*.pdf"), *capital.joinpath("orient_two_class").glob("*.pdf"),
                 *capital.joinpath("merchants_two_class").glob("*.pdf")]
    by_sha = {digest(p): p for p in pdf_files}
    selected, preferred = defaultdict(list), defaultdict(set)
    for label in ("orient_two_class", "merchants_two_class"):
        for row in class_versions(capital / label / "frozen" / "issuer_class_versions.jsonl").values():
            for record in row:
                preferred[record["ts_code"]].add(record["source_sha256"])
    for code in RETIRED:
        preferred[code].add(digest(retired / "originals" / f"{code}.pdf"))
    captured = {}
    for code, sibling in SIBLINGS.items():
        observation, raw_series = source_quote_series(sibling, capital, retired)
        captured[sibling] = observation
        for row in current[code]:
            day = row["local_trade_date"]
            if row["issuer_quote_age_days"] != 0 or (sibling, day) not in quote_lookup:
                continue
            sources = [v for v in versions.get(row["issuer_class_provenance_id"], [])
                       if v["ts_code"] == code and v["source_sha256"] in preferred[code]
                       and v["effective_from"] <= str(day) < (v.get("effective_to") or "9999-12-31")
                       and availability(v["published_at"]) <= row["asof_utc"]]
            source = max(sources, key=lambda v: v["published_at"], default=None)
            if source and by_sha.get(source["source_sha256"]):
                selected[code].append((row, source, observation | {"dates": raw_series}, quote_lookup[sibling, day]))
    outputs = []
    checked_pdfs = {}
    broker_audit = json.loads((capital / "v5_class_crosscheck" / "ah_broker_original_class_amounts.json").read_bytes())
    sample_tracks = [chosen for cases in selected.values() for i, chosen in enumerate(cases) if i in {0, len(cases) - 1}]
    batches = dict(con.execute("""
        SELECT provenance_id,daily_batch FROM quote_sources WHERE provenance_id IN (SELECT unnest(?))
    """, [sorted({x[0]["provenance_id"] for x in sample_tracks})]).fetchall())
    currencies = dict(con.execute("""
        SELECT DISTINCT fundamental_snapshot_id,reporting_currency FROM currencies
        WHERE fundamental_snapshot_id IN (SELECT unnest(?))
    """, [sorted({x[0]["fundamental_snapshot_id"] for x in sample_tracks if x[0]["fundamental_snapshot_id"]})]).fetchall())
    for code in SIBLINGS:
        if not selected[code]:
            raise ValueError(f"No actual valued rows under the known original share evidence for {code}")
        # Use the first and last auditable positive rows under the exact source set.
        for index in sorted({0, len(selected[code]) - 1}):
            stock, record, raw_series, quote = selected[code][index]
            evidence = checked_pdfs.get(record["source_sha256"])
            if evidence is None:
                evidence = original_share_pdf(record, by_sha, broker_audit, args.pdf_python)
                if evidence is None:
                    raise ValueError(f"Retained original PDF did not resolve the exact selected share quantities: {code}")
                checked_pdfs[record["source_sha256"]] = evidence
            if not con.execute("""
                SELECT count(*) FROM pit_sources
                WHERE provenance_id=? AND source_sha256=? AND available_at<=?
            """, [stock["issuer_class_provenance_id"], record["source_sha256"], stock["asof_utc"]]).fetchone()[0]:
                raise ValueError(f"Missing published as-of original source link for {code}")
            result = recompute_sample(con, args.release, stock, record, SIBLINGS[code], raw_series, quote,
                                      (fx_at, fx_rows), batches[stock["provenance_id"]],
                                      currencies.get(stock["fundamental_snapshot_id"]))
            outputs.append(result | {"verified_original_shares": evidence})
    return {"pit_inputs_hashed_in_manifest": proof, "original_fx_batches": archives,
            "archived_foreign_close_evidence": captured, "verified_examples": outputs,
            "release_count_by_venue": releases, "all_class_valuation_source_links": linkage}


def full_source_links(con):
    counts = dict_rows(con.sql("""
        SELECT count(*) AS source_links_checked,
               count_if(p.provenance_id IS NULL OR p.available_at IS NULL OR p.available_at>b.asof_utc
                        OR p.knowledge_quality IS DISTINCT FROM 'historical_original_evidence'
                        OR p.source_sha256 IS NULL OR NOT regexp_full_match(p.source_sha256,'[a-f0-9]{64}')) AS invalid_links
        FROM (SELECT issuer_class_provenance_id,asof_utc FROM stock_release
              WHERE issuer_class_provenance_id IS NOT NULL AND issuer_market_cap_reporting>0
              AND isfinite(issuer_market_cap_reporting)) b
        LEFT JOIN pit_sources p ON p.provenance_id=b.issuer_class_provenance_id
    """))[0]
    if counts["invalid_links"]:
        raise ValueError(f"Published cross-class valuations include unverified or late provenance: {counts}")
    return counts


def replace_references(con, pit, release, siblings):
    con.read_parquet(str(pit / "class_fx.parquet")).create_view("class_fx")
    references = release / "reference"
    con.read_parquet(str(references / "quote_provenance.parquet")).create_view("quote_sources")
    con.read_parquet(str(references / "pit_provenance.parquet")).create_view("pit_sources")
    con.read_parquet(str(release / "stock_fundamental_asof/market_id=CN/year=*/*.parquet")).create_view("currencies")
    return dict_rows(con.execute("""
        SELECT class_id,quote_date,price,currency,available_at,source_sha256
        FROM read_parquet(?) WHERE class_id IN (SELECT unnest(?))
    """, [str(pit / "class_quotes.parquet"), siblings]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("prior", "release", "pit", "registry", "csmar-fx", "work-root", "pdf-python", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    with duckdb.connect(config={"threads": "1", "memory_limit": "448MB"}) as con:
        registry = args.registry.resolve().as_posix().replace("'", "''")
        con.execute(f"ATTACH '{registry}' AS quant (READ_ONLY)")
        old_by_venue, previous = release_rows(con, args.prior)
        new_by_venue, current = release_rows(con, args.release)
        counts, stocks = output_counts(previous, current)
        if any(not r["cross_class_days_v5"] or r["valuation_at_or_after_retirement"] for r in counts):
            raise ValueError(f"One of the seven audited issuers has missing or post-retirement capitalization: {counts}")
        details = inspect_sources(con, args, {"prior": old_by_venue, "release": new_by_venue}, stocks)
    report = {"prior": args.prior.name, "release": args.release.name, "issuer_counts": counts} | details
    partial = args.output.with_suffix(".partial")
    partial.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
    partial.replace(args.output)
    print(json.dumps({"release": args.release.name, "issuer_counts": counts,
                      "source_samples_checked": len(details["verified_examples"])}, default=str))


if __name__ == "__main__":
    main()

