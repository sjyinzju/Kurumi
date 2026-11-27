"""Normalize original document versions and select evidence spans without outcome data."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from importlib.metadata import version as installed_version
from pathlib import Path

import pyarrow.parquet as pq

from .cn_pit import LOCAL, _between_time
from .cn_text_sources import (
    ARCHIVE,
    CNINFO,
    NBS_SOURCE,
    PDF_PATH,
    atomic,
    file_hash,
    read_json,
    record_key,
    sha,
    soup,
    write_json,
)
from .karpo_numeric import KARPO_ENCODING_FILES

CLEANING_VERSION = "cn-original-spans.v1"
HTML_PARSER_VERSION = "cn-archived-article-html.v2"
PDF_CACHE_TAG = "pdf-cn-original-spans.v1"  # PyMuPDF 1.26.7
ASSOCIATION_VERSION = "cn-historical-identity.v1"
DEDUP_VERSION = "same-facts-shingles.v1"
BUDGET_VERSION = "karpo-separated-1024.v1"
PERIODIC = re.compile(r"(?:年度|半年度|第一季度|第三季度|中期|[一三]季)(?:报告|报)")
CORRECTION = re.compile(r"更正|修订|补充|澄清|修正|更新")
EXPLICIT_CODE = re.compile(
    r"(?:证券代码|股票代码)\s*[：:]?\s*(\d{6})(?!\d)"
    r"|[（(]\s*(?:[A-Z]{2}\s*)?(\d{6})(?:\.(?:SH|SZ|BJ))?\s*[）)]"
    r"|(?<!\d)(\d{6})\.(?:SH|SZ|BJ)\b"
)
CJK = re.compile(r"[\u3400-\u9fff]")
SPACE = re.compile(r"\s+")
CHROME = re.compile(
    r"^(?:打印本页|关闭窗口|返回顶部|上一篇|下一篇|字号[：:]?|来源[：:]|责任编辑[：:]|"
    r"上海证券报网络版郑重声明|扫一扫|点击查看[附件原文]+|目录|[第]?\s*\d+\s*(?:页)?$)"
)
WARRANTY = re.compile(
    r"^(?:本公司|公司)?(?:及其)?董事会(?:及全体董事)?.{0,22}"
    r"保证(?:本公告|本报告|信息披露).{0,90}(?:重大遗漏|法律责任|完整性)[。；;]?$"
)
ECONOMIC = re.compile(
    r"订单|中标|合同|价格|产量|收入|利润|现金流|融资|债务|违约|成本|持续经营|风险|"
    r"经营|业务变化|投产|产能|需求|份额|研发|并购|重组|控制权|处罚|诉讼|停产|上市地位|"
    r"房地产|工业增加值|失业率|居民消费|投资|同比|环比"
)
FACTS = re.compile(
    r"[-−+]?\d[\d,.]*(?:\s*(?:亿|万|千|百)?(?:元|股|吨|台|美元|人|%|％|个基点|个百分点|年|月|日|倍))?"
    r"|(?:拟|尚未|未能|不会|不再|不得|不能|没有|不予|不涉及|不确定|不构成|若|待|须|条件|"
    r"取消|撤销|终止|未签署|预中标|中标|签订|签署|生效|批准|审议|通过|实施|完成|失败|"
    r"调增|调减|上升|下降|亏损|盈利|更正|修订|补充|进展|风险|违约|否认|澄清)"
)
SECTION_BENEFIT = re.compile(r"经营情况讨论|管理层讨论|经营回顾|业务概要|主营业务|重要事项|"
                             r"风险因素|未来发展|经营计划|行业格局|盈利预测|核心竞争力")
ANN_STYLE = re.compile(r"公司董事会及全体董事保证|证券代码.{0,25}公告编号|特此公告")


def publication(raw):
    if not raw:
        return None, None, None, "unknown"
    try:
        value = str(raw).strip().replace("/", "-")
        if len(value) == 10:
            return _between_time(value)
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=LOCAL)
        day, released, available, precision = _between_time(stamp.isoformat())
        if re.search(r"[T ]\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?$", value):
            precision = "minute"
        return day, released, available, precision
    except ValueError:
        return None, None, None, "unknown"


def code_parts(ts_code):
    symbol, _, venue = ts_code.partition(".")
    return symbol, {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(venue)


class IdentityHistory:
    def __init__(self, con, anchor: Path):
        self.codes = defaultdict(list)
        self.alternate = defaultdict(list)
        self.names = defaultdict(list)
        self.industries = defaultdict(set)
        rows = pq.read_table(anchor / "reference/security_history.parquet").to_pylist()
        self.issuers = {v["instrument_id"]: v["issuer_id"] for v in rows}
        for row in rows:
            instrument = row["instrument_id"]
            begin, end = row["listing_date"] or date.min, row["delisting_date"] or date.max
            current, prior = row["ts_code"], row["prior_code"]
            switch = row["code_switch_date"] if prior and prior != current else None
            for ticker, lo, hi in ((current, max(begin, switch or begin), end),
                                   (prior, begin, min(end, switch - timedelta(days=1)) if switch else end)):
                if not ticker or lo > hi:
                    continue
                symbol, exchange = code_parts(ticker)
                self.codes[symbol].append((lo, hi, instrument, exchange))
                self.alternate[symbol].append((begin, end, instrument, exchange))
        stock_glob = (anchor / "stock_daily/**/*.parquet").as_posix()
        names = con.execute("""
            WITH observation AS (
                SELECT instrument_id, local_trade_date, name_asof, symbol_asof,
                       lag(name_asof) OVER events AS prior_name,
                       lag(symbol_asof) OVER events AS prior_symbol
                FROM read_parquet(?, hive_partitioning=false)
                WINDOW events AS (PARTITION BY instrument_id ORDER BY local_trade_date)
            ), runs AS (
                SELECT *, sum((name_asof IS DISTINCT FROM prior_name OR symbol_asof IS DISTINCT FROM prior_symbol)::INT)
                    OVER (PARTITION BY instrument_id ORDER BY local_trade_date) AS run
                FROM observation
            )
            , intervals AS (
                SELECT instrument_id, name_asof, min(local_trade_date) AS day_from, max(local_trade_date) AS day_to
                FROM runs GROUP BY instrument_id, name_asof, run
            ), carry AS (
                SELECT *, lead(day_from) OVER (PARTITION BY instrument_id ORDER BY day_from) AS following
                FROM intervals
            )
            SELECT instrument_id, name_asof, day_from, greatest(day_to, least(coalesce(following - 1, day_to), day_to + 7))
            FROM carry WHERE name_asof IS NOT NULL
        """, [stock_glob]).fetchall()
        listing_ends = {r["instrument_id"]: r["delisting_date"] or date.max for r in rows}
        for instrument, name, lo, hi in names:
            hi = min(hi, listing_ends.get(instrument, hi))
            name = self.name_key(name)
            if len(name) >= 2 and CJK.search(name):
                self.names[name].append((lo, hi, instrument))
        # Earlier names and exact rename bounds already supported by original disclosure evidence.
        documented_names = anchor / "reference/security_name_versions.jsonl"
        for line in documented_names.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if not all(d.get(field) for field in ("name_asof", "effective_from", "available_at", "instrument_id")):
                continue
            available = publication(d["available_at"])[0]
            lo = max(date.fromisoformat(d["effective_from"]), available)
            hi = date.fromisoformat(d["effective_to"]) - timedelta(days=1) if d.get("effective_to") else date.max
            self.names[self.name_key(d["name_asof"])].append((lo, hi, d["instrument_id"]))
        aliases = sorted((name for name in self.names if len(name) >= 3), key=lambda name: (-len(name), name))
        self.aliases = re.compile("|".join(map(re.escape, aliases))) if aliases else re.compile(r"(?!)")
        for filename in ("industry_membership", "industry_training_intervals"):
            p = anchor / "reference" / (filename + ".parquet")
            for row in pq.read_table(p, columns=["classification_version", "industry_code", "industry_name"]).to_pylist():
                if all(row.values()):
                    self.industries[row["industry_name"]].add(row["classification_version"] + "|" + row["industry_code"])

    @staticmethod
    def name_key(name):
        return SPACE.sub("", unicodedata.normalize("NFKC", name)).upper()

    def from_code(self, code, venue, day, *, legacy=False):
        candidates = self.alternate if legacy else self.codes
        matching = {instrument for lo, hi, instrument, exchange in candidates[code]
                    if lo <= day <= hi and (not venue or venue == exchange)}
        return next(iter(matching)) if len(matching) == 1 else None

    def from_name(self, name, day):
        matching = {instrument for lo, hi, instrument in self.names[name] if lo <= day <= hi}
        return next(iter(matching)) if len(matching) == 1 else None

    def associate(self, row, body, day):
        if day is None:
            return []
        if row.get("news_scope") == "macro":
            return [("market", "CN", "market_background", "official_macro_archive")]
        if row.get("symbol"):
            instrument = self.from_code(row["symbol"], row.get("exchange"), day)
            if instrument:
                return self.issuer_links(instrument, "source_historical_code")
            if row.get("archive_alias"):
                instrument = self.from_code(row["symbol"], row.get("exchange"), day, legacy=True)
                if instrument:
                    return self.issuer_links(instrument, "documented_archive_code_alias")
            if row["kind"] == "announcement":
                return []
        title = self.name_key(row["title"])
        lede = self.name_key(body[:950])
        explicit = {self.from_code(next(value for value in code.groups() if value), None, day)
                    for code in EXPLICIT_CODE.finditer(title + "\n" + lede)}
        matched = {i: "explicit_security_code" for i in explicit if i}
        names = [m.group() for m in self.aliases.finditer(title)]
        leading = re.match(r"([^:]{2,14})[:]", title)
        if leading and leading[1] not in names:
            names.append(leading[1])
        if not names and ("公司" in (row.get("section") or "") or row.get("section") == "local_company_news"):
            names = [m.group() for m in self.aliases.finditer(lede[:310])]
        for name in names:
            instrument = self.from_name(name, day)
            if instrument:
                matched.setdefault(instrument, "historical_name")
        if matched:
            return sorted({link for i, method in matched.items() for link in self.issuer_links(i, method)})
        if row["kind"] == "announcement":
            return []
        industries = sorted({key for name, keys in self.industries.items()
                            if re.search(re.escape(name) + r"(?:行业|板块|产业)", title) for key in keys})
        if industries:
            return [("industry", key, "industry_background", "historical_classification_title") for key in industries]
        section = row.get("section") or ""
        if re.match(r"^\d+(?:版)?[：:](?:新闻·)?市场(?:$|[·／/ ])", section):
            return [("market", "CN", "market_background", "original_market_section")]
        return []

    def issuer_links(self, instrument, method):
        if instrument not in self.issuers:
            return []
        return [("instrument", instrument, "direct", method),
                ("issuer", self.issuers[instrument], "direct", method)]


class NativeBudget:
    def __init__(self, checkpoint: Path):
        from tokenizers import Tokenizer

        digest = hashlib.sha256()
        for name in KARPO_ENCODING_FILES:
            digest.update(name.encode())
            digest.update(bytes.fromhex(file_hash(checkpoint / name)))
        self.revision = digest.hexdigest()
        self.tokenizer = Tokenizer.from_file(str(checkpoint / "tokenizer.json"))
        specials = [v.content for v in self.tokenizer.get_added_tokens_decoder().values()
                    if "<" in v.content or ">" in v.content]
        self.token_syntax = re.compile("|".join(map(re.escape, sorted(specials, key=len, reverse=True)))
                                       if specials else r"(?!)")

    def escaped(self, text):
        return self.token_syntax.sub(lambda m: m.group().replace("<", "＜").replace(">", "＞"), text)

    def count(self, text):
        return len(self.tokenizer.encode(self.escaped(text), add_special_tokens=False).ids)

    def counts(self, texts):
        return [len(item.ids) for item in self.tokenizer.encode_batch(
            [self.escaped(text) for text in texts], add_special_tokens=False)]


def body_normalize(text):
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")).strip()


def html_body(capture, row, receipt):
    root = soup(capture, receipt)
    if row["provider"] == NBS_SOURCE:
        container = root.select_one(".detail-text-content .txt-content, .detail-text-content, .TRS_Editor")
        pub = root.select_one("meta[name=PubDate]")
        header = root.select_one(".detail-content .detail-title, .detail-content h1, h1")
        if pub:
            raw_time = pub.get("content", "").strip()
        else:
            visible = (root.select_one(".detail-content .detail-time, .detail-content .time, .detail-content .source")
                       or root.select_one(".detail-content"))
            found = re.search(r"20\d{2}[-/.]\d{2}[-/.]\d{2}(?:\s+\d{2}:\d{2})?",
                              visible.get_text(" ", strip=True)[:350] if visible else "")
            raw_time = found.group().replace(".", "-") if found else None
        if raw_time:
            row["published_raw"] = raw_time
            row["time_evidence"] = "publication metadata or dated header of NBS release"
        if header and header.get_text(strip=True):
            row["title"] = header.get_text(" ", strip=True)
        updated = root.select_one("meta[name=ModifyDate], meta[name=UpdateTime]")
        if updated and publication(updated.get("content"))[1] and publication(raw_time)[1]:
            if publication(updated["content"])[1] > publication(raw_time)[1]:
                row["published_raw"] = None
                row["time_evidence"] = "unresolved update time for historical edition"
    else:
        container = root.select_one(
            "#content_article, .content_article, #ozoom, #ContentBody, #articleContent, .article-content")
        title = root.select_one(".article-content h1, .article-header h1, #title h1, h1")
        if title and title.get_text(strip=True):
            row["title"] = title.get_text(" ", strip=True)
    if not container:
        return ""
    for element in container.select("script, style, iframe, .share, .print"):
        element.decompose()
    for element in container.select("br"):
        element.replace_with("\n")
    sections = [t.get_text(" ", strip=True) for t in container.select("p, tr, li")
                if not any(p.name in {"p", "tr", "li"} for p in t.parents)]
    return body_normalize("\n\n".join(t for t in sections if t) if sections else container.get_text("\n", strip=True))


def pdf_body(payload: bytes):
    import pymupdf

    with pymupdf.open(stream=payload, filetype="pdf") as pdf:
        return body_normalize("\f".join(page.get_text(sort=True) for page in pdf))


def quality(body):
    if not body or len(body.strip()) < 28 or len(CJK.findall(body[:12000])) < 12:
        return "insufficient_text"
    if len(re.findall(r"�|[\ue000-\uf8ff]", body[:12000])) > max(4, len(body[:12000]) // 50):
        return "garbled_text"
    return "ok"


def fact_signature(text):
    return Counter(FACTS.findall(SPACE.sub("", unicodedata.normalize("NFKC", text))))


def normalized_body(body):
    return SPACE.sub("", unicodedata.normalize("NFKC", body))


def source_metadata(row):
    title = SPACE.sub(" ", row["title"]).strip()
    stamp = row.get("published_raw") or ""
    provider = row.get("publisher") or row["provider"]
    if row["kind"] == "announcement" and provider != row["provider"]:
        provider = f"{provider} · {row['provider']}"
    return f"{title}\n{provider} · {stamp}"


def evidence_spans(body):
    """Yield original spans, with physical pages when the extraction contains page breaks."""
    pages = body.split("\f")
    repeated = Counter()
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        repeated.update(set(lines[:3] + lines[-3:]))
    page_offset = 0
    for page_no, page in enumerate(pages, start=1):
        for match in re.finditer(r"\S[^\f]*?(?=\n[ \t]*\n|\Z)", page):
            base = match.group().rstrip()
            if not base:
                continue
            # PDF paragraph reconstruction stays within a source page; broad splitting only at sentence boundaries.
            pieces = [m for m in re.finditer(r"[^。！？]*[。！？]+|[^。！？]+$", base)] if len(base) > 360 else []
            bounds = [(m.start(), m.end()) for m in pieces] if pieces else [(0, len(base))]
            for lo, hi in bounds:
                literal = base[lo:hi]
                if not literal.strip():
                    continue
                line = SPACE.sub(" ", literal).strip()
                if (not line or CHROME.search(line) or WARRANTY.fullmatch(line)
                        or repeated.get(literal.strip(), 0) >= 3 and len(line) <= 120):
                    continue
                begin = page_offset + match.start() + lo
                yield (begin, begin + len(literal), page_no if len(pages) > 1 else None, line)
        page_offset += len(page) + 1


def choose_spans(row, body, budget):
    heading = source_metadata(row)
    periodic = row["document_class"] == "periodic"
    spans = list(evidence_spans(body))
    if not spans:
        return "", [], 0, 0, set(), []
    full = heading + "\n" + "\n".join(s[-1] for s in spans)
    # Count actual native tokens once on the original text, in chunks for very long annual reports.
    measure = len(body) <= 30_000 or int(sha(body[:2000].encode())[:4], 16) % 20 == 0
    raw_tokens = (sum(budget.count(part) for part in body.split("\f")) + budget.count(heading)) if measure else None
    low_priority = 400 if periodic else 900
    if row["kind"] == "news" and len(full) < 4500 and budget.count(full) <= low_priority:
        picked = spans
    else:
        # A long report needs narrative and conditions more than large statement tables.
        def score(span):
            text = span[-1]
            score = min(7, len(ECONOMIC.findall(text))) * 4 + min(16, len(FACTS.findall(text)))
            score += 18 * bool(SECTION_BENEFIT.search(text)) if periodic else 0
            score += 4 * bool(re.search(r"风险|条件|不确定|尚未|需经|未签|批准|取消|终止|更正|修订", text))
            if len(text) < 18 or len(CJK.findall(text)) < max(8, len(text) // 9):
                score -= 12
            return score

        # Meanings are preserved by selecting whole evidence spans, with no mid-sentence token truncation.
        ranked = sorted(((-score(span), i, span) for i, span in enumerate(spans)))[:160]
        picked = []
        left = low_priority - budget.count(heading) - 6
        for pos in range(0, len(ranked), 16):
            if left < 10:
                break
            candidates = [span for neg_score, _, span in ranked[pos:pos + 16] if neg_score <= 0]
            counts = budget.counts([span[-1] for span in candidates])
            for span, cost in zip(candidates, counts, strict=True):
                if 9 <= cost + 2 <= left:
                    picked.append(span)
                    left -= cost + 2
        picked.sort()
    selected = heading + "\n" + "\n".join(s[-1] for s in picked)
    if not picked:
        selected = ""
    while picked and budget.count(selected) > low_priority:
        picked.pop()
        selected = heading + "\n" + "\n".join(s[-1] for s in picked) if picked else ""
    selected_tokens = budget.count(selected) if selected else 0
    total_facts = fact_signature("\n".join(s[-1] for s in spans))
    kept = fact_signature("\n".join(s[-1] for s in picked))
    offsets = [dict(start=s[0], end=s[1], page=s[2]) for s in picked]
    return selected, offsets, raw_tokens, selected_tokens, set(total_facts), sorted(kept.keys())


def selected_text(row, body, body_hash, budget, cache):
    key = sha(json.dumps([CLEANING_VERSION, BUDGET_VERSION, budget.revision, body_hash, row["kind"],
                           row["document_class"], source_metadata(row)], ensure_ascii=False).encode())
    path = cache / "spans" / key[:2] / f"{key}.json"
    if path.is_file():
        return read_json(path)
    selected, spans, raw_tokens, tokens, facts, kept = choose_spans(row, body, budget)
    result = (selected, spans, raw_tokens, tokens, len(facts), len(kept))
    write_json(path, result)
    return result


def document_class(row):
    title = row["title"]
    if row["kind"] == "news":
        return "news"
    # A notice about a report is an event. Full revisions remain periodic document versions.
    if PERIODIC.search(title) and not re.search(r"业绩|摘要|审议|延期|取消|问询|说明|更正公告|补充公告|提示|回复", title):
        return "periodic"
    return "event"


def initial_document(row, capture, known_bodies, cache):
    body = ""
    parse_status = "body_missing"
    raw_hash = row.get("raw_hash")
    raw_ref = row.get("raw_ref")
    retrieved = row.get("retrieved_at")
    parser = None
    if raw_hash and raw_hash in known_bodies:
        try:
            path = Path(raw_ref) if raw_ref else None
            if path is None or (path.is_absolute() and file_hash(path) != raw_hash):
                raise ValueError("source_hash_mismatch")
            if not path.is_absolute():
                capture.read(row)
        except (OSError, ValueError):
            return row | dict(body="", parse_status="raw_hash_mismatch", parser=None)
        known = known_bodies[raw_hash]
        body = known["text"]
        parser = "verified_prior_extraction"
        parse_status = quality(body)
    elif raw_hash and raw_ref:
        path = Path(raw_ref)
        pdf_version = installed_version("pymupdf")
        parser_tag = PDF_CACHE_TAG if pdf_version == "1.26.7" else f"{PDF_CACHE_TAG}-{pdf_version}"
        parser_cache = cache / parser_tag / f"{raw_hash}.txt.gz"
        try:
            if parser_cache.is_file():
                body = gzip.decompress(parser_cache.read_bytes()).decode("utf-8")
                parser = "cached_pdf"
            else:
                if path.is_absolute():
                    payload = path.read_bytes()
                    if sha(payload) != raw_hash:
                        raise ValueError("source_hash_mismatch")
                else:
                    payload = capture.read(row)
                body = pdf_body(payload)
                atomic(parser_cache, gzip.compress(body.encode(), compresslevel=3, mtime=0))
                parser = "pdf"
            parse_status = quality(body)
        except (OSError, ValueError, RuntimeError):
            parse_status = "pdf_parse_failed"
    else:
        receipt_path = capture.root / "bodies" / row["provider"] / (record_key(row) + ".json")
        if receipt_path.is_file():
            receipt = read_json(receipt_path)
            if receipt["query_status"] != "ok":
                parse_status = "download_failed"
            else:
                return (
                    initial_document(row | {k: receipt[k] for k in ("raw_ref", "raw_hash", "retrieved_at")},
                                     capture, known_bodies, cache)
                    if row["kind"] == "announcement" else parsed_html(row, capture, receipt)
                )
    return row | dict(body=body, parse_status=parse_status, raw_hash=raw_hash, raw_ref=raw_ref,
                      retrieved_at=retrieved, parser=parser)


def parsed_html(row, capture, receipt):
    row = row.copy()
    try:
        body = html_body(capture, row, receipt)
        status = quality(body)
    except (OSError, ValueError):
        body = ""
        status = "html_parse_failed"
    return row | dict(body=body, parse_status=status, raw_hash=receipt["raw_hash"], raw_ref=receipt["raw_ref"],
                      retrieved_at=receipt["retrieved_at"], parser=HTML_PARSER_VERSION)


def _local_row(provider, url, native_id, title, published, ts_code, path, receipt, *,
               index_hash=None, index_ref=None, alias=False):
    symbol, exchange = code_parts(ts_code)
    return dict(kind="announcement", provider=provider, publisher=None, source_doc_id=str(native_id),
                source_url=url, title=title, symbol=symbol, exchange=exchange, archive_alias=alias,
                published_raw=published, time_evidence="dated archive index and SHA-256 matched original",
                raw_ref=str(path.resolve()), raw_hash=receipt["sha256"], retrieved_at=receipt["observed_at"],
                index_hash=index_hash, index_ref=str(index_ref.resolve()) if index_ref else None)


def legacy_receipts(project: Path, numeric_sources: Path):
    """Import matching pre-existing original bytes and dated catalogue receipts as read-only inputs."""
    prior = project / "artifacts/cn_numeric_followup"
    for folder in (numeric_sources / "bse-issuer-gap-20261121", prior / "bse_financial_originals/issuer_reports"):
        for x in sorted(folder.glob("*/report-*.json")):
            record = read_json(x)
            for attachment in record["attachments"]:
                pdf = x.parent / (attachment.get("file") or "_missing_")
                if attachment.get("status") != 200 or pdf.suffix.lower() != ".pdf" or not pdf.is_file():
                    continue
                yield _local_row("Sina-original-filings", attachment["url"], record["id"], record["title"],
                                 record["published_day"], record["archive_code"] + ".BJ", pdf, attachment,
                                 index_hash=file_hash(x), index_ref=x, alias=True)
    for name in ("current-channels-20261125", "expanded-sources-20261125"):
        for x in sorted((prior / name / "issuer-originals").glob("*/outcome.json")):
            for report in read_json(x)["results"]:
                target = report["target"]
                if not report["archive_ok"]:
                    continue
                for item in report["attempts"]:
                    if not item.get("title") or not item.get("local_path"):
                        continue
                    pdf = Path(item["local_path"])
                    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
                        continue
                    url = item["source_url"]
                    archive = PDF_PATH.fullmatch(url.removeprefix(ARCHIVE)) if url.startswith(ARCHIVE) else None
                    evidence_date = item.get("published_at") or target["published"]
                    if archive and evidence_date[:10] != archive[1]:
                        continue
                    yield _local_row(CNINFO if archive else "exchange-original-filings", url,
                                     archive[2] if archive else item["source_version_id"], item["title"],
                                     evidence_date, target["source_ts_code"], pdf,
                                     {"sha256": item["source_sha256"], "observed_at": item["observed_at"]},
                                     index_hash=file_hash(x), index_ref=x)
    root = prior / "bigquant-fill-20261124"
    for file in ("units_notice_receipts.json", "limits_notice_receipts.json"):
        if not (root / file).is_file():
            continue
        proof_digest = file_hash(root / file)
        for row in read_json(root / file):
            proof = row.get("proof")
            if not proof or not proof.get("local_path") or not proof.get("sha256"):
                continue
            url = proof["source_url"]
            match = PDF_PATH.fullmatch(url.removeprefix(ARCHIVE)) if url.startswith(ARCHIVE) else None
            if not match:
                continue
            title = next((x["title"] for x in row.get("attempts", []) if x.get("id") == match[2] and x.get("title")), None)
            pdf = root / "original_notices" / proof["local_path"]
            code = row.get("historical_ts_code") or row.get("ts_code")
            if title and pdf.is_file() and code and (proof.get("notice_published") or match[1]) == match[1]:
                yield _local_row(CNINFO, url, match[2], title, match[1], code, pdf, proof,
                                 index_hash=proof_digest, index_ref=root / file)


def prior_text(path: Path | None):
    if not path:
        return {}
    result = {}
    for batch in pq.ParquetFile(path).iter_batches(batch_size=12, columns=["source_sha256", "text_sha256", "text"]):
        for row in batch.to_pylist():
            if sha(row["text"].encode()) != row["text_sha256"]:
                raise ValueError("prior parsed text hash mismatch")
            result[row["source_sha256"]] = row
    return result


def csmar_metadata(capture):
    """Retain the returned preview and the demonstrated missing long-text field."""
    probe = capture.root / "probes/csmar_trial_rows.json"
    if not probe.is_file():
        return []
    rows = read_json(probe)
    retrieved = datetime.fromtimestamp(probe.stat().st_mtime, tz=LOCAL).isoformat()
    return [dict(kind="news", provider="CSMAR-CAIN", publisher=None, source_doc_id=str(row["NewsID"]),
                 source_url=None, title=row.get("Title") or "", symbol=row.get("Symbol"),
                 org_id=row.get("InstitutionID"),
                 published_raw=row.get("DeclareDate"), retrieved_at=retrieved,
                 time_evidence="CSMAR DeclareDate field; publication version unconfirmed without original",
                 index_ref=str(probe), index_hash=file_hash(probe))
            for row in rows]


class Deduplicator:
    def __init__(self):
        self.exact = {}
        self.near = defaultdict(list)

    def group(self, doc_version_id, kind, title, body, relations, day):
        if not body:
            return None, None
        normalized = normalized_body(body)
        # The kind is kept in the key so issuer PDF and editorial discussion cannot suppress each other.
        digest = (kind, sha(normalized.encode()))
        if digest in self.exact:
            return self.exact[digest], "exact"
        if not day or not relations or not (90 <= len(normalized) <= 8000):
            self.exact[digest] = doc_version_id
            return doc_version_id, None
        key = (kind, re.sub(r"[\W_]+", "", title), tuple(sorted(x[1] for x in relations if x[0] in ("issuer", "market", "industry"))))
        signature = fact_signature(body)
        shingles = None
        for previous, old_day, old_signature, old_body in self.near[key]:
            if abs((day - old_day).days) > 7 or old_signature != signature:
                continue
            if shingles is None:
                shingles = {normalized[i:i + 5] for i in range(len(normalized) - 4)}
            old_shingles = {old_body[i:i + 5] for i in range(len(old_body) - 4)}
            if len(shingles & old_shingles) >= 0.965 * len(shingles | old_shingles):
                self.exact[digest] = previous
                return previous, "near"
        if len(self.near[key]) < 30:
            self.near[key].append((doc_version_id, day, signature, normalized))
        self.exact[digest] = doc_version_id
        return doc_version_id, None

