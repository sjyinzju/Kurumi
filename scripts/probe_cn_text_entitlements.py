"""Check existing CN news/disclosure permissions without printing credentials."""

from __future__ import annotations

import argparse
import csv
import io
import logging
from pathlib import Path
from zipfile import ZipFile

import requests
from csmar_acquire import SourceError, dump_json, now, service
from csmar_package_probe import fetch_zip
from dotenv import dotenv_values

TABLE = "CAIN_CompanyNewsInfo"
FIELDS = ["NewsID", "InstitutionID", "Symbol", "ShortName", "DeclareDate", "Title", "Content"]


def tushare_probe(path, day):
    token = next((v for k, v in dotenv_values(path, encoding="utf-8-sig", interpolate=False).items()
                  if k.casefold() == "tushare_token"), None)
    if not token:
        return {"status": "no_configured_token"}
    time_params = {"start_date": f"{day} 10:00:00", "end_date": f"{day} 10:10:00"}
    cases = [
        ("news", time_params | {"src": "sina"}, "datetime,content,title,channels"),
        ("major_news", time_params | {"src": "新浪财经"}, "title,content,pub_time,src"),
        ("anns_d", {"ts_code": "000001.SZ", "ann_date": day.replace("-", "")},
         "ann_date,ts_code,name,title,url,rec_time"),
    ]
    results = {}
    for api, params, fields in cases:
        try:
            response = requests.post("https://api.tushare.pro", timeout=(8, 20),
                                     json={"api_name": api, "token": token, "params": params, "fields": fields})
            data = response.json()
            returned = data.get("data") or {}
            results[api] = {"http_status": response.status_code, "service_code": data.get("code"),
                            "columns": returned.get("fields"), "rows": len(returned.get("items") or ()),
                            "requested_fields": fields}
        except (requests.RequestException, ValueError) as error:
            results[api] = {"error": type(error).__name__}
    return results


def csmar_probe(args):
    logging.disable(logging.CRITICAL)
    result = {"requested_at": now(), "table": TABLE}
    try:
        client = service(args.sdk, args.csmar_env)
        result["fields"] = client.getListFields(TABLE)
        n = int(client.queryCount(FIELDS, "", TABLE, args.day, args.day))
        result["count"] = n
        if n:
            try:
                rows = client.query(FIELDS, "", TABLE, args.day, args.day)
                result["preview_rows"] = len(rows)
                result["preview_body_rows"] = sum(bool(r.get("Content")) for r in rows)
                dump_json(args.output / "csmar_trial_rows.json", rows)
            except SourceError:
                result["preview_error"] = "CSMAR query rejected"
            if args.check_csmar_zip:
                job = {"name": "CSMAR company news body probe", "table": TABLE, "condition": "",
                       "columns": FIELDS, "start": args.day, "end": args.day}
                package = args.output / "csmar_packages"
                result["package"] = fetch_zip(client, job, n, package, None)
                with ZipFile(package / "package.zip") as zipped:
                    name = next(name for name in zipped.namelist() if name.lower().endswith(".csv"))
                    blob = zipped.read(name)
                    try:
                        text = blob.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        text = blob.decode("gb18030")
                    csv_reader = csv.DictReader(io.StringIO(text))
                    result["package_body_rows"] = sum(bool(r.get("Content")) for r in csv_reader)
                    result["package_columns"] = csv_reader.fieldnames
    except SourceError as error:
        # The SDK adapter strips secrets. Keep only the error class and service-code prefix here.
        result["error"] = str(error).split(")", 1)[0]
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csmar-env", type=Path, required=True)
    p.add_argument("--tushare-env", type=Path, required=True)
    p.add_argument("--sdk", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--day", default="2024-04-19")
    p.add_argument("--check-csmar-zip", action="store_true")
    args = p.parse_args()
    dump_json(args.output / "tushare_probe.json", tushare_probe(args.tushare_env, args.day))
    dump_json(args.output / "csmar_fields.json", csmar_probe(args))


if __name__ == "__main__":
    main()
