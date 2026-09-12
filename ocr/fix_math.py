#!/usr/bin/env python
"""Repair the broken maths markup the OCR produced, verifying every fix by compiling it.

The model mixes up `$` and `$$` delimiters, drops a closing brace, or leaves a literal
dollar sign (a price on the back cover) looking like maths. Each candidate repair is
handed to pandoc/xelatex on its own before it is allowed to touch the page, so a fix
that does not actually compile is never written.
"""
import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PREAMBLE = r"""
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{array}
\allowdisplaybreaks
\providecommand{\tightlist}{}
"""


def balanced(text):
    # an escaped \$ is a literal dollar sign, not a maths delimiter
    unescaped = re.sub(r"\\\$", "", text)
    return (unescaped.count("$") % 2 == 0
            and text.count("{") == text.count("}")
            and text.count(r"\begin{") == text.count(r"\end{"))


def compiles(text, workdir, timeout=90):
    """True if pandoc can turn this page into a PDF with maths enabled."""
    src = workdir / "probe.md"
    src.write_text(text, encoding="utf-8")
    pre = workdir / "pre.tex"
    pre.write_text(PREAMBLE, encoding="utf-8")
    out = workdir / "probe.pdf"
    log = workdir / "probe.log"
    cmd = ["pandoc", str(src), "-f", "markdown", "-o", str(out),
           "--pdf-engine=xelatex", "-V", "geometry:margin=2cm", "-H", str(pre)]
    try:
        with log.open("wb") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/T", "/F", "/IM", "xelatex.exe"],
                       capture_output=True)
        return False
    ok = rc == 0 and out.exists()
    out.unlink(missing_ok=True)
    return ok


def candidates(text):
    """Ordered repair attempts, most targeted first."""
    out = []

    # A price such as "$16.95" on the cover is not maths.
    if re.search(r"\$\d", text):
        out.append(("escape-price", re.sub(r"(?<!\\)\$(?=\d)", r"\\$", text)))

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.count("$") % 2 == 0:
            continue
        # opened with a single $, closed with $$  ->  close with a single $
        if re.search(r"[^$]\$\$\s*$", line) and not line.lstrip().startswith("$$"):
            fixed = re.sub(r"\$\$(\s*)$", r"$\1", line)
            out.append((f"line{i+1}:close-single", _swap(lines, i, fixed)))
        # opened with $$, closed with a single $  ->  close with $$
        if line.lstrip().startswith("$$") and re.search(r"[^$]\$\s*$", line):
            fixed = re.sub(r"(?<!\$)\$(\s*)$", r"$$\1", line)
            out.append((f"line{i+1}:close-double", _swap(lines, i, fixed)))
        # nested $ inside an inline span - drop the inner pair
        if line.count("$") >= 3:
            inner = re.sub(r"\((\$)([^$]*)(\$)([^$]*)\)", r"(\2\4)", line)
            if inner != line:
                out.append((f"line{i+1}:unnest", _swap(lines, i, inner)))
        # last resort: delete the unmatched delimiter on that line
        idx = line.rfind("$")
        if idx != -1:
            out.append((f"line{i+1}:drop-dollar",
                        _swap(lines, i, line[:idx] + line[idx + 1:])))

    # A stray \[ inside a $$ block: the model escaped an ordinary bracket, and LaTeX
    # reads it as a second display-maths opener.
    if r"\[" in text or r"\]" in text:
        out.append(("unescape-bracket",
                    text.replace(r"\[", "[").replace(r"\]", "]")))

    # A display block opened with $$ that never closes on its line.
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("$$") and not st.endswith("$$") and st.count("$$") == 1:
            out.append((f"line{i+1}:close-display",
                        _swap(lines, i, line.rstrip() + "$$")))

    # `cases` allows two columns; a third & makes LaTeX abort. The extra tab sits
    # between a coefficient and the function it multiplies, so dropping it restores
    # the intended product.
    for i, line in enumerate(lines):
        if line.count("&") >= 2:
            first = line.find("&")
            out.append((f"line{i+1}:drop-extra-tab",
                        _swap(lines, i, line[:first] + line[first + 1:])))

    # a missing closing brace / \end{...}
    if text.count("{") > text.count("}"):
        need = text.count("{") - text.count("}")
        out.append(("add-braces", text.rstrip() + "}" * need + "\n"))
    if text.count("}") > text.count("{"):
        out.append(("drop-brace", text.replace("}", "", 1)))
    nb, ne = text.count(r"\begin{"), text.count(r"\end{")
    if nb > ne:
        envs = re.findall(r"\\begin\{([a-zA-Z*]+)\}", text)
        closed = re.findall(r"\\end\{([a-zA-Z*]+)\}", text)
        for e in envs:
            if envs.count(e) > closed.count(e):
                out.append((f"close-{e}", text.rstrip() + f"\n\\end{{{e}}}\n"))
                break
    return out


def _swap(lines, i, new_line):
    copy = list(lines)
    copy[i] = new_line
    return "\n".join(copy) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-dir", default="ocr_out/pages")
    ap.add_argument("--backup-dir", default="ocr_out/pages_premath")
    ap.add_argument("--pages", required=True, help="comma-separated page numbers")
    a = ap.parse_args()

    pages = [int(x) for x in a.pages.replace(" ", "").split(",") if x]
    backup = Path(a.backup_dir)
    backup.mkdir(parents=True, exist_ok=True)

    fixed, already, stuck = [], [], []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for p in pages:
            f = Path(a.pages_dir) / f"p{p:04d}.md"
            text = f.read_text(encoding="utf-8")
            if balanced(text) and compiles(text, work):
                already.append(p)
                print(f"p{p:04d}: already fine", flush=True)
                continue

            winner = None
            for name, cand in candidates(text):
                if not balanced(cand):
                    continue
                if compiles(cand, work):
                    winner = (name, cand)
                    break
            if winner:
                shutil.copy2(f, backup / f.name)
                f.write_text(winner[1], encoding="utf-8")
                fixed.append(p)
                print(f"p{p:04d}: FIXED via {winner[0]}", flush=True)
            else:
                stuck.append(p)
                print(f"p{p:04d}: no verified repair", flush=True)

    print("\n" + "=" * 46)
    print(f"fixed ({len(fixed)}): {fixed}")
    print(f"already fine ({len(already)}): {already}")
    print(f"still broken ({len(stuck)}): {stuck}")


if __name__ == "__main__":
    main()
