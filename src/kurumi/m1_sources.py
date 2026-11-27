"""Convert the six pinned supervision pools. Only explicit input fields enter a native request."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import operator
import re
import unicodedata
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow.parquet as pq


class Exclude(ValueError):
    """A row-level exclusion with an auditable reason."""


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean(value):
    return str(value).strip() if value is not None else ""


def norm(text):
    return "".join(unicodedata.normalize("NFKC", clean(text)).casefold().split())


def fingerprint(text):
    return digest(" ".join(text.split()))


def missing(text):
    return norm(text) in ("", "n/a", "none", "nan", "null")


def record(
    source, oid, task, state, questions, targets, stem, choices=(), context="", group=None, audit=None
):
    if not clean(stem) or any(not clean(q.get("instructions")) for q in questions.values()):
        raise Exclude("empty_question")
    if not questions or set(targets) != set(questions):
        raise Exclude("missing_target")
    fields = [state, *(q["instructions"] for q in questions.values()), *choices]
    if any(
        re.search(
            r"(?:参考答案|正确答案|答案解析|(?:^|\n)\s*解析)\s*[:：=]|the correct answer is\s+[A-E]\b",
            t,
            re.I,
        )
        for t in fields
    ):
        raise Exclude("solution_marker_in_input")
    if source in {"cfa", "cflue", "fineval"} and any(
        re.search(
            r"(?:答案|(?:correct\s+)?answer|solution(?:\s+to\s+\d+)?)\s*[:：=]\s*[(（]?[A-E对错]|\b[A-E] is correct\b",
            t,
            re.I,
        )
        for t in fields
    ):
        raise Exclude("solution_marker_in_input")
    # These transformations never consume an original solution or generated assistant response.
    if (
        re.search(r"如下图|见下图|下图所示|as shown in the following (?:figure|exhibit)", stem, re.I)
        and not context
    ):
        raise Exclude("missing_referenced_exhibit")
    return dict(
        id=source + ":" + str(oid),
        source=source,
        original_id=str(oid),
        task=task,
        state=state,
        questions=questions,
        targets=targets,
        _stem=stem,
        _choices=list(choices),
        _context=context,
        _group=group,
        supervision=audit or {},
    )


def options_ok(choices):
    if not isinstance(choices, dict) or len(choices) < 2:
        raise Exclude("invalid_candidates")
    out = {clean(k): clean(v) for k, v in choices.items()}
    if (
        len(out) != len(choices)
        or any(missing(v) for v in out.values())
        or len({norm(v) for v in out.values()}) != len(out)
    ):
        raise Exclude("empty_or_equivalent_candidates")
    return out


def choice(
    source, oid, stem, choices, key, *, state="", context="", group=None, task="exam_choice", audit=None
):
    choices = options_ok(choices)
    if key not in choices:
        raise Exclude("invalid_choice_target")
    q = {"q": {"type": "choice", "instructions": stem, "criteria": choices}}
    return record(source, oid, task, state, q, {"q": key}, stem, choices.values(), context, group, audit)


def noul(source, oid, stem, truth, *, state="", context="", group=None, audit=None):
    return record(
        source,
        oid,
        "noul",
        state,
        {"q": {"type": "noul", "instructions": stem}},
        {"q": truth},
        stem,
        context=context,
        group=group,
        audit=audit,
    )


def cflue(oid, row):
    stem, key = clean(row["question"]), clean(row["answer"]).upper()
    raw = row["choices"]
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            raise Exclude("unparseable_candidates") from None
    opts = options_ok(raw)
    kind = row["task"]
    if kind == "判断题":
        bools = {"对": "true", "错": "false", "正确": "true", "错误": "false"}
        if key not in opts or set(bools.get(v) for v in opts.values()) != {"false", "true"}:
            raise Exclude("invalid_judgement")
        return noul("cflue", oid, stem, bools[opts[key]])
    if kind == "单项选择题":
        return choice("cflue", oid, stem, opts, key)
    if kind != "多项选择题" or not key or len(set(key)) != len(key) or not set(key) <= set(opts):
        raise Exclude("invalid_multiselect_target")
    state = stem + "\n" + "\n".join(f"{k}. {v}" for k, v in opts.items())
    questions = {
        k: {"type": "noul", "instructions": f"根据题干，选项 {k} 是否应被选为本题答案？"} for k in opts
    }
    return record(
        "cflue",
        oid,
        "exam_multiselect",
        state,
        questions,
        {k: "true" if k in key else "false" for k in opts},
        stem,
        opts.values(),
    )


def fpb(oid, line):
    text, sep, gold = line.rpartition("@")
    opts = {k: k for k in ("negative", "neutral", "positive")}
    if not sep or not clean(text) or clean(gold) not in opts:
        raise Exclude("invalid_sentiment")
    return choice(
        "fpb",
        oid,
        "What sentiment does the sentence express from a financial perspective?",
        opts,
        clean(gold),
        state=text.strip(),
        context=text.strip(),
        task="sentiment",
    )


def fineval(oid, row):
    return choice("fineval", oid, clean(row["question"]), {k: row[k] for k in "ABCD"}, clean(row["answer"]))


def cfa_key(gold, choices):
    text = clean(gold)
    if missing(text):
        raise Exclude("missing_answer")
    code = re.match(
        r"^(?:(?:correct\s+)?answer\s*(?:is|[:=])\s*)?\(?([A-E])(?:\)|[.:]|\s+is\s+correct\b|\s*$)",
        text,
        re.I,
    )
    if code and code[1].upper() in choices:
        key = code[1].upper()
        tail = text[code.end() :].strip()
        if tail and not re.search(r"correct|answer", text, re.I) and norm(tail) != norm(choices[key]):
            raise Exclude("answer_text_choice_mismatch")
        return key
    hits = [k for k, v in choices.items() if norm(v) == norm(text)]
    if len(hits) != 1:
        raise Exclude("ambiguous_answer")
    return hits[0]


def verify_cfa(stem, opts, gold, material):
    # Map a whitespace-insensitive exact stem to a single location in the original material.
    text = unicodedata.normalize("NFKC", material).translate(str.maketrans("’‘“”", "''\"\""))
    needle = re.sub(r"^\s*\d+[.)]\s*", "", unicodedata.normalize("NFKC", stem)).translate(
        str.maketrans("’‘“”", "''\"\"")
    )
    needle = re.sub(r"\s+", "", needle).lower()
    indexes = [i for i, c in enumerate(text) if not c.isspace()]
    compact = "".join(text[i].lower() for i in indexes)
    at = compact.find(needle)
    if len(needle) < 8 or at < 0 or compact.find(needle, at + 1) >= 0:
        raise Exclude("original_stem_not_unique")
    start, end = indexes[at], indexes[at + len(needle) - 1] + 1
    before, after = text[:start], text[end:]
    numbered = re.search(r"(\d{1,2})[.)]?\s*$", before)
    keycodes = []
    if numbered:
        number = numbered[1]
        quiz = list(re.finditer(r"MODULE\s+QUIZ\s+(\d+\.\d+(?:\s*,\s*\d+\.\d+)*)", before))
        key = re.search(r"ANSWER\s+KEY\s+FOR\s+MODULE\s+QUIZ", after)
        if quiz and key:
            subtitle = quiz[-1][1]
            sections = re.split(r"Module\s+Quiz\s+", after[key.end() :])
            for block in sections[1:]:
                m = re.match(re.escape(subtitle).replace(r"\ ", r"\s*") + r"(?=\s*1[.)])", block)
                if m:
                    keycodes.extend(
                        re.findall(r"(?<!\d)" + number + r"[.)]\s*([A-E])(?=\s)", block[m.end() :])
                    )
        # In CFA examples the answers follow this question set, numbered from one.
        sol = list(
            re.finditer(
                r"Solution\s+to\s+(\d+)\s*:\s*(?:Answer\s*=\s*)?([A-E])(?:\s+is\s+correct|\b)", after, re.I
            )
        )
        if sol:
            first_set = []
            for m in sol:
                if first_set and int(m[1]) <= int(first_set[-1][1]):
                    break
                first_set.append(m)
            # A new example between the stem and the answers belongs to another set.
            if not re.search(r"\bEXAMPLE\s+\d+", after[: sol[0].start()], re.I):
                keycodes += [m[2].upper() for m in first_set if m[1] == number]
    # An explicit immediate answer after the options also binds unnumbered examples.
    last = list(opts.items())[-1]
    endopt = norm(last[1])
    tail = norm(after[: max(1500, 3 * sum(map(len, opts.values())))])
    if endopt and endopt in tail:
        remaining = tail.split(endopt, 1)[1]
        direct = re.match(
            r"^[.,;:]?(?:(?:correct)?answer[:=]|solution:)([a-e])(?:iscorrect|[.,;:]|$)", remaining
        )
        if direct:
            keycodes.append(direct[1].upper())
    if set(keycodes) != {gold}:
        raise Exclude("original_answer_unverified")
    return {"material_sha256": digest(material), "stem_offset": start, "original_answer_key": gold}


def cfa(oid, row):
    if missing(row["answer"]):
        raise Exclude("missing_answer")
    stem = clean(row["questions"])
    text = clean(row["answer_choices"])
    matches = list(re.finditer(r"(?<![A-Za-z0-9])\(?([A-E])[.)]\s*", text))
    if not matches or [m[1] for m in matches] != list("ABCDE"[: len(matches)]):
        raise Exclude("unparseable_candidates")
    opts = options_ok(
        {
            m[1]: text[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
            for i, m in enumerate(matches)
        }
    )
    gold = cfa_key(row["answer"], opts)
    audit = verify_cfa(stem, opts, gold, row["material"])
    context = "\n".join(clean(row[k]) for k in ("scenario", "exhibit") if not missing(row[k]))
    group = "case:" + digest(norm(context)) if len(norm(context)) >= 40 else None
    return choice("cfa", oid, stem, opts, gold, state=context, context=context, group=group, audit=audit)


def plain_number(text):
    text = str(text).strip().lower().replace(",", "").removeprefix("const_")
    text = "-1" if text == "m1" else text
    is_percent = text.endswith("%")
    x = float(text.removesuffix("%"))
    if not math.isfinite(x):
        raise ValueError("nonfinite")
    return x / 100 if is_percent else x


def execute_program(program, table):
    numbers = []
    if "(" not in program:
        return plain_number(program), numbers
    # Arguments are official table row names, decimal constants, or previous instruction results.
    steps = re.split(r"\),\s*(?=[a-z_]+\()", program.strip().removesuffix(")"))
    results = []
    arithmetic = {
        "add": operator.add,
        "subtract": operator.sub,
        "multiply": operator.mul,
        "divide": operator.truediv,
        "exp": operator.pow,
    }

    def value(t):
        if re.fullmatch(r"#\d+", t):
            return results[int(t[1:])]
        return plain_number(t)

    for step in steps:
        name, rest = step.split("(", 1)
        left, right = (x.strip() for x in rest.rsplit(",", 1))
        if name.startswith("table_"):
            rows = [row[1:] for row in table if row[0] == left]
            if not rows or any(row != rows[0] for row in rows):
                raise ValueError("ambiguous table operand")
            vals = [plain_number(x.replace("$", "").split("(")[0]) for x in rows[0]]
            fn = {
                "table_sum": sum,
                "table_max": max,
                "table_min": min,
                "table_average": lambda a: sum(a) / len(a),
            }[name]
            result = fn(vals)
            numbers.extend(vals)
        else:
            a, b = value(left), value(right)
            numbers.extend([a, b])
            if name == "greater":
                result = "yes" if a > b else "no"
            else:
                result = arithmetic[name](a, b)
                if not isinstance(result, (int, float)) or not math.isfinite(result):
                    raise ValueError("invalid result")
                if name == "divide" and a + b:
                    numbers.append(a / (a + b))
        results.append(result)
    return results[-1], numbers


def table_text(x):
    return "\n".join("|" + "|".join(row) + "|" for row in x["table"])


def report_text(x):
    return "\n".join([" ".join(x["pre_text"]), table_text(x), " ".join(x["post_text"])]).strip()


def official_input(source, x):
    if source == "finqa":
        return report_text(x) + "\nQuestion: " + x["qa"]["question"]
    tab = (
        "<table class='wikitable'>"
        + "".join(
            "<tr>" + "".join("<td>" + str(c or "-") + "</td>" for c in [j, *row]) + "</tr>"
            for j, row in enumerate(x["table"], 1)
        )
        + "</table>"
    )
    a = x["annotation"]
    lines = [" ".join([*x["pre_text"], tab, *x["post_text"]])]
    for i, q in enumerate(a["cur_dial"]):
        lines.append("Question: " + q)
        if i + 1 < len(a["cur_dial"]):
            lines.append("Answer: " + str(a["exe_ans_list"][i]))
    return "\n".join(lines)


def numeric_options(oid, gold, operands):
    x = Decimal(str(gold))
    if not x.is_finite():
        raise Exclude("nonfinite_numeric_answer")
    places = min(10, max(0, -x.normalize().as_tuple().exponent))
    quantum = Decimal(1).scaleb(-places)
    if x.quantize(quantum) != x:
        raise Exclude("unrepresentable_numeric_precision")

    def rounded(v):
        d = Decimal(str(v)).quantize(quantum)
        return format(abs(d) if d == 0 else d, f".{places}f")

    correct = rounded(x)
    last = [Decimal(str(v)) for v in operands[-3:] if isinstance(v, (int, float)) and math.isfinite(v)]
    pool = [
        *last,
        -x,
        x * 100,
        x / 100,
        x * 2,
        x / 2,
        x + quantum,
        x - quantum,
        x + 2 * quantum,
        x - 2 * quantum,
    ]
    alternatives = set()
    for v in pool:
        try:
            a = rounded(v)
        except InvalidOperation:
            continue
        if a != correct:
            alternatives.add(a)
    if len(alternatives) < 3:
        raise Exclude("insufficient_distinct_numeric_options")
    selected = sorted(alternatives, key=lambda v: digest("17|distractor|" + oid + "|" + v))[:3] + [correct]
    ordered = sorted(selected, key=lambda v: digest("17|candidate|" + oid + "|" + v))
    opts = dict(zip("ABCD", ordered, strict=True))
    return opts, next(k for k, v in opts.items() if v == correct)


def numerics(source, official):
    lookup = defaultdict(list)
    for x in official:
        lookup[fingerprint(official_input(source, x))].append(x)

    def convert(oid, row):
        if source == "finqa":
            prefix = "Please answer the given financial question based on the context.\nContext: "
            if not row["query"].startswith(prefix) or not row["query"].endswith("\nAnswer:"):
                raise Exclude("unrecognized_query_template")
            question_input = row["query"][len(prefix) : -len("\nAnswer:")]
            label = row["answer"]
        else:
            question_input = row["input"]
            label = row["output"]
        hits = lookup.get(fingerprint(question_input), [])
        if not hits:
            raise Exclude("unmatched_official_input")

        def official_gold(x):
            return (x["qa"] if source == "finqa" else x["annotation"])["exe_ans"]

        def gold_key(y):
            y = clean(y).lower()
            if y in ("yes", "no"):
                return y
            try:
                return Decimal(y).normalize()
            except InvalidOperation:
                return y

        hits = [x for x in hits if gold_key(official_gold(x)) == gold_key(label)]
        if not hits:
            raise Exclude("mirror_official_answer_mismatch")
        if len({(x["filename"], str(official_gold(x))) for x in hits}) != 1:
            raise Exclude("ambiguous_official_report")
        x = hits[0]
        evidence = report_text(x)
        if not x["table"] or not evidence:
            raise Exclude("empty_report")
        if source == "finqa":
            program = x["qa"]["program"]
            stem = x["qa"]["question"]
        else:
            a = x["annotation"]
            program = a["cur_program"]
            stem = a["cur_dial"][-1]
            if len(a["cur_dial"]) > 1:
                evidence += "\n" + "\n".join(
                    f"Question: {q}\nAnswer: {a['exe_ans_list'][i]}" for i, q in enumerate(a["cur_dial"][:-1])
                )
        group = "report:" + str(Path(x["filename"]).parent).casefold()
        meta = {
            "official_ids": [e["id"] for e in hits],
            "input_fingerprint": fingerprint(question_input),
            "program": program,
            "source_result": official_gold(x),
        }
        try:
            computed, operands = execute_program(str(program), x["table"])
            if isinstance(computed, str):
                if computed != clean(label).lower():
                    raise Exclude("program_answer_mismatch")
                return noul(
                    source,
                    oid,
                    stem,
                    "true" if computed == "yes" else "false",
                    state=evidence,
                    context=evidence,
                    group=group,
                    audit=meta,
                )
            if not math.isclose(round(computed, 5), float(label), rel_tol=1e-9, abs_tol=5.1e-6):
                raise Exclude("program_answer_mismatch")
            opts, key = numeric_options(source + ":" + oid, label, operands)
        except Exclude:
            raise
        except (ValueError, TypeError, ArithmeticError, KeyError, IndexError):
            raise Exclude("unverifiable_numeric_program") from None
        return choice(
            source,
            oid,
            stem,
            opts,
            key,
            state=evidence,
            context=evidence,
            group=group,
            task="numeric_choice",
            audit=meta,
        )

    return convert


def source_rows(source, spec, raw, support):
    path = raw / source / Path(spec["file"]).name
    if source == "cflue":
        return enumerate(json.loads(path.read_text(encoding="utf-8"))), cflue
    if source == "fpb":
        with zipfile.ZipFile(path) as z:
            lines = z.read(spec["member"]).decode("iso-8859-1").splitlines()
        return enumerate(lines, 1), fpb
    if source == "fineval":
        rows = []
        with zipfile.ZipFile(path) as z:
            for member in sorted(z.namelist()):
                p = Path(member)
                if len(p.parts) != 2 or p.parts[0] not in spec["splits"] or p.suffix != ".csv":
                    continue
                split = p.parts[0]
                subject = p.stem.removesuffix("_" + split)
                content = z.read(member).decode("utf-8-sig")
                rows.extend((f"{subject}:{split}:{r['id']}", r) for r in csv.DictReader(io.StringIO(content)))
        return rows, fineval
    cols = {
        "cfa": ["questions", "answer_choices", "answer", "material", "scenario", "exhibit"],
        "finqa": ["id", "query", "answer"],
        "convfinqa": ["input", "output"],
    }[source]
    rows = pq.read_table(path, columns=cols).to_pylist()
    if source == "cfa":
        return enumerate(rows), cfa
    support_file = raw / "supervision" / source / Path(support[source]["file"]).name
    if source == "finqa":
        docs = json.loads(support_file.read_text(encoding="utf-8"))
        ids = ((r["id"], r) for r in rows)
    else:
        with zipfile.ZipFile(support_file) as z:
            (member,) = [
                n
                for n in z.namelist()
                if Path(n).name == support[source]["member_basename"] and not n.startswith("__MACOSX")
            ]
            docs = json.loads(z.read(member))
        ids = enumerate(rows)
    return ids, numerics(source, docs)
