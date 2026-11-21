"""Freeze audited A/H capital spans from original filings and independent event archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import duckdb
from stage_cn_orient_class_history import evidence_row, extract, verify_values

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_pit import _with_provenance

SIBLINGS = {
    "600028.SH": "00386.HK", "600585.SH": "00914.HK", "601088.SH": "01088.HK", "601288.SH": "01288.HK",
    "601318.SH": "02318.HK", "601328.SH": "03328.HK", "601988.SH": "03988.HK",
}

# Intervals ending on calendar boundaries are deliberately qualified only through the
# last independently reconciled reporting/sample period before a changing capital episode.
# Later publication is never used to extend these periods back into an unresolved episode.
PHASES = (
    ("600585_20110609_1.pdf", "600585_20260714_FLTN.pdf", "2011-06-16", "2026-07-01", 3_999_702_579, 1_299_600_000,
     {"a_after": "A股.{0,65}3,999,702,579", "h_after": "H股.{0,65}1,299,600,000", "total_after": "5,299,302,579"}),
    ("601088_2013_n.pdf", "601088_20210309_1.pdf", "2013-12-31", "2021-01-01", 16_491_037_955, 3_398_582_500,
     {"ordinary_table": "16,491,037,95582.91.{0,45}3,398,582,50017.09.{0,155}19,889,620,455"}),
    ("601088_20210309_1.pdf", "601088_20260318_M00H.pdf", "2021-03-08", "2026-01-01", 16_491_037_955, 3_377_482_000,
     {"a": "A股16,491,037,955股", "h": "H股3,377,482,000股", "total": "19,868,519,955", "effective": "2021年3月8日"}),
    ("601088_20260318_M00H.pdf", "601088_20210309_1.pdf", "2026-03-16", "2026-04-01", 17_854_286_401, 3_377_482_000,
     {"a_issued": "1,363,248,446", "total_after": "21,231,768,401", "effective": "2026年3月16日"}),
    ("601088_20260409_67KC.pdf", "601088_20210309_1.pdf", "2026-04-07", None, 18_311_952_304, 3_377_482_000,
     {"a_issued": "457,665,903股", "total_after": "21,689,434,304股", "effective": "2026年4月7日"}),
    ("601288_2013_n.pdf", "601288_20180704_1.pdf", "2013-12-31", "2018-04-01", 294_055_293_904, 30_738_823_096,
     {"a": "294,055,293,904", "h": "30,738,823,096", "total": "324,794,117,000"}),
    ("601288_20180704_1.pdf", "601288_2013_n.pdf", "2018-07-02", None, 319_244_210_777, 30_738_823_096,
     {"a_issued": "25,188,916,873", "a_prior": "294,055,293,904", "h": "30,738,823,096", "total_after": "349,983,033,873"}),
    ("601328_20120827_1.pdf", "601328_20120825_1.pdf", "2012-08-24", "2025-04-01", 39_250_864_015, 35_011_862_630,
     {"a_locked": "6,541,810,669", "a_unrestricted": "32,709,053,346", "h": "35,011,862,630", "total": "74,262,726,645"}),
    ("601328_20250619_9N2O.pdf", "601328_20250830_K9ZA.pdf", "2025-06-17", None, 53_351_921_593, 35_011_862_630,
     {"new_a": "14,101,057,578", "h_held": "4,553,999,999", "total_after": "88,363,784,223", "effective": "2025年6月17日"}),
    ("601988_20150310_2.pdf", "601988_20250619_63DL.pdf", "2015-03-06", "2025-04-01", 210_765_514_846, 83_622_276_395,
     {"a": "210,765,514,846", "h": "83,622,276,395", "total": "294,387,791,241", "effective": "2015年3月6日"}),
)
ADDITIONAL_PHASES = (
    ("600028_20150213_1.pdf", "600028_2014_n.pdf", "2015-02-11", "2022-01-01",
     95_557_771_046, 25_513_438_600,
     {"a": "95,557,771,046", "h": "25,513,438,600", "total": "121,071,209,646", "effective": "2015年2月11日"}),
    ("601318_20150113_1.pdf", "601318_20150718_1.pdf", "2015-01-09", "2015-07-27",
     5_416_332_249, 3_723_788_456,
     {"a": "5,416,332,249", "h": "3,723,788,456", "total": "9,140,120,705", "effective": "2015年1月9日"}),
    ("601318_20150718_1.pdf", "2023061500787_c.pdf", "2015-07-27", None,
     10_832_664_498, 7_447_576_912,
     {"a_doubled": "10,832,664,498", "h_doubled": "7,447,576,912", "total": "18,280,241,410", "ex_date": "2015年7月27日"}),
    ("2023061500787_c.pdf", "601318_20230616_UQPR.pdf", "2023-06-16", "2025-07-01",
     10_762_657_695, 7_447_576_912,
     {"a": "10,762,657,695", "h": "7,447,576,912", "total": "18,210,234,607", "effective": "2023年6月16日"}),
    ("601318_20250903_KBYO.pdf", "601318_20230616_UQPR.pdf", "2025-09-03", None,
     10_660_065_083, 7_447_576_912,
     {"a": "10,660,065,083", "h": "7,447,576,912", "total": "18,107,641,995", "effective": "2025年9月3日"}),
)


def _source_file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(root, code):
    scope = json.loads((root / f"{code}.receipt.json").read_bytes())
    raw = root / f"{code}.events.jsonl"
    if not scope["complete"] or scope["publication_through"] != "2026-07-31" or scope["events_sha256"] != _source_file_hash(raw):
        raise ValueError(f"No complete independent event archive for {code}")
    if any(page["source_sha256"] != _source_file_hash(root / page["raw_file"]) for page in scope["pages"]):
        raise ValueError(f"Archive page hash mismatch for {code}")
    records = [json.loads(line) for line in raw.read_text("utf-8").splitlines()]
    if len(records) != scope["rows_retained"]:
        raise ValueError(f"Archive record count mismatch for {code}")
    return scope, records


def _crosscheck(rows, csmar_rows, code, start, end, a, h):
    archive_earlier = [r for r in rows if r["END_DATE"][:10] <= start]
    if not archive_earlier:
        raise ValueError(f"No independent initial ordinary class state for {code} {start}")
    earliest = max(r["END_DATE"][:10] for r in archive_earlier)
    checked = []
    for row in rows:
        day = row["END_DATE"][:10]
        if not earliest <= day < end:
            continue
        vendor_a = (row["LIMITED_A_SHARES"] or 0) + (row["LISTED_A_SHARES"] or 0)
        if (row["TOTAL_SHARES"], vendor_a) != (a + h, a):
            raise ValueError(f"Independent A/ordinary total disagrees at {code} {day}")
        checked.append([day, row["NOTICE_DATE"][:10], vendor_a, row["TOTAL_SHARES"], row["source_sha256"]])
    auth_leading = max((r[0] for r in csmar_rows if r[0] <= start), default=None)
    if auth_leading is None:
        raise ValueError(f"No CSMAR initial state for {code} {start}")
    exact_vendor = []
    for row in csmar_rows:
        day, _, total, h_on_market, b, other = row
        if not auth_leading <= day < end:
            continue
        # TRD_Capchg.Nshrh is unrestricted H. The original interim report names
        # 4,553,999,999 restricted H shares, which remain in the same security class.
        h_locked = 4_553_999_999 if code == "601328.SH" and day >= "2025-06-30" else 0
        if (total, (h_on_market or 0) + h_locked, b or 0, other or 0) != (a + h, h, 0, 0):
            raise ValueError(f"Authorized ordinary history disagrees at {code} {day}: {row}")
        exact_vendor.append({"source_row": row, "separately_disclosed_locked_h": h_locked})
    return {"eastmoney_exact_states": checked, "csmar_exact_states": exact_vendor}


def _stage_sources(con, source, capture, phases):
    receipts = csmar_capture(con, capture, "TRD_Capchg")
    docs = {Path(r["local"]).name: r for r in json.loads((source / "source_receipts.json").read_bytes())}
    archives = {docs[phase[0]]["ts_code"]: _events(source, docs[phase[0]]["ts_code"]) for phase in phases}
    output = defaultdict(list)
    for target, alternative, start, end, a, h, patterns in phases:
        primary = extract(docs[target], patterns)
        code = primary["ts_code"]
        corroboration = extract(docs[alternative], {"issuer_identity": re.escape(code.split(".")[0])})
        if code == "601328.SH" and start == "2025-06-17":
            corroboration = extract(docs[alternative], {
                "complete_a_h": "A股股份53,351,921,593股.{0,35}H股股份35,011,862,630股",
                "locked_h": "H股4,553,999,999股的锁定期", "class_id": "3328",
            })
        csmar_rows = con.execute("""SELECT Shrchgdt::VARCHAR,Shrtyp,Nshrttl,Nshrh,Nshrb,Nshroft FROM TRD_Capchg
            WHERE Stkcd=? ORDER BY Shrchgdt""", [code.split(".")[0]]).fetchall()
        scope, events = archives[code]
        later_phase_start = min((r[2] for r in phases if docs[r[0]]["ts_code"] == code and r[2] > start), default="2026-08-01")
        check = _crosscheck(events, csmar_rows, code, start, min(end or "2026-08-01", later_phase_start), a, h)
        evidence = evidence_row(primary, corroboration, start, a, h, effective_to=end,
            qualified_history_end=end, continuation_evidence=check | {"public_event_archive": scope["events_sha256"]})
        output[code].append(evidence)
    return output, receipts


def _rows(path, values):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in values), "utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--csmar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--additional", action="store_true")
    args = parser.parse_args()
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='850MB'")
        sources, receipts = _stage_sources(con, args.originals, args.csmar, ADDITIONAL_PHASES if args.additional else PHASES)
    combined_shares, combined_classes, results = [], [], {}
    for code, shares in sources.items():
        target = args.output / code
        target.mkdir(parents=True, exist_ok=True)
        classes = [r | {"classes": [
            {"class_id": code, "shares": r["shares_outstanding_security"], "currency": "CNY"},
            {"class_id": SIBLINGS[code], "shares": r["shares_outstanding_h"], "currency": "HKD"},
        ]} for r in shares]
        _rows(target / "share_versions.jsonl", shares)
        _rows(target / "issuer_class_versions.jsonl", classes)
        with duckdb.connect() as con:
            con.execute("SET threads=1; SET memory_limit='850MB'")
            versions = _with_provenance(target, "issuer_class_versions", {})
            results[code] = verify_values(con, args.release, versions, args.quotes)
        combined_shares.extend(shares)
        combined_classes.extend(classes)
    files = (args.output / "share_versions.jsonl", args.output / "issuer_class_versions.jsonl")
    for path, rows in zip(files, (combined_shares, combined_classes), strict=True):
        _rows(path, rows)
    audit = {"release_replayed": args.release.name, "issuers": results, "rows": len(combined_shares),
             "csmar_receipts": receipts, "streams": {p.name: _source_file_hash(p) for p in files}}
    (args.output / "evidence_audit.json").write_text(json.dumps(audit, ensure_ascii=False, default=str, indent=2)+"\n", "utf-8")
    print(json.dumps(results, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
