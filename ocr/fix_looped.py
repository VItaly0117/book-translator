#!/usr/bin/env python
"""Recover pages the model looped on, by keeping only what it actually read.

Part-divider and title pages carry a big frame and a couple of words. With almost
nothing to transcribe the model repeats one line hundreds of times - but the distinct
lines in that output are the real content of the page, so removing the repetition
recovers it without going back to the model.

Also unwraps the HTML tables the model emits instead of plain text, and drops the
commentary it sometimes adds about the image.
"""
import argparse
import re
import shutil
from pathlib import Path

ANY_TAG = re.compile(r"<[^>]+>")
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
# things the model says about the picture rather than transcribing it
CHATTER = re.compile(
    r"^(?:the text (?:that is )?(?:highlighted|shown|visible)|this (?:image|text)|"
    r"the image (?:shows|contains)|here is the|```|note:|"
    # the prompt itself, echoed back instead of transcribed
    r"(?:text|table|figure) recognition:|"
    r"-{3,}$)", re.I)


def clean(text):
    kept = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        cells = CELL.findall(line)
        pieces = cells if cells else [line]
        for piece in pieces:
            piece = ANY_TAG.sub("", piece).strip()
            if not piece or CHATTER.match(piece):
                continue
            low = piece.lower()
            if low in seen:
                continue
            seen.add(low)
            kept.append(piece)

    # A wrapped line often reappears in pieces ("for", "Scientists and"). Drop any
    # entry that is contained in a longer one already kept.
    result = []
    for piece in kept:
        if any(piece != other and piece.lower() in other.lower() for other in kept):
            continue
        result.append(piece)
    return "\n\n".join(result).strip()


def unique_ratio(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return 1.0
    return len(set(lines)) / len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-dir", default="ocr_out/pages")
    ap.add_argument("--backup-dir", default="ocr_out/pages_prelooped")
    ap.add_argument("--pages", required=True, help="comma-separated page numbers")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    backup = Path(a.backup_dir)
    backup.mkdir(parents=True, exist_ok=True)
    fixed, skipped = [], []

    for p in [int(x) for x in a.pages.replace(" ", "").split(",") if x]:
        f = Path(a.pages_dir) / f"p{p:04d}.md"
        before = f.read_text(encoding="utf-8")
        after = clean(before)
        ur_before, ur_after = unique_ratio(before), unique_ratio(after)
        print(f"p{p:04d}: {len(before.strip()):5d} -> {len(after):4d} chars, "
              f"uniq {ur_before:.2f} -> {ur_after:.2f}")
        if not after:
            skipped.append(p)
            print("   -> nothing left after cleaning, kept as is")
            continue
        if a.dry_run:
            for line in after.splitlines():
                if line.strip():
                    print(f"      | {line}")
            continue
        if not (backup / f.name).exists():
            shutil.copy2(f, backup / f.name)
        f.write_text(after + "\n", encoding="utf-8")
        fixed.append(p)

    if not a.dry_run:
        print(f"\ncleaned ({len(fixed)}): {fixed}")
        print(f"untouched ({len(skipped)}): {skipped}")


if __name__ == "__main__":
    main()
