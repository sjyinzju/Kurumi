"""Stage known SW industry intervals from dated archived records and change notices."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import duckdb
import xlrd
from audit_cn_sw_csmar_events import CHINA, checked_source, iso_date, security_lookup
from audit_cn_sw_history import HISTORY_FILENAME, inspect_history

VERSION_END = {"SW2014": date(2021, 7, 30), "SW2021": date(2026, 7, 1)}
VERSION_ID = {"P0211": "SW2014", "P0218": "SW2021"}


def stage(capture, crosswalk, release, base, archive, output):
    mapping = json.loads(crosswalk.read_bytes())["mapping"]
    dictionary = {(row["classification_version"], row["source_industry_code"]): row["industry_code"] for row in mapping}
    names = {(row["classification_version"], row["industry_code"]): row["industry_name"]
             for row in mapping if row["rank"] == 1}
    with duckdb.connect() as con:
        securities = con.read_parquet(str(release / "reference/security_history.parquet")).to_arrow_table().to_pylist()
        resolve = security_lookup(securities)
        class_sources, class_rows = checked_source(con, capture, "STK_INDUSTRYCLASS")
        notice_sources, notices = checked_source(con, capture, "IDX_Chgsmp")

    history = defaultdict(lambda: defaultdict(set))
    for row in class_rows:
        version = VERSION_ID.get(row["IndustryClassificationID"])
        effective = iso_date(row["ImplementDate"])
        index = dictionary.get((version, row["IndustryCode"]))
        symbol = resolve(row["Symbol"], effective) if effective else None
        if symbol and index and effective < VERSION_END[version]:
            history[symbol, version][effective].add(index)

    def expiry(symbol, version, index, anchor):
        subsequent = [day for day, labels in history[symbol, version].items() if day > anchor and labels != {index}]
        return min(subsequent, default=VERSION_END[version])

    def agrees(symbol, version, index, day):
        states = history[symbol, version]
        latest = max((stamp for stamp in states if stamp <= day), default=None)
        return latest is not None and states[latest] == {index}

    rows = [json.loads(line) for line in base.read_bytes().splitlines()]
    counts = Counter()
    for row in rows:
        code, version, index = (row[key] for key in ("ts_code", "classification_version", "industry_code"))
        published = datetime.fromisoformat(row["published_at"])
        day = published.astimezone(CHINA).date() if published.tzinfo else published.date()
        begin = max(date.fromisoformat(row["effective_from"]), day)
        if agrees(code, version, index, begin) and row.get("effective_to"):
            end = expiry(code, version, index, begin)
            old_end = date.fromisoformat(row["effective_to"])
            if end > old_end:
                row["effective_to"] = end.isoformat()
                row["interval_boundary_archive_sha256"] = class_sources[0]["sha256"]
                counts["extended_dated_controls"] += 1

    def add(code, version, index, effective, deadline, public, observed, url, sha, identifier):
        rows.append({"ts_code": code, "classification_version": version, "industry_code": index,
                     "industry_name": names[version, index], "effective_from": effective.isoformat(),
                     "effective_to": deadline.isoformat(), "published_at": public, "observed_at": observed,
                     "source_url": url, "source_sha256": sha, "source_version_id": identifier,
                     "knowledge_quality": "historical_original_evidence",
                     "interval_boundary_archive_sha256": class_sources[0]["sha256"]})

    notice_keys = defaultdict(set)
    removals = defaultdict(list)
    for notice in notices:
        effective, public = (iso_date(notice[key]) for key in ("Chgsmp01", "Chgsmp06"))
        version = "SW2014" if effective and effective < VERSION_END["SW2014"] else "SW2021"
        index = notice["Indexcd"] + ".SI"
        code = resolve(notice["Chgsmp02"], effective) if effective else None
        if not code or not public or (version, index) not in names:
            continue
        if notice["Chgsmp04"] == "2":
            removals[code, version, index].append(effective)
        if notice["Chgsmp04"] == "1" and history[code, version].get(effective) == {index}:
            notice_keys[code, version, index, effective].add(public)
    for (code, version, index, effective), clocks in notice_keys.items():
        if len(clocks) != 1:
            continue
        public, = clocks
        finish = min(expiry(code, version, index, effective),
                     min((day for day in removals[code, version, index] if day > effective), default=date.max))
        if max(effective, public + timedelta(days=1)) >= finish:
            continue
        receipt, = [r for r in notice_sources if r["query"]["start"] <= str(effective) <= r["query"]["end"]]
        add(code, version, index, effective, finish, public.isoformat(), receipt["requested_at"],
            "https://data.csmar.com/", receipt["sha256"], f"IDX_Chgsmp:{code}:{index}:{effective}")
        counts["dated_matching_index_notices"] += 1

    receipts = json.loads((archive / "archive_requests.json").read_bytes())
    package, = [r for r in receipts if r["target"] == "SwClass-legacy.rar" and r["status"] == 200]
    payload = archive / package["target"]
    assert hashlib.sha256(payload.read_bytes()).hexdigest() == package["sha256"]
    public = parsedate_to_datetime(package["http_last_modified"])
    anchor = public.astimezone(CHINA).date()
    states = defaultdict(lambda: defaultdict(set))
    version = "SW2021"
    records, metadata = inspect_history(xlrd, archive / "archive_2022" / HISTORY_FILENAME)
    for symbol, effective, label, updated in records:
        code = resolve(symbol, anchor)
        index = dictionary.get((version, label))
        if code and effective <= anchor and updated.date() <= anchor:
            states[code][effective].add(index)
    for code, by_date in states.items():
        values = by_date[max(by_date)]
        if len(values) != 1 or None in values:
            continue
        index, = values
        if not agrees(code, version, index, anchor):
            continue
        add(code, version, index, anchor, expiry(code, version, index, anchor), public.isoformat(),
            package["observed_at"], package["url"], package["sha256"], f"SW-archive-20221129:{metadata['sha256']}")
        counts["legacy_publisher_archive"] += 1

    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(dict(counts), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("capture", "crosswalk", "release", "base", "archive", "output"):
        parser.add_argument(f"--{key}", required=True, type=Path)
    args = parser.parse_args()
    stage(args.capture, args.crosswalk, args.release, args.base, args.archive, args.output)
