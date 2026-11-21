"""Normalize reviewed original capital filings with a source literal verification trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def normalize(row, directory):
    path = directory / row["file"]
    pdf = path.read_bytes()
    if not pdf.startswith(b"%PDF-"):
        raise ValueError(f"Not an archived PDF: {path}")
    source_hash = hashlib.sha256(pdf).hexdigest()
    if source_hash != row["source_sha256"]:
        raise ValueError(f"Source hash mismatch: {path}")
    if not (row["source_url"].startswith(("https://big5.sse.com.cn/", "https://static.sse.com.cn/",
                                        "https://disc.static.szse.cn/", "https://www.bse.cn/"))
            and f"/{row['published_at']}/" in row["source_url"]):
        raise ValueError(f"Missing official published archive date: {path}")
    result = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=pdf,
                            capture_output=True, check=True, timeout=60)
    text = result.stdout.decode("utf-8")
    lines = [re.sub(r"\s+", " ", line.strip()) for line in text.splitlines()]
    confirmations = [literal for literal in row["source_literals"] if any(literal in line for line in lines)]
    if len(confirmations) != len(row["source_literals"]):
        raise ValueError(f"Original filing no longer matches the reviewed literals: {path}")
    numbers = {int(token.replace(",", "")) for line in confirmations
               for token in re.findall(r"(?<![\d.])\d+(?:,\d{3})*(?![\d.])", line)}
    for share_class, amount in row["shares"].items():
        components = row.get("share_components", {}).get(share_class, [amount])
        if sum(components) != amount or not set(components) <= numbers:
            raise ValueError(f"Original filing cannot verify exact {share_class} components: {path}")
    if sum(row["shares"].values()) != row["total_ordinary_shares"]:
        raise ValueError(f"Ordinary class amounts do not sum to the verified total: {path}")
    currency = row.get("currency_evidence")
    if currency:
        currency_file = directory / currency["file"]
        if (hashlib.sha256(currency_file.read_bytes()).hexdigest() != currency["sha256"]
                or currency["published_at"] > row["published_at"]
                or f"/{currency['published_at']}/" not in currency["url"]):
            raise ValueError(f"Reporting currency evidence is missing or ineligible: {currency_file}")
    return {
        "ts_code": row["ts_code"], "share_precision_shares": 0,
        "shares_outstanding_security": row["shares"]["A"], "shares_outstanding_b": row["shares"].get("B", 0),
        "shares_outstanding_h": row["shares"].get("H", 0), "total_ordinary_shares": row["total_ordinary_shares"],
        "single_share_class": len(row["shares"]) == 1, "reporting_currency": row.get("reporting_currency"),
        "source_url": row["source_url"], "source_sha256": source_hash, "source_version_id": row["file"],
        "published_at": row["published_at"], "effective_from": row["effective_from"],
        "observed_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), "source_literals": confirmations,
        "knowledge_quality": "historical_original_evidence", "verification_rule": "reviewed_exchange_filing.v1",
        "reporting_currency_evidence": currency,
        "corroboration_url": currency["url"] if currency else None,
        "corroboration_sha256": currency["sha256"] if currency else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index = json.loads(args.source_index.read_text(encoding="utf-8"))
    versions = [normalize(row, args.source_index.parent) for row in index]
    stage = args.output.with_suffix(".partial")
    stage.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in versions), encoding="utf-8")
    stage.replace(args.output)
    print(f"Verified {len(versions)} original capital filings")


if __name__ == "__main__":
    main()
