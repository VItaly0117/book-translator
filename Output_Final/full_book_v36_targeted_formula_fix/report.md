# V36 targeted formula/layout repair report

Date: 2026-05-10

## Base

- Started from `Output_Final/full_book_v35_polish/`.
- New working pass: `Output_Final/full_book_v36_targeted_formula_fix/`.
- Final Markdown: `farlou_full_book_v36_targeted_formula_fix.md`.
- Final PDF: `farlou_full_book_v36_targeted_formula_fix.pdf`.

## Main fixes

- Repaired screenshot-reported raw LaTeX/formula failures in lectures 3, 7, 12, 23, 29, 31, 35, and 44.
- Rebuilt the broken Lecture 7 tables for eigenvalues and coefficients `a_n`.
- Rebuilt the broken Lecture 30 Bessel-root table as a proper numeric table.
- Repaired overlong or raw formulas: `(3.1)`, `(3.3)-(3.5)`, `(12.9)`, `(23.5)`, `(29.3)-(29.9)`, Laplacian derivation, `(44.2)`, and the catenary formula.
- Added explicit book part pages:
  - Part 1: Introduction
  - Part 2: Diffusion problems
  - Part 3: Hyperbolic problems
  - Part 4: Elliptic problems
  - Part 5: Numerical and approximate methods
- Added `\markright{...}` for part pages so the running header matches the current structural page.
- Removed obvious Russian/garbled leftovers from the checked slices: `воздействие`, `сложить отклики`, `Таблица`, `Корни`, `гармонических`, `см.`, `имеют вид`, `значит`, `ШАГ`, etc.
- Replaced the repeated mistranslation `похідних похідних` with `частинних похідних`.
- Removed standalone `?` lines and replaced `??` condition labels with `РЧП`, `ГУ`, or `ПУ`.

## Verification

- Final PDF page count: 247 pages.
- Previous v35 page count: 244 pages.
- Lecture count in extracted PDF text: 47 lectures.
- Part count in extracted PDF text: 5 parts.
- Strict marker scan over Markdown/PDF text: no hits for raw `\begin{...}`, raw `\frac`, `MATHBLK`, `MATHINL`, `IMGTOKEN`, `KOLIVNYA`, `PNP`, `TAC`, `PHC`, `??`, standalone `?`, Russian-specific letters `ыэёъ`, or the targeted Russian phrase list.
- Visual spot checks rendered with Poppler:
  - Part pages: 3, 9, 92, 163, 208.
  - Reported formula/table pages: 16-18, 42-43, 74, 125, 150, 157, 169, 237, 239.

## Notes

- Raw strict LaTeX still reports an old `Missing } inserted` location and then succeeds through the project markdown-preparation path. The final delivered PDF is generated successfully by that prepared build path.
- The old `farlou_full_book_v36_targeted_formula_fix_safe.pdf` is a fallback artifact from an earlier failed pass and is not the final target PDF.
