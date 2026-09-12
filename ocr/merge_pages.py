#!/usr/bin/env python
"""Merge per-page OCR output into one markdown file with page markers.

Collapses runs of identical consecutive lines, which the OCR model emits both as
duplicated running headers/footers and as full degenerate loops on decorative pages.
"""
import argparse
from pathlib import Path

NL = chr(10)


def collapse_repeats(text):
    """Drop a line that merely repeats the one before it.

    Maths is left alone: the rows of a matrix ellipsis are legitimately identical,
    and collapsing them silently destroys the array structure so the page will not
    compile.
    """
    out, prev, in_math = [], None, False
    for line in text.splitlines():
        key = line.strip()
        if key.startswith("$$"):
            # a line that opens or closes a display block toggles the state, unless
            # it does both (a complete one-line formula)
            if key.count("$$") % 2:
                in_math = not in_math
            out.append(line)
            prev = None
            continue
        protected = in_math or "&" in line or line.rstrip().endswith("\\\\")
        if key and key == prev and not protected:
            continue
        out.append(line)
        prev = key
    return NL.join(out).strip()


def unique_ratio(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 8:
        return 1.0
    return len(set(lines)) / len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="ocr_out")
    ap.add_argument("--dest", default="ocr_out/book_full_en.md")
    ap.add_argument("--no-collapse", action="store_true")
    a = ap.parse_args()

    pages = sorted(Path(a.out_dir, "pages").glob("p*.md"))
    if not pages:
        raise SystemExit("no pages found in " + str(Path(a.out_dir, "pages")))
    nums = [int(p.stem[1:]) for p in pages]
    missing = [n for n in range(min(nums), max(nums) + 1) if n not in nums]

    chunks, looped = [], []
    for p in pages:
        n = int(p.stem[1:])
        raw = p.read_text(encoding="utf-8")
        if unique_ratio(raw) < 0.35:
            looped.append(n)
        body = raw.strip() if a.no_collapse else collapse_repeats(raw)
        chunks.append(NL * 2 + "<!-- PAGE " + str(n) + " -->" + NL * 2 + body)

    Path(a.dest).write_text("".join(chunks).strip() + NL, encoding="utf-8")
    print("merged " + str(len(pages)) + " pages -> " + a.dest)
    print("missing pages:", missing or "none")
    print("looped/degenerate pages (worth a manual look):", looped or "none")


if __name__ == "__main__":
    main()
