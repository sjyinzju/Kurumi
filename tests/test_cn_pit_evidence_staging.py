import pytest

from scripts.stage_cn_pit_evidence import stage


def test_frozen_pit_sources_are_isolated_and_reused_when_unchanged(tmp_path):
    root = tmp_path / "archive"
    mutable = tmp_path / "financial_versions.jsonl"
    mutable.write_text('{"version":1}\n', encoding="utf-8")
    first = stage(root, [mutable])
    frozen_finance = first / mutable.name
    assert not mutable.samefile(frozen_finance)

    mutable.write_text('{"version":2}\n', encoding="utf-8")
    assert frozen_finance.read_text(encoding="utf-8") == '{"version":1}\n'

    shares = tmp_path / "share_versions.jsonl"
    shares.write_text('{"shares":10}\n', encoding="utf-8")
    second = stage(root, [frozen_finance, shares])
    assert (second / mutable.name).read_bytes() == frozen_finance.read_bytes()
    assert len(list((root / ".objects").iterdir())) == 2
    assert stage(root, [frozen_finance, shares]) == second


def test_frozen_cross_class_versions_require_quotes_and_fx(tmp_path):
    finance = tmp_path / "financial_versions.jsonl"
    classes = tmp_path / "issuer_class_versions.jsonl"
    finance.write_text("", encoding="utf-8")
    classes.write_text('{"version":1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"class_fx\.parquet, class_quotes\.parquet"):
        stage(tmp_path / "archive", [finance, classes])
