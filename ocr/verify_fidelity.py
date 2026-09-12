#!/usr/bin/env python
"""Cross-check OCR output volume against how much ink is actually on each scan page.

Fabricated text gives itself away: the model writes a lot where the scan holds little.
This needs no model - it compares the character count of each page's OCR against the
page's measured ink coverage and reports the outliers.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from extract_figures import page_ink


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages-dir", default="ocr_out/pages")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--report", default="ocr_out/FIDELITY_REPORT.md")
    a = ap.parse_args()

    doc = pymupdf.open(a.pdf)
    rows = []
    for p in range(1, doc.page_count + 1):
        f = Path(a.pages_dir) / f"p{p:04d}.md"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8").strip()
        ink, _, _ = page_ink(doc, p - 1, a.dpi)
        ratio = float(ink.mean())
        rows.append({"page": p, "chars": len(text), "ink": ratio,
                     "blank_marker": text == "*(blank page)*"})

    real = [r for r in rows if not r["blank_marker"] and r["ink"] > 0.0015]
    # characters produced per unit of ink; fabrication sits far above the norm
    for r in real:
        r["cpi"] = r["chars"] / (r["ink"] * 10000)
    cpis = [r["cpi"] for r in real]
    med = statistics.median(cpis)
    # robust spread: median absolute deviation
    mad = statistics.median([abs(c - med) for c in cpis]) or 1e-9
    for r in real:
        r["z"] = (r["cpi"] - med) / (1.4826 * mad)

    suspicious = sorted([r for r in real if r["z"] > 6], key=lambda r: -r["z"])
    thin = sorted([r for r in real if r["z"] < -6], key=lambda r: r["z"])
    blanks = [r for r in rows if r["blank_marker"]]
    empty_scan_with_text = [r for r in rows
                            if r["ink"] <= 0.0015 and not r["blank_marker"]
                            and r["chars"] > 40]

    L = ["# OCR fidelity cross-check", "",
         "Compares how much text each page produced against how much ink the scan",
         "actually carries. Fabricated text shows up as a lot of output over very",
         "little ink.", "",
         f"- pages compared: **{len(rows)}**",
         f"- blank pages marked as blank: **{len(blanks)}**",
         f"- blank scans still holding text: **{len(empty_scan_with_text)}**",
         f"- median chars per ink unit: {med:.1f}", ""]

    L.append("## Pages producing far more text than the scan holds")
    L.append("")
    if suspicious:
        L.append("| page | chars | ink % | ratio | z |")
        L.append("|---|---|---|---|---|")
        for r in suspicious[:25]:
            L.append(f"| {r['page']} | {r['chars']} | {r['ink']*100:.2f} | "
                     f"{r['cpi']:.1f} | {r['z']:.1f} |")
    else:
        L.append("None - no page stands out as invented.")
    L.append("")

    L.append("## Pages producing far less text than the scan holds")
    L.append("")
    L.append("(usually figure-heavy pages, where most ink is a drawing - not an error)")
    L.append("")
    if thin:
        L.append("| page | chars | ink % | ratio | z |")
        L.append("|---|---|---|---|---|")
        for r in thin[:25]:
            L.append(f"| {r['page']} | {r['chars']} | {r['ink']*100:.2f} | "
                     f"{r['cpi']:.1f} | {r['z']:.1f} |")
    else:
        L.append("None.")
    L.append("")

    if empty_scan_with_text:
        L.append("## Blank scans that still carry OCR text - fix these")
        L.append("")
        L.append(", ".join(str(r["page"]) for r in empty_scan_with_text))
        L.append("")

    Path(a.report).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"report -> {a.report}")
    print(f"pages {len(rows)}, blanks marked {len(blanks)}, "
          f"over-producing {len(suspicious)}, under-producing {len(thin)}, "
          f"blank-scan-with-text {len(empty_scan_with_text)}")
    if suspicious:
        print("most suspicious:", [(r["page"], r["chars"], round(r["z"], 1))
                                   for r in suspicious[:10]])


if __name__ == "__main__":
    main()
