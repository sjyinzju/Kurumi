"""Reconcile published China quotes and factors with the exact named raw inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from kurumi.cn_prices import literal


def reconcile(source: Path, temp: Path):
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    with duckdb.connect(config={"threads": 3, "memory_limit": "2GB", "temp_directory": str(temp)}) as con:
        for name, pattern in (("stock", "stock_daily/**/*.parquet"), ("history", "reference/security_history.parquet"),
                              ("parts", "reference/source_parts.parquet"), ("quote", "reference/quote_provenance.parquet")):
            con.execute(f"CREATE VIEW {name} AS FROM read_parquet({literal(source / pattern)},hive_partitioning=false)")
        con.execute("""CREATE TABLE aliases AS SELECT instrument_id,ts_code symbol FROM history
                       UNION ALL SELECT instrument_id,prior_code FROM history WHERE prior_code IS NOT NULL""")
        counts = dict(dataset_version=manifest["dataset_version"])
        for endpoint in ("daily", "adj_factor"):
            canonical = [Path(path) for path, in con.execute("""SELECT DISTINCT path FROM parts
                WHERE endpoint=? AND partition_key<=?""", (endpoint, manifest["label_observation_end_date"][:7]
                                                            .replace("-", "/"))).fetchall()]
            supplement = []
            for relative, checksum in manifest["source_snapshot"]["supplements"].items():
                if relative.startswith(f"sources/{endpoint}/"):
                    path = source.parent / ".build-cn" / relative
                    with path.open("rb") as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                            raise ValueError(f"Raw supplement differs from release manifest: {path}")
                    supplement.append(path)
            files = ",".join(literal(path) for path in (*canonical, *supplement))
            con.execute(f"CREATE VIEW {endpoint} AS FROM read_parquet([{files}],hive_partitioning=false,union_by_name=true)")
            counts[endpoint] = {"canonical_files": len(canonical), "hash_verified_supplement_files": len(supplement)}

        for endpoint, where, batch, match in (
            ("daily", "s.quote_valid", "daily_batch", """raw.close IS NOT DISTINCT FROM s.close_raw
               AND (s.open_raw IS NULL OR raw.open IS NOT DISTINCT FROM s.open_raw)
               AND (s.high_raw IS NULL OR raw.high IS NOT DISTINCT FROM s.high_raw)
               AND (s.low_raw IS NULL OR raw.low IS NOT DISTINCT FROM s.low_raw)
               AND CASE WHEN isfinite(raw.vol) AND raw.vol>=0 THEN raw.vol*100 END
                    IS NOT DISTINCT FROM s.volume_shares
               AND CASE WHEN isfinite(raw.amount) AND raw.amount>=0 THEN raw.amount*1000 END
                    IS NOT DISTINCT FROM s.turnover_amount_local"""),
            ("adj_factor", "s.price_adj_factor IS NOT NULL", "adj_batch", """raw.adj_factor=s.price_adj_factor
                OR abs(raw.adj_factor-s.price_adj_factor)<=1e-12+1e-10*abs(s.price_adj_factor)"""),
        ):
            result = con.sql(f"""WITH candidates AS (
                SELECT s.instrument_id,s.local_trade_date,s.input_valid,
                  count(raw._batch_id) AS raw_candidates,
                  count_if(raw._batch_id IS NOT NULL AND ({match})) AS matches
                FROM stock s LEFT JOIN quote q USING(provenance_id) JOIN aliases a USING(instrument_id)
                LEFT JOIN {endpoint} raw ON raw.ts_code=a.symbol AND raw._batch_id=q.{batch}
                    AND raw.trade_date=strftime(s.local_trade_date,'%Y%m%d')
                WHERE {where} GROUP BY 1,2,3)
                SELECT count(*) AS security_days,count_if(matches>0) AS matching_days,
                  count_if(raw_candidates=0) AS no_linked_raw_row,
                  count_if(raw_candidates>0 AND matches=0) AS conflicting_days,
                  count_if(matches=0 AND input_valid) AS input_valid_without_match,
                  count_if(matches>0 AND raw_candidates>matches) AS matching_alongside_other_candidates
                FROM candidates""")
            counts[endpoint].update(dict(zip(result.columns, result.fetchone(), strict=True)))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result = reconcile(args.source, args.report.with_suffix(".tmp"))
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
