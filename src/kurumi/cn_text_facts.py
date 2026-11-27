"""Extract attributable, whole evidence passages from archived originals."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .cn_text_corpus import ECONOMIC, SPACE, evidence_spans, normalized_body, source_metadata
from .cn_text_sources import sha

EVIDENCE_VERSION = "cn-company-evidence.v1"
LIMITS = {
    "conservative": {"news": 480, "event": 620, "periodic": 416},
    "compact": {"news": 256, "event": 288, "periodic": 224},
}
PREDICATE = re.compile(
    r"签订|签署|中标|订立|中选|交付|投产|扩产|减产|停产|复产|开工|投运|"
    r"收购|出售|划转|重组|增资|减资|回购|分红|派发|减持|增持|质押|解押|"
    r"处罚|立案|调查|起诉|被诉|判决|裁定|仲裁|逾期|违约|偿还|被冻结|"
    r"退市|停牌|复牌|风险警示|撤销|终止|取消|减值|计提|核销|"
    r"调整|更正|修订|上修|下修|预计|预亏|扭亏|减少|增加|增长|下降|亏损|"
    r"实现|录得|达到|降至|升至|获批|批准|通过|决定|授信|发行|募集|"
    r"达成|开发|许可|突破|获得|接获|收到|接到|完成|验收|供应|受理|确认|承诺|"
    r"(?:营业(?:总)?收入|净利(?:润)?|现金流净额)(?:同比|为|达)"
)
SUBJECT = re.compile(
    r"(?:营业(?:总)?收入|净利润|毛利率|净资产|经营活动.{0,8}现金流|"
    r"每股收益|产销量|销量|产量|订单|合同|货款|应收|贷款|投资额|"
    r"万元|亿元|万美元|亿元人民币|万股|人民币)"
)
OPERATING_SUBJECT = re.compile(r"收入|净利润|毛利率|净资产|现金流|每股收益|产销量|销量|产量|订单|合同|货款|应收|贷款")
QUANTITY = re.compile(r"(?<!\d)[+−-]?\d[\d,.]*(?:\s*[亿万千百]?[元股吨台人]|\s*[%％]|\s*个百分点)")
MARKET_ONLY = re.compile(r"涨停|跌停|换手|成交额|股价|涨幅|跌幅|市盈率|市值|收盘|开盘|北向资金")
CONTEXT = re.compile(
    r"^(?:该[项目合同交易事项收购判决调整]|其中|上述|本次|原[公告预案合同]|"
    r"更正[前后]|修订[前后]|若|如[果未获尚]|待|尚[需待未]|但|同时仍|仍[需待未有]|"
    r"不[构成会涉及]|未[完成实施达到取得收到确认]|条件|风险提示)"
)
PROTECTION = re.compile(r"尚未|未获|不再|不得|有待|不确定|若|待|更正|修订|终止|取消|违约")
CHROME = re.compile(
    r"重大遗漏|误导性陈述|真实[、,]准确[、,]完整|承担.{0,10}法律责任|"
    r"敬请.{0,6}投资者注意投资风险[。！]?$|详情请[查阅参见]|"
    r"详见.{0,16}(?:指定|巨潮|披露)|证券代码.{0,24}公告编号"
)
PROCEDURAL = re.compile(r"审议通过.{0,20}议案|通过.{0,15}年度报告")
SENTENCE = re.compile(r"[^。！？]+[。！？]*")
COMPARISON = re.compile(r"相较|相比|比较|与.{0,16}(?:相同|类似)|包括|例如|等多家|以及|、|均[报称有在已将获须需]")
VERB_BRIDGE = re.compile(r"(?:公告|表示|称|披露|消息|记者获悉|方面|旗下|下属|全资子公司|董事会)")
UNSAFE_COLUMNS = re.compile(r"[\u3400-\u9fff] {3,}[\u3400-\u9fff]|\d {3,}[-+−]?\d")
CLAUSE_END = re.compile(r"[。！？][”’」』）)]*$")
METRIC_ROW = re.compile(r"^ *营业(?:总)?收入[ \t]*(?:[（(](?:万?元|人民币万?元)[）)])?[^\S\n]{2,}[-+−]?\d[^\n]*", re.M)
METRIC_START = re.compile(r"本报告期|本季度|本期金额|年初至报告期末|单位\s*[:：]\s*(?:万?元|人民币)")
PERIOD_COLUMNS = re.compile(r"本报告期|本季度|本期金额|年初至报告期末")
MONEY_UNIT = re.compile(r"[（(](?:万?元|人民币万?元)[）)]|单位\s*[:：]\s*(?:万?元|人民币)")
TABLE_NUMBER = re.compile(r"(?<![\d.])[-−+]?\d[\d,]*(?:\.\d+)?%?")


def normal_literal(text):
    return normalized_body(text).strip("。；;")


def substantive(text):
    if len(text) < 12 or CHROME.search(text):
        return False
    subject = SUBJECT.search(text)
    if MARKET_ONLY.search(text) and not OPERATING_SUBJECT.search(text) and not ECONOMIC.search(text):
        return False
    if subject and QUANTITY.search(text):
        return True
    return bool(PREDICATE.search(text) and (ECONOMIC.search(text) or subject or QUANTITY.search(text))
                and not (PROCEDURAL.search(text) and not QUANTITY.search(text)))


def fragments(body, *, complete_prose):
    for start, end, page, _ in evidence_spans(body):
        literal = body[start:end]
        parts = list(SENTENCE.finditer(literal))
        for i, part in enumerate(parts):
            text = SPACE.sub(" ", part[0]).strip()
            if (complete_prose and not CLAUSE_END.search(text)) or len(UNSAFE_COLUMNS.findall(part[0])) >= 2:
                continue
            has_context = CONTEXT.match(text)
            if has_context and i and substantive(SPACE.sub(" ", parts[i - 1][0]).strip()):
                continue
            if not substantive(text):
                continue
            final = part.end()
            for following in parts[i + 1:i + 3]:
                follow_text = SPACE.sub(" ", following[0]).strip()
                if ((complete_prose and not CLAUSE_END.search(follow_text)) or not CONTEXT.match(follow_text)
                        or UNSAFE_COLUMNS.search(following[0])):
                    break
                final = following.end()
            yield (start + part.start(), start + final, page,
                   SPACE.sub(" ", literal[part.start():final]).strip())


def periodic_table(body):
    """Keep a reported metric with its printed currency and period headers when all are present."""
    page_offset = 0
    for page, literal in enumerate(body.split("\f")[:14], start=1):
        for row in METRIC_ROW.finditer(literal):
            prior = literal[max(row.start() - 540, 0):row.start()]
            range_start = next((m.start() for m in METRIC_START.finditer(prior)), None)
            if range_start is None:
                continue
            header = prior[range_start:]
            if not PERIOD_COLUMNS.search(header) or not MONEY_UNIT.search(header + row[0]):
                continue
            if len(TABLE_NUMBER.findall(row[0])) < 2:
                continue
            start = row.start() - len(prior) + range_start
            end = row.end()
            # A line may contain a clean second metric in the same columns. Stop at any wrapped row.
            next_row = re.match(r"\n\s*归属于(?:上市公司|母公司)[^\n]{0,26}净利润[^\n]*", literal[end:])
            if next_row and len(TABLE_NUMBER.findall(next_row[0])) == len(TABLE_NUMBER.findall(row[0])):
                end += next_row.end()
            yield (page_offset + start, page_offset + end, page,
                   SPACE.sub(" ", literal[start:end]).strip())
            return
        page_offset += len(literal) + 1


def news_actor(text, identity, day):
    text = unicodedata.normalize("NFKC", text)
    matches = identity.mentions(text, day)
    if not matches:
        return None
    start, end, instrument, name = matches[0]
    intro = text[:start]
    if start > 30 or COMPARISON.search(intro) or PREDICATE.search(intro):
        return None
    tail = text[end:]
    verb = PREDICATE.search(tail)
    if not verb or verb.start() > 58 or COMPARISON.search(tail[:verb.start()]):
        return None
    if any(pos < end + verb.start() and other != instrument for pos, _, other, _ in matches[1:]):
        return None
    lead = tail[:verb.start()]
    if len(lead) > 23 and not VERB_BRIDGE.search(lead):
        return None
    for pos, end_pos, other, _ in matches[1:]:
        if other != instrument and re.search(r"[,，；。]", text[end + verb.start():pos]):
            if PREDICATE.search(re.split(r"[,，；。]", text[end_pos:], maxsplit=1)[0]):
                return None
    # A later sentence independently asserting another issuer's action is no longer this actor's evidence.
    suffix = text.split("。", 1)[-1] if "。" in text else ""
    if suffix and any(other != instrument for _, _, other, _ in identity.mentions(suffix, day)):
        return None
    return instrument, name


def company_facts(row, body, identity, day, relations):
    """Return whole fact spans grouped by the actor that can see them in training."""
    if not day or row.get("news_scope") == "macro":
        return {}
    result = defaultdict(list)
    observed_names = {}
    issuer_link = [link for link in relations if link[0] == "instrument"]
    if row["kind"] == "announcement" and len(issuer_link) != 1:
        return {}
    for span in fragments(body, complete_prose=row["kind"] == "announcement"):
        if row["kind"] == "announcement":
            instrument, name = issuer_link[0][1], row.get("publisher")
            # The original disclosure identifies its reporting issuer. Do not count an unrelated actor's news.
            if not name:
                name = identity.name_at(instrument, day)
        else:
            actor = news_actor(span[-1], identity, day)
            if not actor:
                continue
            instrument, name = actor
        observed_names.setdefault(instrument, identity.name_at(instrument, day) or name or row.get("symbol") or "")
        result[instrument].append(span)
    if row["kind"] == "announcement" and row["document_class"] == "periodic":
        instrument = issuer_link[0][1]
        table = next(periodic_table(body), None)
        if table:
            observed_names.setdefault(instrument, identity.name_at(instrument, day) or row.get("publisher") or "")
            result[instrument].insert(0, table)
    return {(instrument, observed_names[instrument]): spans for instrument, spans in result.items()}


def fact_key(issuer, name, text):
    literal = normal_literal(text)
    if name:
        subject = normal_literal(name)
        literal = re.sub(r"^(?:(?:记者获悉|公告显示)[,，:：])", "", literal)
        literal = re.sub(r"^(?:本公司|公司)", subject, literal)
        literal = re.sub(r"^" + re.escape(subject) + r"(?:发布公告称|发布公告|公告称|披露称|表示)[:,，]?", subject,
                         literal)
    return sha((issuer + "\0" + literal).encode())[:32]


def pick_facts(row, spans, issuer, name, budget, profile):
    if row["kind"] == "news":
        heading = f"{name}\n{row.get('publisher') or row['provider']} · {row['published_raw']}"
    else:
        heading = source_metadata(row)
    limit = LIMITS[profile][row["document_class"]]
    seen = set()
    candidates = []
    for number, span in enumerate(spans):
        text = span[-1]
        key = fact_key(issuer, name, text)
        if key in seen:
            continue
        seen.add(key)
        table = row["document_class"] == "periodic" and bool(
            PERIOD_COLUMNS.search(text) and MONEY_UNIT.search(text)
            and re.search(r"营业(?:总)?收入.{0,16}\d", text))
        explicit = bool(QUANTITY.search(text))
        opening = number < 3 and span[0] < 3_500 and explicit
        priority = (table, opening, bool(PROTECTION.search(text)), explicit, min(len(ECONOMIC.findall(text)), 3))
        candidates.append((priority, span, key))
    # Only useful passages are tokenized, and batching bounding both work and memory keeps large PDFs cheap.
    ranked = sorted(candidates, key=lambda x: (x[0], -x[1][0]), reverse=True)[:96]
    costs = budget.counts([span[-1] for _, span, _ in ranked])
    left = limit - budget.count(heading) - 2
    chosen = []
    for (_, span, key), cost in zip(ranked, costs, strict=True):
        if cost + 2 <= left:
            chosen.append((span, key))
            left -= cost + 2
    chosen.sort()
    while chosen:
        packed = heading + "\n" + "\n".join(span[-1] for span, _ in chosen)
        count = budget.count(packed)
        if count <= limit:
            return packed, [dict(start=s[0], end=s[1], page=s[2]) for s, _ in chosen], count, [
                key for _, key in chosen], len(candidates)
        chosen.pop()
    return "", [], 0, [], len(candidates)
