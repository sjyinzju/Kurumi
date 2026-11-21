"""Verify the same-listing transition from 000043.SZ to 001914.SZ and its names."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from bs4 import BeautifulSoup

from kurumi.cn_equity_candidates import SZSE_ANNOUNCEMENTS
from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange
from kurumi.cn_name_pit import register_verified_names
from kurumi.cn_pit import _with_provenance

OLD = "000043.SZ"
NEW = "001914.SZ"
INSTRUMENT = "CN-001914.SZ"
SWITCH = "2019-12-16"
CORRECT = "2018-06-01"
STATIC = {
    "2018-05-31-press.html": "https://www.cs.com.cn/ssgs/gsxw/201805/t20180531_5816904.html",
    "2019-12-06-prior.pdf": "https://static.cninfo.com.cn/finalpage/2019-12-06/1207141416.PDF",
    "2019-12-11-szse.html": "https://www.szse.cn/disclosure/notice/general/t20191211_572534.html",
    "2019-12-16-implementation.pdf": "https://static.cninfo.com.cn/finalpage/2019-12-16/1207164397.PDF",
}
CATALOGUE = {
    "2007": ("2007-11-29", "2007-11-30", 35657918),
    "2014": ("2014-10-20", "2014-11-04", 1200328124),
    "2018": ("2018-05-31", "2018-06-02", 1205021684),
}
EXTRACT = """
import json
import sys
import pdfplumber
result = []
for path in sys.argv[1:]:
    with pdfplumber.open(path) as doc:
        result.append('\\n'.join(page.extract_text() or '' for page in doc.pages))
sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
"""


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_sources(root):
    archive = Archive(root, 20, 1.2, allow_network=True, referer="https://www.szse.cn/disclosure/listed/notice/index.html")
    for filename, source in STATIC.items():
        read_exchange(archive, filename, source)
    for year, (first, last, record) in CATALOGUE.items():
        for label, code in ((year, OLD), (year + "-current", NEW)):
            query = dict(seDate=[first, last], channelCode=["listedNotice_disc"], pageSize=30, pageNum=1, stock=[code[:6]])
            body, _ = read_exchange(archive, f"{label}.catalogue.json", SZSE_ANNOUNCEMENTS, payload=query)
            if code != OLD:
                continue
            matches = [row for row in json.loads(body)["data"] if row["annId"] == record and row["secCode"] == [OLD[:6]]]
            if len(matches) != 1:
                raise ValueError(f"Expected one implementation/periodic filing for {year}")
            source = "https://disc.static.szse.cn" + matches[0]["attachPath"]
            read_exchange(archive, f"{year}.{record}.pdf", source)


def verified_archive(root, leaf, version_id):
    path = root / leaf
    receipt = json.loads((root / f"{leaf}.receipt.json").read_bytes())
    if receipt["status"] != 200 or receipt["sha256"] != checksum(path) or receipt["bytes"] != path.stat().st_size:
        raise ValueError(f"Original filing receipt mismatch {leaf}")
    return dict(source_url=receipt["request_url"], source_sha256=receipt["sha256"],
                observed_at=receipt["observed_at"], source_version_id=version_id,
                knowledge_quality="historical_original_evidence")


def clean(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def find_all(text, required, source):
    matched = [re.search(pattern, text) for pattern in required]
    if not all(matched):
        raise ValueError(f"Missing historical trading proof in {source}: {required[matched.index(None)]}")
    return [value[0] for value in matched]


def szse_catalogue(root, year, ann_id, pdf_leaf, *, old_code=OLD):
    name = f"{year}.catalogue.json"
    receipt = verified_archive(root, name, f"SZSE catalogue {year}")
    current = verified_archive(root, f"{year}-current.catalogue.json", f"SZSE alternate code catalogue {year}")
    if receipt["source_sha256"] != current["source_sha256"]:
        raise ValueError(f"The two related official code queries returned different histories in {year}")
    catalog = json.loads((root / name).read_bytes())
    rows = [entry for entry in catalog["data"] if entry["annId"] == ann_id and entry["secCode"] == [old_code[:6]]]
    query_pdf = json.loads((root / f"{pdf_leaf}.receipt.json").read_bytes())["request_url"]
    if len(rows) != 1 or not query_pdf.endswith(rows[0]["attachPath"]):
        raise ValueError(f"Missing unique catalog issuer/filing for {pdf_leaf}")
    return rows[0] | {"source_sha256": receipt["source_sha256"], "source_url": receipt["source_url"]}


def build_sources(root, binary):
    names = {
        "event_2007": ("2007.35657918.pdf", "SZSE 35657918 issuer 2007-52"),
        "period_2014": ("2014.1200328124.pdf", "SZSE 1200328124 Q3 2014"),
        "event_2018": ("2018.1205021684.pdf", "SZSE 1205021684 issuer 2018-31"),
        "press_2018": ("2018-05-31-press.html", "China Securities Journal 5816904"),
        "advance_2019": ("2019-12-06-prior.pdf", "CNINFO 1207141416 issuer 2019-152"),
        "exchange_2019": ("2019-12-11-szse.html", "SZSE t20191211_572534"),
        "event_2019": ("2019-12-16-implementation.pdf", "CNINFO 1207164397 issuer 2019-160"),
    }
    proofs = {key: verified_archive(root, *file_args) for key, file_args in names.items()}
    pdfs = [(key, root / leaf) for key, (leaf, _) in names.items() if leaf.endswith(".pdf")]
    extracted = subprocess.run([str(binary), "-c", EXTRACT, *(str(path) for _, path in pdfs)], capture_output=True, check=True)
    text = {key: clean(body) for (key, _), body in zip(pdfs, json.loads(extracted.stdout), strict=True)}
    for key in ("press_2018", "exchange_2019"):
        text[key] = clean(BeautifulSoup((root / names[key][0]).read_bytes(), "html.parser").get_text(" ", strip=True))
    patterns = {
        "event_2007": (r"2007年11月30日起,由“深南光A”变更为“中航地产”", r"仍为“000043”"),
        "period_2014": (r"证券代码[:：]000043", r"证券简称[:：]中航地产"),
        "event_2018": (r"自2018年6月1日起", r"由“中航地产”变更为“中航善达”", r"仍为“000043”"),
        "press_2018": (r"2018-05-3121:08", r"自6月1日起,公司证券简称由“中航地产”变更为“中航善达”", r"000043"),
        "advance_2019": (r"证券简称及证券代码启用日期[:：]2019年12月16日", r"公司证券简称中航善达招商积余", r"公司证券代码000043001914", r"公司法人主体存续"),
        "exchange_2019": (r"时间[:：]2019-12-11", r"中航善达\(000043\)实施资产重组后更名为招商积余\(001914\)", r"决定于2019年12月16日"),
        "event_2019": (r"证券简称[:：]中航善达", r"变更后的证券代码[:：]001914", r"变更后的证券简称[:：]招商积余", r"2019年12月16日开市起启用", r"公司法人主体存续"),
    }
    for key, checks in patterns.items():
        proofs[key]["source_literals"] = find_all(text[key], checks, key)
    catalogue = {key: szse_catalogue(root, year, ann_id, names[key][0]) for key, year, ann_id in (
        ("event_2007", 2007, 35657918), ("period_2014", 2014, 1200328124), ("event_2018", 2018, 1205021684),
    )}
    for key, record in catalogue.items():
        proofs[key]["exchange_catalogue"] = {field: record[field] for field in ("annId", "secCode", "publishTime", "source_url", "source_sha256")}
    base = dict(instrument_id=INSTRUMENT, ts_code=NEW)
    rows = [
        proofs["event_2007"] | base | dict(symbol_asof=OLD[:6], name_asof="中航地产", effective_from="2014-01-01",
                                          effective_to=CORRECT, published_at="2007-11-30", original_effective_from="2007-11-30",
                                          corroboration_url=proofs["period_2014"]["source_url"],
                                          corroboration_sha256=proofs["period_2014"]["source_sha256"]),
        proofs["press_2018"] | base | dict(symbol_asof=OLD[:6], name_asof="中航善达", effective_from=CORRECT,
                                          effective_to=SWITCH, published_at="2018-05-31T21:08:59+08:00",
                                          source_publication_basis="fact_known_by_clock", press_time_precision="minute",
                                          source_reported_clock="2018-05-31 21:08",
                                          corroboration_url=proofs["event_2018"]["source_url"],
                                          corroboration_sha256=proofs["event_2018"]["source_sha256"]),
        proofs["exchange_2019"] | base | dict(symbol_asof=NEW[:6], name_asof="招商积余", effective_from=SWITCH,
                                             effective_to=None, published_at="2019-12-11",
                                             corroboration_url=proofs["event_2019"]["source_url"],
                                             corroboration_sha256=proofs["event_2019"]["source_sha256"]),
    ]
    alias = proofs["exchange_2019"] | dict(ts_code=NEW, prior_code=OLD, effective_from=SWITCH, published_at="2019-12-11",
                                          corroboration_url=proofs["event_2019"]["source_url"],
                                          corroboration_sha256=proofs["event_2019"]["source_sha256"])
    return rows, alias, proofs


def write_versions(path, versions):
    file = path / "security_name_versions.jsonl"
    file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in versions), encoding="utf-8")
    return file


def verify_on_released_days(dataset, evidence, versions, prefix_cutoffs):
    instrument = versions[0]["instrument_id"]
    new, old = versions[-1]["ts_code"], versions[0]["symbol_asof"] + ".SZ"
    switch = versions[-1]["effective_from"]
    with duckdb.connect() as con:
        ref = str(dataset / "reference/security_history.parquet")
        con.read_parquet(ref).create_view("security_history")
        actual = con.execute("SELECT instrument_id,issuer_id,ts_code,prior_code,code_switch_date FROM security_history WHERE ts_code IN (?,?)",
                             [new, old]).fetchall()
        if actual != [(instrument, instrument, new, None, None)]:
            raise ValueError("The source release no longer has precisely the observed pre-correction identity")
        con.execute(f"""
            CREATE TEMP TABLE test_quotes AS SELECT instrument_id,local_trade_date,name_asof,asof_utc,
                CASE WHEN local_trade_date<DATE '{switch}' THEN '{old[:6]}' ELSE '{new[:6]}' END symbol_asof,
                symbol_asof AS staged_symbol, input_valid,quote_valid,special_treatment_state,provenance_id,missing_reasons,
                NULL::VARCHAR AS name_batch
            FROM read_parquet(?) WHERE ts_code=?
        """, [(dataset / "stock_daily/market_id=CN/year=*/*.parquet").as_posix(), new])
        # Retain the original published symbol separately from the alias simulation used for the name replay.
        view = register_verified_names(con, evidence, "test_quotes")
        con.execute(f"CREATE TABLE actual_names AS SELECT * FROM {view}")
        query = """
            SELECT n.name_asof,n.symbol_asof,min(n.local_trade_date),max(n.local_trade_date),count(*),
                   count_if(q.staged_symbol<>n.symbol_asof),count_if(n.input_valid),count_if(n.quote_valid),
                   count_if(q.name_asof IS DISTINCT FROM n.name_asof),count_if(n.name_batch IS NULL)
            FROM actual_names n JOIN test_quotes q USING(instrument_id,local_trade_date) GROUP BY 1,2 ORDER BY 3
        """
        counts = con.sql(query).fetchall()
        if [(r[0], r[1]) for r in counts] != [(r["name_asof"], r["symbol_asof"]) for r in versions] or any(r[-1] for r in counts):
            raise ValueError("PIT replay failed a verified name/version transition")
        prefix_counts = {}
        for keep, cutoff in prefix_cutoffs:
            with TemporaryDirectory(dir=evidence.parent, prefix="verified-name-prefix-") as stage:
                prefix = [dict(row) for row in versions[:keep]]
                prefix[-1]["effective_to"] = None
                write_versions(Path(stage), prefix)
                con.execute(f"CREATE OR REPLACE VIEW prefix_quotes AS SELECT * FROM test_quotes WHERE local_trade_date<=DATE '{cutoff}'")
                partial = register_verified_names(con, Path(stage), "prefix_quotes")
                rows, differences = con.execute(f"""
                    SELECT count(*),count_if(p.name_asof IS DISTINCT FROM a.name_asof OR p.provenance_id IS DISTINCT FROM a.provenance_id)
                    FROM {partial} p JOIN actual_names a USING(instrument_id,local_trade_date) WHERE a.local_trade_date<=?::DATE
                """, [cutoff]).fetchone()
                if differences:
                    raise ValueError(f"Later name disclosure changed the historical prefix through {cutoff}")
                prefix_counts[cutoff] = rows
        columns = ("name", "historical_symbol", "first_session", "last_session", "sessions", "published_symbol_conflicts",
                   "input_valid", "quote_valid", "published_name_conflicts", "missing_name_proof")
        return {"dataset": dataset.name, "name_intervals": [dict(zip(columns, values, strict=True)) for values in counts],
                "verified_prefix_rows": prefix_counts, "replay_scope": "released_real_rows_with_independent_alias_applied"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ("originals", "output", "pdf-python"):
        cli.add_argument("--" + field, type=Path, required=True)
    cli.add_argument("--dataset", type=Path, nargs="+", required=True)
    cli.add_argument("--fetch-originals", action="store_true")
    args = cli.parse_args()
    if args.fetch_originals:
        fetch_sources(args.originals)
    versions, alias, sources = build_sources(args.originals, args.pdf_python)
    args.output.mkdir(parents=True, exist_ok=True)
    names = write_versions(args.output, versions)
    mapping = args.output / "security_code_changes.json"
    mapping.write_text(json.dumps([alias], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(_with_provenance(args.output, "security_name_versions", {})) != 3:
        raise ValueError("Expected all three verified historical names")
    cutoffs = ((1, "2018-05-31"), (2, "2019-12-11"))
    receipt = {"status": "pass", "sources": sources, "functional_replays": [verify_on_released_days(v, args.output, versions, cutoffs) for v in args.dataset],
               "sha256": {names.name: checksum(names), mapping.name: checksum(mapping)}}
    (args.output / "001914_history_audit.json").write_text(json.dumps(receipt, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"replays": receipt["functional_replays"], "sha256": receipt["sha256"]}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
