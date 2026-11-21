"""Audit missing security names and stage source-certified name intervals for reviewed issuers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa

from .cn_mainland_share_monthly import PDF_EXTRACTOR, checked_receipt

LOCAL = ZoneInfo("Asia/Shanghai")
TARGET_CODES = ("302132.SZ", "001236.SZ", "688347.SH")


def original(pdf, receipt, python, published, checks, *, catalogued_path=None):
    source_url = receipt.get("url") or receipt["source_url"]
    source_hash = receipt.get("sha256") or receipt["source_sha256"]
    status = receipt.get("status") or receipt["http_status"]
    link = urlsplit(source_url)
    body = pdf.read_bytes()
    path_verified = link.path.removeprefix("/download") == catalogued_path if catalogued_path else published in link.path
    if (status != 200 or link.scheme != "https" or link.hostname not in ("disc.static.szse.cn", "big5.sse.com.cn")
            or not path_verified or source_hash != hashlib.sha256(body).hexdigest()):
        raise ValueError(f"Original proof mismatch in {pdf.name}")
    text = subprocess.run([str(python), "-c", PDF_EXTRACTOR], input=body,
                          capture_output=True, check=True, timeout=60).stdout.decode("utf-8")
    compact = re.sub(r"\s+", "", text)
    proof = []
    for pattern in checks:
        match = re.search(pattern, compact)
        if not match:
            raise ValueError(f"Absent issuer fact in {pdf.name}: {pattern}")
        proof.append(match[0])
    available = datetime.combine(date.fromisoformat(published) + timedelta(days=1), time(), LOCAL)
    return {"published_at": published, "available_at": available.isoformat(),
            "observed_at": receipt["observed_at"], "source_url": source_url, "source_sha256": source_hash,
            "source_version_id": link.path.rsplit("/", 1)[-1], "knowledge_quality": "historical_original_evidence",
            "source_literals": proof}


def saved_original(path, file, python, public, *checks):
    receipt = json.loads((path / (file + ".pdf.receipt.json")).read_bytes())
    return original(path / (file + ".pdf"), receipt, python, public, checks)


def verified_names(args):
    data = args.artifacts
    control = data / "cn_numeric_followup/capital"
    ipo_root = control / "security_code_302132"
    change_root = control / "action_reconciled_final_prices"
    stage = data / "cn_security_name_audit"
    receipt = json.loads((ipo_root / "302132_old_symbol_original_listing_audit.json").read_bytes())
    old = original(ipo_root / "szse-300114-2010-listing-original.pdf", receipt, args.pdf_python, "2010-08-26",
                   [r"(?:股票|证券)简称[：:“\"]*中航电测", r"(?:股票|证券)代码[：:“\"]*300114", r"2010年8月27日起上市交易"])
    receipt = json.loads((change_root / "302132_historical_alias_source_receipt.json").read_bytes())[0]
    new = original(change_root / receipt["source_file"], receipt, args.pdf_python, "2025-02-15",
                   [r"(?:股票|证券)简称[：:“\"]*中航电测", r"变更后的证券简称[：:]中航成飞",
                    r"变更后的证券代码[：:]302132", r"启用日期为2025年2月17日"])
    provider = (stage / "302132.SZ.tushare.response.json").read_bytes()
    provider_receipt = json.loads((stage / "302132.SZ.tushare.receipt.json").read_bytes())
    if hashlib.sha256(provider).hexdigest() != provider_receipt["normalized_body_sha256"]:
        raise ValueError("Provider corroboration hash mismatch")
    candidate = json.loads(provider)
    if set(tuple(row[:4]) for row in candidate["items"]) != {
        ("302132.SZ", "中航电测", "20100827", "20250216"), ("302132.SZ", "中航成飞", "20250217", None),
    }:
        raise ValueError("Provider effective names disagree with the two exchange originals")
    old.update(corroboration_url=provider_receipt["source_url"],
               corroboration_sha256=provider_receipt["normalized_body_sha256"])
    new.update(corroboration_url=provider_receipt["source_url"],
               corroboration_sha256=provider_receipt["normalized_body_sha256"])
    stage = stage / "issuer_originals"
    sh_old = saved_original(stage, "688347-ipo", args.pdf_python, "2023-08-04",
                            r"股票简称[：:]华虹公司", r"股票代码[：:]688347", r"上市时间[：:]2023年8月7日")
    sh_new = saved_original(stage, "688347-implementation", args.pdf_python, "2026-06-04",
                            r"2026年6月8日起由[“\"]华虹公司[”\"]变更为[“\"]华虹宏力[”\"]", r"证券代码[“\"]688347[”\"]")
    soy = saved_original(data / "cn_sse_class_monthly/soyafutures_event", "listing-1214214545", args.pdf_python,
                         "2022-08-04", r"股票简称[：:]弘业期货", r"股票代码[：:]001236", r"上市时间[：:]2022年8月5日")
    publication, catalogue = checked_receipt(stage / "001236-board-publication.json",
                                             stage / "001236-board-publication.json.receipt.json", "www.szse.cn")
    disclosure = [row for row in json.loads(publication)["data"] if row["annId"] == 1223567893 and row["secCode"] == ["001236"]]
    if len(disclosure) != 1:
        raise ValueError("SZSE publication metadata missing or ambiguous for the terminated proposal")
    receipt = json.loads((stage / "001236-terminated.pdf.receipt.json").read_bytes())
    ended = original(stage / "001236-terminated.pdf", receipt, args.pdf_python, disclosure[0]["publishTime"][:10],
                     [r"拟变更公司名称、证券简称", r"证券简称仍为[“\"]弘业期货[”\"]"],
                     catalogued_path=disclosure[0]["attachPath"])
    soy.update(corroboration_url=ended["source_url"], corroboration_sha256=ended["source_sha256"],
               corroboration_catalogue_sha256=catalogue["sha256"],
               corroboration_note="The company expressly confirmed the proposed trading-name change did not take effect")
    intervals = [
        ("302132.SZ", "300114", "中航电测", "2010-08-27", "2025-02-17", old),
        ("302132.SZ", "302132", "中航成飞", "2025-02-17", None, new),
        ("001236.SZ", "001236", "弘业期货", "2022-08-05", None, soy),
        ("688347.SH", "688347", "华虹公司", "2023-08-07", "2026-06-08", sh_old),
        ("688347.SH", "688347", "华虹宏力", "2026-06-08", None, sh_new),
    ]
    return [proof | {"ts_code": code, "symbol_asof": symbol, "name_asof": name,
                     "effective_from": start, "effective_to": stop}
            for code, symbol, name, start, stop, proof in intervals]


def audit_release(con, root, names, canonical):
    path = (root / "stock_daily/market_id=CN/year=*/*.parquet").as_posix()
    samples = (root / "samples/market_id=CN/year=*/*.parquet").as_posix()
    con.read_parquet(path).create_view("released_stock")
    con.read_parquet(samples).create_view("released_sample")
    con.execute("""
        CREATE TEMP TABLE missing_name AS
        SELECT ts_code,instrument_id,exchange,local_trade_date,listing_date, quote_valid
        FROM released_stock WHERE name_asof IS NULL
    """)
    gaps = con.execute("""
        SELECT exchange,count(*),count_if(local_trade_date=listing_date),count_if(ts_code='302132.SZ'),
            count_if(quote_valid),count(DISTINCT ts_code)
        FROM missing_name GROUP BY exchange ORDER BY exchange
    """).fetchall()
    samples = con.execute("""
        SELECT split,count(*),count_if(input_valid),count_if(g.ts_code='302132.SZ'),
               count_if(s.input_valid AND g.ts_code='302132.SZ')
        FROM released_sample s JOIN missing_name g USING(instrument_id,local_trade_date)
        GROUP BY split ORDER BY split
    """).fetchall()
    roster = con.execute("""
        SELECT DISTINCT ts_code,instrument_id FROM released_stock WHERE ts_code IN (SELECT unnest(?))
    """, [list(TARGET_CODES)]).fetchall()
    identities = dict(roster)
    if len(roster) != len(TARGET_CODES) or len(identities) != len(TARGET_CODES):
        raise ValueError("The three issuer mappings are ambiguous in this release")
    for row in names:
        row["instrument_id"] = identities[row["ts_code"]]
    con.register("official_names", pa.Table.from_pylist(names))
    changes = con.execute("""
        SELECT s.ts_code,n.name_asof,count(*) AS verified_rows,count_if(s.name_asof IS NULL) prior_null,
           count_if(s.name_asof IS NOT NULL AND s.name_asof<>n.name_asof) prior_wrong,
           min(s.local_trade_date),max(s.local_trade_date)
        FROM released_stock s JOIN official_names n USING(instrument_id)
        WHERE s.local_trade_date>=CAST(n.effective_from AS DATE)
          AND s.local_trade_date < coalesce(CAST(n.effective_to AS DATE),DATE '9999-12-31')
          AND s.asof_utc>=CAST(n.available_at AS TIMESTAMPTZ)
        GROUP BY s.ts_code,n.name_asof ORDER BY s.ts_code,min(s.local_trade_date)
    """).fetchall()
    prefix = {}
    for cutoff in (date(2024, 3, 28), date(2025, 2, 14), date(2026, 6, 3)):
        n, prefix_rows = con.execute("""
            WITH prior AS (
                SELECT instrument_id,local_trade_date,asof_utc
                FROM released_stock WHERE ts_code IN (SELECT unnest(?)) AND local_trade_date<=?
            ), eligible AS (
                SELECT p.instrument_id,p.local_trade_date,n.symbol_asof,n.name_asof,n.published_at
                FROM prior p JOIN official_names n USING(instrument_id)
                WHERE p.local_trade_date>=CAST(n.effective_from AS DATE)
                  AND p.local_trade_date<coalesce(CAST(n.effective_to AS DATE),DATE '9999-12-31')
                  AND p.asof_utc>=CAST(n.available_at AS TIMESTAMPTZ)
            )
            SELECT count(*),count_if(CAST(published_at AS DATE)<=?) FROM eligible
        """, [list(TARGET_CODES), cutoff, cutoff]).fetchone()
        if n != prefix_rows:
            raise ValueError(f"An earlier sample uses a future-published name on {cutoff}")
        prefix[cutoff.isoformat()] = {
            "versions_removed": sum(date.fromisoformat(row["published_at"]) > cutoff for row in names),
            "unchanged_name_day_rows": n,
        }
    if canonical is not None:
        path = (canonical / "*.parquet").as_posix()
        # Source's ambiguous same-date rows count as one gap, regardless of repeated physical shards.
        vendor_lag = con.execute("""
            WITH late AS (
                SELECT DISTINCT ts_code,try_strptime(start_date,'%Y%m%d')::DATE AS day
                FROM read_parquet(?) WHERE start_date=ann_date AND name IS NOT NULL
            )
            SELECT g.exchange,count(*),count_if(g.local_trade_date=g.listing_date)
            FROM missing_name g JOIN late n ON n.ts_code=g.ts_code AND n.day=g.local_trade_date
            GROUP BY g.exchange ORDER BY exchange
        """, [path]).fetchall()
    else:
        vendor_lag = []
    return {"dataset": root.name, "gap_fields": ["exchange", "null_names", "ipo_first_day", "renamed_code_null_names",
                                                  "valid_market_quotes", "distinct_affected_securities"],
            "gap_by_exchange": gaps, "sample_fields": ["split", "matching_candidates", "input_valid",
                                                       "renamed_issuer_candidates", "renamed_issuer_input_valid"],
            "candidate_samples_intersecting_gap": samples, "gap_rows_matching_same_day_vendor_effective_and_ann_date": vendor_lag,
            "verified_scope_fields": ["ts_code", "expected_name", "current_rows", "prior_null", "prior_wrong",
                                      "first_matching_session", "last_matching_session"], "verified_scope": changes,
            "model_name_join_prefix_only": prefix}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--canonical-namechanges", type=Path)
    parser.add_argument("--pdf-python", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    names = verified_names(args)
    with duckdb.connect() as con:
        summary = audit_release(con, args.dataset, names, args.canonical_namechanges)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "security_name_versions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in names), encoding="utf-8",
    )
    (args.output / "identity_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
                                                    encoding="utf-8")
    print(json.dumps({"staged_versions": len(names), "total_affected_rows": sum(r[1] for r in summary["gap_by_exchange"])}))


if __name__ == "__main__":
    main()
