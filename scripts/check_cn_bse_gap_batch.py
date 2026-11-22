"""Measure BSE financial gap repairs on all actual valid-input dates before publishing."""

import argparse
import hashlib
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from verify_cn_bse_financial_filings import financial_by_code, pit_replay

from kurumi.cn_pit import FIN_NUM, FLOW, STOCK


def replay(release, base, repaired, path):
    actual = defaultdict(list)
    measured = ",".join(f"f.{m}" for m in FIN_NUM)
    with duckdb.connect(config={"threads": 3}) as con:
        for table in ("stock_daily", "stock_fundamental_asof"):
            con.read_parquet(str(release / table / "**" / "*.parquet"), hive_partitioning=False).create_view(table)
        for code, issuer, day, clock, *values in con.sql(f"""
            SELECT d.ts_code,d.issuer_id,d.local_trade_date,d.asof_utc,{measured}
            FROM stock_daily d LEFT JOIN stock_fundamental_asof f USING(fundamental_snapshot_id)
            WHERE d.exchange='BSE' AND d.input_valid AND d.local_trade_date<=DATE '2026-06-30'
            ORDER BY 1,3
        """).fetchall():
            actual[code].append((issuer, day, clock, values))
    original = financial_by_code(base, set(actual))
    proposed = financial_by_code(repaired, set(actual))
    core = (*FLOW.values(), *STOCK)
    totals, cohorts = Counter(), defaultdict(Counter)
    restored, lost, changed = Counter(), Counter(), Counter()
    coverage = defaultdict(Counter)
    anchor_changes, examples = Counter(), {}
    for code, days in actual.items():
        issuer, = {row[0] for row in days}
        before = pit_replay(path, original[code], issuer)
        after = pit_replay(path, proposed[code], issuer)
        bclocks = [row["available_at"] for row in before]
        aclocks = [row["available_at"] for row in after]
        for _, date, clock, saved in days:
            stage = ("train" if date.year <= 2023 else "validation" if date.year == 2024 and date.month <= 6
                     else "calibration" if date.year == 2024 else "test")
            cohort = cohorts[date.year, stage]
            for counter in (totals, cohort):
                counter["valid_inputs"] += 1
            bindex = bisect_right(bclocks, clock) - 1
            aindex = bisect_right(aclocks, clock) - 1
            earlier = before[bindex] if bindex >= 0 else {}
            updated = after[aindex] if aindex >= 0 else {}
            for source, row in (("base_v11", earlier), ("repaired", updated)):
                if all(row.get(field) is not None for field in core):
                    for counter in (totals, cohort):
                        counter[f"{source}_all_seven"] += 1
                for field in FIN_NUM:
                    coverage[source][field] += row.get(field) is not None
            coverage["published"].update(field for field, value in zip(FIN_NUM, saved, strict=True) if value is not None)
            for field in FIN_NUM:
                a, b = earlier.get(field), updated.get(field)
                if a is None and b is not None:
                    restored[field] += 1
                elif a is not None and b is None:
                    lost[field] += 1
                    common = ("newer_fiscal_anchor" if updated.get("fiscal_period_end") != earlier.get("fiscal_period_end")
                              else "same_fiscal_anchor")
                    anchor_changes[common, field] += 1
                    examples.setdefault((common, field), {"ticker": code, "trade_date": date.isoformat(),
                        "prior_period": str(earlier.get("fiscal_period_end")),
                        "repaired_period": str(updated.get("fiscal_period_end")),
                        "missing_reason": updated.get("missing_reasons", {}).get(field)})
                elif a is not None and b is not None and not isclose(a, b, rel_tol=1e-10, abs_tol=1e-12):
                    changed[field] += 1
    return {"release": release.name, "issuers": len(actual), "sample_scope": "all_BSE_valid_inputs_through_2026-06-30",
            "totals": dict(totals), "cohorts": [{"year": year, "split": split, **counts}
                for (year, split), counts in sorted(cohorts.items())], "available_values": coverage,
            "new_sources_gains": restored, "new_sources_losses": lost, "new_sources_finite_changes": changed,
            "losses_by_anchor": [{"anchor": anchor, "field": field, "affected_days": count,
                                  "example": examples[anchor, field]}
                                 for (anchor, field), count in sorted(anchor_changes.items())]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "base", "repaired", "output"):
        cli.add_argument(f"--{name}", type=Path, required=True)
    args = cli.parse_args()
    with TemporaryDirectory(dir=args.output.parent) as scratch:
        summary = replay(args.release, args.base, args.repaired, Path(scratch))
    with (args.repaired / "financial_versions.jsonl").open("rb") as source:
        summary["repaired_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["totals"]), flush=True)


if __name__ == "__main__":
    main()
