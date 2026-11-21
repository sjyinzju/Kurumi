"""Freeze exact A/H classes from issuer original disclosures and matched histories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
from stage_cn_orient_class_history import evidence_row, extract, verify_values
from stage_cn_residual_share_classes import _events, _rows, _source_file_hash

from kurumi.cn_capital_sources import csmar_capture
from kurumi.cn_pit import _with_provenance

SIBLINGS = {
    "001289.SZ": "00916.HK", "600938.SH": "00883.HK", "601038.SH": "00038.HK", "601111.SH": "00753.HK",
    "601868.SH": "03996.HK", "601899.SH": "02899.HK",
}

# A year/month boundary limits the certified interval where an exact future
# transition was not publicly scheduled. Actual availability uses the primary notice.
PHASES = (
    ("1212230588.PDF", "1219430686.PDF", "2022-01-24", "2024-01-01", 5_041_934_164, 3_340_029_000,
     ("2022年1月24日", "A股合计5,041,934,164", "H股合计3,340,029,000", "8,381,963,164")),
    ("1219430686.PDF", "2024032701742_c.pdf", "2024-03-11", "2026-08-01", 5_041_934_164, 3_317_882_000,
     ("2024年3月11日.{0,18}注销", "A股5,041,934,164股及?H股3,317,882,000股|A股5,041,934,164股,H股3,317,882,000股",
      "8,359,816,164")),
    ("2022-04-20.pdf", "2022-05-25.pdf", "2022-04-21", "2022-05-01", 2_600_000_000, 44_647_455_984,
     ("2022年4月21日", "2,600,000,000股", "44,647,455,984")),
    ("2022-05-25.pdf", "2022-04-20.pdf", "2022-05-20", "2022-09-01", 2_990_000_000, 44_647_455_984,
     ("2022年5月20日", "1,497,149,308", "1,492,850,692", "44,647,455,984")),
    ("2023032900445.pdf", "2024040202010.pdf", "2022-12-31", "2024-08-01", 2_990_000_000, 44_576_763_984,
     ("44,576,763,984", "2,990,000,000", "47,566,763,984")),
    ("601038_20210219_1.pdf", "2024090203635_c.pdf", "2021-02-09", "2026-08-01", 731_705_275, 391_940_000,
     ("2021年2月9日", "137,795,275", "985,850,000", "1,123,645,275")),
    ("601111_20130201_1.pdf", "CF55160D0DBB6C6C05FC96D18B49697E.pdf", "2013-01-30", "2017-01-01",
     8_522_067_640, 4_562_683_364, ("2013年1月30日", "4,562,683,364", "13,084,751,004")),
    ("601111_20170314_1.pdf", "CF55160D0DBB6C6C05FC96D18B49697E.pdf", "2017-03-10", "2023-01-01",
     9_962_131_821, 4_562_683_364, ("2017年3月10日", "1,440,064,181", "4,562,683,364", "14,524,815,185")),
    ("601111_20230118_WUW5.pdf", "601111_20230118_MLFH.pdf", "2023-01-16", "2024-01-01",
     11_638_109_474, 4_562_683_364, ("2023年1月16日", "1,675,977,653", "4,562,683,364", "16,200,792,838")),
    ("601111_20240208_5L9T.pdf", "601111_20241213_CZW6.pdf", "2024-02-07", "2024-12-01",
     11_638_109_474, 4_955_610_672, ("2024年2月7日", "11,638,109,474", "4,955,610,672", "16,593,720,146")),
    ("601111_20241213_RBTT.pdf", "601111_20241213_CZW6.pdf", "2024-12-10", "2026-06-01",
     12_492_810_328, 4_955_610_672, ("12,492,810,328", "4,955,610,672", "17,448,421,000")),
    ("601111_20260610_3C9M.pdf", "601111_20260610_04S0.pdf", "2026-06-04", "2026-08-01",
     15_536_950_358, 4_955_610_672, ("2026年6月4日", "4,562,683,364", "392,927,308", "20,492,561,030")),
    ("601868_20210927_1_FG67S6rs.pdf", "2022092101176_c.pdf", "2021-09-28", "2026-01-01",
     32_428_727_636, 9_262_436_000,
     ("2021年9月28日", "A股总股本为32,428,727,636股", "H股合计9,262,436,000股", "41,691,163,636")),
    ("601868_20260403_W5DT.pdf", "601868_20210927_1_FG67S6rs.pdf", "2026-04-01", "2026-08-01",
     34_977_747_243, 9_262_436_000, ("2026年4月1日", "2,549,019,607", "41,691,163,636", "44,240,183,243")),
    ("601899_20210629_1_HeawiRtD.pdf", "601899_20211210_1_kC3F33WW.pdf", "2021-06-25", "2021-12-01",
     20_590_662_240, 5_736_940_000, ("2021年6月25日", "20,590,662,240", "5,736,940,000", "26,327,602,240")),
    ("601899_20220113_1_ImmdCCaq.pdf", "601899_20211210_1_kC3F33WW.pdf", "2022-01-17", "2023-01-01",
     20_592_372_240, 5_736_940_000, ("2022年1月17日", "20,592,372,240", "5,736,940,000", "26,329,312,240")),
    ("601899_20230109_STHM.pdf", "601899_20220113_1_ImmdCCaq.pdf", "2023-01-11", "2023-04-01",
     20_591_232_240, 5_736_940_000, ("2023年1月11日", "20,591,232,240", "5,736,940,000", "26,328,172,240")),
    ("601899_20230413_VDZX.pdf", "601899_20230109_STHM.pdf", "2023-04-17", "2024-03-01",
     20_589_631_240, 5_736_940_000, ("2023年4月17日", "20,589,631,240", "5,736,940,000", "26,326,571,240")),
    ("601899_20240315_J60O.pdf", "601899_20230413_VDZX.pdf", "2024-03-19", "2024-06-01",
     20_589_048_940, 5_736_940_000, ("2024年3月19日", "20,589,048,940", "5,736,940,000", "26,325,988,940")),
    ("601899_20240626_CFX2.pdf", "601899_20240315_J60O.pdf", "2024-06-25", "2025-01-01",
     20_589_048_940, 5_988_840_000, ("2024年6月25日完成配售", "20,589,048,940", "5,988,840,000", "26,577,888,940")),
    ("601899_20250114_Q0MQ.pdf", "601899_20240626_CFX2.pdf", "2025-01-16", "2025-11-01",
     20_588_733_940, 5_988_840_000, ("2025年1月16日", "20,588,733,940", "5,988,840,000", "26,577,573,940")),
    ("601899_20251031_01OJ.pdf", "601899_20250114_Q0MQ.pdf", "2025-11-04", "2025-12-01",
     20_588_703_340, 5_988_840_000, ("2025年11月4日", "20,588,703,340", "5,988,840,000", "26,577,543,340")),
    ("601899_20251216_YVXG.pdf", "601899_20251031_01OJ.pdf", "2025-12-18", "2026-03-01",
     20_600_893_140, 5_988_840_000, ("2025年12月18日", "20,600,893,140", "5,988,840,000", "26,589,733,140")),
)


def _verify_capital_archives(events, states, code, start, end, a, h):
    # The independent vendor records free and restricted H counts distinctly.
    effective = max((row["END_DATE"][:10] for row in events if row["END_DATE"][:10] <= start), default=None)
    csmar_start = max((row[0] for row in states if row[0] <= start), default=None)
    if not effective or not csmar_start:
        raise ValueError("An independent starting position is missing")
    vendor_matches, csmar_matches = [], []
    for row in events:
        day = row["END_DATE"][:10]
        if not effective <= day < end:
            continue
        observed = (row["TOTAL_SHARES"], (row["LISTED_A_SHARES"] or 0) + (row["LIMITED_A_SHARES"] or 0),
                    (row["H_FREE_SHARE"] or 0) + (row["LIMITED_H_SHARES"] or 0),
                    (row["B_FREE_SHARE"] or 0) + (row["LIMITED_B_SHARES"] or 0))
        if observed != (a + h, a, h, 0):
            raise ValueError(f"Independent ordinary share amounts differ at {day}: {observed}")
        vendor_matches.append(row)
    for row in states:
        day, total, h_flowable, b, preferred, other = row
        if not csmar_start <= day < end:
            continue
        # The 2024 and 2026 issuer disclosures print 392,927,308 locked H shares.
        possible_h = {h, h - 392_927_308} if code == "601111.SH" and day >= "2024-02-07" else {h}
        if total != a + h or any((b, preferred, other)) or h_flowable not in possible_h:
            raise ValueError(f"Authorized capital history differs at {day}: {row}")
        csmar_matches.append(row)
    return {"eastmoney_exact_states": vendor_matches, "csmar_exact_states": csmar_matches}


def _literal_patterns(literals):
    return {f"verified_literal_{i}": literal for i, literal in enumerate(literals, 1)}


def _baseline_anchors(frozen):
    by_code = {}
    terms = tuple(f'"{code}"' for code in SIBLINGS)
    with (frozen / "share_versions.jsonl").open(encoding="utf-8") as source:
        for line in source:
            if not any(term in line for term in terms):
                continue
            row = json.loads(line)
            if row["ts_code"] in SIBLINGS and row.get("single_share_class") is False:
                by_code.setdefault(row["ts_code"], set()).add((
                    row["effective_from"], row.get("shares_outstanding_security"),
                ))
    return by_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", required=True, type=Path)
    parser.add_argument("--csmar", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--issuer", action="append", choices=tuple(SIBLINGS))
    args = parser.parse_args()
    docs = {Path(r["local"]).name: r for r in json.loads((args.originals / "source_receipts.json").read_bytes())}
    args.output.mkdir(parents=True, exist_ok=True)
    staged, rejected = {}, []
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='850MB'")
        receipts = csmar_capture(con, args.csmar, "TRD_Capchg")
        for target, support, start, end, a, h, literals in PHASES:
            code = docs[target]["ts_code"]
            if args.issuer and code not in args.issuer:
                continue
            raw_scope, events = _events(args.originals, code)
            states = con.execute("""SELECT Shrchgdt::VARCHAR,Nshrttl,Nshrh,Nshrb,Nshrprf,Nshroft
                FROM TRD_Capchg WHERE Stkcd=? ORDER BY Shrchgdt""", [code.split(".")[0]]).fetchall()
            try:
                primary = extract(docs[target], _literal_patterns(literals))
                secondary = extract(docs[support], {})
                checks = _verify_capital_archives(events, states, code, start, end, a, h)
            except ValueError as exc:
                rejected.append({"ts_code": code, "effective_from": start, "document": target, "reason": str(exc)})
                continue
            fact = evidence_row(primary, secondary, start, a, h, effective_to=end, qualified_history_end=end,
                                continuation_evidence=checks | {"provider_event_archive": raw_scope["events_sha256"]})
            staged.setdefault(code, []).append(fact)
    shares, classes, replays = [], [], {}
    baseline = _baseline_anchors(args.frozen)
    for code, positions in staged.items():
        rows = [position | {"classes": [
            {"class_id": code, "shares": position["shares_outstanding_security"], "currency": "CNY"},
            {"class_id": SIBLINGS[code], "shares": position["shares_outstanding_h"], "currency": "HKD"},
        ]} for position in positions]
        issuer = args.output / code
        issuer.mkdir(exist_ok=True)
        _rows(issuer / "issuer_class_versions.jsonl", rows)
        with duckdb.connect() as con:
            con.execute("SET threads=1; SET memory_limit='850MB'")
            replays[code] = verify_values(con, args.release, _with_provenance(issuer, "issuer_class_versions", {}), args.frozen)
        for position in positions:
            known = baseline.get(code, set())
            value, day = position["shares_outstanding_security"], position["effective_from"]
            if any(start <= day and amount == value for start, amount in known):
                # A class count already documented at this clock survives a
                # later change in the sibling class.
                if (day, value) in known or code == "001289.SZ":
                    continue
            # These exact new A facts preserve coverage of the existing A
            # series. Later Air China and Zijin spans also need closure evidence
            # for the existing A timeline before their share side is combined.
            if code in {"601038.SH", "601868.SH"} or (code == "601111.SH" and day < "2016-01-01"):
                shares.append(position)
        classes.extend(rows)
    files = args.output / "share_versions.jsonl", args.output / "issuer_class_versions.jsonl"
    for path, rows in zip(files, (shares, classes), strict=True):
        _rows(path, rows)
    output = {"release_replayed": args.release.name, "baseline": args.frozen.name, "staged_shares": len(shares),
              "staged_complete_classes": len(classes),
              "issuers": replays, "rejected": rejected, "csmar_receipts": receipts,
              "stream_sha256": {path.name: _source_file_hash(path) for path in files}}
    (args.output / "evidence_audit.json").write_text(json.dumps(output, ensure_ascii=False, default=str, indent=2) + "\n", "utf-8")
    print(json.dumps({"staged_shares": len(shares), "staged_complete_classes": len(classes),
                      "rejected": rejected, "issuer_replays": replays}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
