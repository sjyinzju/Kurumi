"""Audit compact CN inputs on stratified old-train rows and screen the full pool for equal X."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from probe_cn_efficiency_render import check_remaining_input, history_values, percentiles, token_counts

from kurumi.cn_efficiency_pool import EfficiencyDataset
from kurumi.cn_efficiency_render import _value, compact_request
from kurumi.karpo_numeric import KarpoNumericEncoder, request_from_input
from kurumi.numeric_loader import CHANNELS

POOL_COLUMNS = "p.sample_id, p.local_trade_date, p.exchange, p.sector, p.market_state"
GROUPABLE = {
    "[Identity]", "[Stock factors]", "[Industry]", "[Market]", "[CSI All Share gross total return H00985]",
    "[Current: prices in quote currency/share, volume in million shares, cap in million quote currency]",
    "[As-of financials: amounts in million reporting currency]",
}


def chunks(rows, size):
    rows = iter(rows)
    while batch := list(islice(rows, size)):
        yield batch


def scan_scope(db, dataset, pool):
    daily = (dataset.directory / "stock_daily/market_id=CN/year=*/*.parquet").as_posix()
    db.from_parquet(str(pool / "pool.parquet")).create_view("p")
    db.from_parquet(daily, hive_partitioning=True).create_view("d")


def select_strata(db):
    design = {
        "year_exchange": ("year(local_trade_date), exchange", "true", 16),
        "year_market_state": ("year(local_trade_date), market_state", "true", 5),
        "sector": ("sector", "true", 5),
        "low_volatility": ("year(local_trade_date)", "low_volatility", 5),
        "low_liquidity": ("year(local_trade_date)", "low_liquidity", 5),
        "missing_industry": ("year(local_trade_date)", "sector IS NULL", 5),
    }
    rows = {}
    for name, (partition, predicate, size) in design.items():
        picks = db.execute(f"""
            SELECT sample_id, local_trade_date, exchange, sector, market_state FROM p
            WHERE split='train' AND ({predicate})
            QUALIFY row_number() OVER (PARTITION BY {partition}
                                      ORDER BY md5(sample_id || ':17'), sample_id) <= {size}
        """).fetchall()
        for sid, day, exchange, sector, state in picks:
            rows.setdefault(sid, dict(id=sid, day=day, exchange=exchange, sector=sector,
                                      market_state=state, strata=[]))["strata"].append(name)
    stress = {
        "largest_magnitude_observed_daily_move": ("isfinite(log_return_1d)", "abs(log_return_1d) DESC"),
        "largest_observed_history_volatility": ("isfinite(volatility_60d_daily)", "volatility_60d_daily DESC"),
        "smallest_observed_raw_close": ("close_raw>0", "close_raw"),
        "largest_observed_raw_close": ("isfinite(close_raw)", "close_raw DESC"),
        "smallest_nonzero_daily_volume": ("volume_shares>0", "volume_shares"),
        "missing_volume_unit_chain": ("NOT split_chain_known", "md5(sample_id || ':17')"),
    }
    for name, (predicate, order) in stress.items():
        picks = db.execute(f"""
            SELECT {POOL_COLUMNS} FROM p JOIN d USING (local_trade_date)
            WHERE d.year<=2023 AND p.split='train' AND p.security_id=d.instrument_id AND ({predicate})
            QUALIFY row_number() OVER (PARTITION BY p.exchange ORDER BY {order}, p.sample_id)<=8
        """).fetchall()
        for sid, day, exchange, sector, state in picks:
            rows.setdefault(sid, dict(id=sid, day=day, exchange=exchange, sector=sector,
                                      market_state=state, strata=[]))["strata"].append(name)
    return sorted(rows.values(), key=lambda row: (row["day"], row["id"]))


def grouped_missing(request):
    lines, absent = [], []
    in_section = False

    def flush():
        if len(absent) > 1:
            lines.append("NA fields: " + ",".join(absent))
        else:
            lines.extend(field + "=NA" for field in absent)
        absent.clear()

    for line in request["state"].splitlines():
        if line.startswith("[") or line.startswith("Coverage ("):
            flush()
            in_section = line in GROUPABLE
        if in_section and line.endswith("=NA"):
            absent.append(line.removesuffix("=NA"))
        else:
            lines.append(line)
    flush()
    return dict(request, state="\n".join(lines))


def expand_missing(request):
    lines = []
    for line in request["state"].splitlines():
        if line.startswith("NA fields: "):
            lines.extend(field + "=NA" for field in line.removeprefix("NA fields: ").split(","))
        else:
            lines.append(line)
    return dict(request, state="\n".join(lines))


def token_audit(dataset, pool, tokenizer):
    with duckdb.connect() as db:
        db.execute("SET threads=4")
        db.execute("SET memory_limit='2GB'")
        scan_scope(db, dataset, pool)
        picks = select_strata(db)
    native = KarpoNumericEncoder.from_checkpoint(tokenizer, max_length=8192)
    outcomes = []
    for batch in chunks(picks, 48):
        xs = dataset.load_model_inputs([row["id"] for row in batch])
        for row, x in zip(batch, xs, strict=True):
            day = row.pop("day")
            baseline = request_from_input(x)
            compact = compact_request(x)
            candidate = grouped_missing(compact)
            expanded = expand_missing(candidate)
            check_remaining_input(baseline, compact)
            check_remaining_input(baseline, expanded)
            original = baseline["state"].splitlines()
            start = original.index(",".join(("session_offset", *CHANNELS))) + 1
            # Round-trip the history with unchanged values and exactly 60 ordered sessions.
            decoded = history_values(compact)
            if len(decoded) != 60 or history_values(expanded) != decoded or any(
                tuple(decoded[i][channel] for channel in CHANNELS)
                != tuple(None if v == "NA" else Decimal(v) for v in line.split(",")[1:])
                for i, line in enumerate(original[start:start + 60])
            ):
                raise ValueError(f"Rendered history changed: {row['id']}")
            counts = {}
            for name, request in (("baseline", baseline), ("compact", compact), ("group_missing", candidate)):
                length, shared, parts, _ = token_counts(native, request)
                counts[name] = dict(length=length, shared=shared, parts=parts)
            outcomes.append(dict(row, day=day.isoformat(), year=day.year,
                                 segment="fit" if day.year <= 2019 else "compare" if day.year <= 2021 else "confirm",
                                 **counts))
        print(f"Tokenized and compared {len(outcomes)}/{len(picks)} CN inputs", flush=True)

    def summary(rows):
        result = {arm: percentiles([r[arm]["length"] for r in rows])
                  for arm in ("baseline", "compact", "group_missing")}
        means = {arm: sum(row[arm]["length"] for row in rows) / len(rows) for arm in result}
        return dict(samples=len(rows), exchange=dict(Counter(r["exchange"] for r in rows)), tokens=result,
                    means=means, compact_reduction=1 - means["compact"] / means["baseline"],
                    group_missing_extra_reduction=1 - means["group_missing"] / means["compact"],
                    parts={arm: dict(Counter(r[arm]["parts"] for r in rows)) for arm in result})

    return dict(dataset_version=dataset.dataset_version, tokenizer_revision=native.tokenizer_revision,
                encoder_revision=native.encoder_revision, selects_from="old_train, PIT input state only",
                overall=summary(outcomes),
                by_segment={s: summary([r for r in outcomes if r["segment"] == s]) for s in ("fit", "compare", "confirm")},
                by_year={str(y): summary([r for r in outcomes if r["year"] == y]) for y in range(2015, 2024)},
                strata=dict(Counter(s for row in outcomes for s in row["strata"])), rows=outcomes)


def visible_key(close, volume, cap, sigma):
    # Each component is verbatim the compact numeric spelling. Equal X forces equal keys.
    return "|".join((_value(close), _value(volume, divisor=1e6), _value(cap, divisor=1e6), _value(sigma)))


def equality_audit(dataset, pool, temp_root):
    with TemporaryDirectory(dir=temp_root, prefix=".equality-") as tmp, duckdb.connect() as db:
        db.execute("SET threads=4")
        db.execute("SET memory_limit='2GB'")
        db.execute("SET temp_directory=?", [tmp])
        scan_scope(db, dataset, pool)
        db.create_function("visible_key", visible_key, ["DOUBLE"] * 4, "VARCHAR", null_handling="special")
        db.execute("CREATE TEMP TABLE screen (sample_id VARCHAR, screening_key UBIGINT)")
        for year in range(2015, 2027):
            db.execute("""
                INSERT INTO screen
                SELECT p.sample_id, hash(visible_key(d.close_raw, d.volume_shares, d.security_market_cap_local,
                                                    d.volatility_60d_daily))
                FROM p JOIN d ON d.instrument_id=p.security_id AND d.local_trade_date=p.local_trade_date
                WHERE d.year=? AND year(p.local_trade_date)=?
            """, [year, year])
            print(f"Screened {year}", flush=True)
        population = db.execute("SELECT count(*) FROM p").fetchone()[0]
        screening = db.execute("SELECT count(*), count(DISTINCT sample_id) FROM screen").fetchone()
        if screening != (population, population):
            raise ValueError(f"Full X screen must match the pool exactly once per sample: {screening} vs {population}")
        repeats = db.execute("""
            WITH collisions AS (SELECT screening_key FROM screen GROUP BY 1 HAVING count(*)>1)
            SELECT screening_key, sample_id FROM screen SEMI JOIN collisions USING (screening_key) ORDER BY 1,2
        """).fetchall()

    identity, no_identity = defaultdict(list), defaultdict(list)
    for batch in chunks(repeats, 64):
        xs = dataset.load_model_inputs([sid for _, sid in batch])
        for (_, sid), x in zip(batch, xs, strict=True):
            request = compact_request(x)
            state = request["state"]
            begin, end = state.index("[Identity]\n"), state.index("[Current:")
            without_identity = dict(request, state=state[:begin] + state[end:])
            identity[json.dumps(request, sort_keys=True)].append(sid)
            no_identity[json.dumps(without_identity, sort_keys=True)].append(sid)
    return dict(check_scope="full eligible pool, X only", eligible_samples=population,
                necessary_key_fields=["close_raw", "volume_shares", "security_market_cap_local", "volatility_60d_daily"],
                screening_candidate_rows=len(repeats), screening_candidate_keys=len({key for key, _ in repeats}),
                equal_X_groups=[group for group in identity.values() if len(group) > 1],
                equal_X_excluding_identity_groups=[group for group in no_identity.values() if len(group) > 1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("tokens", "equality"))
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tokenizer", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    dataset = EfficiencyDataset(args.pool)
    if args.mode == "tokens":
        if args.tokenizer is None:
            parser.error("tokens requires --tokenizer")
        result = token_audit(dataset, args.pool, args.tokenizer)
    else:
        result = equality_audit(dataset, args.pool, args.output.parent)
    manifest = (args.pool / "manifest.json").read_bytes()
    result["pool_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
