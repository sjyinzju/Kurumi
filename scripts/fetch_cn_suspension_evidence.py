"""Archive the specific public documents used by the audited CN suspension intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from kurumi.cn_disclosures import _request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-config", type=Path, default=Path("configs/cn_suspension_evidence.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/cn-suspension-evidence"))
    parser.add_argument("--record-new-hashes", action="store_true")
    args = parser.parse_args()
    events = json.loads(args.evidence_config.read_text(encoding="utf-8"))
    args.output.mkdir(exist_ok=True, parents=True)
    for event in events:
        for edge in ("start", "end", "delisting"):
            url = event.get(f"{edge}_source_url")
            if not url:
                continue
            name = event.get(f"{edge}_source_id", event["ts_code"] + "-delisting")
            if Path(name).name != name:
                raise ValueError("Evidence source ID must be a filename component")
            source = urlsplit(url)
            headers = None
            if source.netloc == "query.sse.com.cn" and source.path == "/commonSoaQuery.do":
                extension = ".jsonp"
                headers = {"Referer": "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"}
            else:
                extension = ".pdf" if source.path.lower().endswith(".pdf") else ".html"
            if source.netloc == "www.bse.cn":
                headers = {"Referer": "https://www.bse.cn/"}
            local_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
            path = args.output / (local_name + extension)
            expected = event.get(f"{edge}_source_sha256")
            if expected is None and not args.record_new_hashes:
                raise ValueError(f"Missing expected SHA-256 for {name}")
            data = path.read_bytes() if path.is_file() else _request("GET", url, headers=headers).content
            if extension == ".pdf" and not data.startswith(b"%PDF-"):
                raise ValueError(f"Non-PDF response for {name}")
            if extension == ".jsonp" and not data.lstrip().startswith(b"jsoncallback("):
                raise ValueError(f"Non-JSONP response for {name}")
            checksum = hashlib.sha256(data).hexdigest()
            if expected and expected != checksum:
                raise ValueError(f"Unverified change to original evidence {name}")
            if not path.is_file():
                partial = path.with_suffix(".partial")
                partial.write_bytes(data)
                partial.replace(path)
            if expected is None:
                event[f"{edge}_source_sha256"] = checksum
            print(f"{name} {checksum}", flush=True)
    if args.record_new_hashes:
        partial = args.evidence_config.with_suffix(".partial")
        partial.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        partial.replace(args.evidence_config)


if __name__ == "__main__":
    main()
