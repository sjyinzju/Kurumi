"""Freeze effective exchange names with independently timed public facts for gap days."""
from __future__ import annotations

import argparse
import hashlib
import html as html_module
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import requests

from kurumi.cn_disclosures import _request

PDF_EXTRACTOR = """
import io
import sys
from pypdf import PdfReader
pages = PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages
sys.stdout.buffer.write('\\n'.join(page.extract_text() or '' for page in pages).encode('utf-8'))
"""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def compact(value):
    return re.sub(r"\s+", "", value)


def take_bytes(url, directory):
    name = digest(url.encode())[:24]
    page = directory / f"{name}.html"
    record = directory / f"{name}.json"
    if page.is_file() and record.is_file():
        body = page.read_bytes()
        receipt = json.loads(record.read_bytes())
        if receipt["source_url"] == url and digest(body) == receipt["sha256"]:
            return body.decode(receipt["encoding"]), receipt
    response = _request("GET", url)
    if urlsplit(response.url).hostname != urlsplit(url).hostname:
        raise ValueError(f"Unexpected publisher redirect for {url}")
    body = response.content
    for encoding in ("utf-8", "gb18030"):
        try:
            html = body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Unable to decode the timestamp evidence at {url}")
    receipt = {"source_url": url, "sha256": digest(body), "encoding": encoding,
               "observed_at": datetime.now(timezone.utc).isoformat()}
    page.write_bytes(body)
    record.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    return html, receipt


def verified_name(fact, catalogue, media, pdf_python):
    ts_code = fact["ts_code"]
    symbol = ts_code.split(".")[0]
    session = date.fromisoformat(fact["session"])
    expected = fact["name"]
    clock = datetime.fromisoformat(fact["public_fact_available_by"])
    if clock.utcoffset() != timedelta(hours=8) or clock.date() > session:
        raise ValueError(f"Unusable local public clock at {session}: {clock}")
    gap = json.loads((catalogue / f"{ts_code}_{session}.json").read_bytes())
    [official_url] = [url for url, value in gap["matches"].items() if value[2] == fact["official_id"]]
    base = catalogue / "originals" / digest(official_url.encode())[:24]
    doc = json.loads(base.with_suffix(".json").read_bytes())
    pdf_bytes = base.with_suffix(".pdf").read_bytes()
    if doc["source_url"] != official_url or doc["sha256"] != digest(pdf_bytes):
        raise ValueError(f"Original document identity does not match the exchange catalogue: {ts_code}")
    pdf_text = subprocess.run([str(pdf_python), "-c", PDF_EXTRACTOR], input=pdf_bytes, capture_output=True,
                              check=True, timeout=60).stdout.decode("utf-8")
    pdf_text = compact(pdf_text)
    if any(compact(value) not in pdf_text for value in (symbol, expected, *fact["official_literals"])):
        raise ValueError(f"Missing effective-name statement in {official_url}")
    html, receipt = take_bytes(fact["timing_url"], media)
    visible = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL)
    visible = compact(html_module.unescape(re.sub(r"<[^>]*>", "", visible)))
    if any(compact(value) not in visible for value in (symbol, expected, fact["clock_literal"], *fact["news_literals"])):
        raise ValueError(f"Independent dated public fact absent for {ts_code}")
    row = {"instrument_id": f"CN-{ts_code}", "ts_code": ts_code, "symbol_asof": symbol, "name_asof": expected,
           "effective_from": session.isoformat(), "effective_to": (session + timedelta(days=1)).isoformat(),
           "published_at": clock.isoformat(), "available_at": clock.isoformat(),
           "observed_at": receipt["observed_at"], "source_url": receipt["source_url"],
           "source_sha256": receipt["sha256"], "source_version_id": f"timed-public-fact:{receipt['sha256']}",
           "knowledge_quality": "historical_original_evidence", "corroboration_url": official_url,
           "corroboration_sha256": doc["sha256"], "official_source_version_id": doc["source_version_id"],
           "official_date_only": doc["published_date"], "clock_basis": "contemporaneous_public_fact_upper_bound"}
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pdf-python", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    media = args.output / "timed_evidence"
    media.mkdir(exist_ok=True)
    rows, blocked = [], []
    for fact in json.loads(args.facts.read_bytes()):
        try:
            rows.append(verified_name(fact, args.catalogue, media, args.pdf_python))
        except (requests.RequestException, ValueError) as error:
            blocked.append({"ts_code": fact["ts_code"], "session": fact["session"], "timing_url": fact["timing_url"],
                            "reason": f"{type(error).__name__}: {error}"})
    dates = [(r["instrument_id"], r["effective_from"]) for r in rows]
    if len(set(dates)) != len(rows):
        raise ValueError("Duplicate reviewed security-date in name facts")
    source = str(args.dataset / "stock_daily" / "**" / "*.parquet")
    with duckdb.connect() as con:
        accepted = []
        for row in rows:
            old = con.execute("""SELECT symbol_asof,name_asof,input_valid,asof_utc FROM read_parquet(?)
                WHERE instrument_id=? AND local_trade_date=?::DATE""",
                [source, row["instrument_id"], row["effective_from"]]).fetchall()
            if (len(old) != 1 or old[0][0] != row["symbol_asof"] or old[0][1] is not None
                    or old[0][3] < datetime.fromisoformat(row["available_at"])):
                raise ValueError(f"Reviewed name did not reconcile to one released NULL/clock: {row['instrument_id']}")
            accepted.append({"instrument_id": row["instrument_id"], "day": row["effective_from"],
                             "input_valid": old[0][2], "verified_name": row["name_asof"]})
    output = args.output / "security_name_versions.jsonl"
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    audit = {"dataset": args.dataset.name, "passed": len(rows), "input_valid": sum(r["input_valid"] for r in accepted),
             "rows": accepted, "evidence_sha256": digest(output.read_bytes()), "blocked": blocked}
    (args.output / "name_clock_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == "__main__":
    main()
