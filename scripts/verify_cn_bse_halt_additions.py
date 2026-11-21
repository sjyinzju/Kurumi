"""Replay additive BSE transfer halts against listing lifecycles and raw quote evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

RULES = [
    "https://www.bse.cn/cxjg_list/200010908.html",
    "https://www.investor.org.cn/information_release/news_release_from_authorities/hsjysfb/202111/P020211103382354669312.pdf",
    "https://www.bse.cn/cxjg_list/200011821.html",
]
SCHEMA = ("ts_code", "state", "effective_from", "effective_to_exclusive", "end_event",
          "start_published_date", "end_published_date", "start_source_id", "end_source_id",
          "start_source_url", "end_source_url", "start_source_sha256", "end_source_sha256",
          "observed_on", "delisting_date")


def verified_sources(path):
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        if row["effective_to_exclusive"] != row["delisting_date"] or row["state"] != "suspended":
            raise ValueError("Unexpected lifecycle event in the BSE transfer halt evidence")
        for side, effective in (("start", row["effective_from"]), ("end", row["effective_to_exclusive"])):
            record = row[side + "_pdf"]
            payload = (path.parent / record["file"]).read_bytes()
            if (not payload.startswith(b"%PDF") or record["status"] != 200 or len(payload) != record["bytes"]
                    or record["sha256"] != hashlib.sha256(payload).hexdigest()
                    or record["sha256"] != row[side + "_source_sha256"]
                    or record["final_url"] != row[side + "_source_url"]
                    or row[side + "_published_date"] > effective):
                raise ValueError(f"Invalid original {side} issuer evidence for {row['ts_code']}")
    return rows


def replay(con, root, registry, rows, existing):
    for name in ("security_history", "quote_provenance", "calendars"):
        con.read_parquet(str(root / "reference" / (name + ".parquet"))).create_view(name)
    stock = root / "stock_daily" / "market_id=CN"
    con.read_parquet(str(stock / "year=*" / "*.parquet")).create_view("stock")
    normalized = {row["ts_code"]: {k: row[k] for k in SCHEMA} for row in rows}
    existing_codes = {r["ts_code"] for r in existing}
    if set(normalized) & existing_codes:
        raise ValueError("An official suspension candidate duplicates an already represented security")
    con.execute("CREATE TEMP TABLE halts(ts_code VARCHAR PRIMARY KEY, known_from DATE, until DATE)")
    con.executemany("INSERT INTO halts VALUES (?,?,?)", [
        (r["ts_code"], max(date.fromisoformat(r["effective_from"]),
                           date.fromisoformat(r["start_published_date"]) + timedelta(days=1)), r["effective_to_exclusive"])
        for r in rows
    ])
    con.execute("""
        CREATE TEMP TABLE expected AS
        SELECT h.ts_code,c.local_trade_date,h.instrument_id
        FROM halts e JOIN security_history h USING(ts_code) JOIN calendars c USING(exchange)
        WHERE c.exchange='BSE' AND e.until=h.delisting_date
         AND c.local_trade_date>=greatest(e.known_from,h.listing_date)
         AND c.local_trade_date<e.until;
    """)
    partitions = con.execute(f"""
        ATTACH '{registry.resolve().as_posix().replace("'", "''")}' AS quant (READ_ONLY);
        SELECT path FROM quant.canonical_parts WHERE active AND endpoint='daily'
         AND partition_key BETWEEN '2021/11' AND '2022/07'
    """).fetchall()
    if not partitions:
        raise ValueError("Cannot verify against the active raw quote inventory")
    con.read_parquet([path for (path,) in partitions], union_by_name=True).create_view("canonical_daily")
    canonical = con.sql("""
        SELECT e.ts_code,count(*),count_if(d.close>0 AND isfinite(d.close))
        FROM expected e JOIN security_history h USING(instrument_id,ts_code)
        JOIN canonical_daily d ON d.trade_date=strftime(e.local_trade_date,'%Y%m%d')
          AND d.ts_code IN (h.ts_code,h.prior_code)
        GROUP BY e.ts_code
    """).fetchall()
    if canonical:
        raise ValueError(f"Published archive contains quote rows within claimed full-session halts: {canonical}")
    report = {}
    for result in con.sql("""
        SELECT e.ts_code, count(*) AS sessions, min(e.local_trade_date),max(e.local_trade_date),
               count(s.local_trade_date) AS stock_rows, count_if(coalesce(s.close_raw>0 OR s.quote_valid,false)),
               count_if(p.daily_batch IS NOT NULL), count_if(s.suspension_reported),
               count_if(s.suspension_verified),count_if(s.input_valid),
               count_if(s.price_adj_factor>0 AND isfinite(s.price_adj_factor)), count_if(s.trading_status='unknown')
        FROM expected e
        LEFT JOIN stock s ON s.exchange='BSE' AND s.local_trade_date BETWEEN DATE '2021-11-15' AND DATE '2022-07-31'
         AND s.instrument_id=e.instrument_id AND s.local_trade_date=e.local_trade_date
        LEFT JOIN quote_provenance p USING(provenance_id)
        GROUP BY e.ts_code ORDER BY e.ts_code
    """).fetchall():
        code, count, first, last, stock_rows, quotes, daily_batches, reported, verified, samples, factors, unknown = result
        if (quotes or daily_batches or verified or samples
                or not stock_rows == count == factors == unknown or not count):
            raise ValueError(f"{code} fails independently replayed halt and raw quote checks: {result}")
        report[code] = {"sessions": count, "first_open_session": str(first), "last_open_session": str(last),
                        "raw_factor_rows": factors, "positive_actual_quotes": quotes, "daily_quote_batches": daily_batches,
                        "input_valid_rows": samples, "verified_suspensions_before": verified,
                        "verified_suspensions_after": count, "reported_suspensions_before": reported,
                        "reported_suspensions_after": count}
    if set(report) != set(normalized):
        raise ValueError("The published security/lifecycle grid is incomplete for BSE transfer halt candidates")
    totals = con.sql("""
        SELECT count_if(exchange='BSE' AND suspension_reported),count_if(exchange='BSE' AND suspension_verified),
               count_if(suspension_reported),count_if(suspension_verified) FROM stock
    """).fetchone()
    addition = sum(r["sessions"] for r in report.values())
    reported_addition = sum(r["reported_suspensions_after"] - r["reported_suspensions_before"] for r in report.values())
    return list(normalized.values()), {
        "per_security": report, "projected_addition": addition,
        "active_legacy_daily_parts_scanned": len(partitions),
        "all_stock_days_baseline": {
            "BSE": {"reported": totals[0], "verified": totals[1]},
            "CN": {"reported": totals[2], "verified": totals[3]},
        },
        "all_stock_days_with_projected_additions": {
            "BSE": {"reported": totals[0]+reported_addition, "verified": totals[1]+addition},
            "CN": {"reported": totals[2]+reported_addition, "verified": totals[3]+addition},
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = verified_sources(args.source)
    existing = json.loads(args.existing.read_text(encoding="utf-8"))
    with duckdb.connect(config={"threads": "2", "memory_limit": "2GB"}) as con:
        evidence, baseline = replay(con, args.release, args.registry, rows, existing)
    result = {"dataset_version": args.release.name, "rule_sources": RULES,
              "source_evidence": str(args.source), "known_date_policy": "date-only start usable after its public date",
              "terminal_time_policy": "termination is a separate observed exit; no earlier feature gets its date",
              "halt_start_semantics": "publicly started open-ended transfer halt; pending until published exit",
              **baseline}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in (("suspension_followup_v4_additions.json", evidence), ("suspension_v4_replay_audit.json", result)):
        (args.output / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["all_stock_days_with_projected_additions"]))


if __name__ == "__main__":
    main()
