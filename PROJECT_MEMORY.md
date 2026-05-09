# Project Memory

Last updated: 2026-04-27

## Purpose

This repo is a working pipeline for translating and repairing a mathematical physics textbook into Ukrainian while preserving LaTeX math, Markdown images, and PDF output.

The project is no longer just a raw translator. Current work is mostly manual repair, PDF rebuilding, and optional illustration replacement.

## Current Book State

- Input PDF currently present: `input/test_v2_1.pdf`.
- Important: after updating git, the current checkout contains later passes `v26`, `v27`, `v28`, and `v29`.
- Latest known chunk-based final pass in the current checkout:
  - `Output_Final/manual_help_pass_29_final/`
  - Contains 8 Markdown chunks from pages `000-049` through `350-370`.
  - Added in commit `2198533` (`Add PDF range splitter for rescanning book chunks`).
  - No `report.md`, `manifest.txt`, generated PDF, or EPUB is present in that directory.
  - It differs from `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/` in chunks `000-049`, `100-149`, `150-199`, and `200-249`.
- Latest known full-book pass:
  - commit `1caf7cb` (`Tune PDF layout for cleaner pagination`)
  - `Output_Final/manual_help_pass_28_user_fix_ukr/farlou_full_book_user_fix_v28.md`
  - 6922 lines, based on `Output_Final/reference_keep/current_working_v24_my_fix.md`
  - build mode was `partial`, not clean strict compilation
  - tracked report: `Output_Final/manual_help_pass_28_user_fix_ukr/report.md`
  - tracked strict error summary: `Output_Final/manual_help_pass_28_user_fix_ukr/strict_error.txt`
  - generated PDF path in the old worktree was `Output_Final/manual_help_pass_28_user_fix_ukr/farlou_full_book_user_fix_v28.pdf`, but that PDF is not present in the current checkout.
- Main translated/canonical chunk set:
  - `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/`
  - Contains 8 Markdown chunks from pages `000-049` through `350-370`.
  - `chunk_manifest.tsv` marks all chunks as `OK`, but the referenced chunk PDFs are not present in the current checkout.
- Visible later full-book working Markdown in current checkout:
  - `Output_Final/reference_keep/current_working_v24.md`
  - Same line count as `Output_Final/manual_help_pass_24_final_tail/farlou_full_book_final_tail_v24.md`.
- Reference material for restoring removed sections:
  - `Output_Final/reference_keep/reference_etalon_final.md`
  - `Output_Final/reference_keep/reference_raw_uk.md`

## Canonical / Source Of Truth Notes

There are several source-of-truth candidates because the work advanced over time:

- `Output_Final/CANONICAL_REPAIR_WORKFLOW.md` says manual fixes should be applied to:
  - `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/*.md`
- `Output_Final/manual_help_pass_24_final_tail/MANUAL_REVIEW_AND_RESTORE.md` says current hand-work should use:
  - `Output_Final/reference_keep/current_working_v24.md`
- current checkout contains a later full-book user-fix pass:
  - `Output_Final/manual_help_pass_28_user_fix_ukr/farlou_full_book_user_fix_v28.md` at commit `1caf7cb`
- current checkout also contains the newest chunk final:
  - `Output_Final/manual_help_pass_29_final/*.md` at commit `2198533`

Before editing content, decide which branch of workflow is active:

1. Chunk repair workflow: edit canonical page chunks, rebuild selected review PDFs.
2. Full-book v24 workflow: edit/copy `current_working_v24.md`, rebuild the whole PDF.
3. Full-book v28 workflow: continue from `manual_help_pass_28_user_fix_ukr/farlou_full_book_user_fix_v28.md`.
4. Chunk v29 workflow: continue from `manual_help_pass_29_final/*.md`.

## What Was Intentionally Removed In v24

According to `MANUAL_REVIEW_AND_RESTORE.md`, v24 intentionally removed:

- crosswords
- formula handbook / formula tables at the end
- `Джерела`
- name index
- subject index
- final `Зміст`
- small OCR-noise images that broke layout or added no educational value

The final publishing page was added back in v24.

## Review Priorities From Existing Notes

- Pages around `47-80`: Fourier/Laplace formulas and transform tables.
- Page around `70`: table 12.1 / Fourier transforms.
- Pages around `77-80`: check for stray tiny images near formulas.
- Pages around `63-66`: images should not overflow right or sit inside math blocks.
- Pages around `110-129`: characteristics, canonical form, tables, and figures.
- Pages around `101-130`: OCR noise, lecture transitions, raw TeX.
- Page around `140`: Bessel/angular/radial equations.
- Last pages of v24: decide whether to restore `Джерела` or indexes.

## Build / Tooling

- Main script: `book_translator.py`
- Review rebuild script: `rebuild_manual_review.py`
- Force compile helper: `force_compile.py`
- Image workspace scripts:
  - `prepare_nanobanana_assets.py`
  - `apply_nanobanana_results.py`
- Tests: `test_translator.py`
- Dependencies: `requirements.txt`

Detected locally:

- `pandoc` is available.
- `xelatex` is available.
- bundled Tectonic is available through the LaTeX Tectonic plugin, but the current project code builds PDFs through Pandoc/XeLaTeX rather than checking in `.tex` files.

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
- Present now:
  - `nanobanana_workspace/manifests/images_manifest.json`
  - `nanobanana_workspace/manifests/images_manifest.csv`
  - `nanobanana_workspace/prompts/master_prompt.txt`
  - many per-image prompt files
- Not present in current checkout:
  - `nanobanana_workspace/input_images/`
  - `nanobanana_workspace/processed_images/`
  - `Output_Final/images/`

Apply redesigned images with:

```bash
python3 apply_nanobanana_results.py --processed-dir nanobanana_workspace/processed_images --target-images-dir Output_Final/images
```

This requires both directories to exist first.

## Risks / Things To Confirm Before Next Work

- Current checkout has Markdown outputs and EPUBs for numbered `v24`/`v25`, but no generated final PDFs except `input/test_v2_1.pdf`.
- Current checkout has `v26`, `v27`, `v28`, and `v29` Markdown/directories after the git update.
- Some manifests reference PDFs or absolute paths from older Codex worktrees that may no longer exist locally.
- Do not read or print `.env`; it likely contains Azure secrets.
- `README.md` is Windows-oriented, while this environment is macOS-like. Prefer `python3` and the local available `pandoc`/`xelatex`.
- `force_compile.py` references `GARBAGE_SCRIPTS`, which is not defined in the visible top section; inspect/fix before using it for cleanup.

## Suggested Next Decision

Ask the user which mode to continue with:

1. Treat `Output_Final/manual_help_pass_29_final/` as the newest chunk-level content base.
2. Rebuild/merge `v29` chunks into a review PDF and inspect the result.
3. Treat `Output_Final/manual_help_pass_28_user_fix_ukr/farlou_full_book_user_fix_v28.md` as the newest single full-book Markdown base.
4. Decide whether to continue chunk workflow (`v29`) or regenerate a single full-book file from the latest chunks.
5. Rebuild the `v28` PDF only if deliberately continuing from the full-book workflow.
6. Continue manual content review using the priority page ranges.
7. Restore removed end matter from `reference_keep`.
8. Resume the Nanobanana image replacement workflow.
