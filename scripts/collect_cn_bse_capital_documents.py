"""Locate original issuer statement text near the largest BSE capital gaps for review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import duckdb
import requests
from audit_cn_market_denominator import attach_release, records

LIST_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
BODY_API = "https://np-cnotice-stock.eastmoney.com/api/content/ann"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
TITLE = re.compile(r"权益分派实施|注销|股份变动|登记|授予结果|发行情况|上市公告|定向发行|注册资本|章程")


def largest_gaps(release, capital, limit):
    with duckdb.connect() as con:
        attach_release(con, release)
        con.read_json(capital.as_posix(), convert_strings_to_integers=False).create_view("capital")
        return records(con, """
            WITH scored AS (
                SELECT instrument_id, max(symbol_asof) AS current_code, min(local_trade_date) AS first_listed,
                       count_if(quote_valid AND price_adj_factor > 0 AND security_market_cap_local IS NULL) AS gaps
                FROM stock_daily WHERE exchange='BSE' AND instrument_id<>'CN-830799.BJ'
                GROUP BY instrument_id HAVING length(max(symbol_asof))=6 AND starts_with(max(symbol_asof),'920')
                ORDER BY gaps DESC NULLS LAST, instrument_id LIMIT ?
            ), snapshots AS (
                SELECT instrument_id, current_code, first_listed, gaps, Shrchgdt::DATE AS effective,
                       CASE WHEN count(DISTINCT (Nshrttl,Nshrb,Nshrh,Nshrprf,Nshroft))=1
                                  AND max(Nshrb)=0 AND max(Nshrh)=0 AND max(Nshrprf)=0 AND max(Nshroft)=0
                            THEN max(Nshrttl)::BIGINT END AS shares
                FROM capital a JOIN scored s ON a.Stkcd=s.current_code
                WHERE Shrchgdt::DATE <= DATE '2026-07-31' GROUP BY ALL
            ), changes AS (
                SELECT *, lag(shares) OVER change AS preceding_shares,
                    max(effective) FILTER (WHERE effective<=first_listed) OVER (PARTITION BY instrument_id) AS anchor
                FROM snapshots WINDOW change AS (PARTITION BY instrument_id ORDER BY effective)
            )
            SELECT * EXCLUDE(anchor) FROM changes WHERE shares IS NOT NULL
              AND (effective=anchor OR (effective>first_listed AND shares IS DISTINCT FROM preceding_shares))
            ORDER BY gaps DESC, instrument_id, effective
        """, [limit])


def read_public_json(url, params, output, key):
    cache_key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    cache = output / f"{key}-{cache_key[:16]}.json"
    if cache.is_file():
        saved = json.loads(cache.read_bytes())
        if saved.get("status") == 200:
            return saved
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=(4, 10))
        result = {"status": response.status_code, "request_url": response.url,
                  "response_sha256": hashlib.sha256(response.content).hexdigest()}
        if response.ok:
            result["payload"] = response.json()
            (output / f"{key}-{cache_key[:16]}.response.json").write_bytes(response.content)
    except (requests.RequestException, ValueError) as exc:
        result = {"error": type(exc).__name__, "url": url, "params": params}
    cache.write_text(json.dumps(result, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return result


def list_near_change(target, output):
    code = target["current_code"]
    effective = target["effective"]
    following_days = 90 if (effective.month, effective.day) in ((6, 30), (3, 31), (9, 30), (12, 31)) else 24
    result = read_public_json(LIST_API, {
        "sr": -1, "st": "notice_date", "page_size": 100, "page_index": 1, "ann_type": "A,BJA",
        "client_source": "web", "f_node": 0, "s_node": 0, "stock_list": code,
        "begin_time": str(effective - timedelta(days=16)),
        "end_time": str(min(date(2026, 8, 30), effective + timedelta(days=following_days))),
    }, output, code + "-listing")
    items = ((result.get("payload") or {}).get("data") or {}).get("list") or []
    candidates = [item for item in items if TITLE.search(item.get("title_ch") or item.get("title") or "")
                  and "已取消" not in (item.get("title_ch") or item.get("title") or "")]
    return dict(target, request_status=result.get("status"), request_error=result.get("error"),
                request_sha256=result.get("response_sha256"), response_items=len(items),
                articles=[item["art_code"] for item in candidates])


def read_notice(article, output):
    result = read_public_json(BODY_API, {"art_code": article, "client_source": "web", "page_index": 1}, output, article)
    payload = (result.get("payload") or {}).get("data") or {}
    return article, result | {"fields": payload}


def exact_overlaps(target, bodies):
    share = target["shares"]
    prior = target["preceding_shares"]
    effective = "{}年{}月{}日".format(target["effective"].year, target["effective"].month, target["effective"].day)
    result = []
    for article in target["articles"]:
        body = bodies[article]
        detail = body["fields"]
        data = re.sub(r"[\s,，]", "", detail.get("notice_content") or "")
        exact_count = re.search(rf"(?<!\d){share}(?!\d)", data)
        if not exact_count:
            continue
        prior_match = bool(prior is not None and re.search(rf"(?<!\d){prior}(?!\d)", data))
        result.append({
            "article_id": article, "title": detail.get("notice_title"), "notice_date": detail.get("notice_date"),
            "page_count": detail.get("page_size"), "prior_amount_found": prior_match, "source_url": body["request_url"],
            "exact_effective_found": effective in data, "published_body_sha256": body["response_sha256"],
            "near_new_amount": data[max(0, exact_count.start() - 20):exact_count.end() + 24],
        })
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("release", type=Path)
    cli.add_argument("--csmar-capital", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--issuers", default=4, type=int, choices=range(1, 9))
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "original_responses"
    cache.mkdir(exist_ok=True)
    targets = largest_gaps(args.release, args.csmar_capital, args.issuers)
    with ThreadPoolExecutor(max_workers=4) as pool:
        locators = list(pool.map(partial(list_near_change, output=cache), targets))
        articles = sorted({article for target in locators for article in target["articles"]})
        bodies = dict(pool.map(partial(read_notice, output=cache), articles))
    result = {
        "dataset_version": json.loads((args.release / "manifest.json").read_bytes())["dataset_version"],
        "scope": "supplier_caps_only_target_selection_human_checks_required",
        "inspected_article_count": len(bodies),
        "targets": [target | {"exact_overlaps": exact_overlaps(target, bodies)} for target in locators],
    }
    (args.output / "bse_archive_candidate_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8",
    )
    matched = sum(bool(target["exact_overlaps"]) for target in result["targets"])
    print(len(targets), "dated capital events", len(bodies), "archived notices", matched,
          "events with exact amount in at least one notice")


if __name__ == "__main__":
    main()
