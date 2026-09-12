#!/usr/bin/env python
"""Re-OCR the pages the QA audit rejected, trying several settings until one is clean.

Re-running with identical settings is pointless: temperature is 0, so the model returns
the same loop (and Ollama may even serve it from cache). Each attempt therefore changes
the render size, the prompt mode or the sampling, and the result is checked before it is
allowed to replace what is on disk. The old page is kept in <out>/pages_bad/.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from ocr_book import PROMPTS, ocr_image, render_page
from qa_report import PLACEHOLDER, unique_ratio

# (mode, max_edge, temperature, repeat_penalty)
LADDER = [
    ("text", 1200, 0.0, 1.0),
    ("table", 1600, 0.0, 1.0),
    ("text", 2200, 0.4, 1.15),
    ("text", 1000, 0.7, 1.10),
]


def quality(text):
    """(is_clean, reason, score) - score ranks near-misses so the best is kept."""
    stripped = text.strip()
    lines = [l.strip() for l in stripped.splitlines() if l.strip()]
    ur = unique_ratio(lines)
    if len(stripped) < 80:
        return False, "near-empty", (0, len(stripped))
    if PLACEHOLDER.search(stripped):
        return False, "placeholder-text", (1, len(stripped))
    if ur < 0.35:
        return False, "looped", (2, round(ur, 2))
    return True, "clean", (3, round(ur, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="ocr_out")
    ap.add_argument("--pages", required=True,
                    help="comma-separated page numbers, e.g. 3,23,257,411")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="glm-ocr")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=1600)
    ap.add_argument("--timeout", type=int, default=420)
    a = ap.parse_args()

    pages = [int(x) for x in a.pages.replace(" ", "").split(",") if x]
    out = Path(a.out)
    pages_dir = out / "pages"
    bad_dir = out / "pages_bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    log = out / "redo_log.jsonl"

    doc = pymupdf.open(a.pdf)
    fixed, improved, stuck = [], [], []

    for p in pages:
        dest = pages_dir / f"p{p:04d}.md"
        before = dest.read_text(encoding="utf-8") if dest.exists() else ""
        _, before_why, before_score = quality(before)
        print(f"\np{p:04d}  was: {before_why}", flush=True)

        best = (before_score, before, "unchanged", before_why)
        for mode, edge, temp, rp in LADDER:
            t0 = time.time()
            png = render_page(doc, p - 1, edge)
            try:
                text = ocr_image(a.host, a.model, png, PROMPTS[mode], a.num_ctx,
                                 a.timeout, a.num_predict, rp, temp)
            except Exception as exc:  # noqa: BLE001
                print(f"   {mode}/{edge}/t{temp}: request failed - {exc}", flush=True)
                continue
            ok, why, score = quality(text)
            dt = time.time() - t0
            tag = f"{mode}/{edge}/t{temp}/rp{rp}"
            print(f"   {tag}: {why}, {len(text.strip())} chars, {dt:.0f}s", flush=True)
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"page": p, "attempt": tag, "result": why,
                                     "chars": len(text.strip()),
                                     "secs": round(dt, 1)}) + "\n")
            if score > best[0]:
                best = (score, text, tag, why)
            if ok:
                break

        if best[2] == "unchanged":
            stuck.append(p)
            print(f"   -> kept the old text, nothing beat it", flush=True)
            continue

        if dest.exists():
            shutil.copy2(dest, bad_dir / f"p{p:04d}.md")
        dest.write_text(best[1].strip() + "\n", encoding="utf-8")
        if best[3] == "clean":
            fixed.append(p)
            print(f"   -> FIXED via {best[2]} (old copy in pages_bad/)", flush=True)
        else:
            improved.append(p)
            print(f"   -> improved to '{best[3]}' via {best[2]}", flush=True)

    print("\n" + "=" * 50)
    print(f"fixed clean ({len(fixed)}): {fixed}")
    print(f"improved but still flagged ({len(improved)}): {improved}")
    print(f"no improvement ({len(stuck)}): {stuck}")


if __name__ == "__main__":
    main()
