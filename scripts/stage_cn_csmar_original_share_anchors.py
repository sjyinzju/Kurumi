"""Stage class-complete issuer originals corroborated by CSMAR A-share capital history."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

import duckdb

from csmar_acquire import dump_json, file_sha256
from kurumi.cn_capital_sources import csmar_capture
from stage_cn_csmar_cashflow_originals import write_lines


def share_table_pages(pages, quantity):
    value = rf"(?<![\d,])(?:{quantity:,}|{quantity})(?:\.00)?\s+100(?:\.00)?%?(?=\s|$)"
    common, total = set(), set()
    for page, body in enumerate(pages, 1):
        if re.search(r"(?m)人民币普通股[^\n]*?" + value, body):
            common.add(page)
        if re.search(r"(?m)股份总数[^\n]*?" + value, body):
            total.add(page)
    return sorted({p for a in common for b in total if abs(a - b) <= 1 for p in (a, b)})


def verified_table_cells(document, layout, quantity):
    """Read the explicit end-of-period cells when a PDF wraps values across lines."""
    page = document[layout["page"] - 1]
    for label, cells in (("人民币普通股", layout["common"]), ("股份总数", layout["total"])):
        title, shares, percentage = [re.sub(r"\s+", "", page.get_text(clip=cell)) for cell in cells]
        if not title.endswith(label) or shares.replace(",", "") != str(quantity) or percentage != "100":
            return []
    return [layout["page"]]


def stage(capture, originals, output):
    import pymupdf

    output.mkdir(parents=True, exist_ok=True)
    anchors, declined = [], {}
    with duckdb.connect() as con:
        receipt, = csmar_capture(con, capture / "requests", "TRD_Capchg")
        for original in json.loads((originals / "publisher_originals.json").read_bytes()):
            code = original["ts_code"]
            pdf = originals / original["file"]
            if file_sha256(pdf) != original["source_sha256"]:
                raise ValueError(f"{code} original PDF hash changed")
            quantity = original["count"]
            with pymupdf.open(pdf) as document:
                text = [page.get_text(sort=True) for page in document]
                if not any(code.split(".")[0] in page for page in text[:10]):
                    raise ValueError(f"{code} could not be identified in the original PDF")
                pages = (verified_table_cells(document, original["share_table_cells"], quantity)
                         if "share_table_cells" in original else share_table_pages(text, quantity))
            if not pages:
                declined[code] = "original_common_and_total_share_schedule_not_verified"
                continue
            effective = date.fromisoformat(original["period_end"])
            published = date.fromisoformat(original["published_at"])
            history = con.execute("""
                SELECT Shrchgdt, bool_and(coalesce(Nshrttl=? AND Nshra=? AND Nshrb=0 AND Nshrh=0
                       AND Nshrprf=0 AND Nshroft=0,false)) AS matched
                FROM TRD_Capchg WHERE Stkcd=? GROUP BY 1 ORDER BY 1
            """, [quantity, quantity, code.split(".")[0]]).fetchall()
            prior = [(day, match) for day, match in history if day <= effective]
            expiry = next((day for day, match in history if day > effective and not match), None)
            if not prior or not prior[-1][1] or not expiry or not effective <= published < expiry:
                declined[code] = "capital_chain_or_its_end_unconfirmed"
                continue
            anchors.append({**{key: original[key] for key in ("ts_code", "published_at", "observed_at",
                            "source_url", "source_sha256")}, "effective_from": effective.isoformat(),
                            "effective_to": expiry.isoformat(), "shares_outstanding_security": quantity,
                            "single_share_class": True, "reporting_currency": "CNY", "share_precision_shares": 0,
                            "source_version_id": f"issuer-class-schedule:{code}:{effective}",
                            "source_pdf_pages": pages, "corroboration_sha256": receipt["sha256"],
                            "corroboration_url": "https://data.csmar.com/", "capital_event": prior[-1][0].isoformat(),
                            "verification_rule": "published_initial_report_capital",
                            "knowledge_quality": "historical_original_evidence"})
    write_lines(output / "share_versions.jsonl", anchors)
    dump_json(output / "anchor_audit.json", {"accepted": anchors, "declined": declined})
    print(f"Qualified {len(anchors)} original share intervals; withheld {len(declined)}", flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("capture", "originals", "output"):
        cli.add_argument(f"--{key}", type=Path, required=True)
    args = cli.parse_args()
    stage(args.capture, args.originals, args.output)


if __name__ == "__main__":
    main()
