#!/usr/bin/env python
"""Detect and crop figures/diagrams from the scanned book pages.

The OCR model returns text only, so illustrations have to be cut out of the scan
separately. No layout model is used: the pages are clean 600 dpi bitonal scans, and a
figure differs from text in one robust way - text produces short ink runs (one per
printed line, ~20px tall at 200 dpi) separated by regular blank rows, while a drawing
produces one tall continuous ink run.

Non-destructive: writes crops and a manifest to its own directory and touches nothing
that already exists.
"""
import argparse
import csv
import re
from pathlib import Path

import numpy as np
import pymupdf

# Not anchored to the line start: the model sometimes writes the caption inside a
# markdown image placeholder (`![Figure 39.2 ...`), and anchoring skipped those pages
# entirely - the figures on them were never even looked for.
CAPTION = re.compile(r"(?:FIG(?:URE)?\.?|Fig\.?)\s*\d+\.\d+", re.M)


def page_ink(doc, pno, dpi):
    """Binary ink mask of a page: True where there is ink."""
    pix = doc[pno].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return arr < 160, pix.width, pix.height


def runs(mask_1d):
    """Yield (start, end) of contiguous True runs."""
    idx = np.flatnonzero(np.diff(np.concatenate(([0], mask_1d.view(np.int8), [0]))))
    return list(zip(idx[0::2], idx[1::2]))


def blocks_from_rows(ink, min_gap):
    """Split the page into vertical blocks separated by >= min_gap blank rows."""
    row_has_ink = ink.any(axis=1)
    out = []
    for start, end in runs(row_has_ink):
        if out and start - out[-1][1] < min_gap:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def block_features(ink, top, bot):
    band = ink[top:bot]
    if band.size == 0 or not band.any():
        return None
    cols = np.flatnonzero(band.any(axis=0))
    left, right = int(cols[0]), int(cols[-1]) + 1
    band = band[:, left:right]
    h, w = band.shape

    row_has_ink = band.any(axis=1)
    ink_runs = runs(row_has_ink)
    run_heights = [e - s for s, e in ink_runs]
    tallest = max(run_heights) if run_heights else 0

    # longest horizontal ink run in any row: axes and frames give a long one
    max_h_run = 0
    step = max(1, h // 200)
    for r in range(0, h, step):
        row = band[r]
        if row.any():
            rr = runs(row)
            max_h_run = max(max_h_run, max(e - s for s, e in rr))

    return {
        "top": top, "bot": bot, "left": left, "right": right,
        "h": h, "w": w,
        "density": float(band.mean()),
        "tallest_run": int(tallest),
        "tallest_frac": tallest / h if h else 0.0,
        "max_h_run_frac": max_h_run / w if w else 0.0,
        "n_line_runs": len(ink_runs),
    }


def is_figure(f, page_h, dpi, min_h=60, margin=0.05):
    """Heuristic: a tall continuous ink mass, or a block with long straight rules."""
    scale = dpi / 200.0
    # No margin guard: figures do sit directly under a running header or at the foot
    # of a page, and excluding the margins cost more real figures than it saved.
    if f["h"] < min_h * scale:
        # a short block can still be a wide flat diagram: one long rule, few ink runs
        if (f["h"] >= 40 * scale and f["max_h_run_frac"] >= 0.85
                and f["n_line_runs"] <= 3):
            return True, "flat-diagram"
        return False, "too-short"
    if f["h"] < 0.05 * page_h:
        return False, "tiny"
    # A drawing forms one tall ink run; a paragraph forms many short ones.
    if f["tallest_run"] >= 70 * scale and f["tallest_frac"] >= 0.30:
        return True, "tall-ink-mass"
    # Framed plots / tables: long horizontal rule plus few text lines.
    if f["max_h_run_frac"] >= 0.55 and f["n_line_runs"] <= 12:
        return True, "long-rule"
    return False, "text-like"


def merge_and_absorb(blocks, merge_gap, absorb_gap, tol):
    """Join figure blocks that belong to one illustration.

    Panels of a multi-part figure arrive as separate blocks, and an axis annotation
    under a diagram arrives as its own short block. Both should end up in one crop.
    A caption line is left out: it starts at the page margin, outside the figure's
    horizontal span, whereas an annotation sits within it.
    """
    figs = [b for b in blocks if b["is_fig"]]
    others = [b for b in blocks if not b["is_fig"]]
    if not figs:
        return []

    merged = [dict(figs[0])]
    for b in figs[1:]:
        prev = merged[-1]
        if b["top"] - prev["bot"] <= merge_gap:
            prev["bot"] = b["bot"]
            prev["left"] = min(prev["left"], b["left"])
            prev["right"] = max(prev["right"], b["right"])
            prev["reason"] = prev["reason"] + "+merged"
        else:
            merged.append(dict(b))

    for m in merged:
        for o in others:
            small = o["h"] <= max(45, absorb_gap * 1.5)
            inside = o["left"] >= m["left"] - tol and o["right"] <= m["right"] + tol
            near_below = 0 <= o["top"] - m["bot"] <= absorb_gap
            near_above = 0 <= m["top"] - o["bot"] <= absorb_gap
            if small and inside and (near_below or near_above):
                m["top"] = min(m["top"], o["top"])
                m["bot"] = max(m["bot"], o["bot"])
                # widen too, or an annotation wider than the drawing gets clipped
                m["left"] = min(m["left"], o["left"])
                m["right"] = max(m["right"], o["right"])
                m["reason"] = m["reason"] + "+annot"
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--ocr-dir", default="ocr_out/pages",
                    help="per-page OCR markdown, used to find pages with figure captions")
    ap.add_argument("--out", default="figures_out")
    ap.add_argument("--dpi", type=int, default=200, help="analysis resolution")
    ap.add_argument("--crop-dpi", type=int, default=400, help="resolution of saved crops")
    ap.add_argument("--pad", type=int, default=14, help="padding around a crop, analysis px")
    ap.add_argument("--min-height", type=int, default=60,
                    help="analysis-px height below which a block is not a figure")
    ap.add_argument("--min-gap", type=int, default=14, help="blank rows that separate blocks")
    ap.add_argument("--merge-gap", type=int, default=55,
                    help="join figure blocks closer than this - panels of one illustration")
    ap.add_argument("--absorb-gap", type=int, default=50,
                    help="pull in a short block this close, e.g. an axis annotation")
    ap.add_argument("--tol", type=int, default=45,
                    help="horizontal slack when deciding a short block belongs to a figure")
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, default=0)
    ap.add_argument("--all-pages", action="store_true",
                    help="scan every page instead of only pages whose OCR has a figure caption")
    ap.add_argument("--debug-overlay", action="store_true",
                    help="also save the full page with detected boxes drawn on it")
    a = ap.parse_args()

    out = Path(a.out)
    (out / "crops").mkdir(parents=True, exist_ok=True)
    if a.debug_overlay:
        (out / "overlays").mkdir(exist_ok=True)

    doc = pymupdf.open(a.pdf)
    last = a.last or doc.page_count

    ocr_dir = Path(a.ocr_dir)
    caption_pages = set()
    if not a.all_pages:
        for f in ocr_dir.glob("p*.md"):
            try:
                if CAPTION.search(f.read_text(encoding="utf-8")):
                    caption_pages.add(int(f.stem[1:]))
            except Exception:
                pass
        print(f"pages with figure captions in OCR: {len(caption_pages)}")

    rows = []
    scanned = 0
    for pno in range(a.first, last + 1):
        if not a.all_pages and pno not in caption_pages:
            continue
        scanned += 1
        ink, pw, ph = page_ink(doc, pno - 1, a.dpi)
        blocks = []
        for top, bot in blocks_from_rows(ink, a.min_gap):
            f = block_features(ink, top, bot)
            if not f:
                continue
            ok, why = is_figure(f, ph, a.dpi, a.min_height)
            f["is_fig"], f["reason"] = ok, why
            blocks.append(f)

        found = 0
        for f in merge_and_absorb(blocks, a.merge_gap, a.absorb_gap, a.tol):
            found += 1
            why = f["reason"]
            # map the analysis-resolution box onto the page in PDF points
            s = 72.0 / a.dpi
            rect = pymupdf.Rect(
                max(0, f["left"] - a.pad) * s, max(0, f["top"] - a.pad) * s,
                min(pw, f["right"] + a.pad) * s, min(ph, f["bot"] + a.pad) * s)
            name = f"p{pno:04d}_fig{found}.png"
            doc[pno - 1].get_pixmap(clip=rect, dpi=a.crop_dpi).save(out / "crops" / name)
            rows.append({
                "file": name, "page": pno, "reason": why,
                "x0": round(rect.x0, 1), "y0": round(rect.y0, 1),
                "x1": round(rect.x1, 1), "y1": round(rect.y1, 1),
                "height_px": f["bot"] - f["top"], "width_px": f["right"] - f["left"],
                "density": round(f["density"], 3),
                "tallest_frac": round(f["tallest_frac"], 2),
                "max_h_run_frac": round(f["max_h_run_frac"], 2),
                "n_line_runs": f["n_line_runs"],
            })

        if a.debug_overlay and found:
            pg = doc[pno - 1]
            for r in rows[-found:]:
                pg.draw_rect(pymupdf.Rect(r["x0"], r["y0"], r["x1"], r["y1"]),
                             color=(1, 0, 0), width=1.5)
            pg.get_pixmap(dpi=110).save(out / "overlays" / f"p{pno:04d}.png")
            doc.reload_page(pg)

        if found:
            print(f"  p{pno:04d}: {found} figure(s)", flush=True)

    man = out / "figures_manifest.csv"
    if rows:
        with man.open("w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
    print(f"\nscanned {scanned} pages, cropped {len(rows)} figures -> {out/'crops'}")
    print(f"manifest -> {man}" if rows else "no figures detected")


if __name__ == "__main__":
    main()
