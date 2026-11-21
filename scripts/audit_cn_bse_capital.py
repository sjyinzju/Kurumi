"""Validate the disclosed 830799/920799 ordinary share changes and measure their potential reach."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

import duckdb
from audit_cn_market_denominator import attach_release, records

# These are observations from the archived statements, checked against the complete record bodies.
EVENTS = (
    ("AN202109171516798092", "2021-09-17", "2021-09-27", 140769250, "权益登记日"),
    ("AN202205271568235539", "2022-05-27", "2022-06-01", 210795000, "除权除息日"),
    ("AN202208181577348126", "2022-08-18", "2022-08-17", 210688500, "股份注销完成后"),
    ("AN202308181595072806", "2023-08-18", "2023-08-16", 210592500, "股份注销完成后"),
    ("AN202308231595538733", "2023-08-23", "2023-08-22", 210369300, "股份注销完成后"),
    ("AN202408231639428424", "2024-08-23", "2024-08-21", 209787550, "注销完成后"),
    ("AN202408301639625331", "2024-08-30", "2024-08-28", 209780050, "股份注销完成后"),
    ("AN202604141821196409", "2026-04-14", "2026-04-13", 209145400, "注销完成后"),
)
INSTRUMENT = "CN-830799.BJ"


def issuer_documents(root):
    locator = json.loads((root / "bse_eastmoney_originals_locator.json").read_bytes())
    urls = {
        notice["article_id"]: notice["detail_url"]
        for query in locator["probes"] for notice in query["selected"]
    }
    receipts = {
        row["article_id"]: row for row in json.loads((root / "bse_eastmoney_originals_body_receipt.json").read_bytes())
    }
    result = []
    for article, published, effective, shares, assertion in EVENTS:
        filename = root / f"{article}.json"
        payload = filename.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        notice = json.loads(payload)["data"]
        date_parts = tuple(map(int, effective.split("-")))
        compact_effective = "{}年{}月{}日".format(*date_parts)
        body = re.sub(r"\s+", "", notice["notice_content"])
        share_literal = f"{shares:,}"
        if (digest != receipts[article]["sha256"] or notice["art_code"] != article
                or notice["notice_date"][:10] != published or "艾融软件" not in notice["notice_title"]
                or {s["stock"] for s in notice["security"]} != {"830799", "920799"}
                or "已取消" in notice["notice_title"] or notice["page_size"] != 1
                or "上海艾融软件股份有限公司" not in body or compact_effective not in body
                or share_literal not in body or assertion not in body):
            raise ValueError(f"Issuer disclosure evidence changed: {article}")
        if result and f"{result[-1]['shares']:,}" not in body:
            raise ValueError(f"Published before-and-after share chain broke: {article}")
        can_use_after = date.fromisoformat(published) + timedelta(days=1)
        result.append({
            "announcement_id": article, "declared_effective": effective, "published_date": published,
            "vendor_index_time_local": notice["eitime"], "first_candidate_date": max(date.fromisoformat(effective), can_use_after),
            "shares": shares, "source_url": urls[article], "source_sha256": digest,
            "source_form": "issuer_statement_text_in_eastmoney_archive", "source_file": str(filename),
            "observed_at": receipts[article]["observed_at_utc"],
        })
    return result


def measured_reach(con, release, candidate_events, source_capital, instrument=INSTRUMENT, current_code="920799"):
    attach_release(con, release)
    con.read_json(source_capital.as_posix(), convert_strings_to_integers=False).create_view("source_capital")
    # The CSMAR history is an ex-post comparison with the announced values. Use its disagreements only in this audit.
    con.execute("""
        CREATE TEMP TABLE comparison AS
        SELECT Shrchgdt::DATE AS effective,
               CASE WHEN count(DISTINCT (Nshrttl,Nshrb,Nshrh,Nshrprf,Nshroft))=1
                          AND max(Nshrb)=0 AND max(Nshrh)=0 AND max(Nshrprf)=0 AND max(Nshroft)=0
                    THEN max(Nshrttl) END AS shares
        FROM source_capital WHERE Stkcd IN (?, ?) GROUP BY 1
    """, [instrument.removeprefix("CN-").removesuffix(".BJ"), current_code])
    con.execute("CREATE TEMP TABLE candidate_starts(effective DATE, available_on DATE, shares BIGINT)")
    con.executemany("INSERT INTO candidate_starts VALUES (?,?,?)", [
        (r["declared_effective"], r["first_candidate_date"], r["shares"]) for r in candidate_events
    ])
    return records(con, """
        WITH daily AS (
            SELECT s.local_trade_date,s.quote_valid,s.price_adj_factor,s.shares_outstanding_security,
                   s.security_market_cap_local, c.effective, c.available_on, c.shares AS archive_shares,
                   v.shares AS csmar_shares
            FROM stock_daily s ASOF LEFT JOIN candidate_starts c ON s.local_trade_date>=c.effective
            ASOF LEFT JOIN comparison v ON s.local_trade_date>=v.effective
            WHERE s.instrument_id=?
        )
        SELECT year(local_trade_date) AS year, count(*) AS security_days,
               count_if(security_market_cap_local>0) AS existing_cap_rows,
               count_if(archive_shares=csmar_shares AND local_trade_date>=available_on) AS crosschecked_candidates,
               count_if(archive_shares=csmar_shares AND local_trade_date>=available_on AND
                   quote_valid AND price_adj_factor>0 AND security_market_cap_local IS NULL) AS priced_cap_gaps_with_candidate,
               count_if(archive_shares IS NOT NULL AND archive_shares IS DISTINCT FROM csmar_shares) AS archive_vs_csmar_mismatch,
               count_if(archive_shares=csmar_shares AND local_trade_date<available_on) AS unavailable_at_cutoff
        FROM daily GROUP BY ALL ORDER BY 1
    """, [instrument])


def normalize_frozen_shares(out, evidence, candidates):
    official = {r["name"]: r for r in json.loads((evidence / "bse_issuer_probe_receipt.json").read_bytes())}
    anchor_names = ("830799_2022_rights_proposal", "830799_2022_annual", "830799_2022_H1_cninfo",
                    "830799_2023_financials", "830799_2023_financials", None, None, "920799_2026_creditors")
    rows = []
    for event, anchor_name in zip(candidates, anchor_names, strict=True):
        anchor = official[anchor_name] if anchor_name else None
        if anchor:
            pdf = (evidence / f"{anchor_name}.pdf").read_bytes()
            if not pdf.startswith(b"%PDF") or hashlib.sha256(pdf).hexdigest() != anchor["sha256"]:
                raise ValueError(f"Official companion proof changed: {anchor_name}")
        rows.append({
            "ts_code": "920799.BJ", "effective_from": event["declared_effective"],
            "published_at": event["published_date"], "observed_at": event["observed_at"],
            "shares_outstanding_security": event["shares"], "total_ordinary_shares": event["shares"],
            "single_share_class": True, "reporting_currency": "CNY", "share_precision_shares": 0,
            "shares_outstanding_b": 0, "shares_outstanding_h": 0,
            "source_url": event["source_url"], "source_sha256": event["source_sha256"],
            "source_version_id": event["announcement_id"], "source_form": event["source_form"],
            "knowledge_quality": "historical_original_evidence",
            "verification_rule": "published_implemented_unit_terms",
            "corroboration_url": anchor["url"] if anchor else None,
            "corroboration_sha256": anchor["sha256"] if anchor else None,
        })
    return verify_and_freeze(out, rows, candidates)


def verify_and_freeze(out, rows, candidates):
    import pyarrow as pa

    from kurumi.cn_pit import _effective_segments, _materialize, _with_provenance

    out.mkdir(parents=True, exist_ok=True)
    path = out / "share_versions.jsonl"
    with tempfile.TemporaryDirectory(dir=out) as folder:
        pending = Path(folder) / path.name
        pending.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        ledger = {}
        readback = _with_provenance(Path(folder), "share_versions", ledger)
        segments = list(_effective_segments(readback, "ts_code", (
            "shares_outstanding_security", "single_share_class", "reporting_currency",
        )))
        with duckdb.connect() as con:
            _materialize(con, "share_segments", segments, {
                "start_date": pa.date32(), "shares_outstanding_security": pa.float64(),
                "provenance_id": pa.string(),
            })
            eligible = con.execute("""
                SELECT start_date,shares_outstanding_security FROM share_segments
                WHERE provenance_id IS NOT NULL ORDER BY start_date
            """).fetchall()
        if len(ledger) != len(rows) or eligible != [(r["first_candidate_date"], r["shares"]) for r in candidates]:
            raise ValueError("Production PIT eligibility changed the original share timeline")
        pending.replace(path)
    return {"path": str(path), "source_rows": len(ledger), "runtime_segments": len(eligible),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--csmar-capital", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--normalized-dir", type=Path)
    args = parser.parse_args()
    release = args.release.resolve()
    candidates = issuer_documents(args.evidence.resolve())
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='1GB'")
        measured = measured_reach(con, release, candidates, args.csmar_capital.resolve())
    with args.csmar_capital.open("rb") as stream:
        comparison_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "dataset_version": json.loads((release / "manifest.json").read_bytes())["dataset_version"],
        "instrument_id": INSTRUMENT, "scope": "audited_candidate_overlap_not_published_training_rows",
        "source_csmar_sha256": comparison_sha256,
        "corroboration_detail": "CSMAR total matches the issuer archived share count with zero documented B,H,preferred,offshore shares; CSMAR used only for audit",
        "events": candidates, "coverage_by_year": measured,
    }
    if args.normalized_dir:
        result["normalized_share_versions"] = normalize_frozen_shares(
            args.normalized_dir.resolve(), args.evidence.resolve(), candidates,
        )
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(INSTRUMENT, sum(r["priced_cap_gaps_with_candidate"] or 0 for r in measured), "priced cap gaps with evidence")


if __name__ == "__main__":
    main()
