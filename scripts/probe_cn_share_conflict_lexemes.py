"""Record current exact TuShare response tokens for a small V3 conflict sample."""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import requests


class CapturedSession(requests.Session):
    def post(self, *args, **kwargs):
        response = super().post(*args, **kwargs)
        self.content_digest = hashlib.sha256(response.content).hexdigest()
        response.json = lambda: json.loads(response.content, parse_float=Decimal)
        return response


def main():
    from quant.config import load_settings
    from quant.data.sources.tushare import SourceError, TushareAdapter

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--data-root", default=Path("E:/QuantData"), type=Path)
    args = parser.parse_args()
    examples = json.loads(args.sample.read_bytes())["examples"]
    selected = [r for r in examples if r["abs_delta"] <= 10 or r["ts_code"] in {
        "300427.SZ", "002839.SZ", "600367.SH", "600958.SH",
    }]
    fields = ("ts_code", "trade_date", "total_share", "total_mv", "close")
    spec = SimpleNamespace(endpoint="daily_basic", schema_spec=SimpleNamespace(fields=fields))
    audit = []
    with CapturedSession() as session:
        settings = load_settings(args.data_root).model_copy(update={"requests_per_minute": 20, "timeout_seconds": 12})
        adapter = TushareAdapter(settings, session=session)
        for sample in selected:
            query = {"ts_code": sample["ts_code"], "trade_date": sample["first_date"].replace("-", "")}
            session.content_digest = None
            evidence = {"query": query, "canonical_ts_total_share": sample["ts_total_share"],
                        "canonical_batch_id": sample["share_check_batch_id"], "canonical_row_hash": sample["raw_row_hash"]}
            try:
                result = adapter.fetch(spec, query)
                if len(result.rows) != 1:
                    raise ValueError(f"Expected one scoped response row, received {len(result.rows)}")
                row = dict(zip(result.fields, result.rows[0], strict=True))
                if any(row.get(field) != value for field, value in query.items()):
                    raise ValueError("Response does not correspond to its requested stock and date")
                total = row["total_share"]
                evidence.update(status="ok", observed_at=str(result.fetched_at), response_fields=list(result.fields),
                                total_share_token=str(total), total_mv_token=str(row["total_mv"]),
                                close_token=str(row["close"]), share_quantity=str(Decimal(total) * 10000),
                                matches_old_canonical=Decimal(total) == Decimal(str(sample["ts_total_share"])))
            except (SourceError, ValueError) as error:
                evidence.update(status="error", error_type=type(error).__name__, reason=str(error))
            evidence["response_sha256"] = session.content_digest
            audit.append(evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"requests": len(audit), "matched": sum(r.get("matches_old_canonical", False) for r in audit)}))


if __name__ == "__main__":
    main()
