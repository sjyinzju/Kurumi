import json
from datetime import date

import pytest

from kurumi.cn_suspension_clock import suspension_schedule


def test_documented_same_day_public_fact_stays_distinct_from_date_only_notice(tmp_path):
    evidence = tmp_path / "halts.json"
    row = dict(ts_code="920808.BJ", state="suspended", effective_from="2025-05-26",
               effective_to_exclusive="2025-05-27", start_published_date="2025-05-26", start_source_id="original")
    evidence.write_text(json.dumps([row]), encoding="utf8")
    assert suspension_schedule(evidence)["first_known_session"][0].as_py() == date(2025, 5, 27)
    timed = row | dict(public_fact_available_by="2025-05-26T09:03:00+08:00",
                       public_fact_source_url="https://example.com/notice-report", public_fact_source_sha256="a" * 64)
    evidence.write_text(json.dumps([timed]), encoding="utf8")
    assert suspension_schedule(evidence)["first_known_session"][0].as_py() == date(2025, 5, 26)
    evidence.write_text(json.dumps([timed | {"public_fact_available_by": "2025-05-26T09:03:00"}]), encoding="utf8")
    with pytest.raises(ValueError, match="Invalid contemporaneous suspension proof"):
        suspension_schedule(evidence)
