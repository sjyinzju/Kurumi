"""Write the prioritized CN source capture plans from inspected CSMAR metadata."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

from csmar_acquire import RUNTIME, dump_json

QEND_FILTER = "Typrep = 'A'"
FINANCE_FIELDS = {
    "FS_Combas": "Stkcd Accper Typrep A001000000 A002000000 A003100000 IfCorrect DeclareDate",
    "FS_Comins": "Stkcd Accper Typrep B001100000 B001101000 B002000000 B002000101 IfCorrect DeclareDate",
    "FS_Comscfd": "Stkcd Accper Typrep C001000000 IfCorrect DeclareDate",
}
END = "2026-07-31"


def dated_jobs(table: str, columns: str, periods: list[tuple[int, int]], condition: str = ""):
    return [
        job(table, columns, f"{first}-01-01", END if last == 2026 else f"{last}-12-31", condition)
        for first, last in periods
    ]


def job(table: str, columns: str, start: str = "", end: str = "", condition: str = "") -> dict:
    return {"table": table, "columns": columns.split(), "start": start, "end": end, "condition": condition}


def sw_index_publication_plan() -> list[dict]:
    prefix = "Indexcd like '801%'"
    fields = "Indexcd Chgsmp01 Chgsmp02 Chgsmp04 Chgsmp06 Chgsmp07"
    return [
        job("IDX_Idxinfo", "Indexcd Idxinfo01 Idxinfo04 Idxinfo06", condition=prefix),
        *dated_jobs("IDX_Chgsmp", fields, [(2014, 2016), (2017, 2019), (2020, 2022), (2023, 2025)], prefix),
        job("IDX_Chgsmp", fields, "2026-01-01", "2026-06-30", prefix),
    ]


def sw_index_composition_plan() -> list[dict]:
    prefix = "Indexcd like '801%'"
    return [
        job("IDX_Idxcop", "Indexcd Idxcop02 Idxcop05 Idxcop06", "2015-01-01", "2018-12-31", prefix),
        job("IDX_Idxcop", "Indexcd Idxcop02 Idxcop05 Idxcop06", "2019-01-01", "2022-12-31", prefix),
        job("IDX_Idxcop", "Indexcd Idxcop02 Idxcop05 Idxcop06", "2023-01-01", "2026-06-30", prefix),
    ]


def base_plan(capture: Path) -> list[dict]:
    cap = json.loads((capture / "fields" / "TRD_Capchg.json").read_text(encoding="utf-8"))["data"]
    plan = [
        job("STK_INDCLASSIFYVERSION", "IndClassifySystemCode IndClassifySystem ImplementDate AbandonDate InstitutionName"),
        job("STK_INDCLASSIFYSETS", "INDUSTRYCODE INDCLASSIFYSYSTEMCODE INDUSTRYNAME P_INDUSTRYCODE INDUSTRYID RANK"),
        job("TRD_Co", "Stkcd Stknme Conme Curtrd Crcd Commnt FormerCode Markettype Statdt Listdt Ipodt Nshripo"),
        job("TRD_Capchg", " ".join(x["field"] for x in cap), "1990-01-01", "2026-07-31"),
        job("TRD_Cptl", "Stkcd Disttyp Annodt Exdistdt Paydt Amount Roprc Markettype", "1990-01-01", "2026-07-31"),
        job("TRD_Exchange", "Exchdt Rmbusd Hkdusd Hkdrmb Ihkdrmb", "2014-01-01", "2026-07-31"),
    ]
    for year in range(2013, 2018):
        for table, fields in FINANCE_FIELDS.items():
            plan.append(job(table, fields, f"{year}-01-01", f"{year}-12-31", QEND_FILTER))
    return plan


def cross_codes(capture: Path) -> tuple[set[str], set[str]]:
    paths = sorted((capture / "requests" / "TRD_Co").glob("*.jsonl.gz"))
    if not paths:
        raise ValueError("Complete the TRD_Co source request before planning cross-class quotes")
    h, b = set(), set()
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                code = row["Commnt"]
                if code and len(code) == 5 and code.isdigit():
                    h.add(code)
                for code in (row["Stkcd"], row["Crcd"]):
                    if code and len(code) == 6 and code.startswith(("200", "900")) and code.isdigit():
                        b.add(code)
    return h, b


def targeted_codes(path: Path | None) -> dict[str, set[str]]:
    symbols: dict[str, set[str]] = {"HK": set(), "B": set()}
    if path:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                symbol = row["code"]
                market = row["share_class"]
                if market not in symbols or not symbol.isascii() or not symbol.isdigit():
                    raise ValueError("Supplemental identifiers must have HK/B share_class and numeric code")
                symbols[market].add(symbol)
    return symbols


def remaining_plan(capture: Path, extra_codes: Path | None) -> list[dict]:
    h, b = cross_codes(capture)
    extra = targeted_codes(extra_codes)
    h_filter = "Symbol in (" + ",".join(f"'{code}'" for code in sorted(h | extra["HK"])) + ")"
    b_filter = "Stkcd in (" + ",".join(f"'{code}'" for code in sorted(b | extra["B"])) + ")"
    plan = [
        job("STK_INDUSTRYCLASS", "InstitutionID Symbol IndustryClassificationID IndustryClassificationName "
            "ImplementDate IndustryCode IndustryName", condition="IndustryClassificationID in ('P0211','P0218')"),
        *sw_index_publication_plan(),
        job("CD_Dividend", "Stkcd Finyear Disye Schedu Ddadt Annopub Annocont Perspt Pertran Btperdiv Numsptr "
            "Numdiv Regdt Lastchgdt Exdistdt Paydt Divdt Trfojb Rank DistributionBaseShares", "1990-01-01", "2026-07-31"),
        *dated_jobs("IAR_Rept", "Stkcd Reptyp Accper Annodt Annopub Profita Profitb Asseta Assetb Erana Eranb",
                    [(2013, 2019), (2020, 2026)]),
        *dated_jobs("IAR_Forecdt", "Stkcd Accper Actudt", [(2013, 2019), (2020, 2026)]),
        *dated_jobs("FS_Combas", FINANCE_FIELDS["FS_Combas"], [(2018, 2022), (2023, 2026)], QEND_FILTER),
        *dated_jobs("FS_Comins", FINANCE_FIELDS["FS_Comins"], [(2018, 2022), (2023, 2026)], QEND_FILTER),
        *dated_jobs("FS_Comscfd", FINANCE_FIELDS["FS_Comscfd"], [(2017, 2022), (2023, 2026)], QEND_FILTER),
        job("STK_HK_CapitalChange", "InstitutionID SecurityID Symbol DeclareDate PrevShareCap CurrShareCap "
            "ChangeShare ChangeDate Reason", "2005-01-01", "2026-07-31", h_filter),
        job("STK_HK_InstitutionInfo", "InstitutionID SecurityID Symbol Name FullName ShareType ShareType2 ListedDate ISIN", condition=h_filter),
        *sw_index_composition_plan(),
        job("FE_Exrated", "Date Curcd C000001", "2014-01-01", "2026-07-31"),
        job("STK_HK_Divident", "InstitutionID SecurityID Symbol DeclareDate CATypeID TradeCurrency ExDate "
            "HKDDividend HKDSpecialDividend BonusShareRatio BonusShareTypeID BSPayDate RightsShareRatio Rank", "1999-01-01", "2026-07-31", h_filter),
        *dated_jobs("HK_STK_DQUOTE", "InstitutionID SecurityID TradingDate Filling Symbol OpenPrice ClosePrice Volume",
                    [(2014, 2017), (2018, 2021), (2022, 2025), (2026, 2026)], h_filter),
        *dated_jobs("TRD_Dalyr", "Stkcd Trddt Clsprc Adjprcwd Dnshrtrd Markettype Trdsta",
                    [(2014, 2018), (2019, 2023), (2024, 2026)], b_filter),
        *dated_jobs("FN_Fn044", "Stkcd Accper Typrep Fn04401 Fn04402 Fn04403 Fn04406 Fn04408 Fn04412 Fn04414",
                    [(2013, 2016), (2017, 2019), (2020, 2022), (2023, 2024), (2025, 2026)]),
        job("AIQ_LCFinRestatY", "Symbol Title RestatementObject RestatementYear DeclareDate RestatementType "
            "IsFinancialDataChange AdjustedAccountingItems", "2013-01-01", "2026-07-31"),
        job("TSR_Stkstat", "Stkcd Annctime Type Suspdate Susptime Resmdate Resmtime Timeperd Reason", "2014-01-01", "2026-07-31"),
    ]
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("initial", "remaining"))
    parser.add_argument("--capture", type=Path, default=RUNTIME / "capture")
    parser.add_argument("--cross-codes", type=Path, help="Optional independently verified share_class,code CSV")
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    plan = base_plan(args.capture) if args.phase == "initial" else remaining_plan(args.capture, args.cross_codes)
    dump_json(args.plan, plan)
    print(f"Saved {len(plan)} scoped queries")


if __name__ == "__main__":
    main()
