#!/usr/bin/env python
"""Tie the cropped figures to the figure numbers used in the book text.

The crops come out of a layout heuristic and know only their page. The text knows
"FIGURE 3.4" but not where the picture is. This pairs the two, reports what could not
be paired in either direction, compares coverage against the previously extracted
image set, and writes a markdown copy with the images referenced in place.
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

CAPTION = re.compile(r"(?:FIGURE|Figure)\s+(\d+\.\d+)")
PAGE_MARK = re.compile(r"<!--\s*PAGE\s+(\d+)\s*-->")


# A real caption is printed as its own line beginning "FIGURE 4.2"; an in-text mention
# ("See Figure 4.2.") is not. Only the former identifies the picture above it.
CAPTION_LINE = re.compile(r"^\s*FIGURE\s+(\d+\.\d+)", re.M)


def figure_key(s):
    return tuple(int(x) for x in s.split("."))


def read_caption_under(page, crop, doc, host, model):
    """OCR the strip spanning the bottom of a crop and the line just below it.

    Geometry cannot separate a plot from a displayed formula, but the printed caption
    can, so pages with more crops than captions are settled by reading.
    """
    import pymupdf
    from ocr_book import PROMPTS, ocr_image

    pg = doc[page - 1]
    y1 = float(crop["y1"])
    clip = pymupdf.Rect(pg.rect.x0, y1 - 42, pg.rect.x1, min(pg.rect.y1, y1 + 34))
    scale = 1600 / max(clip.width, clip.height)
    png = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip,
                        colorspace=pymupdf.csGRAY).tobytes("png")
    try:
        txt = ocr_image(host, model, png, PROMPTS["text"], 4096, 180, 120, 1.0, 0.0)
    except Exception:
        return None
    m = CAPTION_LINE.search(txt)
    return m.group(1) if m else None


def load_crops(manifest):
    per_page = defaultdict(list)
    for r in csv.DictReader(open(manifest, encoding="utf-8")):
        per_page[int(r["page"])].append(r)
    for page in per_page:
        per_page[page].sort(key=lambda r: float(r["y0"]))
    return per_page


def load_captions(pages_dir):
    """Figure numbers captioned on each page, in reading order."""
    per_page = {}
    for f in sorted(Path(pages_dir).glob("p*.md")):
        nums = []
        for m in CAPTION.finditer(f.read_text(encoding="utf-8")):
            if m.group(1) not in nums:
                nums.append(m.group(1))
        if nums:
            per_page[int(f.stem[1:])] = nums
    return per_page


def old_figure_numbers(old_manifest):
    """Figure numbers recoverable from the previous extraction's captions."""
    nums = set()
    p = Path(old_manifest)
    if not p.exists():
        return nums, 0
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    for r in rows:
        m = re.search(r"(\d+\.\d+)", r.get("caption", ""))
        if m:
            nums.add(m.group(1))
    return nums, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="figures_out/figures_manifest.csv")
    ap.add_argument("--pages-dir", default="ocr_out/pages")
    ap.add_argument("--md", default="ocr_out/book_full_en.md")
    ap.add_argument("--old-manifest",
                    default="nanobanana_workspace/manifests/images_manifest.csv")
    ap.add_argument("--crops-rel", default="../figures_out/crops",
                    help="path to the crops as written into the markdown")
    ap.add_argument("--dest-md", default="ocr_out/book_with_figures.md")
    ap.add_argument("--report", default="ocr_out/FIGURES_REPORT.md")
    ap.add_argument("--verify-captions", action="store_true",
                    help="on pages with more crops than captions, read the caption "
                         "printed under each crop instead of pairing in order")
    ap.add_argument("--pdf",
                    default="book-pdf/partial_differential_equations_for_scientists"
                            "_and_engineers_reprintnbsped.pdf")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="glm-ocr")
    ap.add_argument("--caption-cache", default="figures_out/caption_cache.json",
                    help="remembers captions already read, so re-runs are instant")
    a = ap.parse_args()

    crops = load_crops(a.manifest)
    captions = load_captions(a.pages_dir)

    # A caption sits under its picture, so a crop is matched to a caption on its own
    # page first, then to one on the next page (figure at the foot, caption overleaf).
    assigned = {}          # crop file -> figure number
    verified_pages = []    # pages settled by reading the printed caption
    caption_page = {}      # crop file -> page whose caption it was tied to
    used_numbers = set()
    doc = None
    cache_path = Path(a.caption_cache)
    cache = {}
    if a.verify_captions:
        import pymupdf
        doc = pymupdf.open(a.pdf)
        if cache_path.exists():
            cache = json.loads(cache_path.read_text(encoding="utf-8"))

    for page in sorted(crops):
        src = page
        nums = [n for n in captions.get(page, []) if n not in used_numbers]
        if not nums:
            src = page + 1
            nums = [n for n in captions.get(page + 1, []) if n not in used_numbers]
        page_crops = crops[page]

        # More crops than captions means a displayed formula was taken for a drawing
        # and pairing in order would shift every figure on the page. Read the caption
        # printed under each crop and let that decide.
        if doc is not None and len(page_crops) > len(nums) >= 1:
            resolved = {}
            for c in page_crops:
                if c["file"] in cache:
                    num = cache[c["file"]]
                else:
                    num = read_caption_under(page, c, doc, a.host, a.model)
                    cache[c["file"]] = num
                    cache_path.write_text(json.dumps(cache, indent=1),
                                          encoding="utf-8")
                if num and num not in used_numbers:
                    resolved[c["file"]] = num
            if resolved:
                # Panels of one illustration share a single caption, printed under the
                # last of them, so a crop with no caption of its own belongs to the
                # first captioned crop below it.
                for i, c in enumerate(page_crops):
                    num = resolved.get(c["file"])
                    if num is None:
                        below = [resolved.get(x["file"]) for x in page_crops[i + 1:]]
                        below = [n for n in below if n]
                        num = below[0] if below else None
                    if num is None:
                        continue
                    assigned[c["file"]] = num
                    caption_page[c["file"]] = page
                    used_numbers.add(num)
                verified_pages.append(page)
                continue

        if len(nums) == 1 and len(page_crops) >= 1:
            # one caption, several crops: panels of the same illustration
            for c in page_crops:
                assigned[c["file"]] = nums[0]
                caption_page[c["file"]] = src
            used_numbers.add(nums[0])
        else:
            for c, n in zip(page_crops, nums):
                assigned[c["file"]] = n
                caption_page[c["file"]] = src
                used_numbers.add(n)

    all_numbers = sorted({n for v in captions.values() for n in v}, key=figure_key)
    unmatched_crops = [c["file"] for page in sorted(crops) for c in crops[page]
                       if c["file"] not in assigned]
    missing_numbers = [n for n in all_numbers if n not in used_numbers]

    old_nums, old_count = old_figure_numbers(a.old_manifest)
    only_new = sorted(used_numbers - old_nums, key=figure_key)
    only_old = sorted(old_nums - used_numbers, key=figure_key)

    # ---- markdown with the pictures put back in ----
    by_number = defaultdict(list)
    for fname, num in assigned.items():
        by_number[num].append(fname)
    for num in by_number:
        by_number[num].sort()

    # Where each picture belongs: on the page its caption is printed on. Matching the
    # first mention of "Figure 5.3" anywhere would drop the picture next to an in-text
    # cross-reference pages earlier, so insertion is confined to that one page.
    want = defaultdict(list)      # (caption page, number) -> [crop files]
    for fname, num in assigned.items():
        want[(caption_page[fname], num)].append(fname)
    for key in want:
        want[key].sort()

    md = Path(a.md).read_text(encoding="utf-8")
    out_lines = []
    inserted = 0
    current_page = None
    pending = []                  # images for this page not yet placed
    for line in md.splitlines():
        pm = PAGE_MARK.search(line)
        if pm:
            # anything unplaced on the previous page goes at its end
            for fname in pending:
                out_lines.append("")
                out_lines.append(f"![]({a.crops_rel}/{fname}){{width=72%}}")
                inserted += 1
            pending = []
            current_page = int(pm.group(1))
            pending = [f for (pg, _), files in want.items() if pg == current_page
                       for f in files]
        out_lines.append(line)
        m = CAPTION.search(line)
        if m and current_page is not None:
            files = want.get((current_page, m.group(1)))
            if files:
                for fname in files:
                    out_lines.append("")
                    # empty alt text: pandoc would otherwise print its own
                    # "Figure N:" caption on top of the book's own one
                    out_lines.append(f"![]({a.crops_rel}/{fname}){{width=72%}}")
                    inserted += 1
                    if fname in pending:
                        pending.remove(fname)
                want.pop((current_page, m.group(1)))
    for fname in pending:
        out_lines.append("")
        out_lines.append(f"![]({a.crops_rel}/{fname}){{width=72%}}")
        inserted += 1
    Path(a.dest_md).write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# Figure mapping report", "",
         f"- crops detected: **{len(assigned) + len(unmatched_crops)}**",
         f"- figure numbers used in the text: **{len(all_numbers)}**",
         f"- crops tied to a figure number: **{len(assigned)}**",
         f"- figure numbers with no crop: **{len(missing_numbers)}**",
         f"- crops with no caption to tie to: **{len(unmatched_crops)}**",
         f"- images referenced in `{Path(a.dest_md).name}`: **{inserted}**",
         f"- pages settled by reading the printed caption: **{len(verified_pages)}**"
         + (f" ({', '.join(str(p) for p in verified_pages)})" if verified_pages else ""),
         "",
         "## Against the previous extraction", "",
         f"- images in the old set: **{old_count}**",
         f"- figure numbers recoverable from old captions: **{len(old_nums)}**",
         f"- numbers covered now but not before: **{len(only_new)}**",
         f"- numbers in the old set but not matched now: **{len(only_old)}**", ""]
    if only_old:
        L += ["Numbers only in the old set (check these by hand):", "",
              ", ".join(only_old), ""]
    if missing_numbers:
        L += ["## Figure numbers with no detected crop", "",
              ", ".join(missing_numbers), ""]
    if unmatched_crops:
        L += ["## Crops with no caption", "",
              "Either a picture whose caption the OCR lost, or a false positive "
              "(a large displayed formula reads like a drawing).", "",
              ", ".join(unmatched_crops), ""]

    Path(a.report).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"report -> {a.report}")
    print(f"markdown with figures -> {a.dest_md}")
    print(f"crops {len(assigned) + len(unmatched_crops)}, tied {len(assigned)}, "
          f"numbers {len(all_numbers)}, missing {len(missing_numbers)}, "
          f"unmatched crops {len(unmatched_crops)}, inserted {inserted}")


if __name__ == "__main__":
    main()
