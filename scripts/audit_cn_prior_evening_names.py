"""Verify early public knowledge of exchange-confirmed security abbreviation changes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from bs4 import BeautifulSoup

from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_name_pit import register_verified_names
from kurumi.cn_pit import _with_provenance

LOCAL = ZoneInfo("Asia/Shanghai")
# Each publicity clock was read from the archived newsroom response for the reviewed event.
PRESS = (
    ("000791", "2023-02-17", "甘肃电投", "甘肃能源", "2023年02月16日 18:41:53", "https://www.cls.cn/detail/1269255"),
    ("000629", "2022-09-08", "攀钢钒钛", "钒钛股份", "2022-09-07 17:47", "https://www.stcn.com/article/detail/680190.html"),
    ("002501", "2023-05-19", "利源精制", "利源股份", "2023-05-18 19:47:08", "https://www.nbd.com.cn/articles/2023-05-18/2831594.html"),
    ("000796", "2019-12-25", "凯撒旅游", "凯撒旅业", "2019-12-24 18:30", "https://m.cls.cn/detail/421392"),
    ("002201", "2021-11-11", "九鼎新材", "正威新材", "2021-11-10 18:06:00", "https://m.yicai.com/news/101225505.html"),
    ("002420", "2021-11-11", "毅昌股份", "毅昌科技", "2021-11-10 18:06:00", "https://m.yicai.com/news/101225505.html"),
    ("300650", "2021-10-15", "太龙照明", "太龙股份", "2021-10-14 19:27:34", "https://finance.sina.com.cn/7x24/2021-10-14/doc-iktzscyx9687277.shtml"),
    ("002976", "2021-12-31", "瑞玛工业", "瑞玛精密", "2021.12.30 16:03", "https://finance.sina.cn/stock/ssgs/2021-12-30/detail-ikyamrmz2168887.d.html?wm=3049_0015"),
    ("000697", "2018-11-06", "炼石有色", "炼石航空", "2018-11-05 18:30:07", "https://m.yicai.com/news/100053144.html"),
    ("300341", "2019-01-22", "麦迪电气", "麦克奥迪", "2019-01-21 18:31:37", "https://m.yicai.com/news/100103608.html"),
    ("000889", "2018-12-11", "茂业通信", "中嘉博创", "2018-12-10 18:30:58", "https://www.yicai.com/news/100076662.html"),
    ("300306", "2017-09-07", "远方光电", "远方信息", "2017-09-06 18:51:23", "https://www.yicai.com/news/5341563.html"),
    ("300464", "2020-12-22", "星徽精密", "星徽股份", "2020-12-21 21:07", "https://www.cls.cn/detail/645359"),
    ("002729", "2021-09-24", "好利来", "好利科技", "2021-09-23 21:37", "https://www.stcn.com/article/detail/446377.html"),
    ("003027", "2024-12-26", "同兴环保", "同兴科技", "2024-12-25 22:55", "https://www.sohu.com/a/841859722_120988576"),
)
EXTRACT = """
import json
import sys
import pdfplumber
all_text = []
for path in sys.argv[1:]:
    with pdfplumber.open(path) as pdf:
        all_text.append('\\n'.join(page.extract_text() or '' for page in pdf.pages))
sys.stdout.buffer.write(json.dumps(all_text, ensure_ascii=False).encode('utf-8'))
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def event_date_pattern(day, with_year):
    prefix = rf"{day.year}年" if with_year else rf"(?:{day.year}年)?"
    return rf"{prefix}0?{day.month}月0?{day.day}日"


def compact(text):
    return re.sub(r"\s+", "", text)


def fetch_press(root):
    archive = Archive(root, len(PRESS), 0.8, allow_network=True)
    for url in dict.fromkeys(row[-1] for row in PRESS):
        filename = digest(url.encode())[:16] + ".html"
        if not (root / filename).with_suffix(".receipt.json").is_file():
            archive.session.headers.update({"Referer": url})
            archive.read(filename, url)


def press_evidence(root, url, display, on, old, new):
    file = root / (digest(url.encode())[:16] + ".html")
    receipt_file = file.with_suffix(".receipt.json")
    if not receipt_file.is_file():
        receipt_file = file.with_name(file.name + ".receipt.json")
    receipt = json.loads(receipt_file.read_bytes()) | {"file": file.name}
    body = file.read_bytes()
    if receipt["status"] != 200 or receipt["sha256"] != digest(body) or receipt["request_url"] != url:
        raise ValueError(f"Unverified archived page {url}")
    visible = compact(BeautifulSoup(body, "html.parser").get_text(" ", strip=True))
    if compact(display) not in visible and f"[ published at {display} ]" not in body.decode("utf-8", "replace"):
        raise ValueError(f"Original media timestamp unavailable {url}")
    date_text, clock_text = display.split()
    date_text = re.sub(r"[.年月]", "-", date_text).removesuffix("日")
    known = datetime.fromisoformat(f"{date_text}T{clock_text}").replace(tzinfo=LOCAL)
    precision = "second" if clock_text.count(":") == 2 else "minute"
    if known.date() + timedelta(days=1) != on or known.hour < 15:
        raise ValueError(f"Publication outside the previous evening {url}")
    if precision == "minute":
        known = known.replace(second=59)
    date_pattern = event_date_pattern(on, False)
    for new_match in re.finditer(re.escape(new), visible):
        nearby = visible[max(0, new_match.start()-130):new_match.end()+110]
        if old in nearby and "简称" in nearby and re.search(date_pattern, nearby):
            return known, precision, receipt
    raise ValueError(f"Media article does not confirm the reviewed names/effective date {url}")


def official_sources(root):
    return {receipt["source_url"]: receipt for file in (root / "originals").glob("*.json")
            if (receipt := json.loads(file.read_bytes())).get("http_status") == 200}


def audit(args):
    sources = official_sources(args.catalogue)
    reviewed = []
    for code, day, old, new, display, url in PRESS:
        trade = date.fromisoformat(day)
        ts_code = code + ".SZ"
        listing = json.loads((args.catalogue / f"{ts_code}_{day}.json").read_bytes())
        originals = [sources[url] for url in listing["matches"] if url in sources
                     and "简称" in sources[url]["title"] and "独立意见" not in sources[url]["title"]]
        if len(originals) != 1 or not listing["input_valid"] or listing["date"] != day:
            raise ValueError(f"Missing unique exchange match for valid input {ts_code} {day}")
        official = originals[0]
        document = args.catalogue / "originals" / official["file"]
        if digest(document.read_bytes()) != official["sha256"]:
            raise ValueError(f"Exchange original hash mismatch {ts_code} {day}")
        known, precision, bulletin = press_evidence(args.press, url, display, trade, old, new)
        reviewed.append((code, day, old, new, display, document, official, known, precision, bulletin))
    extracts = subprocess.run([str(args.pdf_python), "-c", EXTRACT, *(str(entry[5]) for entry in reviewed)],
                              capture_output=True, check=True).stdout
    admitted = []
    for (code, day, old, new, display, _, official, known, precision, bulletin), pdf in zip(reviewed, json.loads(extracts), strict=True):
        phrase = re.search(event_date_pattern(date.fromisoformat(day), True), compact(pdf))
        if phrase is None or code not in compact(pdf) or old not in compact(pdf) or new not in compact(pdf):
            raise ValueError(f"Exchange original does not establish the precise name change {code} {day}")
        admitted.append(dict(ts_code=code + ".SZ", symbol_asof=code, name_asof=new, prior_name=old,
                             effective_from=day, effective_to=(date.fromisoformat(day) + timedelta(days=1)).isoformat(),
                             effective_scope="observed_missing_session_only", published_at=known.isoformat(),
                             knowledge_quality="historical_original_evidence", source_url=bulletin["url"],
                             source_sha256=bulletin["sha256"], observed_at=bulletin["observed_at"],
                             source_version_id=f"{code}:{bulletin['file']}", source_reported_clock=display,
                             press_time_precision=precision, source_publication_basis="fact_known_by_clock",
                             corroboration_url=official["source_url"], corroboration_sha256=official["sha256"],
                             corroboration_version=official["source_version_id"], corroboration_effective_date=phrase[0],
                             proof_scope="verified_implementation_not_board_proposal"))
    return admitted


def actual_scope(con, dataset, rows):
    history = str(dataset / "reference/security_history.parquet")
    con.read_parquet(history).create_view("security_history")
    con.execute("CREATE TEMP TABLE expected_names(ts_code VARCHAR, ast DATE, old_name VARCHAR, new_name VARCHAR)")
    con.executemany("INSERT INTO expected_names VALUES (?,?,?,?)", [
        (row["ts_code"], row["effective_from"], row["prior_name"], row["name_asof"]) for row in rows
    ])
    stocks = (dataset / "stock_daily/market_id=CN/year=*/*.parquet").as_posix()
    con.execute("""
        CREATE TABLE target_quotes AS SELECT p.instrument_id,p.ts_code,p.local_trade_date,p.symbol_asof,p.name_asof,
            p.asof_utc,p.input_valid,p.special_treatment_state,p.provenance_id,p.missing_reasons,NULL::VARCHAR AS name_batch
        FROM read_parquet(?) p JOIN expected_names n ON (p.ts_code=n.ts_code AND abs(p.local_trade_date-n.ast)<=3)
    """, [stocks])
    mapped = con.sql("""SELECT n.ts_code, q.instrument_id FROM expected_names n JOIN target_quotes q
                        ON q.ts_code=n.ts_code AND q.local_trade_date=n.ast
                        WHERE q.name_asof IS NULL AND q.input_valid""").fetchall()
    if len(mapped) != len(rows) or len(mapped) != len({code for code, _ in mapped}):
        raise ValueError("Reviewed receipt does not identify exactly one missing, valid session per name")
    return dict(mapped)


def compare_production(con, output, dataset):
    view = register_verified_names(con, output, "target_quotes")
    observed = con.sql(f"""
        SELECT count(*), count_if(p.name_asof IS DISTINCT FROM r.name_asof),
               count_if(p.local_trade_date=n.ast AND r.name_asof=n.new_name AND p.input_valid),
               count_if(p.local_trade_date<>n.ast AND p.name_asof IS DISTINCT FROM r.name_asof)
        FROM target_quotes p JOIN {view} r USING(instrument_id,local_trade_date) JOIN expected_names n ON p.ts_code=n.ts_code
    """).fetchone()
    days, changes, matched, non_target_changes = observed
    if changes != matched or non_target_changes or matched != con.sql("SELECT count(*) FROM expected_names").fetchone()[0]:
        raise ValueError("Production PIT name assembly exceeded the validated scope or missed a requested row")
    return dict(source_version=dataset.name, total_dates_compared=days, filled_input_valid_name_dates=matched,
                affected_dates_outside_review_scope=non_target_changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("catalogue", "press", "pdf-python", "dataset", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--fetch-press", action="store_true")
    args = parser.parse_args()
    if args.fetch_press:
        fetch_press(args.press)
    rows = audit(args)
    args.output.mkdir(exist_ok=True, parents=True)
    fact_path = args.output / "security_name_versions.jsonl"
    with duckdb.connect() as con:
        mapped = actual_scope(con, args.dataset, rows)
        rows = [dict(row, instrument_id=mapped[row["ts_code"]]) for row in rows]
        fact_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        if len(_with_provenance(args.output, "security_name_versions", {})) != len(rows):
            raise ValueError("Native verification rejected a source receipt")
        report = compare_production(con, args.output, args.dataset)
    with (args.output / "prior_evening_name_facts.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report["stage_sha256"] = digest(fact_path.read_bytes())
    (args.output / "prior_evening_name_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
