"""Verify the same A-share listing across the 000022.SZ to 001872.SZ code change."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from audit_cn_001914_names import (
    EXTRACT,
    checksum,
    clean,
    find_all,
    szse_catalogue,
    verified_archive,
    verify_on_released_days,
    write_versions,
)

from kurumi.cn_equity_candidates import SZSE_ANNOUNCEMENTS
from kurumi.cn_hkex_monthly import Archive
from kurumi.cn_mainland_share_monthly import read_exchange
from kurumi.cn_pit import _with_provenance

OLD = "000022.SZ"
NEW = "001872.SZ"
SWITCH = "2018-12-26"
SOURCES = {
    "old_2013": ("2013.63192826.pdf", "SZSE 63192826 issuer 2013-057"),
    "old_2014": ("2014.1200329964.pdf", "SZSE 1200329964 issuer 2014-045"),
    "advance": ("2018.1205685040.pdf", "SZSE 1205685040"),
    "implementation": ("2018.1205690369.pdf", "SZSE 1205690369 issuer 2018-124"),
    "index_confirmation": ("2018-index-confirmation.pdf", "SZSE and Shenzhen Securities Information annex"),
    "cninfo_advance": ("2018-12-24-prior.pdf", "CNINFO 1205685040"),
    "cninfo_implementation": ("2018-12-26-implementation.pdf", "CNINFO 1205690369 issuer 2018-124"),
}
STATIC = {
    "2018-12-24-prior.pdf": "https://static.cninfo.com.cn/finalpage/2018-12-24/1205685040.PDF",
    "2018-12-26-implementation.pdf": "https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF",
    "2018-index-confirmation.pdf": "https://www.cnindex.com.cn/zh_information/notices_news/2018/201812/P020191213349118816996.pdf",
}
CATALOGUE = {
    2013: ("2013-10-24", "2013-10-28", (63192826,)),
    2014: ("2014-10-24", "2014-10-27", (1200329964,)),
    2018: ("2018-12-21", "2018-12-26", (1205685040, 1205690369)),
}


def fetch_sources(root):
    archive = Archive(root, 20, 1.15, allow_network=True, referer="https://www.szse.cn/disclosure/listed/notice/index.html")
    for leaf, url in STATIC.items():
        read_exchange(archive, leaf, url)
    for year, (first, last, ids) in CATALOGUE.items():
        for tag, code in (("", OLD), ("-current", NEW)):
            query = dict(seDate=[first, last], channelCode=["listedNotice_disc"], pageSize=30, pageNum=1, stock=[code[:6]])
            body, _ = read_exchange(archive, f"{year}{tag}.catalogue.json", SZSE_ANNOUNCEMENTS, payload=query)
            if code != OLD:
                continue
            records = [r for r in json.loads(body)["data"] if r["annId"] in ids and r["secCode"] == [OLD[:6]]]
            if len(records) != len(ids):
                raise ValueError(f"Missing official listing/name record for {year}")
            for row in records:
                url = "https://disc.static.szse.cn" + row["attachPath"]
                read_exchange(archive, f"{year}.{row['annId']}.pdf", url)


def build_sources(root, binary):
    sources = {key: verified_archive(root, *reference) for key, reference in SOURCES.items()}
    docs = [str(root / leaf) for leaf, _ in SOURCES.values()]
    extracted = subprocess.run([str(binary), "-c", EXTRACT, *docs], capture_output=True, check=True)
    text = {key: clean(content) for key, content in zip(SOURCES, json.loads(extracted.stdout), strict=True)}
    old_checks = (r"证券代码:000022/200022", r"证券简称:深赤湾A/深赤湾B")
    advance_checks = (r"公司将于2018年12月26日变更证券简称", r"新增股份上市日期2018年12月26日",
                      r"公司原证券简称“深赤湾A/深赤湾B”变更为“招商港口/招港B”",
                      r"将原证券代码“000022/200022”变更为“001872/201872”")
    implementation_checks = (r"2018年12月26日开市起以变更后的证券简称及证券代码复牌并交易",
                             r"变更后的证券代码:001872/201872", r"公司法人主体存续",
                             r"2018年12月21日、12月24日、12月25日", r"持有本公司股份数量不变")
    index_checks = (r"深赤湾A\(000022\)、深赤湾B\(200022\)", r"招商港口\(001872\)、招港B\(201872\)",
                    r"2018年12月26日对中小创新等指数", r"2018年12月21日")
    groups = {"old_2013": old_checks, "old_2014": old_checks,
              "advance": advance_checks, "cninfo_advance": advance_checks,
              "implementation": implementation_checks, "cninfo_implementation": implementation_checks,
              "index_confirmation": index_checks}
    for key, checks in groups.items():
        sources[key]["source_literals"] = find_all(text[key], checks, key)
    catalogs = (("old_2013", 2013, 63192826), ("old_2014", 2014, 1200329964),
                ("advance", 2018, 1205685040), ("implementation", 2018, 1205690369))
    for key, year, record in catalogs:
        proof = szse_catalogue(root, year, record, SOURCES[key][0], old_code=OLD)
        sources[key]["published_at"] = proof["publishTime"][:10]
        sources[key]["exchange_catalogue"] = {field: proof[field] for field in ("annId", "secCode", "publishTime", "source_url", "source_sha256")}
    if sources["old_2013"]["published_at"] != "2013-10-25" or sources["advance"]["published_at"] != "2018-12-24":
        raise ValueError("Unexpected official available dates for the two name versions")
    base = {"ts_code": NEW, "instrument_id": "CN-001872.SZ"}
    rows = [
        sources["old_2013"] | base | dict(symbol_asof=OLD[:6], name_asof="深赤湾A", effective_from="2014-01-01", effective_to=SWITCH,
                                          corroboration_url=sources["old_2014"]["source_url"],
                                          corroboration_sha256=sources["old_2014"]["source_sha256"]),
        sources["advance"] | base | dict(symbol_asof=NEW[:6], name_asof="招商港口", effective_from=SWITCH, effective_to=None,
                                         corroboration_url=sources["implementation"]["source_url"],
                                         corroboration_sha256=sources["implementation"]["source_sha256"]),
    ]
    alias = sources["advance"] | dict(ts_code=NEW, prior_code=OLD, effective_from=SWITCH,
                                      corroboration_url=sources["implementation"]["source_url"],
                                      corroboration_sha256=sources["implementation"]["source_sha256"])
    return rows, alias, sources


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ("originals", "output", "pdf-python"):
        cli.add_argument("--" + field, type=Path, required=True)
    cli.add_argument("--dataset", type=Path, nargs="+", required=True)
    cli.add_argument("--fetch-originals", action="store_true")
    args = cli.parse_args()
    if args.fetch_originals:
        fetch_sources(args.originals)
    versions, alias, sources = build_sources(args.originals, args.pdf_python)
    args.output.mkdir(parents=True, exist_ok=True)
    names = write_versions(args.output, versions)
    mapping = args.output / "security_code_changes.json"
    mapping.write_text(json.dumps([alias], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(_with_provenance(args.output, "security_name_versions", {})) != 2:
        raise ValueError("Expected two proven names for the A security")
    cutoffs = ((1, "2018-12-24"),)
    receipt = dict(
        status="pass", sources=sources, a_security_mapping=alias,
        independently_renamed_b_share={"old_code": "200022.SZ", "new_code": "201872.SZ", "effective_from": SWITCH,
                                      "included_in_a_mapping": False},
        last_old_code_actual_trade="2018-12-20", officially_suspended_old_code=["2018-12-21", "2018-12-24", "2018-12-25"],
        functional_replays=[verify_on_released_days(path, args.output, versions, cutoffs) for path in args.dataset],
        sha256={names.name: checksum(names), mapping.name: checksum(mapping)},
    )
    (args.output / "001872_history_audit.json").write_text(json.dumps(receipt, ensure_ascii=False, default=str, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"functional_replays": receipt["functional_replays"], "sha256": receipt["sha256"]}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
