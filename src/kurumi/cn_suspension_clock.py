"""Resolve date-only notices and independently timed public suspension evidence."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

import pyarrow as pa

from .cn_pit import LOCAL, _known_sample_day


def suspension_schedule(evidence):
    facts = json.loads(evidence.read_text(encoding="utf-8-sig"))
    output = []
    for row in facts:
        state = row["state"]
        if state not in {"suspended", "listing_suspended", "reported_suspension"}:
            continue
        first = date.fromisoformat(row["effective_from"])
        stop = date.fromisoformat(row["effective_to_exclusive"])
        clock = row.get("public_fact_available_by")
        if state == "reported_suspension" and clock:
            raise ValueError("Later observed suspension facts cannot supply a public input clock")
        if state == "reported_suspension":
            known = first
        else:
            publication = date.fromisoformat(row["start_published_date"])
            known = publication + timedelta(days=1)
            if clock:
                moment = datetime.fromisoformat(clock)
                if (moment.tzinfo is None or moment.astimezone(LOCAL).date() != publication
                        or not re.fullmatch(r"[a-f0-9]{64}", row["public_fact_source_sha256"])
                        or not row["public_fact_source_url"].startswith("https://")):
                    raise ValueError(f"Invalid contemporaneous suspension proof for {row['ts_code']}")
                known = _known_sample_day(moment)
        output.append((row["ts_code"], state, str(row["start_source_id"]), max(first, known), stop))
    schema = pa.schema({"ts_code": pa.string(), "state": pa.string(), "start_source_id": pa.string(),
                        "first_known_session": pa.date32(), "effective_to_exclusive": pa.date32()})
    return pa.Table.from_arrays([pa.array([row[i] for row in output], type=field.type)
                                 for i, field in enumerate(schema)], schema=schema)
