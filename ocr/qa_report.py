#!/usr/bin/env python
"""Audit the per-page OCR output and write a QA report listing pages to redo.

Checks each page for: degenerate repetition loops, output-cap truncation, unbalanced
math delimiters, suspiciously empty output, and characters that shouldn't appear in an
English maths textbook (a hallucination signal for this model).
"""
import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path

# The model sometimes invents an apology/placeholder instead of reading the scan.
# This is the most dangerous failure mode: it reads as plausible prose.
PLACEHOLDER = re.compile(
    r"sample text|not clearly visible|image'?s quality|image quality|"
    r"not discernible|appears to be a paragraph|as an AI|unable to (?:read|discern)|"
    r"cannot be (?:read|determined)|placeholder text|the content is not",
    re.I,
)
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
CJK = re.compile(r"[　-鿿가-힯]")
SENTENCE_END = re.compile(r"[.!?:;)}\]$]\s*$")


def unique_ratio(lines):
    if len(lines) < 8:
        return 1.0
    return len(set(lines)) / len(lines)


def longest_repeat_run(lines):
    best = run = 1
    for a, b in zip(lines, lines[1:]):
        run = run + 1 if a == b else 1
        best = max(best, run)
    return best if lines else 0


def analyse(path, cap_chars):
    raw = path.read_text(encoding="utf-8")
    text = raw.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    flags = []

    ur = unique_ratio(lines)
    if ur < 0.35:
        flags.append("looped")
    elif longest_repeat_run(lines) >= 4:
        flags.append("repeated-lines")

    if len(text) == 0:
        flags.append("empty")
    elif len(text) < 80:
        flags.append("near-empty")

    # Hitting the generation cap truncates mid-sentence. (A page merely *ending*
    # mid-sentence is normal in running prose, so that is deliberately not a flag.)
    if len(text) >= cap_chars:
        flags.append("maybe-truncated")

    # an escaped \$ is a literal dollar sign (a price), not a maths delimiter
    if re.sub(r"\\\$", "", text).count("$") % 2:
        flags.append("odd-dollar")
    if text.count(r"\begin{") != text.count(r"\end{"):
        flags.append("begin-end-mismatch")
    if text.count("{") != text.count("}"):
        flags.append("brace-mismatch")

    hit = PLACEHOLDER.search(text)
    if hit:
        flags.append("placeholder-text")

    cyr = len(CYRILLIC.findall(text))
    cjk = len(CJK.findall(text))
    if cyr > 3:
        flags.append(f"cyrillic:{cyr}")
    if cjk > 0:
        flags.append(f"cjk:{cjk}")

    return {
        "page": int(path.stem[1:]),
        "chars": len(text),
        "lines": len(lines),
        "uniq": round(ur, 2),
        "flags": flags,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="ocr_out")
    ap.add_argument("--dest", default="ocr_out/QA_REPORT.md")
    ap.add_argument("--total-pages", type=int, default=428)
    ap.add_argument("--cap-chars", type=int, default=5800,
                    help="output length that indicates the num-predict cap was hit")
    a = ap.parse_args()

    pages_dir = Path(a.out_dir, "pages")
    files = sorted(pages_dir.glob("p*.md"))
    if not files:
        raise SystemExit("no pages in " + str(pages_dir))

    rows = [analyse(f, a.cap_chars) for f in files]
    have = {r["page"] for r in rows}
    missing = [n for n in range(1, a.total_pages + 1) if n not in have]

    # timing / error data from the run log
    log = Path(a.out_dir, "ocr_log.jsonl")
    timed, errors = [], []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            (errors if "error" in rec else timed).append(rec)

    counter = Counter(f.split(":")[0] for r in rows for f in r["flags"])
    flagged = [r for r in rows if r["flags"]]
    clean = [r for r in rows if not r["flags"]]
    chars = [r["chars"] for r in rows]

    L = []
    L.append("# OCR QA report")
    L.append("")
    L.append(f"- pages OCR'd: **{len(rows)} / {a.total_pages}**")
    L.append(f"- clean pages: **{len(clean)}**  ({len(clean)*100//max(len(rows),1)}%)")
    L.append(f"- flagged pages: **{len(flagged)}**")
    L.append(f"- missing pages: **{len(missing)}**")
    L.append(f"- request errors logged: **{len({r['page'] for r in errors})}**")
    if chars:
        L.append(f"- chars per page: median {int(statistics.median(chars))}, "
                 f"min {min(chars)}, max {max(chars)}")
    if timed:
        secs = [r["secs"] for r in timed]
        L.append(f"- seconds per page: median {statistics.median(secs):.1f}, "
                 f"mean {statistics.mean(secs):.1f}, max {max(secs):.1f}")
    L.append("")

    L.append("## Flag counts")
    L.append("")
    if counter:
        L.append("| flag | pages | meaning |")
        L.append("|---|---|---|")
        meanings = {
            "looped": "model repeated a few lines - page content is lost, redo",
            "repeated-lines": "4+ identical consecutive lines, usually running headers",
            "empty": "no output at all",
            "near-empty": "under 80 chars - may be a genuinely blank page",
            "maybe-truncated": "hit the generation cap, tail of the page is missing",
            "abrupt-end": "text does not end on sentence/formula punctuation",
            "odd-dollar": "unbalanced $ - inline math broken",
            "begin-end-mismatch": r"\begin{} / \end{} counts differ",
            "brace-mismatch": "unbalanced { } - LaTeX will not compile as-is",
            "cyrillic": "Cyrillic in an English source - hallucination",
            "cjk": "CJK characters in an English source - hallucination",
            "placeholder-text": "model invented an apology/placeholder instead of reading the scan",
        }
        for flag, n in counter.most_common():
            L.append(f"| `{flag}` | {n} | {meanings.get(flag, '')} |")
    else:
        L.append("No flags raised.")
    L.append("")

    L.append("## Pages to redo first")
    L.append("")
    priority = ("placeholder-text", "looped", "empty", "maybe-truncated",
                "cjk", "cyrillic")
    for flag in priority:
        hits = sorted(r["page"] for r in rows
                      if any(f.split(":")[0] == flag for f in r["flags"]))
        if hits:
            L.append(f"- **{flag}** ({len(hits)}): {hits}")
    if missing:
        L.append(f"- **missing** ({len(missing)}): {missing}")
    if errors:
        L.append(f"- **errored** : {sorted({r['page'] for r in errors})}")
    L.append("")

    L.append("## All flagged pages")
    L.append("")
    L.append("| page | chars | lines | uniq | flags |")
    L.append("|---|---|---|---|---|")
    for r in flagged:
        L.append(f"| {r['page']} | {r['chars']} | {r['lines']} | {r['uniq']} | "
                 f"{', '.join(r['flags'])} |")
    L.append("")

    Path(a.dest).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"QA report -> {a.dest}")
    print(f"pages {len(rows)}/{a.total_pages}, clean {len(clean)}, flagged {len(flagged)}, "
          f"missing {len(missing)}")
    for flag, n in counter.most_common():
        print(f"  {flag}: {n}")


if __name__ == "__main__":
    main()
