"""Probe one CSMAR package using the shipping SDK and retain the original ZIP."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import TextIOWrapper
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

from csmar_acquire import (
    CSMAR_DAY, PAGE_ROWS, PROJECT, RUNTIME, DailyQuotaError, SourceError, dump_json, file_sha256, now, receipt_path, service,
)


def result(client, sign):
    import websocket

    try:
        with closing(websocket.create_connection(client.urlUtil.getWebsocketUrl(), timeout=25)) as conn:
            token, _, _ = client.getTokenFromFile()
            conn.send(json.dumps({"outlineId": sign, "status": "start", "token": token.strip()}))
            deadline = monotonic() + 300
            while monotonic() < deadline:
                raw = conn.recv()
                data = json.loads(raw)
                if data.get("code") != 0:
                    if data.get("code") == -2404:
                        raise DailyQuotaError("CSMAR daily download quota reached (service code -2404)")
                    raise SourceError(f"CSMAR package status rejected (service code {int(data['code'])})")
                state = data.get("data", {})
                if str(state.get("status")) == "1":
                    return state, hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest(), "websocket"
                if str(state.get("status")) == "0":
                    raise SourceError("CSMAR reported packaging failure (status 0)")
    except (OSError, websocket.WebSocketException, ValueError, TypeError, KeyError, AttributeError):
        pass
    # The SDK also exposes a status query for the same already submitted package.
    data = client.getPackResultBySignCode(sign)["data"]
    if str(data.get("status")) != "1":
        raise SourceError("CSMAR package result is not ready after the status check")
    return data, client.last_response_sha256, "poll"


def download(client, state, path):
    import urllib3

    url = state["filePath"]
    domain = urlsplit(url)
    if domain.scheme != "https" or not (domain.hostname == "csmar.com" or (domain.hostname or "").endswith(".csmar.com")):
        raise SourceError("Package download address is outside the official HTTPS service")
    temporary = path.with_suffix(".zip.part")
    sha = hashlib.sha256()
    try:
        response = client.http.request("GET", url, preload_content=False, redirect=False)
        try:
            if response.status != 200:
                raise SourceError(f"CSMAR ZIP HTTP status {response.status}")
            with temporary.open("wb") as output:
                for block in response.stream(1 << 20):
                    sha.update(block)
                    output.write(block)
        finally:
            response.close()
            response.release_conn()
    except (OSError, urllib3.exceptions.HTTPError) as exc:
        raise SourceError(f"CSMAR package download failure ({type(exc).__name__})") from None
    try:
        with ZipFile(temporary) as zipped:
            if zipped.testzip() is not None:
                raise SourceError("CSMAR ZIP member checksum mismatch")
            members = [{"file": m.filename, "bytes": m.file_size} for m in zipped.infolist() if not m.is_dir()]
    except BadZipFile:
        if temporary.stat().st_size <= 64_000:
            try:
                error = json.loads(temporary.read_bytes())
            except (UnicodeError, json.JSONDecodeError):
                error = None
            if isinstance(error, dict) and error.get("code") == -2404:
                raise DailyQuotaError("CSMAR daily download quota reached (service code -2404)") from None
        raise SourceError("CSMAR package download is not a valid ZIP") from None
    temporary.replace(path)
    return {"zip_sha256": sha.hexdigest(), "zip_bytes": path.stat().st_size, "members": members}


def fetch_zip(client, job, count, directory, count_hash):
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / "package_probe.json"
    ticket = directory / "package.pending"
    state = json.loads(receipt.read_bytes()) if receipt.is_file() else {"scope": job, "requested_at": now()}
    if state["scope"] != job:
        raise SourceError("Existing package probe receipt belongs to another scope")
    source = directory / "package.zip"
    if state.get("status") == "zip_verified":
        if not source.is_file() or file_sha256(source) != state["zip_sha256"]:
            raise SourceError("Existing CSMAR package ZIP is missing or differs from its receipt")
        return state
    if state.get("pack_submit_started") and not ticket.is_file():
        previous = datetime.fromisoformat(state["pack_submit_started"])
        if "-2404" not in state.get("error", "") or (
            previous.astimezone(CSMAR_DAY).date() >= datetime.now(CSMAR_DAY).date()
            or datetime.now(UTC) - previous < timedelta(minutes=30)
        ):
            raise SourceError("Previous package submission recorded. Reusing the recorded result or rejection prevents duplicate detail requests.")
    try:
        if not ticket.is_file():
            state.update(count=count, count_response_sha256=count_hash)
            state.update(pack_submit_started=now(), status="submitting")
            dump_json(receipt, state)
            response = client.pack(job["columns"], job["condition"], job["table"], job["start"], job["end"])
            sign = response["data"]
            if not isinstance(sign, str) or not sign:
                raise SourceError("SDK package response did not supply a result identifier")
            ticket.write_text(sign, encoding="utf-8")
            state.update(status="submitted", pack_response_sha256=client.last_response_sha256)
            dump_json(receipt, state)
            print(f"CSMAR accepted one package submission for {count:,} counted rows", flush=True)
        info, status_hash, channel = result(client, ticket.read_text(encoding="utf-8"))
        state.update(status="downloading", result_response_sha256=status_hash, result_channel=channel)
        dump_json(receipt, state)
        state.update(download(client, info, source), status="zip_verified", observed_at=now())
        state.pop("error", None)
        dump_json(receipt, state)
        ticket.unlink()
        print(f"CSMAR ZIP verified: {state['zip_bytes']:,} bytes, {len(state['members'])} members", flush=True)
        return state
    except SourceError as exc:
        state.update(status="failed", error=str(exc), failed_at=now())
        if client and client.last_response_sha256:
            state["last_response_sha256"] = client.last_response_sha256
        dump_json(receipt, state)
        raise


def convert_row(values, fields, date_fields, job):
    row = {}
    for name, value in zip(job["columns"], values, strict=True):
        if value and name in date_fields:
            try:
                day = date.fromisoformat(value[:10]).isoformat()
            except ValueError as exc:
                raise SourceError(f"Invalid date in package field {name}") from exc
            if (job["start"] and day < job["start"]) or (job["end"] and day > job["end"]):
                raise SourceError(f"Out-of-scope date in package field {name}")
        if value and fields[name]["fieldType"] in {"decimal", "int", "bigint", "double", "float"}:
            try:
                number = Decimal(value)
            except InvalidOperation as exc:
                raise SourceError(f"Invalid numeric package field {name}") from exc
            if not number.is_finite():
                raise SourceError(f"Non-finite numeric package field {name}")
            value = int(number) if number == number.to_integral_value() else float(number)
        row[name] = value if value != "" else None
    return row


def archive_zip(out, job, directory):
    state = json.loads((directory / "package_probe.json").read_bytes())
    if state["scope"] != job or state["status"] != "zip_verified":
        raise SourceError("CSMAR ZIP scope differs from the verified package receipt")
    source = directory / "package.zip"
    if file_sha256(source) != state["zip_sha256"]:
        raise SourceError("Package ZIP hash differs from the verified download")
    path, query = receipt_path(out, "package", job, job["condition"])
    if path.is_file():
        return cached_package(path, job, state["count"])
    archive = path.with_suffix(".zip")
    page = path.with_suffix(".jsonl.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((out / "fields" / f"{job['table']}.json").read_bytes())["data"]
    fields = {f["field"]: f for f in metadata if f["field"] in job["columns"]}
    date_keys = {name for name, field in fields.items() if field.get("fieldKey") == "Date"}
    date_fields = date_keys if len(date_keys) == 1 else set()
    if fields.keys() != set(job["columns"]):
        raise SourceError("Package requests fields absent from the official dictionary")
    count = 0
    temporary = page.with_suffix(".part")
    try:
        with ZipFile(source) as zipped:
            table = job["table"]
            instructions = zipped.read(f"{table}[DES][csv].txt")
            description = instructions.decode("utf-8-sig")
            for name in job["columns"]:
                if f"{name} [{fields[name]['fieldName']}]" not in description:
                    raise SourceError(f"Package field description disagrees with metadata for {name}")
            with TextIOWrapper(zipped.open(f"{table}.csv"), encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                if next(reader, None) != job["columns"]:
                    raise SourceError("Package CSV header differs from requested fields")
                with gzip.open(temporary, "wt", encoding="utf-8", newline="\n", compresslevel=5) as output:
                    for values in reader:
                        try:
                            row = convert_row(values, fields, date_fields, job)
                        except ValueError as exc:
                            raise SourceError("Package CSV field count differs from header") from exc
                        output.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
                        count += 1
        if count != state["count"]:
            raise SourceError(f"Package contains {count} rows, expected {state['count']}")
        digest = file_sha256(temporary)
        tmp_zip = archive.with_suffix(".zip.part")
        shutil.copyfile(source, tmp_zip)
        if file_sha256(tmp_zip) != state["zip_sha256"]:
            raise SourceError("Package ZIP changed during archival")
        tmp_zip.replace(archive)
        temporary.replace(page)
    except (BadZipFile, KeyError, UnicodeError, csv.Error) as exc:
        raise SourceError(f"Could not verify the official ZIP structure ({type(exc).__name__})") from None
    finally:
        temporary.unlink(missing_ok=True)
    record = {**state, "query": query, "columns": job["columns"], "status": "ok", "rows": count,
              "field_description_sha256": hashlib.sha256(instructions).hexdigest(), "sha256": digest}
    dump_json(path, record)
    return record


def cached_package(path, job, expected):
    state = json.loads(path.read_bytes())
    if (state["columns"] != job["columns"] or state["rows"] != expected
            or file_sha256(path.with_suffix(".jsonl.gz")) != state["sha256"]
            or file_sha256(path.with_suffix(".zip")) != state["zip_sha256"]):
        raise SourceError("Cached package data or metadata differs")
    return state


def acquire_package(client, out, job, expected, count_hash):
    path, _ = receipt_path(out, "package", job, job["condition"])
    if path.is_file():
        return cached_package(path, job, expected)
    directory = out / ".package-work" / path.stem
    fetch_zip(client, job, expected, directory, count_hash)
    return archive_zip(out, job, directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sdk", type=Path, default=RUNTIME / "sdk")
    parser.add_argument("--env", type=Path, default=PROJECT / ".env")
    parser.add_argument("--archive-to", type=Path, help="Import the verified ZIP into the existing source archive")
    args = parser.parse_args()
    job = json.loads(args.scope.read_bytes())
    try:
        if args.archive_to:
            record = archive_zip(args.archive_to, job, args.output)
            print(f"Archived {record['rows']:,} verified package rows", flush=True)
        else:
            client = service(args.sdk, args.env)
            count = int(client.queryCount(job["columns"], job["condition"], job["table"], job["start"], job["end"]))
            if count <= PAGE_ROWS:
                raise SourceError("Package test scope no longer exceeds 200,000 rows")
            fetch_zip(client, job, count, args.output, client.last_response_sha256)
    except SourceError as exc:
        print(str(exc), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
