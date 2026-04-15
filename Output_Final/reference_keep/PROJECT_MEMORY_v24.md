# Project Memory v24

This repository is a book-repair workspace. Keep the scope narrow and avoid rescanning the whole tree unless something structural changes.

## Source of Truth

- `Output_Final/reference_keep/current_working_v24_my_fix_numbered.md` is the current assembled numbered master file.
- `Output_Final/reference_keep/reference_etalon_final.md` is the reference for visual verification and image/file naming.
- `Output_Final/images/` contains the real image assets used by the book.
- The numbered master now includes a manual `# ЗМІСТ` section near the front and has lecture 3 normalized to a single top-level heading.

## Clean Lecture Extracts

These lecture files are the current working inserts/recovery blocks:

- `Output_Final/reference_keep/lecture_15_from_raw4.md`
- `Output_Final/reference_keep/lecture_16_from_raw4.md`
- `Output_Final/reference_keep/lecture_17_from_raw4.md`
- `Output_Final/reference_keep/lecture_20_from_raw4.md`
- `Output_Final/reference_keep/lecture_23_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_25_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_26_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_28_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_29_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_30_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_31_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_32_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_33_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_34_from_raw4.md`
- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_35_from_raw4.md`

## Image Recovery Rule

For the raw extract lectures above, broken image links used the `chunkNN__page_...jpeg` pattern. The repair rule is:

- `chunk03__page_X` -> `images/_page_{X+100}_...jpeg`
- `chunk04__page_X` -> `images/_page_{X+150}_...jpeg`
- `chunk05__page_X` -> `images/_page_{X+200}_...jpeg`
- `chunk06__page_X` -> `images/_page_{X+250}_...jpeg`

Do not invent image names. Only use files that exist under `Output_Final/images/`.

## Compile Fix Rule

- Replace `\begin{case}` with `\begin{cases}`.
- Replace `\end{case}` with `\end{cases}`.

## Formula Recovery Notes

- In the recovered lectures, OCR sometimes turns `u_t` into `u_1`, `u_{tt}` into `u_{II}`, and `u_{xx}` into `u_{x+}`. Fix those only when the surrounding PDE context makes the intended derivative unambiguous.
- In Lecture 16, the telegraph-equation coefficient should be `\alpha^2`, not `\alpha^3`.
- In Lecture 17, the D'Alembert formula uses `\frac{1}{2c}` and the upper integral limit is `x+ct`.
- In Lecture 20, the bounded-string boundary-value problems use `u_t(x,0)` for the initial velocity, not `u_1(x,0)`.
- In Lecture 29, `u_1` is a real variable name in the PDE system and should not be rewritten automatically.

## Known Gaps

- `Output_Final/reference_keep/local_extract_pass2_pack/lecture_28_candidate_fragment_from_raw4.md` is archived only; the usable lecture 28 is `lecture_28_from_raw4.md`.
- Lecture 35 in the numbered master is kept in the safe truncated form ending before the contaminated donor block; the internal recovery note was removed from the main file.
- `tmp/pdfs/rk_r1/` was temporary Runge-Kutta workspace and has been removed from the project.

## Working Practice

- Prefer patching only the affected lecture block.
- Keep the numbering and insert order aligned with `LECTURE_MASTER_TOC_v24.md` and the assembled numbered master file.
- When in doubt, verify the exact image or page in `reference_etalon_final.md` before editing.
