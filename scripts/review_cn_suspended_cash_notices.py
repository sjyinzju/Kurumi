"""Index candidate full-halt language for independent issuer-notice review."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path

from verify_cn_mainland_suspended_cash import compact_original, read_discovery

ACTION = re.compile(
    r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
    r"(?P<link>(?:\([^)]{1,9}\)|[上午下午开市时起继续始连停股票及债将]){0,20})"
    r"(?P<kind>停牌|复牌)"
)
STILL_HALTED = re.compile(r"(?:公司|本公司)(?:A股)?(?:股票|证券|股股票)(?:目前|仍|将|继续|拟|于|自|[（(][^）)]{1,40}[）)]){0,12}"
                          r"(?:继续停牌|处于停牌状态|持续停牌)")


def reviews(directory):
    for path in sorted(directory.glob("*_suspension_cash_receipt.json")):
        discovery = read_discovery(path)
        row = discovery["original_exact_key"]
        notes = []
        for document in discovery["suspension"]["documents"]:
            if "raw_pdf" not in document:
                continue
            body = compact_original(document)
            events = []
            for match in ACTION.finditer(body):
                year, month, day = (int(match[key]) for key in ("year", "month", "day"))
                try:
                    event_day = date(year, month, day).isoformat()
                except ValueError:
                    continue
                phrase = body[max(0, match.start() - 18):match.end() + 12]
                events.append({"date": event_day, "kind": match["kind"], "phrase": phrase})
            continued = [m.group() for m in STILL_HALTED.finditer(body)]
            notes.append({"id": document["native_notice_id"], "published": document["published_date"],
                          "title": document["title"], "events": events, "explicit_ongoing_halt": continued,
                          "original_text": document["extracted_text"], "receipt": document["receipt"]})
        yield {"ts_code": row["ts_code"], "prior_date": row["prior_date"], "trade_date": row["trade_date"],
               "docs": notes, "unavailable_cash_sources": sum("raw_pdf" not in d for d in discovery["cash"]["candidates"])}


def suggest(row):
    """Propose documents for manual review, without assigning source authority."""
    previous, target = row["prior_date"], row["trade_date"]
    before, after = [], []
    for doc in row["docs"]:
        starts = [e for e in doc["events"] if e["kind"] == "停牌" and e["date"] <= previous
                  and "下午" not in e["phrase"]]
        dated_resume = next((e for e in doc["events"] if e["kind"] == "复牌"
                             and target < e["date"] <= (date.fromisoformat(doc["published"]) + timedelta(days=5)).isoformat()
                             and "复牌" in doc["title"] and "延期复牌" not in doc["title"]
                             and not any(word in e["phrase"] for word in ("最晚", "预计", "之前", "日前"))), None)
        if doc["published"] <= previous and starts:
            before.append((doc, max(starts, key=lambda e: e["date"])))
        if doc["published"] > target and (starts or doc["explicit_ongoing_halt"]) and (
            dated_resume or doc["explicit_ongoing_halt"]
        ):
            after.append((doc, dated_resume))
    if not before or not after:
        return None
    start, first = max(before, key=lambda x: (x[0]["published"] < previous, bool(x[0]["explicit_ongoing_halt"]),
                                              x[0]["published"]))
    end, resumes = min(after, key=lambda x: (x[1] is None, x[0]["published"]))
    return {"ts_code": row["ts_code"], "trade_date": target, "start_id": start["id"], "end_id": end["id"],
            "original_start": first["date"], "resume": resumes["date"] if resumes else None,
            "start_published": start["published"], "start_excerpt": first["phrase"],
            "end_published": end["published"],
            "end_excerpt": resumes["phrase"] if resumes else end["explicit_ongoing_halt"][0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = list(reviews(args.directory))
    destination = args.directory / "issuer_halt_review_index.json"
    destination.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    suggestions = [suggest(row) for row in rows]
    (args.directory / "issuer_halt_candidate_pairs.json").write_text(json.dumps({
        "proposals": [choice for choice in suggestions if choice],
        "no_proposed_pair": [[row["ts_code"], row["trade_date"]] for row, choice in zip(rows, suggestions, strict=True)
                             if choice is None],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
