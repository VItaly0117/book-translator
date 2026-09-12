#!/usr/bin/env python
"""Translate the OCR'd book into Ukrainian page by page, protecting the maths.

Formulas and images are masked into word-like tokens before the text is sent to a
translator and restored afterwards, using the masking already proven in this project.
Every page is then verified: if a formula went missing or a placeholder came back
mangled, the page is rejected rather than written, because a damaged formula is far
harder to spot later than an untranslated page.

Note: the project's own `clean_markdown_formatting` is deliberately NOT applied here.
It strips `$` delimiters from maths-heavy pages (measured: 86 -> 66 on p0190), which
is the very corruption PROJECT_MEMORY warns about.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import requests

import book_translator as bt

PLACEHOLDER = re.compile(r"MATH(?:INL|BLK)\d{4}X|IMGBLK\d{4}X|[A-Z]{3,8}\d{4}X")

OLLAMA_PROMPT = """You are a professional translator of mathematics textbooks.
Translate the text below from English into Ukrainian.

Rules:
- Tokens like MATHINL0003X or MATHBLK0012X are formula placeholders. Reproduce every
  one of them exactly as written, in the same order. Never translate, split, renumber
  or drop them.
- Keep Markdown structure: headings, lists, line breaks, blank lines.
- Translate only prose. Leave numbers, equation labels like (2.5), and names as they are.
- Use standard Ukrainian mathematical terminology.
- Output only the translation, with no commentary.

TEXT:
"""


def signature(text):
    """The parts that must survive translation untouched."""
    return {
        "dollars": text.count("$"),
        "begin": len(re.findall(r"\\begin\{", text)),
        "end": len(re.findall(r"\\end\{", text)),
        "images": len(re.findall(r"!\[", text)),
    }


def translate_azure(masked, target):
    return bt.translate_text_azure(
        masked,
        api_key=bt.AZURE_TRANSLATOR_KEY,
        endpoint=bt.AZURE_TRANSLATOR_ENDPOINT,
        region=bt.AZURE_TRANSLATOR_REGION,
        target_lang=target,
    )


def translate_ollama(masked, host, model, timeout, num_ctx=8192):
    r = requests.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": OLLAMA_PROMPT + masked,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": num_ctx},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


def check(source, masked, translated_masked, restored):
    """Reasons this page must not be accepted."""
    problems = []
    want = PLACEHOLDER.findall(masked)
    got = PLACEHOLDER.findall(translated_masked)
    if want != got:
        missing = [p for p in want if p not in got]
        problems.append(f"placeholders changed ({len(want)} -> {len(got)}"
                        + (f", missing {missing[:3]}" if missing else "") + ")")
    a, b = signature(source), signature(restored)
    if a != b:
        problems.append(f"maths changed {a} -> {b}")
    if not translated_masked.strip():
        problems.append("empty translation")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-dir", default="ocr_out/pages")
    ap.add_argument("--out-dir", default="translated_uk/pages")
    ap.add_argument("--backend", choices=("azure", "ollama"), default="azure")
    ap.add_argument("--target", default="uk")
    ap.add_argument("--model", default="gemma3:12b", help="ollama backend only")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, default=0)
    ap.add_argument("--pages", default="", help="explicit comma-separated page list")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="mask and verify only - no translator is called")
    a = ap.parse_args()

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rejected_dir = out.parent / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    log_path = out.parent / "translate_log.jsonl"

    src_files = sorted(Path(a.src_dir).glob("p*.md"))
    if a.pages:
        wanted = {int(x) for x in a.pages.replace(" ", "").split(",") if x}
        src_files = [f for f in src_files if int(f.stem[1:]) in wanted]
    else:
        last = a.last or 10 ** 6
        src_files = [f for f in src_files if a.first <= int(f.stem[1:]) <= last]

    todo = [f for f in src_files
            if a.force or not (out / f.name).exists()
            or (out / f.name).stat().st_size == 0]

    if a.backend == "azure" and not a.dry_run and not bt.AZURE_TRANSLATOR_KEY:
        sys.exit("AZURE_TRANSLATOR_KEY is not set: create .env with your Azure "
                 "Translator key, endpoint and region, then re-run.")

    print(f"backend={a.backend} target={a.target} pages todo={len(todo)}"
          + (f" model={a.model}" if a.backend == "ollama" else ""), flush=True)

    done = ok = rejected = 0
    t_start = time.time()
    for f in todo:
        page = int(f.stem[1:])
        source = f.read_text(encoding="utf-8")
        masked, elements = bt.mask_elements(source, emit_log=False)

        if a.dry_run:
            problems = check(source, masked, masked,
                             bt.unmask_elements(masked, elements))
            status = "clean" if not problems else "; ".join(problems)
            print(f"  p{page:04d}: {len(elements):3d} masked, round-trip {status}",
                  flush=True)
            continue

        t0 = time.time()
        try:
            if a.backend == "azure":
                translated_masked = translate_azure(masked, a.target)
            else:
                translated_masked = translate_ollama(masked, a.host, a.model,
                                                     a.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"  p{page:04d}: request failed - {exc}", flush=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"page": page, "error": str(exc)}) + "\n")
            continue

        restored = bt.unmask_elements(translated_masked, elements)
        problems = check(source, masked, translated_masked, restored)
        dt = time.time() - t0
        done += 1

        if problems:
            rejected += 1
            (rejected_dir / f.name).write_text(restored + "\n", encoding="utf-8")
            print(f"  p{page:04d} REJECTED ({dt:.0f}s): {'; '.join(problems)}",
                  flush=True)
        else:
            ok += 1
            (out / f.name).write_text(restored.strip() + "\n", encoding="utf-8")
            print(f"  p{page:04d} ok ({dt:.0f}s, {len(restored)} chars) "
                  f"| {ok}/{len(todo)}", flush=True)

        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"page": page, "secs": round(dt, 1),
                                 "chars": len(restored),
                                 "problems": problems}) + "\n")

    if not a.dry_run:
        mins = (time.time() - t_start) / 60
        print(f"\ntranslated {ok}, rejected {rejected}, of {len(todo)} "
              f"in {mins:.1f} min", flush=True)
        if rejected:
            print(f"rejected pages kept for inspection in {rejected_dir}")


if __name__ == "__main__":
    main()
