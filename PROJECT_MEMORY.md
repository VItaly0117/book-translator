# Project Memory

Last updated: 2026-07-21

## Purpose

This repo is a working pipeline for translating and repairing a mathematical physics textbook
(Farlow, "Partial Differential Equations for Scientists and Engineers") into Ukrainian while
preserving LaTeX math, Markdown images, and PDF output.

The project is no longer just a raw translator. Current work is mostly manual repair,
PDF rebuilding, and optional illustration replacement (Nanobanana workflow).

## Current Book State

- Latest structural baseline (per its own handoff note): `Output_Final/full_book_v34_complete_structure/`
  - `farlou_full_book_v34_complete_structure.md` / `.pdf`
  - `HANDOFF_V34_COMPLETE_STRUCTURE.md` documents how it was built and what's still wrong with it.
  - `report.md` has the build report.
  - Lectures 1-47 present, no gaps/duplicates, PDF builds strict (242 pages).
  - Explicitly **not** final: residual Russian text in lectures 20-35, raw `\begin{array}` blocks,
    formulas/tables need visual review.
- `Output_Final/full_book_v33_restored_20_39/` is the direct predecessor of v34 (kept as a donor/reference).
- `Output_Final/full_book_v32_round5_with_images/` and `_round6_with_images/` are earlier full-book
  attempts, kept for comparison.
- `Output_Final/manual_help_pass_24_final_tail/` through `manual_help_pass_32_*`: a long chain of
  per-pass and per-page-range QA checkpoints (`check_pXXX_YYY`, `_round2/3/4/5`, `_worker`, `_review_all`,
  `_with_images`, etc.). These accumulated over many editing sessions and are **not individually
  documented** — nothing in the repo currently states which of these are safe to delete vs. still
  needed as reference. Treat this whole family as a candidate for pruning/archiving, but don't delete
  without checking with the project owner first (see "Suggested Next Decision" below).
- `Output_Final/reference_keep/`: earlier v24/v25 donor material, TOC/structure analysis notes, and
  `PROJECT_MEMORY_v24.md` (an older, now-superseded memory file — kept for history).
- `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/`: an older page-range chunk workflow
  (`chunk_manifest.tsv` + 8 `.md` chunks, `p000-049` through `p350-370`). Superseded by the full-book
  workflow above but still referenced by `CANONICAL_REPAIR_WORKFLOW.md`.
- `Output_Final/images/`: extracted book illustrations used by the PDF/EPUB build.
- Loose files directly under `Output_Final/` (`current_working_v24_my_fix_numbered_uk.md`,
  `current_working_v25_my_fix_numbered_uk.md` + a stray `.bak43` backup, two `.epub` exports, and a
  couple of `_p200-249_raw`/`_uk` fragments) are older working copies, not the current baseline.

## Canonical / Source Of Truth

As of this update, the most current, best-documented baseline is:

`Output_Final/full_book_v34_complete_structure/farlou_full_book_v34_complete_structure.md`

Continue work from there unless you have a specific reason to fall back to an older pass (e.g. to
recover text that v34 dropped — check `reference_keep/` and the v32/v33 directories first).

## What Was Intentionally Removed In v24

According to notes carried over from `reference_keep/PROJECT_MEMORY_v24.md`, v24 intentionally removed:

- crosswords
- formula handbook / formula tables at the end
- `Джерела`
- name index
- subject index
- final `Зміст`
- small OCR-noise images that broke layout or added no educational value

The final publishing page was added back in v24. This should still hold true for v34 since v34 was
built on top of the v24/v25 lineage, but it hasn't been re-verified.

## Review Priorities (carried over, not re-verified against v34)

- Residual Russian text in lectures 20-35 (explicitly flagged in the v34 handoff as the top remaining item).
- Raw `\begin{array}` blocks that may render poorly.
- Fourier/Laplace formulas and transform tables.
- Lecture 31: Laplacian coordinate formulas (partially repaired in v34, worth re-checking).
- Stray tiny OCR-noise images near formulas.

## Build / Tooling

- Main script: `book_translator.py`
- Review rebuild script: `rebuild_manual_review.py`
- Force compile helper: `force_compile.py` (had a broken `clean_project()` referencing an undefined
  `GARBAGE_SCRIPTS` list — removed; the script now only does the force-compile step).
- Image workspace scripts:
  - `prepare_nanobanana_assets.py`
  - `apply_nanobanana_results.py`
- PDF chunking helpers: `split_pdf_ranges.py`, `split_middle_200_299.py`
- Sequential scan runners: `run_middle_scan_sequential.py` / `.sh`
- Tests: `test_translator.py`
- Dependencies: `requirements.txt`

Useful commands:

```bash
python3 -m pytest
python3 rebuild_manual_review.py --help
python3 rebuild_manual_review.py --pass-name manual_help_pass_25_some_name farlou_rebuild_chunked_v6_p000-049.md
```

Main interactive pipeline:

```bash
python3 book_translator.py
```

## Image / Nanobanana State

- `nanobanana_workspace/README.md` says 177 textbook illustrations were prepared for redesign.
- Present: `nanobanana_workspace/manifests/`, `nanobanana_workspace/prompts/` (per-image prompt files).
- Not present in current checkout: `nanobanana_workspace/input_images/`, `nanobanana_workspace/processed_images/`.

Apply redesigned images with:

```bash
python3 apply_nanobanana_results.py --processed-dir nanobanana_workspace/processed_images --target-images-dir Output_Final/images
```

This requires both directories to exist first.

## Repo Hygiene (2026-07-21 cleanup)

- `tmp/pdf_build/` (LaTeX build scratch, regenerated by `book_translator.py` at `TEMP_PDF_BUILD_DIR`)
  and `tmp/tex_probe/` were tracked in git by mistake — dozens of `.aux`/`.log`/`.tex` files with no
  source value. Untracked and deleted; now gitignored.
- `cache.db` (the SQLite translation cache) was tracked despite being in `.gitignore` — the ignore rule
  didn't apply retroactively. Untracked (kept on disk; regenerated by the script).
- `tmp/restored_v25_uk.md` is real translated content, not a build artifact — left in place and tracked.
- `force_compile.py`'s `clean_project()` referenced an undefined `GARBAGE_SCRIPTS` list and would have
  raised `NameError` on every run. Removed the dead function.
- Not touched: the large `Output_Final/manual_help_pass_*` accumulation (~150MB+ across dozens of
  QA-checkpoint directories) and the stray `.bak`/`.bak43` files inside `Output_Final/`. These may hold
  real review history — pruning them needs a decision from the project owner, not an automated guess.

## Risks / Things To Confirm Before Next Work

- Do not read or print `.env`; it likely contains Azure secrets.
- `README.md` is Windows-oriented (the interactive script assumes a Windows `venv` layout), while this
  environment is Linux/macOS-like. Prefer `python3` and the local available `pandoc`/`xelatex`.
- Per `HANDOFF_V34_COMPLETE_STRUCTURE.md`: do not run a broad automatic Azure translation pass over the
  full book — a past full residual pass damaged math/raw-LaTeX blocks. Work one lecture at a time, back
  up before each edit, mask math/images before translation, and visually inspect rendered pages after
  rebuilding.

## Suggested Next Decision

Ask the user which mode to continue with:

1. Continue lecture-by-lecture cleanup of `full_book_v34_complete_structure` (residual Russian text,
   `\begin{array}` normalization, formula/table review) — this is the actively recommended next step
   per the v34 handoff notes.
2. Decide whether to prune/archive the `manual_help_pass_24` through `_32` checkpoint directories in
   `Output_Final/` to shrink repo size, and if so, which ones are safe to drop.
3. Resume the Nanobanana image replacement workflow.
