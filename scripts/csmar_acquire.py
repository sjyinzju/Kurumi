"""Acquire audited, resumable source snapshots using the official CSMAR SDK."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / "artifacts" / "cn_numeric" / "csmar_runtime"


class SourceError(RuntimeError):
    pass


class DailyQuotaError(SourceError):
    pass


def credentials(path: Path) -> tuple[str, str]:
    from dotenv import dotenv_values

    values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    legacy_labels = {"csmar账号": "csmar_account", "csmar密码": "csmar_password"}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            pair = re.split(r"[:：]", line, maxsplit=1)
            if len(pair) == 2 and (standard := legacy_labels.get(pair[0].strip().casefold())):
                values.setdefault(standard, pair[1].strip())
    values.update({key: os.environ[key] for key in ("CSMAR_ACCOUNT", "CSMAR_PASSWORD") if key in os.environ})
    folded = {key.casefold(): value for key, value in values.items()}
    account = folded.get("csmar_account") or folded.get("csmar_username")
    password = folded.get("csmar_password") or folded.get("csmar_pwd")
    if not account or not password:
        raise SourceError("CSMAR account/password are missing from the configured .env")
    return account, password


def service(sdk: Path, env: Path):
    import urllib3

    sys.path.insert(0, str(sdk.resolve()))
    from csmarapi.CsmarService import CsmarService
    from csmarapi.UrlUtil import UrlUtil

    class CsmarSession(CsmarService):
        def __init__(self):
            self.urlUtil = UrlUtil()
            self.logger = logging.getLogger("CsmarService")
            self.logger.disabled = True
            self.http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=8.0, read=145.0), retries=False)
            self.token = None
            self.secrets = ()
            self.last_response_sha256 = None

        def writeToken(self, token, lang, belong):
            self.token = [token, lang, belong] if token else None

        def getTokenFromFile(self):
            if self.token is None:
                raise SourceError("SDK session has no login token")
            return self.token

        def doPost(self, targetUrl, body=None, headers=None):
            return self.request("POST", targetUrl, body, headers)

        def doGet(self, targetUrl, headers=None):
            return self.request("GET", targetUrl, None, headers)

        def request(self, method, url, body, headers):
            try:
                result = self.http.request(method, url, body=body, headers=headers, redirect=False)
            except (urllib3.exceptions.HTTPError, OSError) as exc:
                raise SourceError(f"CSMAR connection failure ({type(exc).__name__})") from None
            if result.status != 200:
                raise SourceError(f"CSMAR HTTP status {result.status}")
            self.last_response_sha256 = hashlib.sha256(result.data).hexdigest()
            try:
                payload = json.loads(result.data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise SourceError("CSMAR returned a non-JSON response") from None
            code = payload.get("code") if isinstance(payload, dict) else None
            if code != 0:
                msg = str(payload.get("msg", "")) if isinstance(payload, dict) else ""
                categories = {
                    "captcha": ("验证码", "captcha", "验证登录"),
                    "institutional network": ("机构ip", "校内", "ip地址", "ip 地址"),
                    "credentials": ("密码错误", "账号或密码", "incorrect password", "invalid credentials"),
                    "permission": ("权限", "未购买", "授权", "permission", "not purchased"),
                    "rate limit": ("30分钟", "频繁", "重复", "次数限制", "次数已", "额度", "rate limit", "too many"),
                }
                label = next(
                    (label for label, words in categories.items() if any(word in msg.lower() for word in words)),
                    "service rejection",
                )
                safe_code = code if isinstance(code, int) else "unknown"
                detail = ""
                if method != "POST" or url != self.urlUtil.getLoginUrl():
                    for secret in (*self.secrets, *(self.token or [])[:1]):
                        msg = msg.replace(secret, "[redacted]")
                    detail = f" {msg.strip()[:240]}" if msg.strip() else ""
                if code == -2404 and "limit today" in msg.lower():
                    raise DailyQuotaError("CSMAR daily download quota reached (service code -2404)")
                raise SourceError(f"CSMAR {label} (service code {safe_code}){detail}")
            return payload

    client = CsmarSession()
    client.secrets = credentials(env)
    client.login(*client.secrets, "0")
    if client.token is None:
        raise SourceError("CSMAR login supplied no token")
    return client


def dump_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def now() -> str:
    return datetime.now(UTC).isoformat()


def request_cached(out: Path, method: str, job: dict, condition: str, fetch):
    query = {"method": method, "table": job["table"], "condition": condition,
             "start": job.get("start", ""), "end": job.get("end", "")}
    req_id = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
    path = out / "requests" / query["table"] / (req_id + ".json")
    data_path = path.with_suffix(".jsonl.gz")
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["status"] == "ok":
            if state["columns"] != job["columns"]:
                raise SourceError("Cached query columns differ; retain the original request and its evidence")
            if method == "query" and (
                not data_path.is_file()
                or hashlib.sha256(data_path.read_bytes()).hexdigest() != state["sha256"]
            ):
                raise SourceError("Cached data file missing or hash differs")
            return state
        retry_after = datetime.fromisoformat(state["requested_at"]) + timedelta(minutes=30)
        if datetime.now(UTC) < retry_after:
            raise SourceError(f"CSMAR request cooldown until {retry_after.isoformat()}")
    state = {"query": query, "columns": job["columns"], "requested_at": now(), "status": "requested"}
    dump_json(path, state)
    try:
        result = fetch(job["columns"], condition, job["table"], query["start"], query["end"])
        response_hash = getattr(getattr(fetch, "__self__", None), "last_response_sha256", None)
        if response_hash:
            state["response_body_sha256"] = response_hash
        if method == "count":
            if not (isinstance(result, int) or (isinstance(result, str) and result.isdecimal())):
                raise SourceError("Unexpected result type from queryCount")
            state["rows"] = int(result)
        else:
            if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                raise SourceError("Unexpected result type from query")
            temp = data_path.with_suffix(".part")
            with gzip.open(temp, "wt", encoding="utf-8", newline="\n", compresslevel=5) as output:
                for row in result:
                    output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            temp.replace(data_path)
            state.update(rows=len(result), sha256=hashlib.sha256(data_path.read_bytes()).hexdigest())
    except SourceError as exc:
        dump_json(path, state | {"status": "failed", "error": str(exc)})
        raise
    state.update(status="ok", observed_at=now())
    dump_json(path, state)
    return state


def acquire(client, out: Path, plan: Path, count_only: bool) -> int:
    failed = 0
    for job in json.loads(plan.read_text(encoding="utf-8")):
        table = job["table"]
        condition = job.get("condition", "").strip()
        label = f"{table} {job.get('start', '')} {job.get('end', '')}"
        if not re.fullmatch(r"\w+", table) or re.search(r"\b(?:limit|order\s+by)\b", condition, re.I):
            raise SourceError(f"Unsupported query plan for {label}")
        try:
            count = request_cached(out, "count", job, condition, client.queryCount)["rows"]
            if count_only:
                print(f"CSMAR {label}: {count:,} eligible source rows", flush=True)
                continue
            downloaded = 0
            for offset in range(0, count, 200_000):
                page = condition if count <= 200_000 else f"{condition} limit {offset},200000".strip()
                state = request_cached(out, "query", job, page, client.query)
                if state["rows"] != min(200_000, count - offset):
                    raise SourceError(f"CSMAR page length {state['rows']} differs from count {count}")
                downloaded += state["rows"]
            print(f"CSMAR {label}: reconciled {downloaded:,} rows", flush=True)
        except DailyQuotaError:
            raise
        except SourceError as exc:
            print(f"CSMAR {label}: {exc}", file=sys.stderr, flush=True)
            failed += 1
    return failed


def inventory(client, out: Path, refresh: bool):
    path = out / "databases.json"
    if not refresh and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))["data"]
    data = client.getListDbs()
    if not isinstance(data, list):
        raise SourceError("Unexpected response shape from getListDbs")
    dump_json(path, {"observed_at": now(), "data": data})
    print(f"CSMAR getListDbs returned {len(data)} entries", flush=True)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=RUNTIME / "sdk")
    parser.add_argument("--env", type=Path, default=PROJECT / ".env")
    parser.add_argument("--out", type=Path, default=RUNTIME / "capture")
    parser.add_argument("--database", action="append", default=[])
    parser.add_argument("--table", action="append", default=[])
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--count-only", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        client = service(args.sdk, args.env)
        inventory(client, args.out, args.refresh)
        for name in args.database:
            if re.search(r'[\\/:*?"<>|]', name) or name in {".", ".."}:
                raise SourceError("Unsupported database identifier for inventory filename")
            path = args.out / "tables" / (name + ".json")
            if args.refresh or not path.is_file():
                data = client.getListTables(name)
                if not isinstance(data, list):
                    raise SourceError("Unexpected response shape from getListTables")
                dump_json(path, {"observed_at": now(), "database": name, "data": data})
                print(f"CSMAR database {name}: {len(data)} tables", flush=True)
        for name in args.table:
            if not re.fullmatch(r"\w+", name):
                raise SourceError("Unsupported table identifier for inventory filename")
            path = args.out / "fields" / (name + ".json")
            if args.refresh or not path.is_file():
                data = client.getListFields(name)
                if not isinstance(data, list):
                    raise SourceError("Unexpected response shape from getListFields")
                dump_json(path, {"observed_at": now(), "table": name, "data": data})
                print(f"CSMAR table {name}: {len(data)} fields", flush=True)
        if args.plan:
            return int(acquire(client, args.out, args.plan, args.count_only) != 0)
    except SourceError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
