"""Clone reviewed source repositories and save original paper PDFs, without executing them."""
import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference"
DOCS = ROOT / "docs/references"
PAPERS = ROOT / "docs/papers"
ENV = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=240, env=ENV, check=True, **kwargs).stdout.strip()


def clone_repo(item):
    repo = item["repo"]
    destination = REFERENCE / repo.split("/")[1]
    result = {"repo": repo, "path": destination.relative_to(ROOT).as_posix(), "source_url": f"https://github.com/{repo}.git",
              "previously_reviewed_sha": item["sha"]}
    try:
        if destination.exists():
            result["action"] = "preserved_existing_checkout"
        else:
            run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", result["source_url"], str(destination)])
            # The Git clone retains repository identity. Omitted blobs are available on demand.
            run(["git", "-C", str(destination), "sparse-checkout", "init", "--no-cone"])
            patterns = "/*\n!/DATA/\n!/EXPORTS/\n!/datasets/\n!/data/raw/\n!/data/processed/\n!*.safetensors\n!*.bin\n!*.pt\n!*.pth\n!*.ckpt\n!*.pkl\n!*.pickle\n!*.parquet\n!*.csv\n!*.zip\n!*.tar.gz\n"
            if repo == "yumoxu/stocknet-dataset":
                patterns = "/README*\n/LICENSE*\n"
            run(["git", "-C", str(destination), "sparse-checkout", "set", "--no-cone", "--stdin"], input=patterns)
            run(["git", "-C", str(destination), "checkout"])
            result["action"] = "shallow_partial_clone_sparse_checkout"
            result["sparse_patterns"] = patterns.splitlines()
        result["origin"] = run(["git", "-C", str(destination), "remote", "get-url", "origin"])
        result["sha"] = run(["git", "-C", str(destination), "rev-parse", "HEAD"])
        result["matches_reviewed_sha"] = result["sha"] == item["sha"]
        result["shallow"] = run(["git", "-C", str(destination), "rev-parse", "--is-shallow-repository"])
        result["status"] = "ok"
    except (OSError, subprocess.SubprocessError) as exc:
        result["status"] = "failed"
        result["error"] = str(exc) + " " + (getattr(exc, "stderr", "") or "")[-1500:]
    print(f"REPO {repo}: {result['status']}", flush=True)
    return result


def save_paper(item):
    paper = item["paper"]
    result = {"id": item["id"], "title": item["name"], "landing_url": paper}
    if "arxiv.org/abs/" in paper:
        paper_id = paper.rsplit("/", 1)[1]
        version = item.get("paper_version_read", "")
        result["download_url"] = "https://arxiv.org/pdf/" + paper_id + version
        filename = f"{item['id']}_{paper_id}{version}.pdf"
    else:
        result["download_url"] = "https://aclanthology.org/P18-1183.pdf"
        filename = f"{item['id']}_P18-1183.pdf"
    destination = PAPERS / filename
    result["path"] = destination.relative_to(ROOT).as_posix()
    try:
        if not destination.exists():
            partial = destination.with_suffix(".pdf.partial")
            run(["curl.exe", "--fail", "--location", "--silent", "--show-error", "--retry", "2", "--connect-timeout", "20", "--max-time", "120", "--output", str(partial), result["download_url"]])
            with partial.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("Response is not a PDF")
            partial.replace(destination)
        info = run(["pdfinfo", str(destination)])
        match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
        if not match:
            raise ValueError("PDF parser returned no page count")
        result["pages"] = int(match.group(1))
        result["bytes"] = destination.stat().st_size
        with destination.open("rb") as stream:
            result["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        text = run(["pdftotext", "-f", "1", "-l", "1", "-enc", "UTF-8", str(destination), "-"])
        expected = set(re.findall(r"[a-z]{3,}", item["name"].lower()))
        actual = set(re.findall(r"[a-z]{3,}", text.lower()))
        result["title_word_coverage_on_first_page"] = round(len(expected & actual) / len(expected), 3)
        result["first_page_text_preview"] = text[:900]
        if result["title_word_coverage_on_first_page"] < 0.5:
            raise ValueError("First page title needs manual verification")
        result["status"] = "ok"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result["status"] = "failed"
        result["error"] = str(exc) + " " + (getattr(exc, "stderr", "") or "")[-1500:]
    print(f"PAPER {item['id']}: {result['status']}", flush=True)
    return result


def write_indexes(result):
    """Keep the tracked index outside the ignored reference directory."""
    lines = ["# 本地参考资料", "", "仓库保存在 `reference/`，由根目录 `.gitignore` 忽略。研究清单和论文保存在 `docs/`。", "",
             "已有 Karpo 目录保留；新增仓库使用 depth=1、blob:none 的浅层部分克隆及稀疏检出，禁用 LFS。跳过权重、CSV/Parquet等数据文件及部分数据目录；StockNet数据仓库仅检出说明。按需读取被省略的Git对象可能再次联网。未运行第三方代码或下载HF权重/大数据集。", "",
             "## 仓库", "", "| 仓库 | 本地路径 | HEAD | 保存结果 |", "|---|---|---|---|"]
    for item in result["repositories"]:
        lines.append(f"| {item['repo']} | `{item['path']}` | `{item.get('sha', '未取得')}` | {item['status']} |")
    lines += ["", "已有基座代码：`reference/karpo-decision/`，未拉取、覆盖或重置。", "",
              "## 论文", "", "15篇PDF及逐篇页数见 [论文目录](../papers/README.md)。FinGPT-Forecaster没有在原清单中列出单独论文，保留其源码和模型链接；其余15个条目各保存一篇。", "",
              "- [研究筛选与适配建议](../research_references.md)",
              "- [机器可读研究清单](research_catalog.json)", "- [检索时GitHub版本](research_revisions.json)",
              "- [实际下载与克隆记录](download_manifest.json)：下载URL、实际提交、PDF字节数、页数、SHA-256和首页文本核验。", "",
              "## 复现", "", "从项目根目录运行：", "", "```powershell",
              "& E:\\quant\\.venv\\Scripts\\python.exe scripts/fetch_references.py", "```", "",
              "需允许访问GitHub、arXiv和ACL，并有git、curl.exe、pdfinfo和pdftotext。已有目录与PDF默认保留，只读核验；源网站更新不会覆盖已有本地文件。未指定版本的arXiv链接首次下载时取网站当前版本，以文件哈希固定实际内容。", ""]
    (DOCS / "README.md").write_text("\n".join(lines), encoding="utf-8")
    lines = ["# 论文 PDF 目录", "", "全部为作者/出版机构原始PDF。逐篇通过pdfinfo解析及首页标题词覆盖检查；未编辑PDF或复现论文实验。完整SHA-256见 [下载记录](../references/download_manifest.json)。", "",
             "| 编号 | 论文 | 页数 | 文件大小 |", "|---|---|---:|---:|"]
    for item in result["papers"]:
        label = f"[{item['title']}]({Path(item['path']).name})" if item["status"] == "ok" else item["title"]
        lines.append(f"| {item['id']} | {label} | {item.get('pages', '失败')} | {item.get('bytes', 0):,} 字节 |")
    (PAPERS / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    PAPERS.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((DOCS / "research_catalog.json").read_text(encoding="utf-8"))
    revisions = json.loads((DOCS / "research_revisions.json").read_text(encoding="utf-8"))
    result = {"started_utc": datetime.now(timezone.utc).isoformat(), "repositories": [], "papers": [],
              "policy": "Shallow partial Git clones with sparse code checkout; LFS disabled. No external code executed. No HF weights or bulk datasets fetched."}
    with ThreadPoolExecutor(max_workers=3) as pool:
        work = {pool.submit(clone_repo, item): "repositories" for item in revisions["repositories"]}
        work.update({pool.submit(save_paper, item): "papers" for item in catalog["resources"] if "paper" in item})
        for future in as_completed(work):
            result[work[future]].append(future.result())
            (DOCS / "download_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["repositories"].sort(key=lambda x: x["repo"])
    result["papers"].sort(key=lambda x: x["id"])
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (DOCS / "download_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_indexes(result)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
