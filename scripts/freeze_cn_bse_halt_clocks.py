"""Verify the bounded same-day availability of two exchange halt facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path

import duckdb


def check_bytes(path, signature):
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != signature:
        raise ValueError(f"Published proof bytes changed: {path}")
    return body


def freeze(receipt, existing):
    result = []
    for fact in receipt["rows"]:
        code, day = fact["ts_code"], fact["effective_from"]
        article, notice = fact["public_news_proof"], fact["issuer_original"]
        available = datetime.fromisoformat(fact["public_fact_available_by"])
        if available.tzinfo is None or day != available.date().isoformat():
            raise ValueError(f"Missing local same-day public fact time for {code}")
        article_body = check_bytes(Path(article["file"]), article["source_sha256"]).decode("utf-8")
        title = re.search(r"<title>\s*(.+?)\s*</title>", article_body, re.S | re.I)
        if not (title and all(x in article_body for x in (
            fact["public_news_published_display"], article["verified_identity"], article["verified_content"]
        ))):
            raise ValueError(f"Original article content or clock missing for {code}")
        first = next(r for r in existing if r["ts_code"] == code and r["effective_from"] == day)
        if first["start_published_date"] != day or first["start_source_sha256"] != notice["sha256"]:
            raise ValueError(f"Primary issuer halt proof mismatch for {code}")
        if not check_bytes(Path(notice["file"]), notice["sha256"]).startswith(b"%PDF"):
            raise ValueError(f"Issuer halt original missing for {code}")
        chosen = notice.get("exchange_hosted_alternate")
        if chosen and not check_bytes(Path(chosen["file"]), chosen["source_sha256"]).startswith(b"%PDF"):
            raise ValueError(f"Exchange-hosted issuer original is not a PDF for {code}")
        raw_url = chosen["source_url"] if chosen else first["start_source_url"]
        raw_sha = chosen["source_sha256"] if chosen else first["start_source_sha256"]
        row = first | {
            "start_source_url": raw_url, "start_source_sha256": raw_sha,
            "effective_to_exclusive": (date.fromisoformat(day) + timedelta(days=1)).isoformat(),
            "end_event": "source_clock_proof_interval_end",
            "end_published_date": day, "end_source_id": first["start_source_id"],
            "end_source_url": raw_url, "end_source_sha256": raw_sha,
            "public_fact_available_by": available.isoformat(), "public_fact_source_url": article["source_url"],
            "public_fact_source_sha256": article["source_sha256"],
            "public_fact_source_title": unescape(" ".join(title.group(1).split())),
            "public_fact_time_precision": fact["public_news_time_precision"],
        }
        result.append(row)
    return result


def replay(con, release, registry, additions):
    con.read_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet")).create_view("stock")
    for name in ("security_history", "calendars", "quote_provenance"):
        con.read_parquet(str(release / "reference" / f"{name}.parquet")).create_view(name)
    con.execute("CREATE TABLE required(ts_code VARCHAR, trade_date DATE, first_available TIMESTAMPTZ)")
    con.executemany("INSERT INTO required VALUES (?,?,?)", [
        (r["ts_code"], r["effective_from"], r["public_fact_available_by"]) for r in additions
    ])
    result = con.sql("""
        SELECT s.ts_code,s.local_trade_date,s.asof_utc,r.first_available
        FROM required r JOIN stock s ON r.ts_code=s.ts_code AND r.trade_date=s.local_trade_date
        JOIN calendars c USING(exchange,local_trade_date)
        LEFT JOIN quote_provenance p ON s.provenance_id=p.provenance_id
        WHERE s.exchange='BSE' AND s.suspension_reported AND NOT s.suspension_verified
          AND s.trading_status='unknown' AND NOT s.quote_valid AND s.close_raw IS NULL AND p.daily_batch IS NULL
          AND r.first_available<=s.asof_utc
        ORDER BY 1
    """).fetchall()
    if len(result) != len(additions):
        raise ValueError(f"Same-day evidence missing from released open-session data: {result}")
    registered = registry.resolve().as_posix().replace("'", "''")
    con.execute(f"ATTACH '{registered}' AS quant (READ_ONLY)")
    months = sorted({r["effective_from"][:7].replace("-", "/") for r in additions})
    paths = con.execute("""
        SELECT path FROM quant.canonical_parts
        WHERE active AND endpoint='daily' AND partition_key IN (SELECT unnest(?))
    """, [months]).fetchall()
    con.read_parquet([p for (p,) in paths], union_by_name=True).create_view("daily_sources")
    raw = con.sql("""
        SELECT d.ts_code,d.trade_date,d.close FROM required r JOIN security_history h USING(ts_code)
        JOIN daily_sources d ON d.trade_date=strftime(r.trade_date,'%Y%m%d')
          AND d.ts_code IN (h.ts_code,h.prior_code)
    """).fetchall()
    if raw:
        raise ValueError(f"Existing canonical raw quotes conflict with proposed halt: {raw}")
    return {"verified_no_quote_sessions": result, "canonical_quote_parts_scanned": len(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    existing = json.loads(args.existing.read_text(encoding="utf-8"))
    if args.release.name != receipt["baseline_dataset_version"]:
        raise ValueError("Release does not match the source clock evidence")
    additions = freeze(receipt, existing)
    with duckdb.connect(config={"threads": "2", "memory_limit": "2GB"}) as con:
        proof = replay(con, args.release, args.registry, additions)
    for name, content in (
        ("suspension_same_day_v4_additions.json", additions),
        ("suspension_same_day_v4_audit.json", {
            "dataset_version": args.release.name, "source_receipt": str(args.receipt), **proof,
        }),
    ):
        path = args.receipt.parent / name
        temporary = path.with_suffix(".partial")
        temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)
    print(len(additions))


if __name__ == "__main__":
    main()
