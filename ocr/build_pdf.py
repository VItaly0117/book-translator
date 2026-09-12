#!/usr/bin/env python
"""Build a review PDF from the merged OCR markdown.

Raw OCR output contains LaTeX that does not always compile, so the book is built in
chunks: a chunk that fails is reported and skipped rather than killing the whole PDF.
Whatever compiled is merged into one file for review.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

PAGE_MARK = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")

PREAMBLE = r"""
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{array}
\allowdisplaybreaks
\setlength{\emergencystretch}{3em}
\providecommand{\tightlist}{}
"""


def sanitize(text):
    """Repair the math-delimiter artifacts the OCR model produces.

    These break xelatex outright, so they are fixed for the PDF build only - the
    canonical markdown in ocr_out/pages is left exactly as the model wrote it.
    """
    text = text.replace(r"\[\[", r"\[").replace(r"\]\]", r"\]")
    text = text.replace(r"\$\$", "$$").replace("$$$$", "$$")
    # An odd number of $ leaves math unterminated and derails the rest of the page.
    if text.count("$") % 2:
        idx = text.rfind("$")
        if idx != -1:
            text = text[:idx] + text[idx + 1:]
    return text


def split_chunks(md_text, pages_per_chunk):
    """Split merged markdown on page markers into chunks of N pages."""
    parts = PAGE_MARK.split(md_text)
    # parts = [pre, num, body, num, body, ...]
    pages = []
    for i in range(1, len(parts) - 1, 2):
        pages.append((int(parts[i]), parts[i + 1]))
    if not pages:
        return [(None, None, md_text)]
    chunks = []
    for i in range(0, len(pages), pages_per_chunk):
        group = pages[i:i + pages_per_chunk]
        body = []
        for num, text in group:
            body.append(f"\n\n\\begin{{center}}\\small\\textit{{-- scan page {num} --}}\\end{{center}}\n\n")
            body.append(sanitize(text.strip()))
        chunks.append((group[0][0], group[-1][0], "\n".join(body)))
    return chunks


def build_chunk(md, dest, preamble_file, engine, timeout, math=True,
                resource_path=None, mainfont=None):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(md)
        src = fh.name
    # Fallback mode: hand the maths to LaTeX as plain text. OCR sometimes emits
    # delimiters or arrays that cannot compile, and a readable page with visible
    # formula source beats no page at all in a review copy.
    fmt = "markdown" if math else "markdown-tex_math_dollars-raw_tex"
    cmd = [
        "pandoc", src, "-f", fmt, "-o", str(dest),
        f"--pdf-engine={engine}",
        "-V", "geometry:margin=2cm",
        "-V", "fontsize=10pt",
    ]
    # Latin Modern has no Cyrillic, so a translated book needs a font that does
    if mainfont:
        cmd += ["-V", f"mainfont={mainfont}"]
    cmd += [
        "-H", str(preamble_file),
    ]
    # the markdown is compiled from a temp file, so pandoc needs to be told where
    # relative image paths are anchored
    if resource_path:
        cmd += ["--resource-path", resource_path]
    # Output goes to a file, never a pipe: a runaway xelatex outlives the pandoc process
    # it was spawned from, and an inherited pipe would keep the timeout blocked forever
    # waiting for EOF that never comes.
    log = Path(str(dest) + ".log")
    try:
        with log.open("wb") as out:
            proc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=timeout)
        err = log.read_text(encoding="utf-8", errors="replace").strip()
        return proc.returncode, err
    except subprocess.TimeoutExpired:
        # kill the whole tree, or the orphaned engine keeps burning CPU
        subprocess.run(["taskkill", "/T", "/F", "/IM", "xelatex.exe"],
                       capture_output=True)
        return 124, f"pandoc timed out after {timeout}s"
    finally:
        Path(src).unlink(missing_ok=True)


def first_error_line(stderr):
    for line in stderr.splitlines():
        if line.startswith("!") or "Error" in line or "error" in line:
            return line.strip()[:200]
    return (stderr.splitlines() or [""])[-1][:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="ocr_out/book_full_en.md")
    ap.add_argument("--dest", default="ocr_out/book_full_en.pdf")
    ap.add_argument("--work-dir", default="ocr_out/pdf_chunks")
    ap.add_argument("--pages-per-chunk", type=int, default=25)
    ap.add_argument("--engine", default="xelatex")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--mainfont", default=None,
                    help="font for the body text; required for Cyrillic")
    a = ap.parse_args()

    md_path = Path(a.md)
    if not md_path.exists():
        sys.exit("merged markdown not found: " + str(md_path))
    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    preamble_file = work / "preamble.tex"
    preamble_file.write_text(PREAMBLE, encoding="utf-8")

    chunks = split_chunks(md_path.read_text(encoding="utf-8"), a.pages_per_chunk)
    print(f"{len(chunks)} chunks of up to {a.pages_per_chunk} scan pages each", flush=True)

    res_path = os.pathsep.join([str(md_path.parent.resolve()), str(Path.cwd())])
    built, failed, degraded = [], [], []
    for lo, hi, body in chunks:
        name = f"chunk_p{lo:04d}-{hi:04d}" if lo else "chunk_all"
        dest = work / (name + ".pdf")
        rc, err = build_chunk(body, dest, preamble_file, a.engine, a.timeout,
                              resource_path=res_path, mainfont=a.mainfont)
        if rc == 0 and dest.exists():
            built.append(dest)
            print(f"  {name}: ok", flush=True)
            continue

        first = first_error_line(err)
        rc2, err2 = build_chunk(body, dest, preamble_file, a.engine, a.timeout,
                                math=False, resource_path=res_path,
                                mainfont=a.mainfont)
        if rc2 == 0 and dest.exists():
            built.append(dest)
            degraded.append((name, first))
            print(f"  {name}: ok (maths as plain text - {first})", flush=True)
        else:
            failed.append((name, first_error_line(err2)))
            print(f"  {name}: FAILED - {first_error_line(err2)}", flush=True)

    if not built:
        print("\nno chunk compiled - leaving the markdown as the only deliverable")
        sys.exit(1)

    out = pymupdf.open()
    for pdf in built:
        with pymupdf.open(pdf) as doc:
            out.insert_pdf(doc)
    out.save(a.dest)
    out.close()

    print(f"\nPDF -> {a.dest}  ({len(built)}/{len(chunks)} chunks, "
          f"{pymupdf.open(a.dest).page_count} pages)")
    if degraded:
        print("chunks built with maths as plain text (formulas need a look):")
        for name, err in degraded:
            print(f"  {name}: {err}")
    if failed:
        print("failed chunks:")
        for name, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
