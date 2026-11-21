"""Verify issuer evidence and exact calendar joins for the remaining BSE halts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import duckdb

# Each choice was traced to exact archived issuer language and to the next open session.
NOTICES = {
    ("920023", "2026-04-29"): ("12260367", "12260367"),
    ("920039", "2023-03-01"): ("8855391", "8876140", "8870897"),
    ("920058", "2026-05-13"): ("12314050", "12354574", "12335064"),
    ("920090", "2023-08-02"): ("9383138", "9394300"),
    ("920090", "2026-04-23"): ("12153985", "12153985"),
    ("920171", "2023-11-28"): ("9665644", "9674038"),
    ("920174", "2024-11-26"): ("10609996", "10637207", "10623399"),
    ("920198", "2023-12-04"): ("9676009", "9692807"),
    ("920239", "2022-01-24"): ("7801599", "7825882", "7817508"),
    ("920263", "2021-12-21"): ("7731206", "7767119", "7748168"),
    ("920305", "2025-04-30"): ("11081900", "11081900"),
    ("920305", "2025-07-07"): ("11223986", "11235005"),
    ("920305", "2026-02-05"): ("11952275", "11963154"),
    ("920305", "2026-04-30"): ("920305_20260429_start", "920305_20260701_resume"),
    ("920415", "2021-12-24"): ("7740372", "7775606", "7758706"),
    ("920415", "2022-07-25"): ("8377859", "8391472"),
    ("920526", "2023-11-28"): ("9665645", "9674039"),
    ("920575", "2026-04-30"): ("920575_20260429_halt_and_resume", "920575_20260429_halt_and_resume"),
    ("920641", "2025-12-31"): ("11890731", "11906576"),
    ("920675", "2026-06-08"): ("12377635", "12405498", "12390725"),
    ("920685", "2026-07-16"): ("12447634", "12467944", "12457904"),
    ("920753", "2023-07-17"): ("9351293", "9368993", "9363336"),
    ("920808", "2025-05-26"): ("11140937", "11171872", "11155652"),
    ("920856", "2023-10-16"): ("9568891", "9600841", "9579131"),
    ("920961", "2025-09-16"): ("11458255", "11473453"),
    ("920964", "2024-10-22"): ("10533790", "10545778", "10543120"),
}
HDR = re.compile(r"公告编号[:：]([0-9]{4}-[0-9]+)")
SECURITY = re.compile(r"证券代码[:：](\d{6})")
VISUAL_REVIEW = {
    "9394300": {"file": "920090_9394300_page-2.png",
                "transcription": "证券代码:430090公告编号:2023-079本公司股票自2023年8月9日起复牌。2023年8月8日"},
}


def cn_date(value):
    day = date.fromisoformat(value)
    return f"{day.year}年{day.month}月{day.day}日"


def verify_pdf(path, checksum):
    payload = path.read_bytes()
    if not payload.startswith(b"%PDF") or hashlib.sha256(payload).hexdigest() != checksum:
        raise ValueError(f"Original issuer PDF missing or changed: {path}")


def source_document(root, discovered, agent_code, key):
    if key.isdigit():
        doc = discovered[agent_code, key]
        proof = doc["original"]
        path = Path(doc["local_pdf"])
        text = Path(doc["local_text"]).read_text(encoding="utf-8")
        published = doc["published_at"]
    else:
        path = root / "direct_sources" / f"{key}.pdf"
        proof = json.loads(path.with_name(path.name + ".receipt.json").read_text(encoding="utf-8"))
        text = path.with_suffix(".txt").read_text(encoding="utf-8")
        published = date.fromisoformat(proof["source_url"].split("/")[-2]).isoformat()
    verify_pdf(path, proof["source_sha256"])
    if key in VISUAL_REVIEW:
        inspection = VISUAL_REVIEW[key]
        if text.strip() or not (path.parent / inspection["file"]).is_file():
            raise ValueError(f"Visual review inputs differ for {path}")
        text = inspection["transcription"]
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    identifier = HDR.search(text)
    if not identifier:
        raise ValueError(f"Missing issuer document identifier for {path}")
    return {
        "published": published, "text": text, "id": identifier.group(1), "file": str(path),
        "sha256": proof["source_sha256"], "source_url": proof["source_url"], "observed_at": proof["observed_at"],
        "visual_review": VISUAL_REVIEW.get(key),
    }


def segment(code, start, exclusive_end, begin, finish, kind):
    return {
        "ts_code": code, "effective_from": start, "effective_to_exclusive": exclusive_end, "state": "suspended",
        "end_event": kind, "start_published_date": begin["published"], "end_published_date": finish["published"],
        "start_source_id": code[:6] + "-" + begin["id"], "end_source_id": code[:6] + "-" + finish["id"],
        "start_source_url": begin["source_url"], "end_source_url": finish["source_url"],
        "start_source_sha256": begin["sha256"], "end_source_sha256": finish["sha256"],
        "observed_on": min(begin["observed_at"], finish["observed_at"])[:10],
    }


def normalize(root, spans):
    discovery = json.loads((root / "halt_disclosure_discovery.json").read_text(encoding="utf-8"))
    discovered = {(r["code"], Path(d["local_pdf"]).stem.split("_")[-1]): d
                  for r in discovery for d in r["documents"] if "local_pdf" in d}
    records, proof, excluded = [], [], []
    for span in spans:
        stable = span["ts_code"]
        code, first, resume = stable[:6], span["start"], span["next_open"]
        if code == "920680":
            continue
        originals = [source_document(root, discovered, code, key) for key in NOTICES[code, first]]
        for item in originals:
            if not set(SECURITY.findall(item["text"])) & set(span["source_symbols"] + [code]):
                raise ValueError(f"Ticker identity missing from {item['file']}")
        initial, terminal = originals[:2]
        start_date, end_date = cn_date(first), cn_date(resume)
        if not (re.search(re.escape(start_date) + r"[^。]{0,20}停牌", initial["text"])
                and re.search(re.escape(end_date) + r"[^。]{0,25}复牌", terminal["text"])
                and initial["published"] <= first and terminal["published"] < resume):
            raise ValueError(f"Unverified effective start/resumption for {stable} {first} {resume}")
        uncovered = [d for d in span["dates"] if d <= initial["published"]]
        excluded.extend({"ts_code": stable, "date": d, "reason": "same_day_original_without_exact_release_clock",
                         "observed_start_source_sha256": initial["sha256"]} for d in uncovered)
        if len(originals) == 2:
            if span["sessions"] > 5 and code != "920305":
                raise ValueError(f"Long non-regulatory halt has no continuing issuer disclosure: {stable}")
            records.append(segment(stable, first, resume, initial, terminal, "listing_resumed"))
        else:
            bridge = originals[2]
            continuation = span["dates"][3 if code == "920964" else 5]
            if not (bridge["published"] < continuation and start_date in bridge["text"]
                    and ("继续停牌" in bridge["text"] or "将延期复牌" in bridge["text"])):
                raise ValueError(f"Missing contemporaneous continuation notice for {stable} {continuation}")
            records.append(segment(stable, first, continuation, initial, bridge, "suspension_extended"))
            records.append(segment(stable, continuation, resume, bridge, terminal, "listing_resumed"))
        proof.append({"ts_code": stable, "start": first, "resume": resume, "sessions": span["sessions"],
                      "originals": [{k: v for k, v in n.items() if k != "text"} for n in originals]})
    return records, proof, excluded


def replay(con, release, registry, spans, records, excluded):
    con.read_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock")
    for name in ("security_history", "quote_provenance", "calendars"):
        con.read_parquet(str(release / "reference" / f"{name}.parquet")).create_view(name)
    con.execute("CREATE TABLE ranges(ts_code VARCHAR, first DATE, until DATE)")
    con.executemany("INSERT INTO ranges VALUES (?,?,?)", [
        (r["ts_code"], max(date.fromisoformat(r["effective_from"]),
                           date.fromisoformat(r["start_published_date"])+timedelta(days=1)), r["effective_to_exclusive"])
        for r in records
    ])
    con.execute("""
        CREATE TEMP TABLE replayed AS
        SELECT h.ts_code,h.instrument_id,c.local_trade_date
        FROM ranges r JOIN security_history h USING(ts_code) JOIN calendars c USING(exchange)
        WHERE c.exchange='BSE' AND c.local_trade_date>=greatest(r.first,h.listing_date)
          AND c.local_trade_date<least(r.until,coalesce(h.delisting_date,DATE '9999-12-31'))
    """)
    keys = [(code, str(day)) for code, day in con.sql("SELECT ts_code,local_trade_date FROM replayed").fetchall()]
    wanted = {(r["ts_code"], d) for r in spans for d in r["dates"]} - {(r["ts_code"], r["date"]) for r in excluded}
    if len(keys) != len(wanted) or set(keys) != wanted:
        raise ValueError(f"Replay has omitted or unexpected candidate sessions: {set(keys) ^ wanted}")
    unmatched = con.sql("""
        SELECT r.ts_code,r.local_trade_date FROM replayed r LEFT JOIN stock s USING(instrument_id,local_trade_date)
        LEFT JOIN quote_provenance p USING(provenance_id)
        WHERE NOT coalesce(s.suspension_reported,false) OR coalesce(s.suspension_verified,false)
           OR coalesce(s.quote_valid,false) OR s.close_raw IS NOT NULL OR p.daily_batch IS NOT NULL
           OR s.trading_status IS DISTINCT FROM 'unknown'
    """).fetchall()
    if unmatched:
        raise ValueError(f"Release has quotes or incompatible source states on claimed full halt dates: {unmatched}")
    con.execute(f"ATTACH '{registry.resolve().as_posix().replace(chr(39), chr(39)*2)}' AS quant (READ_ONLY)")
    months = sorted({day[:7].replace("-", "/") for _, day in keys})
    paths = con.execute("""
        SELECT path FROM quant.canonical_parts
        WHERE active AND endpoint='daily' AND partition_key IN (SELECT unnest(?))
    """, [months]).fetchall()
    con.read_parquet([p for (p,) in paths], union_by_name=True).create_view("daily_sources")
    raw = con.sql("""
        SELECT d.ts_code,d.trade_date,d.close FROM replayed r
        JOIN security_history h USING(instrument_id,ts_code)
        JOIN daily_sources d ON d.trade_date=strftime(r.local_trade_date,'%Y%m%d')
          AND d.ts_code IN (h.ts_code,h.prior_code)
    """).fetchall()
    if raw:
        raise ValueError(f"Registered raw quote rows found on proposed suspension dates: {raw}")
    con.execute("CREATE TABLE resumptions(ts_code VARCHAR, trade_date DATE)")
    con.executemany("INSERT INTO resumptions VALUES (?,?)", [(r["ts_code"], r["next_open"]) for r in spans])
    resume_mismatch = con.sql("""
        SELECT r.ts_code,r.trade_date FROM resumptions r LEFT JOIN stock s
          ON s.ts_code=r.ts_code AND s.exchange='BSE' AND s.local_trade_date=r.trade_date
        WHERE NOT coalesce(s.quote_valid,false) OR NOT coalesce(s.close_raw>0,false)
    """).fetchall()
    if resume_mismatch:
        raise ValueError(f"Official resumption did not match real release quote: {resume_mismatch}")
    return {"verified_sessions": len(keys), "active_quote_parts_scanned": len(paths),
            "traded_resume_sessions": len(spans), "reported_only_after": len(excluded)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--additional-issuer", type=Path, required=True)
    args = parser.parse_args()
    root = args.directory
    inventory = json.loads((root / "reported_only_bse_halt_spans.json").read_text(encoding="utf-8"))
    if args.release.name != inventory["dataset_version"]:
        raise ValueError("Official suspension discovery and released prices refer to different versions")
    records, evidence, excluded = normalize(root, inventory["spans"])
    extension = json.loads(args.additional_issuer.read_text(encoding="utf-8"))
    records.extend(extension)
    records.sort(key=lambda row: (row["ts_code"], row["effective_from"]))
    with duckdb.connect(config={"threads": "2", "memory_limit": "2GB"}) as con:
        validation = replay(con, args.release, args.registry, inventory["spans"], records, excluded)
    for name, data in (
        ("suspension_remaining_v4_additions.json", records),
        ("suspension_remaining_v4_audit.json", {"dataset_version": args.release.name,
                                             "source_intervals": len(records), "original_proofs": evidence,
                                             "additional_issuer_source": str(args.additional_issuer),
                                             "additional_issuer_sha256": hashlib.sha256(
                                                 args.additional_issuer.read_bytes()).hexdigest(),
                                             "excluded": excluded, "replay": validation}),
    ):
        path = root / name
        partial = path.with_suffix(".partial")
        partial.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        partial.replace(path)
    print(json.dumps(validation))


if __name__ == "__main__":
    main()
