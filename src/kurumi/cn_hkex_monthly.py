"""Archive HKEX official issuer monthly returns and verify the reported A/H balances."""

from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import duckdb
import requests

SITE = "https://www1.hkexnews.hk"
HK = ZoneInfo("Asia/Hong_Kong")
MONTHLY_CATEGORY = 51500
TREASURY_RULE_START = date(2024, 6, 11)
PRIORITY = ("01398", "01288", "00939", "03988", "02318", "01211", "03968", "01658")
DELISTED = {"06837": 69665, "06116": 111475}
A_LISTING_END = {"06116": date(2022, 5, 23)}
FORM_SECTION = re.compile(r"(?ims)^\s*II\.\s*Movements in Issued[^\n]*\n(.*?)(?=^\s*III\.\s*Details|\Z)")
CLASS = re.compile(
    r"(?im)^\s*\d+\.\s*Class of shares\s+([^\n]+?)\s+Type of shares\s+([^\n]+?)\s+Listed on\b"
)
INTEGER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
STOCK_PATH = re.compile(r"/listedco/listconews/sehk/\d{4}/\d{4}/(?:ltn)?\d+\.pdf", re.I)


class StopDownload(RuntimeError):
    """End this bounded run with only the obtained receipts."""


class Archive:
    def __init__(self, root, max_requests, interval, *, allow_network=False, referer=None):
        self.root = root
        self.max_requests = max_requests
        self.interval = interval
        self.allow_network = allow_network
        self.calls = 0
        self.last_call = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0",
                                     "Referer": referer or SITE + "/search/titlesearch.xhtml?lang=en"})
        root.mkdir(parents=True, exist_ok=True)

    def read(self, name, url, params=None, *, payload=None):
        file = self.root / name
        receipt = self.root / f"{name}.receipt.json"
        method = "POST" if payload is not None else "GET"
        requested = requests.Request(method, url, params=params).prepare().url
        if file.is_file() and receipt.is_file():
            body = file.read_bytes()
            evidence = json.loads(receipt.read_bytes())
            if evidence["sha256"] != hashlib.sha256(body).hexdigest() or evidence["status"] != 200:
                raise ValueError(f"Invalid saved response {file}")
            target, stored = urlsplit(requested), urlsplit(evidence.get("request_url", evidence["url"]))
            if (target[:3] != stored[:3] or sorted(parse_qsl(target.query)) != sorted(parse_qsl(stored.query))
                    or payload != evidence.get("request")):
                raise ValueError(f"Saved response belongs to a different request {file}")
            return body, evidence
        if not self.allow_network:
            raise StopDownload("cache_miss_live_hkex_disabled")
        if self.calls >= self.max_requests:
            raise StopDownload("request_budget_exhausted")
        time.sleep(max(0, self.interval - (time.monotonic() - self.last_call)))
        self.calls += 1
        self.last_call = time.monotonic()
        try:
            response = self.session.request(method, url, params=params, json=payload, timeout=(10, 30))
        except requests.RequestException as exc:
            with (self.root / "failed_requests.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"name": name, "url": url, "kind": type(exc).__name__}) + "\n")
            raise StopDownload(f"transport_{type(exc).__name__}") from None
        body = response.content
        evidence = {
            "name": name, "url": response.url, "request_url": requested, "status": response.status_code,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        if payload is not None:
            evidence["request"] = payload
        if not response.ok:
            with (self.root / "failed_requests.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(evidence) + "\n")
            if response.status_code in (403, 429) or response.status_code >= 500:
                raise StopDownload(f"HTTP_{response.status_code}")
            return None, evidence
        for destination, contents in ((file, body), (receipt, json.dumps(evidence).encode())):
            part = destination.with_name(destination.name + ".partial")
            part.write_bytes(contents)
            part.replace(destination)
        return body, evidence


def planned_cohort(capture, quotes):
    with duckdb.connect() as con:
        quoted = {r[0] for r in con.execute("""
            SELECT DISTINCT substring(class_id,1,5) FROM read_parquet(?) WHERE ends_with(class_id,'.HK')
        """, [str(quotes)]).fetchall()}
    linked = defaultdict(set)
    a_listings = defaultdict(list)
    for file in sorted(capture.glob("*.jsonl.gz")):
        with gzip.open(file, "rt", encoding="utf-8-sig") as stream:
            for line in stream:
                row = json.loads(line)
                a = str(row.get("Stkcd") or "")
                h = str(row.get("Commnt") or "").strip()
                if (re.fullmatch(r"\d{6}", a) and re.fullmatch(r"\d{1,5}", h)
                        and row.get("Markettype") in (1, 4, 16, 32, 64)):
                    code = h.zfill(5)
                    linked[code].add(a)
                    listed = str(row.get("Listdt") or "")
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", listed):
                        a_listings[code].append(listed)
    result = {
        h: {"a_candidates": sorted(a), "local_h_quotes": h in quoted,
            "earliest_candidate_a_listing": min(a_listings[h], default=None)}
        for h, a in linked.items()
    }
    return dict(sorted(result.items(), key=lambda row: (
        row[0] not in PRIORITY, PRIORITY.index(row[0]) if row[0] in PRIORITY else 0,
        not row[1]["local_h_quotes"], row[0],
    )))


def lookup(archive, code):
    body, _ = archive.read(
        f"lookup-{code}.jsonp", SITE + "/search/prefix.do",
        {"callback": "callback", "lang": "EN", "type": "A", "name": code, "market": "SEHK"},
    )
    if not body:
        return None
    envelope = re.fullmatch(r"callback\((.*)\);\s*", body.decode("utf-8-sig"), re.S)
    if envelope is None:
        raise ValueError("Unexpected stock lookup response")
    candidates = [int(row["stockId"]) for row in json.loads(envelope[1])["stockInfo"] if row["code"] == code]
    return candidates[0] if len(candidates) == 1 else None


def published(row):
    return datetime.strptime(row["DATE_TIME"], "%d/%m/%Y %H:%M").replace(tzinfo=HK)


def listing(archive, code, issuer, start, end, category=0):
    for row_range in range(200, 1001, 100):
        body, evidence = archive.read(
            f"titles-{code}-{issuer}-{start}-{end}-{row_range}.json", SITE + "/search/titleSearchServlet.do", {
                "sortDir": 0, "sortByOptions": "DateTime", "category": category, "market": "SEHK",
                "stockId": issuer, "documentType": -1, "title": "", "searchType": 0,
                "t1code": MONTHLY_CATEGORY, "t2Gcode": -2, "t2code": -2, "rowRange": row_range,
                "lang": "EN", "fromDate": start, "toDate": end,
            },
        )
        if not body:
            return None, evidence
        response = json.loads(body)
        rows = json.loads(response["result"] or "[]")
        count = int(response["recordCnt"])
        if count != len(rows) or response["hasNextRow"] is not False:
            continue
        accepted = []
        for row in rows:
            when = published(row).strftime("%Y%m%d")
            symbols = re.split(r"\s*<br\s*/?>\s*", row["STOCK_CODE"], flags=re.I)
            if code not in symbols or not start <= when <= end or any(not s.isdecimal() for s in symbols):
                raise ValueError(f"Invalid exchange listing scope for {code}")
            classification = row["LONG_TEXT"]
            if classification in ("Monthly Returns", "(Headline Revised) Monthly Returns", "(Headlines Revised) Monthly Returns"):
                accepted.append(row)
            elif not re.fullmatch(r"\(Cancelled[^)]*\) Monthly Returns", classification, flags=re.I):
                raise ValueError(f"Unrecognized monthly filing classification for {code}")
        if len({row["NEWS_ID"] for row in rows}) != len(rows):
            raise ValueError(f"Repeated disclosure id for {code}")
        return accepted, evidence | {"listed_metadata_rows": count, "cancelled_metadata_rows": count - len(accepted)}
    raise ValueError(f"HKEX listing cap exceeded for {code}")


def reported_month(text):
    match = re.search(
        r"(?is)For the month ended.{0,90}?\b(\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{4}|\d{1,2}\s+[a-z]+\s+\d{4})\b",
        text,
    )
    if not match:
        raise ValueError("unknown_month_end")
    literal = " ".join(match[1].split())
    result = (datetime.strptime(literal.replace(" ", ""), "%d/%m/%Y") if "/" in literal
              else datetime.strptime(literal, "%d %B %Y")).date()
    if result.day != calendar.monthrange(result.year, result.month)[1]:
        raise ValueError("non_month_end")
    return result


def closing_cells(section):
    match = re.search(r"(?im)^\s*Balance at close of\s+the\s+month\b([^\r\n]*\S)[ \t]*$", section)
    if match:
        cells = match[1].split()
    else:
        match = re.search(r"(?im)^\s*Balance at close of the[ \t]*([^\r\n]*)\r?\n(?:[ \t]*\r?\n)*"
                          r"(?:[ \t]*([0-9][^\r\n]*)\r?\n(?:[ \t]*\r?\n)*)?[ \t]*month\b([^\r\n]*)", section)
        if not match:
            raise ValueError("missing_close_balance_line")
        cells = re.sub(r"\b[AH] shares\b", "", " ".join(x or "" for x in match.groups()), flags=re.I).split()
    if not cells or not all(INTEGER.fullmatch(cell) or cell.lower() in ("nil", "n/a", "-", "–")
                            for cell in cells):
        raise ValueError("ambiguous_close_balance_line")
    return [int(c.replace(",", "")) if INTEGER.fullmatch(c) else 0 for c in cells], match


def legacy_column_names(section, header, authorized, balances):
    names = [x[1].lower() for x in re.finditer(r"(?i)\b([AH]) shares\b", header)]
    domestic = re.search(r"(?i)\((\d+)\)\s*domestic\b", header)
    if domestic and (domestic[1] != "3" or len(balances) < 5 or balances[2] != 0):
        raise ValueError("legacy_domestic_ordinary_shares_remaining")
    if re.search(r"(?i)\bB shares\b", header) or (re.search(r"\(3\)", header) and not domestic):
        raise ValueError("legacy_other_ordinary_class_scope_unresolved")
    if len(balances) < 2 or "other" not in header.lower():
        raise ValueError("legacy_other_ordinary_class_scope_unresolved")
    named_codes = []
    if names not in (["a", "h"], ["h", "a"]):
        columns = list(re.finditer(
            r"(?im)^\s*\(([12])\) Stock code\s*:[ \t]*\d+[ \t]+Description\s*:[ \t]*([AH]) shares\b",
            authorized,
        ))
        if [m[1] for m in columns] != ["1", "2"] or re.findall(r"\(([12])\)", header) != ["1", "2"]:
            raise ValueError("legacy_ordinary_class_scope_unresolved")
        numbered = [m[2].lower() for m in columns]
        numbered_only = not names and not re.search(r"(?i)\bdomestic shares\b", header)
        domestic_caption = names == ["h"] and numbered == ["h", "a"] and "domestic shares" in header.lower()
        if not numbered_only and not domestic_caption:
            raise ValueError("legacy_ordinary_class_scope_unresolved")
        for i, column in enumerate(columns):
            end = columns[i + 1].start() if i + 1 < len(columns) else len(authorized)
            balance = re.search(r"(?im)^\s*Balance at close of the month[ \t]+([0-9,]+)\b",
                                authorized[column.end():end])
            if not balance or int(balance[1].replace(",", "")) != balances[i]:
                raise ValueError("legacy_numbered_class_not_corroborated")
            named_codes.append(" ".join(column[0].split()))
        names = numbered
    if len(balances) < 4:
        preceding = re.search(r"(?im)\bpreceding month[ \t]+([^\r\n]+)", section)
        no_other_previous = preceding and re.search(r"(?i)[ \t](?:nil|n/a)[ \t]+(?:nil|n/a)\s*$", preceding[1])
        no_other_authorized = re.search(
            r"(?ims)^\s*3\.\s*Other Classes of Shares\s*Stock code[ \t]*:\s*(?:N/A[ \t]+)?Description[ \t]*:"
            r"[ \t]*\r?\n(?:(?!Balance at close of the month).)*Balance at close of the month[ \t]*$", authorized,
        )
        if len(balances) != 2 or not (no_other_previous or no_other_authorized):
            raise ValueError("legacy_missing_other_class_balance")
    elif balances[-1] != 0:
        raise ValueError("legacy_other_ordinary_class_scope_unresolved")
    return names, named_codes


def observed_classes(text, h, candidates):
    period = reported_month(text)
    sec = FORM_SECTION.search(text)
    if sec is None:
        raise ValueError("missing_issued_share_section")
    section = sec[1]
    blocks = list(CLASS.finditer(section))
    found, literals = {}, []
    if blocks:
        if len(blocks) != len(re.findall(r"(?im)^\s*\d+\.\s*Class of shares\b", section)):
            raise ValueError("incomplete_issued_class_scope")
        excluded_treasury = "excluding treasury shares" in section.lower()
        if period >= TREASURY_RULE_START and not excluded_treasury:
            raise ValueError("treasury_share_scope_unproven")
        for i, block in enumerate(blocks):
            kind, share_type = (term.strip().lower() for term in block.groups())
            if kind == "preference shares":
                continue
            end = blocks[i + 1].start() if i + 1 < len(blocks) else len(section)
            content = section[block.end():end]
            balances, match = closing_cells(content)
            if excluded_treasury and (len(balances) != 3 or balances[0] + balances[1] != balances[2]):
                raise ValueError("treasury_balance_check_failed")
            value = balances[0]
            if kind != "ordinary shares":
                if value:
                    raise ValueError("unclassified_equity_class_has_balance")
                continue
            if share_type not in ("a", "h"):
                if value:
                    raise ValueError("other_ordinary_class_has_balance")
                continue
            code = re.search(r"(?im)^\s*Stock code(?:\s+\(if listed\))?\s+([0-9]+)\b", content)
            if not code or share_type in found:
                raise ValueError("ordinary_class_code_unresolved")
            found[share_type] = code[1].zfill(5 if share_type == "h" else 6), value
            literals.append(" ".join((block[0] + " " + match[0]).split()))
        basis = "issued_excluding_treasury" if excluded_treasury else "legacy_issued_pre_treasury_rule"
    else:
        if period >= TREASURY_RULE_START:
            raise ValueError("legacy_treasury_scope_unproven")
        balances, closing = closing_cells(section)
        header = section[:section.lower().find("balance at close of")]
        authorized = text[:sec.start()]
        names, named_codes = legacy_column_names(section, header, authorized, balances)
        digits = {m[1] for m in re.finditer(r"(?im)\bStock code\s*:\s*(\d+)\b", authorized)}
        digits.update(m[1] for m in re.finditer(
            r"(?im)^\s*(\d{6})\s+\((?:Shanghai|Shenzhen)\s+Stock\s+"
            r"\(\d+\)\s+Stock code\s*:\s*Exchange\)\s+Description\s*:\s*A shares\b", authorized,
        ))
        a_codes = sorted(set(candidates) & {code.zfill(6) for code in digits if len(code) == 6})
        if len(a_codes) != 1 or h not in {code.zfill(5) for code in digits if len(code) <= 5}:
            raise ValueError("legacy_ordinary_class_code_unresolved")
        found = {kind: (a_codes[0] if kind == "a" else h, balances[i]) for i, kind in enumerate(names)}
        literals.extend(named_codes)
        literals.append(" ".join((header + closing[0]).split()))
        basis = "legacy_issued_pre_treasury_rule"
    if set(found) != {"a", "h"} or found["h"][0] != h or found["a"][0] not in candidates:
        raise ValueError("original_pair_not_confirmed")
    if min(found["a"][1], found["h"][1]) <= 0:
        raise ValueError("nonpositive_ordinary_class_balance")
    return period, found, basis, literals


def check_document(archive, h, row, known, listing_evidence):
    identity, path = row["NEWS_ID"], row["FILE_LINK"]
    if not identity.isdecimal() or row["FILE_TYPE"].upper() != "PDF" or not STOCK_PATH.fullmatch(path):
        raise ValueError("unexpected_disclosure_original_link")
    body, receipt = archive.read(f"original-{h}-{identity}.pdf", SITE + path)
    if not body:
        raise ValueError(f"PDF_HTTP_{receipt['status']}")
    if not body.startswith(b"%PDF-"):
        raise ValueError("original_is_not_pdf")
    text = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
        input=body, capture_output=True, check=True, timeout=45,
    ).stdout.decode("utf-8")
    period, shares, basis, literals = observed_classes(text, h, known)
    release = published(row)
    if period > release.date():
        raise ValueError("reported_period_does_not_match_release")
    return {
        "a_code": shares["a"][0], "h_code": h, "period_end": period.isoformat(),
        "issued_outstanding_a": shares["a"][1], "issued_outstanding_h": shares["h"][1],
        "issued_outstanding_ordinary_total": shares["a"][1] + shares["h"][1],
        "precision_shares": 1, "basis": basis, "published_at": release.isoformat(timespec="minutes"),
        "published_time_precision": "minute", "observed_at": receipt["observed_at"],
        "source_url": receipt["url"], "source_sha256": receipt["sha256"], "source_version_id": identity,
        "listing_url": listing_evidence["url"], "listing_sha256": listing_evidence["sha256"],
        "knowledge_quality": "historical_original_evidence", "closing_balance_literals": literals,
        "effective_scope": "month_end_balance_only",
    }


def dated_rows(rows, asof, historical_anchor):
    ordered = sorted(rows, key=published)
    if asof is not None:
        ordered = [row for row in ordered if published(row).date() <= asof]
    # This vendor listing date only scopes the files to read. The original verifies the class and date.
    if historical_anchor:
        ordered = [row for row in ordered if published(row).strftime("%Y-%m") > historical_anchor[:7]]
    return ordered


def choose_months(rows, count, asof=None, historical_anchor=None):
    if count <= 0:
        return []
    ordered = dated_rows(rows, asof, historical_anchor)
    if not ordered:
        return []
    indices = {len(ordered) - 1} if count == 1 else {
        round(x * (len(ordered) - 1) / (count - 1)) for x in range(count)
    }
    return [ordered[i] for i in sorted(indices)]


def attempt_original(archive, row, candidate, evidence, observations, role):
    check = {"id": row["NEWS_ID"], "role": role}
    try:
        proof = check_document(archive, candidate["hk_code"], row, candidate["a_candidates"], evidence)
    except (ValueError, subprocess.SubprocessError) as exc:
        candidate["original_checks"].append(check | {"reason": str(exc)})
        return False
    observations.append(proof | {"acquisition_role": role})
    candidate["original_checks"].append(check | {"status": "verified_month_end_balance"})
    return True


def write_results(args, cohort, archive, records, observations, termination):
    summary = {
        "planned_hk_codes": len(cohort), "planned_a_h_pairs": sum(len(r["a_candidates"]) for r in cohort.values()),
        "planned_h_codes_with_usable_local_quote_history": sum(r["local_h_quotes"] for r in cohort.values()),
        "observed_issuer_records": records, "issuer_counts": dict(Counter(r.get("status", "interrupted") for r in records)),
        "metadata_rows": sum(r.get("returned_rows", 0) for r in records), "verified_original_balance_rows": len(observations),
        "network_requests_this_run": archive.calls, "termination": termination,
        "release_window": [args.start, args.end], "pdfs_per_issuer": args.pdfs_per_issuer,
        "sample_issuers": args.sample_issuers, "quoted_pdf_only": args.quoted_pdf_only,
        "sample_asof_date": args.sample_asof.isoformat() if args.sample_asof else None,
        "seed_attempts": args.seed_attempts, "chronological_fill": args.chronological_fill,
    }
    for name, content in (
        ("hkex_monthly_share_observations.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in observations)),
        ("source_intake_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"),
    ):
        path = args.output / name
        partial = path.with_suffix(path.suffix + ".partial")
        partial.write_text(content, encoding="utf-8")
        partial.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csmar-company-capture", type=Path, required=True)
    parser.add_argument("--class-quotes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", default="20140101")
    parser.add_argument("--end", default="20260731")
    parser.add_argument("--max-requests", type=int, default=32)
    parser.add_argument("--interval", type=float, default=1.25)
    parser.add_argument("--max-issuers", type=int)
    parser.add_argument("--pdfs-per-issuer", type=int, default=0)
    parser.add_argument("--sample-issuers", type=int, default=len(PRIORITY))
    parser.add_argument("--quoted-pdf-only", action="store_true")
    parser.add_argument("--sample-asof", type=date.fromisoformat, default=date(2026, 6, 30))
    parser.add_argument("--seed-attempts", type=int, default=1)
    parser.add_argument("--chronological-fill", action="store_true")
    parser.add_argument("--with-hkex-written-permission", action="store_true",
                        help="Enable live HKEXnews requests only under applicable HKEX written permission.")
    args = parser.parse_args()
    if not args.with_hkex_written_permission:
        parser.error("HKEXnews original acquisition and reuse require applicable HKEX written permission")
    if args.interval < 1 or args.max_requests <= 0 or args.seed_attempts <= 0:
        parser.error("Use positive limits and at least one second between public requests")
    if args.seed_attempts > 1 and args.pdfs_per_issuer != 2:
        parser.error("Retry sampling needs two seed observations per issuer")
    cohort = planned_cohort(args.csmar_company_capture, args.class_quotes)
    archive = Archive(args.output / "raw", args.max_requests, args.interval,
                      allow_network=args.with_hkex_written_permission)
    (args.output / "candidate_cohort.json").write_text(json.dumps(cohort, indent=2), encoding="utf-8")
    records, observations = [], []
    fill = []
    termination = "planned_scope_reached"
    try:
        for index, (code, candidate) in enumerate(cohort.items()):
            if args.max_issuers is not None and index >= args.max_issuers:
                break
            if index and index % 10 == 0:
                write_results(args, cohort, archive, records, observations, "in_progress")
            record = {"hk_code": code, **candidate}
            records.append(record)
            try:
                issuer = lookup(archive, code)
            except (ValueError, KeyError, TypeError) as exc:
                record.update(status="lookup_schema_unverified", reason=str(exc))
                continue
            record["stock_id"] = issuer
            category = 0
            if issuer is None and code in DELISTED:
                issuer = record["stock_id"] = DELISTED[code]
                category = 1
                record["stock_id_source"] = SITE + f"/search/titlesearch.xhtml?category=1&lang=EN&market=SEHK&stockId={issuer}"
            if issuer is None:
                record["status"] = "exact_active_lookup_unresolved"
                continue
            try:
                rows, evidence = listing(archive, code, issuer, args.start, args.end, category)
            except (ValueError, KeyError, TypeError) as exc:
                record.update(status="listing_scope_unverified", reason=str(exc))
                continue
            if rows is None:
                record["status"] = f"metadata_HTTP_{evidence['status']}"
                continue
            record.update(status="metadata_complete", returned_rows=len(rows),
                          listed_metadata_rows=evidence["listed_metadata_rows"],
                          cancelled_metadata_rows=evidence["cancelled_metadata_rows"],
                          listing_sha256=evidence["sha256"], original_checks=[])
            if rows:
                record.update(first_release=min(map(published, rows)).isoformat(),
                              last_release=max(map(published, rows)).isoformat())
            sample = index < args.sample_issuers and (candidate["local_h_quotes"] or not args.quoted_pdf_only)
            if sample:
                asof = min(args.sample_asof, A_LISTING_END.get(code, args.sample_asof))
                ordered = dated_rows(rows, asof, candidate["earliest_candidate_a_listing"])
                if args.pdfs_per_issuer == 2:
                    attempted = {}
                    for role, choices in (("earliest", ordered), ("latest", reversed(ordered))):
                        for row in list(choices)[:args.seed_attempts]:
                            identity = row["NEWS_ID"]
                            if identity not in attempted:
                                attempted[identity] = attempt_original(archive, row, record, evidence, observations, role)
                            if attempted[identity]:
                                break
                else:
                    for row in choose_months(ordered, args.pdfs_per_issuer):
                        attempt_original(archive, row, record, evidence, observations, "sample")
                if args.chronological_fill:
                    attempted_ids = {check["id"] for check in record["original_checks"]}
                    fill.extend((row, record, evidence) for row in ordered if row["NEWS_ID"] not in attempted_ids)
            print(code, record["status"], len(rows), len(record["original_checks"]), flush=True)
        for index, (row, record, evidence) in enumerate(sorted(fill, key=lambda item: published(item[0]))):
            if index % 10 == 0:
                write_results(args, cohort, archive, records, observations, "chronological_fill_in_progress")
            attempt_original(archive, row, record, evidence, observations, "chronological_fill")
    except StopDownload as exc:
        termination = str(exc)
    finally:
        archive.session.close()
    write_results(args, cohort, archive, records, observations, termination)


if __name__ == "__main__":
    main()
