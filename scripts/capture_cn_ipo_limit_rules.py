"""Archive the exchange rules used to recognize IPO sessions without price limits."""

import argparse
import json
import re
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from locate_sina_issuer_pdfs import retrieve

RULES = {
    "SSE_2023": ("https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10824490/files/dcbe58edb194451d93f19b1f7dd8fb4c.docx",
                 "首次公开发行上市的股票上市后的前5个交易日"),
    "SSE_2026": ("https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/e3a3b98e36894edca77841837936e006.docx",
                 "首次公开发行上市的股票上市后的前5个交易日"),
    "SZSE_GEM_2020": ("https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf",
                      "创业板首次公开发行上市的股票，上市后的前五个交易日不设价格涨跌幅限制"),
    "SZSE_2023": ("https://investor.szse.cn/knowledge/qa/t20230509_600303.html",
                  "股票首次公开发行上市后的前五个交易日不实行价格涨跌幅限制"),
    "SZSE_2026": ("https://docs.static.szse.cn/www/lawrules/rule/stock/trade/W020260424690713155663.pdf",
                  "首次公开发行上市后的前五个交易日"),
}


def capture(out):
    from pypdf import PdfReader

    out.mkdir(parents=True, exist_ok=True)
    receipts = {}
    for name, (url, phrase) in RULES.items():
        receipt, body = retrieve(url)
        if body is None:
            receipts[name] = receipt | {"accepted": False}
            continue
        if body.startswith(b"%PDF-"):
            text = "".join(page.extract_text() for page in PdfReader(BytesIO(body)).pages)
            filename = f"{name}.pdf"
        elif body.startswith(b"PK\x03\x04") and url.endswith(".docx"):
            with ZipFile(BytesIO(body)) as archive:
                text = "".join(ElementTree.fromstring(archive.read("word/document.xml")).itertext())
            filename = f"{name}.docx"
        else:
            text = re.sub(r"<[^>]*>", "", body.decode("utf-8", errors="replace"))
            filename = f"{name}.html"
        (out / filename).write_bytes(body)
        receipts[name] = receipt | {"accepted": phrase in re.sub(r"\s+", "", text),
                                    "file": filename, "phrase": phrase}
    (out / "exchange_ipo_limit_rules.json").write_text(json.dumps(receipts, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
    print({name: row["accepted"] for name, row in receipts.items()}, flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    capture(cli.parse_args().output)
