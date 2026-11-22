from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.fixture
def acquire():
    script = Path(__file__).resolve().parents[1] / "scripts" / "csmar_acquire.py"
    spec = importlib.util.spec_from_file_location("csmar_capture", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cached_page(tmp_path, acquire):
    calls = []
    job = {"table": "TEST", "columns": ["Stkcd"], "start": "2024-01-01", "end": "2024-01-01"}

    def download(*args):
        calls.append(args)
        return [{"Stkcd": "000001"}]

    first = acquire.request_cached(tmp_path, "query", job, "", download)
    assert acquire.request_cached(tmp_path, "query", job, "", download) == first
    with pytest.raises(acquire.SourceError, match="columns differ"):
        acquire.request_cached(tmp_path, "query", job | {"columns": ["Different"]}, "", download)
    assert len(calls) == 1
    next(tmp_path.rglob("*.jsonl.gz")).write_bytes(b"corrupt")
    with pytest.raises(acquire.SourceError, match="hash differs"):
        acquire.request_cached(tmp_path, "query", job, "", download)
    assert len(calls) == 1


def test_cooldown(tmp_path, acquire):
    calls = []
    job = {"table": "TEST", "columns": ["Stkcd"]}

    def rejected(*args):
        calls.append(args)
        raise acquire.DailyQuotaError("daily quota")

    with pytest.raises(acquire.DailyQuotaError, match="daily quota"):
        acquire.request_cached(tmp_path, "query", job, "", rejected)
    with pytest.raises(acquire.SourceError, match="cooldown"):
        acquire.request_cached(tmp_path, "query", job, "", rejected)
    assert len(calls) == 1


def test_acquisition_stops_at_first_daily_limit(tmp_path, acquire):
    calls = []

    class Client:
        def queryCount(self, _columns, _condition, table, *_):
            calls.append(("count", table))
            return 1

        def query(self, _columns, _condition, table, *_):
            calls.append(("detail", table))
            raise acquire.DailyQuotaError("CSMAR daily download quota reached (service code -2404)")

    plan = tmp_path / "plan.json"
    acquire.dump_json(plan, [{"table": name, "columns": ["Stkcd"]} for name in ("FIRST", "SECOND")])
    with pytest.raises(acquire.DailyQuotaError):
        acquire.acquire(Client(), tmp_path, plan, count_only=False)
    assert calls == [("count", "FIRST"), ("detail", "FIRST")]


def test_package_archive_is_compatible_and_reused(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import duckdb
    from csmar_acquire import archived_package_for, dump_json, file_sha256, request_cached
    from csmar_package_probe import acquire_package, archive_zip

    from kurumi.cn_capital_sources import csmar_capture

    out = tmp_path / "capture"
    package = tmp_path / "download"
    package.mkdir()
    job = {"table": "TEST", "columns": ["Stkcd", "Accper", "Amount"], "condition": "",
           "start": "2024-01-01", "end": "2024-12-31"}
    dump_json(out / "fields/TEST.json", {"data": [
        {"field": "Stkcd", "fieldName": "Code", "fieldType": "varchar", "fieldKey": "Code"},
        {"field": "Accper", "fieldName": "Date", "fieldType": "varchar", "fieldKey": "Date"},
        {"field": "Amount", "fieldName": "Cash", "fieldType": "decimal"},
    ]})
    source = package / "package.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("TEST[DES][csv].txt", "Stkcd [Code]\nAccper [Date]\nAmount [Cash]\n")
        archive.writestr("TEST.csv", "Stkcd,Accper,Amount\n000001,2024-04-30,-1.25\n000002,2024-12-31,\n")
    dump_json(package / "package_probe.json", {"scope": job, "status": "zip_verified", "count": 2,
                                               "zip_sha256": file_sha256(source), "zip_bytes": source.stat().st_size})
    request_cached(out, "count", job, "", lambda *_: 2)
    imported = archive_zip(out, job, package)
    assert acquire_package(None, out, job, 2, None) == imported
    assert archive_zip(out, job, package) == imported
    assert archived_package_for(out, job | {"start": "2024-04-01", "end": "2024-06-30"}, "") == imported
    assert archived_package_for(out, job | {"start": "2023-01-01"}, "") is None
    with gzip.open(next(out.rglob("*.jsonl.gz")), "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    assert rows == [{"Stkcd": "000001", "Accper": "2024-04-30", "Amount": -1.25},
                    {"Stkcd": "000002", "Accper": "2024-12-31", "Amount": None}]
    with duckdb.connect() as con:
        receipts = csmar_capture(con, out / "requests", "TEST")
        assert receipts[0]["rows_in_query_count"] == 2
        assert con.sql("SELECT count(*) FROM TEST").fetchone() == (2,)
