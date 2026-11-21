import json

import pytest

from scripts.replace_cn_financial_versions import replace


def test_reviewed_same_clock_improves_known_fields_only(tmp_path):
    original = dict(ts_code="832317.BJ", period_end="2022-03-31", published_at="2022-04-20",
                    source_version_id="prior", source_sha256="a" * 64, assets=10.0)
    improved = original | dict(source_version_id="original", source_sha256="b" * 64, revenue_ytd=3.0)
    untouched = original | {"ts_code": "000001.SZ"}
    source = tmp_path / "source.jsonl"
    output = tmp_path / "output.jsonl"
    source.write_text("\n".join(map(json.dumps, (original, untouched))) + "\n", encoding="utf-8")
    result = replace(source, [improved], [original], output)
    assert result["replacements"][0]["new_fields"] == ["revenue_ytd"]
    assert [json.loads(line) for line in output.read_bytes().splitlines()] == [improved, untouched]
    with pytest.raises(ValueError, match="Existing certified amounts changed"):
        replace(source, [improved | {"assets": 11.0}], [original], output)
    assert json.loads(output.read_bytes().splitlines()[0]) == improved

    amended = improved | {"published_at": "2023-04-28", "revenue_ytd": 2.5}
    result = replace(source, [improved], [original], output, [amended])
    assert result["rows"] == 3
    assert [json.loads(line) for line in output.read_bytes().splitlines()] == [improved, untouched, amended]
    with pytest.raises(ValueError, match="Supplement duplicates an existing publication clock"):
        replace(source, [improved], [original], output, [untouched])
    assert len(output.read_bytes().splitlines()) == 3
