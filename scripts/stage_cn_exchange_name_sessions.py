"""Recover actual trading names and proposal-only dates from archived issuer notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pymupdf

from stage_cn_tushare_market_gaps import name_evidence, save_lines

LOCAL = ZoneInfo("Asia/Shanghai")


def scan(archive, gap, symbol, day, previous, following):
    path = archive / f"{gap}_{day}.json"
    if not path.is_file():
        return "", {}
    ledger = json.loads(path.read_bytes())
    date = rf"{day.year}年0?{day.month}月0?{day.day}日"
    dated = re.compile(rf"(?:自|从|将于){date}(?:开市|起|生效|启用|变更|,)|"
                       rf"(?:启用|生效|变更)日期(?:为|:)?{date}|{date}(?:起启用|正式启用|开市起)")
    matchers = {}
    for url, (publication, title, document_id, catalogue) in ledger.get("matches", {}).items():
        if publication != day.isoformat():
            continue
        path = archive / "originals" / hashlib.sha256(url.encode()).hexdigest()[:24]
        if not path.with_suffix(".pdf").is_file():
            continue
        receipt = json.loads(path.with_suffix(".json").read_bytes())
        with path.with_suffix(".pdf").open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != receipt["sha256"]:
                raise ValueError(f"Original name notice failed its hash check: {gap} {day}")
        with pymupdf.open(path.with_suffix(".pdf")) as doc:
            raw = "\n".join(doc[index].get_text() for index in range(min(3, len(doc))))
        compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw))
        header_name = r"(?:证券|股票)简称:?([^:：,，]+?)"
        header_code = rf"(?:证券|股票)代码:?{symbol}"
        header = (re.search(header_code + header_name + r"(?:公告编号|公告号|编号)", compact[:180])
                  or re.search(header_name + header_code, compact[:180]))
        if not header:
            continue
        original_name = header[1]
        if ("公告" not in title or re.search(r"独立意见|更正|补充|修订后章程", title)):
            continue
        proof = {"observed_at": receipt["observed_at"], "source_url": url, "source_sha256": receipt["sha256"],
                 "source_version_id": f"exchange-trading-name:{document_id}", "official_notice_date": publication,
                 "corroboration_url": catalogue["source_url"], "corroboration_sha256": catalogue["source_sha256"]}
        if following and len(following) <= 24 and re.search(r"证券简称|股票简称", title):
            segments = re.split(r"[。;；]", compact)
            implemented = any(dated.search(part) and following in part
                              and re.search(r"(?:证券|股票)(?:中文)?简称|中文证券简称", part)
                              and re.search(r"发生变更|变更为|变为|启用|调整为", part) for part in segments)
            explicit_date = re.search(rf"(?:证券|股票)简称(?:的)?(?:启用|生效|变更)日期(?:为|:)?{date}",
                                      compact)
            identifies_new_name = (original_name == following or
                                   re.search(rf"(?:变更后的(?:中文)?(?:证券|股票)简称(?:为|:)|"
                                             rf"变更为|调整为)[“\"【]?{re.escape(following)}", compact))
            if (implemented or (explicit_date and identifies_new_name)) and "拟变更" not in title:
                matchers[following] = (proof, "exchange_implemented_trading_name")
                continue
        if (previous and original_name == previous
                and re.search(r"变更|审议|提请", title)
                and re.search(r"尚需(?:获得|提交|经)|方可实施|尚未(?:实施|完成)|尚需.*审议", compact)
                and not dated.search(compact)):
            matchers[previous] = (proof, "proposal_preserves_preexisting_name")
    if len(matchers) != 1:
        return "", {}
    name, (proof, basis) = matchers.popitem()
    return name, proof | {"clock_basis": basis}


def stage(release, archives, output):
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 3}) as con:
        con.read_parquet(str(release / "stock_daily/**/*.parquet"), hive_partitioning=False).create_view("daily")
        keys = con.sql("""
            WITH names AS (
                SELECT instrument_id,ts_code,symbol_asof,local_trade_date,name_asof,input_valid,quote_valid,
                       lag(name_asof) OVER w AS previous_name,lead(name_asof) OVER w AS next_name
                FROM daily WHERE instrument_id IN (
                    SELECT DISTINCT instrument_id FROM daily WHERE input_valid AND name_asof IS NULL
                ) WINDOW w AS (PARTITION BY instrument_id,symbol_asof ORDER BY local_trade_date)
            ) SELECT instrument_id,ts_code,symbol_asof,local_trade_date,previous_name,next_name
              FROM names WHERE input_valid AND quote_valid AND name_asof IS NULL ORDER BY 2,4;
        """).fetchall()
    outcomes, rows = Counter(), []
    for instrument, code, symbol, day, previous, following in keys:
        matches = {}
        for directory in archives:
            name, proof = scan(directory, code, symbol, day, previous, following)
            if name:
                matches[name] = proof
        if len(matches) != 1:
            outcomes["conflicting_or_insufficient_original"] += 1
            continue
        name, proof = matches.popitem()
        # The actual exchange trading fact is observable by the session close.
        # On a proposal date the previously published name remains in force.
        clock = datetime.combine(day, time(15), LOCAL).isoformat()
        rows.append(name_evidence(instrument, code, symbol, day, name, clock) | proof)
        outcomes[proof["clock_basis"]] += 1
    save_lines(output / "security_name_versions.jsonl", rows)
    (output / "name_session_audit.json").write_text(json.dumps(
        {"release": release.name, "outcomes": dict(outcomes), "accepted": rows},
        ensure_ascii=False, default=str, indent=2) + "\n", "utf-8")
    print(dict(outcomes), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage(args.release, args.archive, args.output)
