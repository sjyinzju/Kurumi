"""Reconstruct suspended-day F only inside corroborated no-event factor intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def paired_factors(pair_proofs):
    pairs = {}
    for item in pair_proofs["sources"]:
        if item["provider_code"] != "0":
            continue
        digest = hashlib.sha256(json.dumps(item["rows"], separators=(",", ":")).encode()).hexdigest()
        if digest != item["response_rows_sha256"]:
            raise ValueError(f"Paired price archive changed for {item['code']}")
        exchange, symbol = item["code"].split(".")
        code = f"{symbol}.{exchange.upper()}"
        pairs.setdefault(code, {})[item["adjustment"]] = item
    result = {}
    for code, proof in pairs.items():
        unadjusted = {v["date"]: v for v in proof["3"]["rows"]}
        adjusted = {v["date"]: v for v in proof["1"]["rows"]}
        ratios = {}
        suspended = set()
        for day in sorted(unadjusted.keys() & adjusted.keys()):
            raw, hfq = unadjusted[day], adjusted[day]
            if raw["code"] != proof["3"]["code"] or hfq["code"] != raw["code"] or (
                raw["adjustflag"] != "3" or hfq["adjustflag"] != "1" or
                raw["tradestatus"] != hfq["tradestatus"] or raw["volume"] != hfq["volume"]
            ):
                raise ValueError(f"Paired records disagree on identity or trading state for {code} {day}")
            if raw["close"] and hfq["close"] and Decimal(raw["close"]) > 0 and Decimal(hfq["close"]) > 0:
                ratios[day] = Decimal(hfq["close"]) / Decimal(raw["close"])
            if raw["tradestatus"] == "0" and raw["volume"] and Decimal(raw["volume"]) == 0:
                suspended.add(day)
        hashes = [v["response_rows_sha256"] for v in proof.values()]
        result[code] = (ratios, suspended, hashes)
    return result


def run(release, baostock_receipt, capture, output, paired_receipt=None, bse_receipt=None):
    raw = json.loads(baostock_receipt.read_text(encoding="utf-8"))
    if raw["input_release"] != release.name:
        raise ValueError("Archived factor probes do not match the price baseline")
    paired_proofs = json.loads(paired_receipt.read_text(encoding="utf-8")) if paired_receipt else {}
    pairs = paired_factors(paired_proofs) if paired_receipt else {}
    bse = json.loads(bse_receipt.read_text(encoding="utf-8")) if bse_receipt else {}
    pages = []
    audits = []
    for path in sorted((capture / "requests/TRD_Cptl").glob("*.jsonl.gz")):
        audit = json.loads(path.with_suffix("").with_suffix(".json").read_text(encoding="utf-8"))
        query = audit["query"]
        if query["condition"] or query["start"] > "2013-01-01" or query["end"] < "2026-07-31":
            continue
        if audit["status"] != "ok" or sha256(path) != audit["sha256"]:
            raise ValueError(f"Invalid CSMAR action archive shard {path.name}")
        pages.append(str(path))
        audits.append(audit)
    if len(pages) != 1:
        raise ValueError("Need one complete unfiltered CSMAR distribution archive")

    recovered, requests, remaining = [], [], []
    with duckdb.connect() as con:
        con.from_parquet(str(release / "stock_daily/market_id=CN/year=*/*.parquet"), hive_partitioning=False).create_view("stock")
        con.from_parquet(str(release / "reference/security_history.parquet")).create_view("history")
        con.read_json(pages, convert_strings_to_integers=False).create_view("csmar_actions")
        count = con.sql("SELECT count(*) FROM csmar_actions").fetchone()[0]
        if count != audits[0]["rows"]:
            raise ValueError("CSMAR action archive row count differs from its receipt")
        for item in raw["records"]:
            code = item["ts_code"]
            day_text = item["missing_days"]
            events = item["events"]
            bse_actions = bse.get("dividend", {}) if code == "920179.BJ" else {}
            if not bse_actions and (item["provider_code"] != "0" or (not events and code not in pairs)):
                remaining.append({"ts_code": code, "dates": len(day_text), "reason": "independent_archive_not_established"})
                continue
            earliest, latest = date.fromisoformat(day_text[0]), date.fromisoformat(day_text[-1])
            actual_hash = hashlib.sha256(json.dumps(events, ensure_ascii=False,
                                                    separators=(",", ":")).encode()).hexdigest()
            if actual_hash != item["response_rows_sha256"]:
                raise ValueError(f"Factor event hash differs from archived source rows for {code}")
            clocks = [date.fromisoformat(event["dividOperateDate"]) for event in events]
            bse_hashes = []
            if bse_actions:
                historical, = con.execute("SELECT prior_code FROM history WHERE ts_code=?", [code]).fetchone()
                for alias in (code, historical):
                    action = bse_actions[alias]
                    rows = action["rows"]
                    digest = hashlib.sha256(json.dumps([action["fields"], rows], ensure_ascii=False,
                                                       separators=(",", ":")).encode()).hexdigest()
                    if not rows or digest != action["response_sha256"]:
                        raise ValueError(f"Unverified TuShare distribution archive for {alias}")
                    bse_hashes.append(digest)
                    for raw_event in rows:
                        event = dict(zip(action["fields"], raw_event, strict=True))
                        if event["ts_code"] != alias:
                            raise ValueError(f"Unexpected issuer in distribution archive for {alias}")
                        if event["ex_date"]:
                            clocks.append(date.fromisoformat(event["ex_date"]))
            anchors = con.execute("""
                SELECT local_trade_date,price_adj_factor FROM stock WHERE ts_code=?
                AND local_trade_date<? AND price_adj_factor IS NOT NULL ORDER BY local_trade_date DESC LIMIT 2
            """, [code, earliest]).fetchall()
            paired = pairs.get(code)
            if paired and not anchors:
                ratios, suspended, hashes = paired
                confirmed = [day for day in day_text if day in suspended and day in ratios]
                if not confirmed:
                    remaining.append({"ts_code": code, "dates": len(day_text), "reason": "paired_provider_basis_conflict"})
                    continue
                if len(confirmed) != len(day_text):
                    remaining.append({"ts_code": code, "dates": len(day_text) - len(confirmed),
                                      "reason": "paired_provider_basis_conflict"})
                batch = "baostock-paired-factor-" + hashlib.sha256("|".join(hashes).encode()).hexdigest()[:28]
                recovered.extend(dict(ts_code=code, trade_date=day.replace("-", ""),
                                      adj_factor=float(ratios[day]), _batch_id=batch) for day in confirmed)
                requests.append(dict(ts_code=code, batch_id=batch, source=item["source_url"],
                                     response_sha256=hashes[0], unadjusted_response_sha256=hashes[1],
                                     observed_at=paired_proofs["observed_at"], reconstructed_days=confirmed,
                                     basis="same_day_provider_back_adjusted_over_raw_zero_volume_factor_only"))
                continue
            if len(anchors) != 2 or anchors[0][1] != anchors[1][1] or anchors[0][1] <= 0:
                remaining.append({"ts_code": code, "dates": len(day_text), "reason": "fixed_source_basis_unverified"})
                continue
            prior_day, factor = anchors[0]
            csmar_clocks = con.execute("""
                SELECT DISTINCT try_cast(c.Exdistdt AS DATE) FROM csmar_actions c JOIN history h ON h.ts_code=?
                WHERE (c.Stkcd=split_part(h.ts_code,'.',1) OR c.Stkcd=split_part(h.prior_code,'.',1))
                  AND try_cast(c.Exdistdt AS DATE)>? AND try_cast(c.Exdistdt AS DATE)<=?
            """, [code, prior_day, latest]).fetchall()
            first_event = min((clock for clock in (*clocks, *(r[0] for r in csmar_clocks)) if clock > prior_day),
                              default=date.max)
            confirmed = [day for day in day_text if date.fromisoformat(day) < first_event]
            if paired:
                ratios, suspended, hashes = paired
                anchor_ratio = ratios.get(prior_day.isoformat())
                confirmed = [day for day in confirmed if day in suspended and ratios.get(day) == anchor_ratio]
            if len(confirmed) != len(day_text):
                remaining.append({"ts_code": code, "dates": len(day_text) - len(confirmed),
                                  "reason": "factor_event_inside_window"})
            if not confirmed:
                continue
            archive_hash = item["response_rows_sha256"]
            proof_hash = archive_hash if not bse_actions else sha256(bse_receipt)
            source_url = item["source_url"] if not bse_actions else bse_actions[code]["source"]
            basis = f"{release.name}|{code}|{prior_day}|{factor}|{proof_hash}|{audits[0]['sha256']}"
            batch = "no-action-factor-" + hashlib.sha256(basis.encode()).hexdigest()[:28]
            recovered.extend(dict(ts_code=code, trade_date=day.replace("-", ""), adj_factor=factor, _batch_id=batch)
                             for day in confirmed)
            requests.append(dict(ts_code=code, batch_id=batch, source=source_url,
                                 response_sha256=proof_hash, observed_at=(bse if bse_actions else raw)["observed_at"],
                                 original_tushare_factor_anchor=prior_day.isoformat(), provider_anchor_factor=factor,
                                 second_prior_basis_check=anchors[1][0].isoformat(),
                                 paired_price_source_sha256=paired[2] if paired else None,
                                 bse_alias_distribution_sha256=bse_hashes or None,
                                 csmar_distribution_archive_sha256=audits[0]["sha256"],
                                 reconstructed_days=confirmed))
    if not recovered:
        raise ValueError("No suspended-day F values met the archived event and anchor requirements")
    output.mkdir(parents=True, exist_ok=True)
    stem = "suspended-f-" + hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest()[:24]
    shard = output / (stem + ".parquet")
    pq.write_table(pa.Table.from_pylist(recovered), shard.with_suffix(".partial"), compression="zstd")
    shard.with_suffix(".partial").replace(shard)
    report = output / (stem + ".json")
    report.write_text(json.dumps(dict(rule="anchored_no_action_step_function.v1", input_release=release.name,
                                      requests=requests, recovered=len(recovered), remaining=remaining,
                                      parquet_sha256=sha256(shard)), indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"Reconstructed {len(recovered)} factors from archived no-action intervals; {sum(x['dates'] for x in remaining)} unresolved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--baostock-receipt", type=Path, required=True)
    parser.add_argument("--csmar-capture", type=Path, required=True)
    parser.add_argument("--paired-receipt", type=Path)
    parser.add_argument("--bse-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.release, args.baostock_receipt, args.csmar_capture, args.output, args.paired_receipt, args.bse_receipt)
