from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from kurumi.cn_text_corpus import Deduplicator, IdentityHistory, choose_spans, html_body, publication
from kurumi.cn_text_index import Selector
from kurumi.encoding_cache import EncodingCache
from kurumi.text_input import text_condition


class TestBudget:
    __test__ = False

    @staticmethod
    def count(text):
        return len(text)

    @staticmethod
    def counts(texts):
        return list(map(len, texts))


def test_date_only_and_exact_schedules_do_not_use_next_body_early():
    trade_day = date(2025, 2, 14)
    cutoff = datetime(2025, 2, 14, 15, 59, 59, tzinfo=UTC)
    post = publication("2025-02-14")[2]
    assert post == cutoff + timedelta(seconds=1)
    relation = [("issuer", "CN-302132.SZ", "direct", "source_historical_code")]
    rows = []
    for i, available in enumerate((publication("2025-02-14T12:35:01+08:00")[2], post)):
        rows.append(dict(doc_version_id=str(i), kind="announcement", published_local_day=trade_day,
                         available_at=available, document_class="periodic", duplicate_group=str(i),
                         version_group="issuer-report-Q4", input_text=f"version {i}", input_tokens=9,
                         correction_or_progress=bool(i), relations=relation, facts=1))
    selector = Selector(rows, TestBudget(), "test")
    selector.build_calendar([(trade_day, cutoff), (date(2025, 2, 17), cutoff + timedelta(days=3))])
    for day_cutoff, previous in (((trade_day, cutoff), "0"),
                                 ((date(2025, 2, 17), cutoff + timedelta(days=3)), "1")):
        refs = tuple(selector.calendar[day_cutoff][("issuer", "CN-302132.SZ")])
        assert selector.select("announcement", refs, ())[0] == (previous,)


def test_duplicate_guard_keeps_amount_and_event_stage_changes():
    dup = Deduplicator()
    d = date(2024, 4, 19)
    relations = [("issuer", "issuer-a", "direct", "source_historical_code")]
    opening = "本项目将服务于公共交通和城市基础设施，主要产品由发行人生产。" * 8
    v1 = opening + "签署合同金额1.5亿元，尚未收到付款。"
    assert dup.group("old", "announcement", "重大合同", v1, relations, d) == ("old", None)
    assert dup.group("same", "announcement", "重大合同", " " + v1 + "\n", relations, d) == ("old", "exact")
    edited_amount = v1.replace("1.5亿元", "1.6亿元")
    edited_stage = v1.replace("尚未收到付款", "已完成付款")
    assert dup.group("amount", "announcement", "重大合同", edited_amount, relations, d)[1] is None
    assert dup.group("progress", "announcement", "重大合同", edited_stage, relations, d)[1] is None


def test_old_codes_and_renamed_or_delisted_company_must_match_the_historical_date():
    dates = tuple(date.fromisoformat(x) for x in ("2015-01-05", "2025-02-16", "2025-02-17", "2026-01-07"))
    history = IdentityHistory.__new__(IdentityHistory)
    history.issuers = {"stable": "stable-issuer"}
    history.codes = defaultdict(list, {"300114": [(dates[0], dates[1], "stable", "SZSE")],
                                      "302132": [(dates[2], dates[3], "stable", "SZSE")]})
    assert history.from_code("300114", "SZSE", dates[1]) == "stable"
    assert history.from_code("300114", "SZSE", dates[2]) is None
    assert history.from_code("302132", "SZSE", dates[1]) is None
    assert history.from_code("302132", "SZSE", dates[3] + timedelta(days=1)) is None
    assert history.from_code("302132", "BSE", dates[2]) is None


def test_selected_evidence_keeps_conditions_and_points_back_to_original_page():
    raw = ("本公司董事会及全体董事保证本公告内容不存在虚假记载、误导性陈述或者重大遗漏。"
           "\n\n拟签订合同，金额12.6亿元。若未获得批准，则不得实施。"
           "\f上海证券报网络版郑重声明\n\n目前仍尚未确认收入，存在违约风险。")
    row = {"title": "重大合同进展", "publisher": "某公司", "provider": "CNINFO",
           "kind": "announcement", "document_class": "event", "published_raw": "2024-04-19"}
    selected, offsets, raw_tokens, tokens, _, kept = choose_spans(row, raw, TestBudget())
    assert "虚假记载" not in selected and "网络版郑重声明" not in selected
    assert {"12.6亿元", "未获", "不得"} & set(kept) and "不得实施" in selected
    assert raw_tokens > tokens
    assert all(raw[s["start"]:s["end"]].strip() in selected for s in offsets)
    assert {s["page"] for s in offsets} == {1, 2}


def test_four_training_groups_have_fixed_evaluation_input():
    assert [text_condition(g, "train") for g in ("G0", "GN", "GA", "GNA")] == [
        "none", "news", "announcement", "both"]
    assert {text_condition(g, "test") for g in ("G0", "GN", "GA", "GNA")} == {"both"}
    assert text_condition("GNA", "test", no_text_diagnostic=True) == "none"

def test_plan_cache_coalesces_lru_writes_without_changing_the_cached_payload(tmp_path, monkeypatch):
    clock = 10_000_000_000
    monkeypatch.setattr("kurumi.encoding_cache.time.time_ns", lambda: clock)
    key = ("text-v1", "CN/2024-04", "id", "request")
    cache = EncodingCache(tmp_path, max_bytes=4 * 1024**2, touch_interval_seconds=60)
    try:
        cache.put(*key, b"encoded")
        clock += 1_000_000_000
        assert cache.get(*key) == b"encoded"
        assert cache.db.execute("SELECT last_used FROM plans").fetchone()[0] == 10_000_000_000
        clock += 60_000_000_000
        assert cache.get(*key) == b"encoded"
        assert cache.db.execute("SELECT last_used FROM plans").fetchone()[0] == clock
        assert cache.get(*key[:-1], "different") is None
    finally:
        cache.close()

def test_extracts_the_original_company_text_from_old_newspaper_markup():
    document = """<html lang="zh"><div id="Main"><div id="content">
    <h1>历史报纸版次</h1>
    <div id="content_article"><p>公司签订合同，金额12亿元。</p>
    <p>合同尚待合作方批准。</p></div><p>返回版次索引</p></div></div></html>"""
    capture = SimpleNamespace(read=lambda receipt: document.encode())
    record = {"provider": "CNSTOCK-paper", "title": "公告报道", "published_raw": "2015-01-12"}
    assert html_body(capture, record, {}) == "公司签订合同，金额12亿元。\n\n合同尚待合作方批准。"
    assert record["published_raw"] == "2015-01-12"
