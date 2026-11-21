from __future__ import annotations

import importlib.util
from pathlib import Path

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
