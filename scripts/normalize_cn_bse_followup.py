"""Normalize audited BSE issuer share records from preserved primary statement originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
from audit_cn_bse_capital import measured_reach, verify_and_freeze

DATANG = (
    ("AN202111121528574702", "2021-11-12", "2021-11-12", 145315601, 145265601),
    ("AN202205241567601897", "2022-05-24", "2022-05-31", 145265601, 261478081),
    ("AN202207281576639626", "2022-07-28", "2022-07-27", 261478081, 261046081),
    ("AN202210191579280910", "2022-10-19", "2022-10-18", 261046081, 261017281),
    ("AN202307121592211199", "2023-07-12", "2023-07-11", 261017281, 258790681),
    ("836433_2023_cancel_exact", "2023-10-25", "2023-10-24", 258790681, 258777181),
    ("836433_2024_cancel_exact", "2024-05-27", "2024-05-23", 258777181, 255919681),
)
DEYUAN = (
    ("AN202109081515011274", "2021-09-08", "2021-08-31", 62458000, 65286000),
    ("AN202206231574236741", "2022-06-23", "2022-06-21", 65286000, 65250500),
    ("AN202210241579409058", "2022-10-24", "2022-10-20", 65250500, 65240500),
    ("AN202305081586365597", "2023-05-08", "2023-05-17", 65240500, 78288600),
    ("2023-06-15_sina", "2023-06-15", "2023-06-13", 78288600, 78275640),
    ("2023-10-19_sina", "2023-10-19", "2023-10-17", 78275640, 78245040),
    ("2024-10-31_sina", "2024-10-31", "2024-10-29", 78245040, 78210660),
    ("832735_2025_distribution", "2025-05-21", "2025-05-29", 78210660, 117315990),
    ("920735_2026_distribution", "2026-04-20", "2026-04-29", 117315990, 129047589),
)


def publisher_pdf(root, receipts, identifier):
    from pypdf import PdfReader

    record = receipts[identifier]
    path = root / f"{identifier}.pdf"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record["sha256"] or not record["is_pdf"] or record["status"] != 200:
        raise ValueError(f"Invalid original {identifier}")
    document = PdfReader(path)
    text = "\n".join(page.extract_text(extraction_mode="layout") for page in document.pages)
    return record["url"], digest, record["observed_at"], "publisher_pdf", str(path), text


def mirrored_notice(root, identifier, known_date, old_code, current_code):
    path, = (root / "original_responses").glob(f"{identifier}-*.response.json")
    request = path.with_suffix("").with_suffix(".json")
    record = json.loads(request.read_bytes())
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    details = json.loads(raw)["data"]
    if (digest != record["response_sha256"] or details["art_code"] != identifier
            or details["notice_date"][:10] != known_date or details["page_size"] != 1
            or {s["stock"] for s in details["security"]} != {old_code, current_code}
            or "已取消" in details["notice_title"]):
        raise ValueError(f"Invalid mirror edition {identifier}")
    observed_at = record.get("observed_at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return record["request_url"], digest, observed_at, "issuer_statement_text_in_eastmoney_archive", str(path), details["notice_content"]


def compact(text):
    return re.sub(r"[\s,，]", "", text)


def cn_date(value):
    d = date.fromisoformat(value)
    return rf"{d.year}年0?{d.month}月0?{d.day}日"


def check_total(text, amount):
    return re.search(rf"(?<!\d){amount}(?!\d)", text) is not None


def datang_rows(root):
    exact = {r["name"]: r for r in json.loads((root / "publisher_exact_receipt.json").read_bytes())}
    official = {r["name"]: r for r in json.loads((root / "publisher_originals_receipt.json").read_bytes())}
    return statement_rows(root, DATANG, "836433", "920433", "内蒙古大唐药业股份有限公司",
                          {key: (root, exact) for key in exact}, publisher_pdf(root, official, "836433_2024h1"),
                          255919681)


def deyuan_rows(root):
    peer = root.parent / "deyuan_support"
    official = {r["name"]: r for r in json.loads((root / "deyuan_publisher_receipt.json").read_bytes())}
    mirror = {}
    for row in json.loads((peer / "deyuan_originals_receipt.json").read_bytes()):
        raw = row["pdfs"][0]
        identifier = Path(raw["file"]).stem
        mirror[identifier] = raw | {"is_pdf": raw["verified"]}
    archives = {key: (root, official) for key in official} | {key: (peer, mirror) for key in mirror}
    return statement_rows(root, DEYUAN, "832735", "920735", "江苏德源药业股份有限公司",
                          archives, publisher_pdf(root, official, "832735_2023H1"), 78275640)


def statement_rows(root, events, old_code, new_code, issuer, archives, share_scope, confirmed_scope_count):
    class_url, class_hash, _, _, class_path, class_text = share_scope
    if "普通股股本结构" not in compact(class_text) or not check_total(compact(class_text), confirmed_scope_count):
        raise ValueError(f"Ordinary-class scope absent from the exchange filing for {issuer}")
    result = []
    for identifier, published, effective, before, after in events:
        source = (mirrored_notice(root, identifier, published, old_code, new_code) if identifier.startswith("AN")
                  else publisher_pdf(*archives[identifier], identifier))
        url, digest, observed_at, form, path, text = source
        body = compact(text)
        quantities = re.sub(r"[,，]", "", text)
        if (issuer not in body or (old_code not in body and new_code not in body)
                or re.search(cn_date(effective), body) is None or re.search(cn_date(published), body) is None
                or not check_total(quantities, before) or not check_total(quantities, after)
                or "股本" not in body or not any(t in body for t in ("实施公告", "注销完成", "完成工商变更"))):
            raise ValueError(f"Share effect or amounts unverified in {identifier}")
        if result and result[-1]["shares"] != before:
            raise ValueError(f"Ordinary-share version chain is discontinuous before {identifier}")
        result.append({
            "announcement_id": identifier, "declared_effective": effective, "published_date": published,
            "first_candidate_date": max(date.fromisoformat(effective), date.fromisoformat(published)+timedelta(days=1)),
            "prior_shares": before, "shares": after, "source_url": url, "source_sha256": digest,
            "source_form": form, "source_file": path, "observed_at": observed_at,
            "corroboration_url": class_url, "corroboration_sha256": class_hash, "class_scope_file": class_path,
        })
    return result


def tongxiang_rows(root, equity_archive):
    sibling = root.parent / "tongxiang_support"
    archived = {r["name"].removesuffix(".pdf"): r for r in
                json.loads((sibling / "sina_attachments_and_nearby_receipt.json").read_bytes())}
    receipt_080, = [r for r in json.loads((sibling / "sina_exact_080_receipt.json").read_bytes()) if r["id"] == 10266290]
    archived["sina_2024_detail_10266290"] = {
        "url": receipt_080["pdf_url"], "status": receipt_080["pdf_status"], "sha256": receipt_080["pdf_sha256"],
        "is_pdf": receipt_080["pdf_valid"], "observed_at": receipt_080["observed_at"],
    }
    original = {r["name"]: r for r in json.loads((root / "publisher_retry_receipt.json").read_bytes())}
    source = (
        ("2021Q3", "2021-10-27", "2021-09-30", 103320000, "普通股股本结构", 103320000,
         publisher_pdf(sibling, archived, "sina_2021Q3_vip")),
        ("2022-074", "2022-09-21", "2022-09-28", 109320000, "发行新增股票将于", 6000000,
         mirrored_notice(root, "AN202209211578562122", "2022-09-21", "839167", "920167")),
        ("2024-080", "2024-06-07", "2024-06-12", 109706125, "股票登记日", 386125,
         publisher_pdf(sibling, archived, "sina_2024_detail_10266290")),
        ("2026-001", "2026-01-15", "2026-01-22", 110026500, "股票登记日", 320375,
         publisher_pdf(root, original, "920167_2026_option_result")),
    )
    q3_hash = source[0][-1][1]
    charter = publisher_pdf(sibling, archived, "sina_2024-082_vip")
    if not all(check_total(compact(charter[-1]), count) for count in (109320000,109706125)):
        raise ValueError("Tongxiang contemporaneous charter did not corroborate option exercise")
    previous = 0
    result = []
    for version, known, effective, shares, concept, increase, info in source:
        url, digest, observed, form, path, text = info
        body = compact(text)
        if (not re.search(r"同享[（(]苏州[)）]电子材料科技股份有限公司", body)
                or ("839167" not in body and "920167" not in body)
                or re.search(cn_date(effective), body) is None or concept not in body
                or not check_total(body, increase) or shares != previous+increase
                or (version != "2022-074" and not check_total(body, shares))):
            raise ValueError(f"Tongxiang ordinary share chain not verified in {version}")
        if version == "2024-080" and not check_total(body, previous):
            raise ValueError("Missing ordinary share basis in 2024-080")
        result.append({
            "announcement_id": version, "declared_effective": effective, "published_date": known,
            "first_candidate_date": max(date.fromisoformat(effective), date.fromisoformat(known)+timedelta(days=1)),
            "prior_shares": previous or None, "shares": shares, "source_url": url, "source_sha256": digest,
            "source_form": form, "source_file": path, "observed_at": observed,
            "corroboration_url": charter[0] if version == "2024-080" else source[0][-1][0],
            "corroboration_sha256": charter[1] if version == "2024-080" else q3_hash,
        })
        previous = shares
    with duckdb.connect() as con:
        con.read_parquet(equity_archive.as_posix()).create_view("vendor")
        compared = con.execute("""
            SELECT END_DATE::DATE,TOTAL_SHARES FROM vendor WHERE SECUCODE='920167.BJ'
            AND (END_DATE::DATE IN ('2022-09-28','2024-06-12','2026-01-22'))
            AND coalesce(LISTED_A_SHARES,0)+coalesce(LIMITED_A_SHARES,0)=TOTAL_SHARES
            ORDER BY END_DATE
        """).fetchall()
    if compared != [(date.fromisoformat(row["declared_effective"]), row["shares"]) for row in result[1:]]:
        raise ValueError("Independent date-scoped ordinary share archive conflicts with issuer statements")
    return result


def frozen_rows(code, events):
    return [{
        "ts_code": code, "effective_from": event["declared_effective"],
        "published_at": event["published_date"], "observed_at": event["observed_at"],
        "shares_outstanding_security": event["shares"], "total_ordinary_shares": event["shares"],
        "single_share_class": True, "reporting_currency": "CNY", "share_precision_shares": 0,
        "shares_outstanding_b": 0, "shares_outstanding_h": 0,
        "source_url": event["source_url"], "source_sha256": event["source_sha256"],
        "source_version_id": event["announcement_id"], "source_form": event["source_form"],
        "knowledge_quality": "historical_original_evidence", "verification_rule": "published_implemented_unit_terms",
        "corroboration_url": event["corroboration_url"], "corroboration_sha256": event["corroboration_sha256"],
    } for event in events]


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("release", type=Path)
    cli.add_argument("--evidence", required=True, type=Path)
    cli.add_argument("--csmar-capital", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--issuer", choices=("920433", "920167", "920735"), default="920433")
    cli.add_argument("--eastmoney-capital", type=Path)
    args = cli.parse_args()
    if args.issuer == "920167":
        if args.eastmoney_capital is None:
            cli.error("Tongxiang requires the date-scoped equity candidate archive for event date corroboration")
        events = tongxiang_rows(args.evidence.resolve(), args.eastmoney_capital.resolve())
        instrument = "CN-839167.BJ"
    elif args.issuer == "920735":
        events = deyuan_rows(args.evidence.resolve())
        instrument = "CN-832735.BJ"
    else:
        events = datang_rows(args.evidence.resolve())
        instrument = "CN-836433.BJ"
    with duckdb.connect() as con:
        con.execute("SET threads=2; SET memory_limit='1GB'")
        coverage = measured_reach(con, args.release.resolve(), events, args.csmar_capital.resolve(),
                                  instrument=instrument, current_code=args.issuer)
    summary = {
        "dataset_version": json.loads((args.release / "manifest.json").read_bytes())["dataset_version"],
        "instrument_id": instrument, "events": events, "coverage_by_year": coverage,
        "normalized_share_versions": verify_and_freeze(args.output.resolve(), frozen_rows(args.issuer+".BJ", events), events),
    }
    (args.output / f"{args.issuer}_capital_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, default=str, indent=2)+"\n", encoding="utf-8",
    )
    print(instrument, sum(row["priced_cap_gaps_with_candidate"] or 0 for row in coverage), "priced cap gaps with evidence")


if __name__ == "__main__":
    main()
