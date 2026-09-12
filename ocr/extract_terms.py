#!/usr/bin/env python
"""Pull the recurring technical vocabulary out of the OCR'd book.

The glossary has to cover what this book actually says, not what a generic maths
dictionary contains, so candidates come from counting n-grams across every page with
the formulas masked out first - otherwise LaTeX fragments dominate the counts.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import book_translator as bt

STOP = set("""
a an the and or but if then than that this these those of in on at to for from by with
without into onto over under above below between among is are was were be been being am
do does did doing have has had having can could shall should will would may might must
we you they he she it i us them him her our your their its as so such not no nor only
just also very more most much many few some any each every other another same one two
three four five six seven eight nine ten first second third next last new old good well
where when what which who whom how why all both either neither because while although
though since until after before during about against along across behind beyond near
here there now later once again still yet even ever never always often sometimes
figure lesson chapter section page problem problems example examples solution solutions
see let us section part note notes hint hints reading other following given find shows
show shown using use used uses called consider suppose means value values case cases
form forms way ways time times point points number numbers thing things
""".split())

WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")


def ngrams(words, n):
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-dir", default="ocr_out/pages")
    ap.add_argument("--out", default="glossary/terms_frequency.json")
    ap.add_argument("--min-count", type=int, default=8)
    ap.add_argument("--top", type=int, default=120)
    a = ap.parse_args()

    counts = {1: Counter(), 2: Counter(), 3: Counter()}
    pages = sorted(Path(a.pages_dir).glob("p*.md"))
    for f in pages:
        text = f.read_text(encoding="utf-8")
        masked, _ = bt.mask_elements(text, emit_log=False)
        # drop the placeholders themselves and any stray markup
        masked = re.sub(r"[A-Z]{3,8}\d{4}X", " ", masked)
        words = [w.lower() for w in WORD.findall(masked)]
        for n in (1, 2, 3):
            for g in ngrams(words, n):
                parts = g.split()
                if any(len(p) < 3 for p in parts):
                    continue
                if all(p in STOP for p in parts):
                    continue
                if parts[0] in STOP or parts[-1] in STOP:
                    continue
                counts[n][g] += 1

    out = {}
    for n in (3, 2, 1):
        rows = [(g, c) for g, c in counts[n].most_common() if c >= a.min_count]
        out[f"{n}-gram"] = rows[:a.top]

    dest = Path(a.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"pages scanned: {len(pages)}")
    for n in (3, 2, 1):
        rows = out[f"{n}-gram"]
        print(f"\n--- {n}-word terms (>= {a.min_count} occurrences): {len(rows)} ---")
        for g, c in rows[:30]:
            print(f"  {c:5d}  {g}")
    print(f"\nwritten to {dest}")


if __name__ == "__main__":
    main()
