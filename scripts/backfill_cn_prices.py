"""Fetch only currently missing Kurumi CN quote and F keys through the quant adapter."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from build_cn_numeric import digest, sha256, write_json
from filelock import FileLock


def gap_plan(con, endpoint):
    if endpoint in ("daily", "suspend_d"):
        predicate = "q.missing_close AND NOT q.suspension_verified AND NOT q.quote_conflict"
    else:
        predicate = "q.missing_adjustment AND NOT coalesce(q.adjustment_conflict,false)"
    return con.sql(f"""
        SELECT q.ts_code,h.prior_code,list(strftime(q.local_trade_date,'%Y%m%d')
               ORDER BY q.local_trade_date) AS days
        FROM quote_gaps q JOIN security_history h USING(instrument_id)
        WHERE {predicate}
        GROUP BY 1,2 ORDER BY len(days) DESC,1
    """).fetchall()


def source_row_usable(endpoint, row):
    if endpoint == "daily":
        close, volume = row.get("close"), row.get("vol")
        return close is not None and math.isfinite(close) and close > 0 and (volume is None or volume > 0)
    if endpoint == "adj_factor":
        factor = row.get("adj_factor")
        return factor is not None and math.isfinite(factor) and factor > 0
    return row.get("suspend_type") == "S" and row.get("suspend_timing") in (None, "", "全天", "09:30-15:00")


def fetch_missing(root: Path, project: Path, limit: int | None, endpoints):
    sys.path.insert(0, str(project / "src"))
    from quant.config import load_settings
    from quant.data.schemas.catalog import load_catalog
    from quant.data.sources.tushare import SourceError, TushareAdapter

    settings = load_settings(root).model_copy(
        update={"max_attempts": 3, "timeout_seconds": 12, "requests_per_minute": 130}
    )
    adapter = TushareAdapter(settings)
    catalog = load_catalog()
    workspace = root / "numeric" / ".build-cn"
    attempt_count = 0
    with FileLock(str(root / "90_metadata" / "ingestion.lock"), timeout=0):
        with duckdb.connect(str(workspace / "work.duckdb"), read_only=True) as con:
            plans = {endpoint: gap_plan(con, endpoint) for endpoint in endpoints}
        for endpoint, groups in plans.items():
            target = workspace / "sources" / endpoint
            target.mkdir(parents=True, exist_ok=True)
            outcome = {"scopes": len(groups), "requested_keys": sum(len(row[2]) for row in groups),
                       "filled_keys": 0, "completed_scopes": 0, "errors": {}}
            failures = 0
            for code, previous, days in groups:
                if limit is not None and attempt_count >= limit:
                    break
                state_id = digest([endpoint, code, previous, days])[:32]
                marker = target / f"{state_id}.json"
                parquet = target / f"{state_id}.parquet"
                previous_state = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
                if previous_state.get("state") == "unavailable":
                    reason = previous_state["error_kind"]
                    outcome["errors"][reason] = outcome["errors"].get(reason, 0) + 1
                    if reason == "permission_denied":
                        break
                    continue
                if previous_state.get("state") == "complete" and (
                    not previous_state.get("parquet_sha256")
                    or (parquet.exists() and sha256(parquet) == previous_state["parquet_sha256"])
                ):
                    outcome["completed_scopes"] += 1
                    outcome["filled_keys"] += previous_state["filled_keys"]
                    continue
                missing = set(days)
                recovered = []
                requests = []
                try:
                    for alias in filter(None, (code, previous)):
                        if not missing:
                            break
                        params = {"ts_code": alias, "start_date": min(missing), "end_date": max(missing)}
                        attempt_count += 1
                        result = adapter.fetch(catalog[endpoint], params)
                        if len(result.rows) >= catalog[endpoint].max_rows:
                            raise SourceError("row_limit", "Source reached its row limit for this scope")
                        raw_id = digest([result.fields, result.rows])
                        batch = f"tushare-{endpoint}-{raw_id[:40]}"
                        requests.append({"parameters": params, "source": catalog[endpoint].doc_url,
                                         "fetched_at": result.fetched_at.isoformat(), "response_sha256": raw_id,
                                         "batch_id": batch, "source_row_count": len(result.rows)})
                        for values in result.rows:
                            row = dict(zip(result.fields, values, strict=True))
                            day = row["trade_date"]
                            if day in missing and source_row_usable(endpoint, row):
                                if row.get("suspend_timing") == "":
                                    row["suspend_timing"] = None
                                row["_batch_id"] = batch
                                recovered.append(row)
                                missing.remove(day)
                except SourceError as ex:
                    outcome["errors"][ex.kind] = outcome["errors"].get(ex.kind, 0) + 1
                    write_json(marker, {"state": "retryable" if ex.retryable else "unavailable",
                                        "error_kind": ex.kind, "error": str(ex), "requests": requests,
                                        "observed_at": datetime.now(timezone.utc), "code": code, "days": days})
                    failures += 1
                    if failures >= 3 or ex.kind in {"permission_denied", "rate_limit"}:
                        break
                    continue
                failures = 0
                checksum = None
                if recovered:
                    partial = parquet.with_suffix(".partial")
                    pq.write_table(pa.Table.from_pylist(recovered), partial, compression="zstd")
                    os.replace(partial, parquet)
                    checksum = sha256(parquet)
                write_json(marker, {"state": "complete", "requests": requests, "filled_keys": len(recovered),
                                    "unreturned_days": sorted(missing), "parquet_sha256": checksum})
                outcome["completed_scopes"] += 1
                outcome["filled_keys"] += len(recovered)
                if outcome["completed_scopes"] % 50 == 0:
                    print(endpoint, outcome, flush=True)
            write_json(workspace / f"backfill_{endpoint}.json", outcome)
            print(endpoint, outcome, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("E:/QuantData"))
    parser.add_argument("--quant", type=Path, default=Path("E:/quant"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--endpoint", action="append", choices=("daily", "adj_factor", "suspend_d"))
    options = parser.parse_args()
    fetch_missing(options.data_root, options.quant, options.limit, options.endpoint or ("daily", "adj_factor"))
