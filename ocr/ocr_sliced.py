#!/usr/bin/env python
"""Re-OCR a page in horizontal slices to break the model out of a repetition loop.

On a full page of dot-leader contents the model latches onto one line and repeats it
until the token budget runs out. A slice holds only a few lines, so there is nothing
to loop on, and the slices are stitched back together afterwards.

Only installs the result when it is measurably better than what is on disk.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from ocr_book import PROMPTS, ocr_image
from qa_report import PLACEHOLDER, unique_ratio


def slice_text(doc, page_no, top, bot, host, model, mode, num_predict, timeout):
    pg = doc[page_no - 1]
    r = pg.rect
    clip = pymupdf.Rect(r.x0, r.y0 + r.height * top, r.x1, r.y0 + r.height * bot)
    scale = 1600 / max(clip.width, clip.height)
    png = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip,
                        colorspace=pymupdf.csGRAY).tobytes("png")
    return ocr_image(host, model, png, PROMPTS[mode], 8192, timeout,
                     num_predict, 1.0, 0.0).strip()


def stitch(chunks):
    """Join slices, dropping lines a neighbouring slice already contributed."""
    out, seen = [], set()
    for chunk in chunks:
        for line in chunk.splitlines():
            key = line.strip()
            if not key:
                if out and out[-1] != "":
                    out.append("")
                continue
            if key in seen and len(key) > 12:
                continue
            seen.add(key)
            out.append(line)
    return "\n".join(out).strip()


def quality(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    ur = unique_ratio(lines)
    if PLACEHOLDER.search(text):
        return 0.0, "placeholder-text"
    if len(text.strip()) < 40:
        return 0.0, "near-empty"
    return ur, ("looped" if ur < 0.35 else "clean")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages-dir", default="ocr_out/pages")
    ap.add_argument("--backup-dir", default="ocr_out/pages_prelooped")
    ap.add_argument("--pages", required=True, help="comma-separated page numbers")
    ap.add_argument("--slices", type=int, default=6)
    ap.add_argument("--overlap", type=float, default=0.02,
                    help="fraction of page height each slice overlaps the next")
    ap.add_argument("--mode", default="text", choices=list(PROMPTS))
    ap.add_argument("--num-predict", type=int, default=700,
                    help="per-slice cap; small, because a slice holds few lines")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="glm-ocr")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    doc = pymupdf.open(a.pdf)
    backup = Path(a.backup_dir)
    backup.mkdir(parents=True, exist_ok=True)

    improved, kept = [], []
    for p in [int(x) for x in a.pages.replace(" ", "").split(",") if x]:
        dest = Path(a.pages_dir) / f"p{p:04d}.md"
        before = dest.read_text(encoding="utf-8") if dest.exists() else ""
        ur_before, why_before = quality(before)
        print(f"\np{p:04d}: was {why_before} (uniq {ur_before:.2f}, "
              f"{len(before.strip())} chars)", flush=True)

        chunks = []
        step = 1.0 / a.slices
        t0 = time.time()
        for i in range(a.slices):
            top = max(0.0, i * step - a.overlap)
            bot = min(1.0, (i + 1) * step + a.overlap)
            try:
                txt = slice_text(doc, p, top, bot, a.host, a.model, a.mode,
                                 a.num_predict, a.timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"   slice {i+1}/{a.slices}: failed - {exc}", flush=True)
                continue
            lines = len([l for l in txt.splitlines() if l.strip()])
            print(f"   slice {i+1}/{a.slices}: {len(txt):5d} chars, {lines:3d} lines",
                  flush=True)
            chunks.append(txt)

        result = stitch(chunks)
        ur_after, why_after = quality(result)
        print(f"   stitched: {why_after} (uniq {ur_after:.2f}, {len(result)} chars, "
              f"{time.time()-t0:.0f}s)", flush=True)

        if ur_after > ur_before and len(result) > 40:
            if dest.exists() and not (backup / dest.name).exists():
                shutil.copy2(dest, backup / dest.name)
            dest.write_text(result + "\n", encoding="utf-8")
            improved.append(p)
            print("   -> INSTALLED (old copy in "
                  f"{backup}/{dest.name})", flush=True)
        else:
            kept.append(p)
            print("   -> kept the old text, slicing did not beat it", flush=True)

    print("\n" + "=" * 46)
    print(f"improved ({len(improved)}): {improved}")
    print(f"unchanged ({len(kept)}): {kept}")


if __name__ == "__main__":
    main()
