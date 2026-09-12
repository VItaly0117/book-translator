#!/usr/bin/env python
"""OCR a scanned PDF page-by-page through a local Ollama vision model (glm-ocr).

Resumable: each page is written to <out>/pages/pNNNN.md and skipped on re-run.
"""
import argparse, base64, io, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pymupdf
import requests

PROMPTS = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "figure": "Figure Recognition:",
}


def render_page(doc, pno, max_edge, gray=True):
    page = doc[pno]
    rect = page.rect
    scale = max_edge / max(rect.width, rect.height)
    cs = pymupdf.csGRAY if gray else pymupdf.csRGB
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=cs)
    return pix.tobytes("png")


def ink_ratio(doc, pno, dpi=100):
    """Fraction of dark pixels on a page. A blank separator page scores ~0.00004."""
    pix = doc[pno].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    return float((np.frombuffer(pix.samples, dtype=np.uint8) < 160).mean())


def ocr_image(host, model, png, prompt, num_ctx, timeout, num_predict,
              repeat_penalty, temperature=0.0, retries=3):
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(png).decode()],
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict,
                    "repeat_penalty": repeat_penalty},
    }
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{host}/api/generate", json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json().get("response", "")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"ollama failed after {retries} attempts: {last}")


def repetition_ratio(text):
    """1.0 = every line unique, ~0 = the model looped on a few lines."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 8:
        return 1.0
    return len(set(lines)) / len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="ocr_out")
    ap.add_argument("--first", type=int, default=1, help="first page (1-based)")
    ap.add_argument("--last", type=int, default=0, help="last page (0 = end)")
    ap.add_argument("--model", default="glm-ocr")
    ap.add_argument("--mode", default="text", choices=list(PROMPTS))
    ap.add_argument("--max-edge", type=int, default=2000)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=1600,
                    help="hard cap on generated tokens per page (stops runaway output)")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--blank-threshold", type=float, default=0.0015,
                    help="ink coverage below this is a blank page - never sent to the "
                         "model, which reliably hallucinates text for empty scans")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="raise to break a deterministic repetition loop on a retry")
    ap.add_argument("--repeat-penalty", type=float, default=1.0,
                    help="raise slightly (e.g. 1.05) if pages come back as repetition loops")
    ap.add_argument("--workers", type=int, default=1,
                    help="concurrent pages; needs OLLAMA_NUM_PARALLEL >= this on the server")
    ap.add_argument("--force", action="store_true", help="redo pages that already exist")
    ap.add_argument("--keep-png", action="store_true", help="also save the rendered page images")
    args = ap.parse_args()

    out = Path(args.out)
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    png_dir = out / "png"
    if args.keep_png:
        png_dir.mkdir(exist_ok=True)
    log_path = out / "ocr_log.jsonl"

    doc = pymupdf.open(args.pdf)
    last = args.last or doc.page_count
    first = max(1, args.first)
    prompt = PROMPTS[args.mode]

    todo = []
    for p in range(first, last + 1):
        dest = pages_dir / f"p{p:04d}.md"
        if dest.exists() and dest.stat().st_size > 0 and not args.force:
            continue
        todo.append(p)

    print(f"pdf={args.pdf} pages={doc.page_count} range={first}-{last} "
          f"todo={len(todo)} model={args.model} mode={args.mode} max_edge={args.max_edge}",
          flush=True)

    t_start = time.time()
    state = {"done": 0}
    lock = threading.Lock()
    doc_lock = threading.Lock()

    def handle(p):
        t0 = time.time()
        with doc_lock:  # pymupdf pages are not thread-safe
            ratio = ink_ratio(doc, p - 1)
            png = render_page(doc, p - 1, args.max_edge)
        if ratio < args.blank_threshold:
            (pages_dir / f"p{p:04d}.md").write_text("*(blank page)*\n",
                                                    encoding="utf-8")
            with lock:
                state["done"] += 1
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"page": p, "secs": 0.0, "chars": 14,
                                         "rep": 1.0, "blank": True}) + "\n")
                print(f"  p{p:04d} blank page ({ratio*100:.3f}% ink), skipped",
                      flush=True)
            return
        if args.keep_png:
            (png_dir / f"p{p:04d}.png").write_bytes(png)
        try:
            text = ocr_image(args.host, args.model, png, prompt, args.num_ctx,
                             args.timeout, args.num_predict, args.repeat_penalty,
                             args.temperature)
        except Exception as exc:  # noqa: BLE001
            with lock:
                print(f"  p{p:04d} FAILED: {exc}", flush=True)
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"page": p, "error": str(exc)}) + "\n")
            return
        (pages_dir / f"p{p:04d}.md").write_text(text.strip() + "\n", encoding="utf-8")
        rep = repetition_ratio(text)
        flag = "  <-- LOOPED, recheck" if rep < 0.35 else ""
        dt = time.time() - t0
        with lock:
            state["done"] += 1
            done = state["done"]
            avg = (time.time() - t_start) / done
            eta = avg * (len(todo) - done)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"page": p, "secs": round(dt, 1), "chars": len(text),
                                     "rep": round(rep, 2)}) + "\n")
            print(f"  p{p:04d} {dt:5.1f}s {len(text):5d} chars | {done}/{len(todo)} "
                  f"avg {avg:.1f}s ETA {eta/60:.0f}m{flag}", flush=True)

    if args.workers <= 1:
        for p in todo:
            handle(p)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for fut in as_completed([pool.submit(handle, p) for p in todo]):
                fut.result()

    elapsed = (time.time() - t_start) / 60
    print(f"finished: {state['done']} pages in {elapsed:.1f} min", flush=True)


if __name__ == "__main__":
    main()
