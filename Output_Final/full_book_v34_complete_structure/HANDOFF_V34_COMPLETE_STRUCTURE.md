# Handoff v34 Complete Structure

## Current Best Version

Use this directory as the current structural baseline:

`Output_Final/full_book_v34_complete_structure/`

Main files:

- `farlou_full_book_v34_complete_structure.md`
- `farlou_full_book_v34_complete_structure.pdf`
- `report.md`

This is the first pass where the book skeleton is restored as lectures 1-47 without missing lecture numbers.

## What Was Fixed

- Restored visible lecture numbering from 1 to 47.
- Fixed the earlier structural jump after lecture 19.
- Restored the missing middle lecture sequence 20-39 from the full numbered donor.
- Restored lecture 40 as a proper heading before lecture 41.
- Added forced page breaks before every lecture using raw LaTeX blocks:

```markdown
```{=latex}
\clearpage
```
```

- Kept the existing PDF header/footer system from `book_translator.py`:
  - top right: current lecture title;
  - bottom center: page number.
- Normalized several broken headings:
  - Lecture 20: `КОЛИВАННЯ ОБМЕЖЕНОЇ СТРУНИ (СТОЯЧІ ХВИЛІ)`
  - Lecture 23: `КЛАСИФІКАЦІЯ РІВНЯНЬ З ЧАСТИННИМИ ПОХІДНИМИ...`
  - Lecture 33: `ВНУТРІШНЯ ЗАДАЧА ДІРІХЛЕ ДЛЯ КОЛА`
  - Lecture 40: `АНАЛІТИЧНІ РОЗВ'ЯЗКИ ТА ЧИСЛОВІ РОЗВ'ЯЗКИ`
- Removed math from the lecture 15 heading (`$u_x$` -> `u_x`) so the running header can detect it cleanly.
- Repaired a visible raw-LaTeX layout issue in lecture 31 around the Laplacian coordinate formulas.

## Important Source Files Used

The strongest donor for full lecture numbering:

`Output_Final/reference_keep/current_working_v25_my_fix_numbered.md`

Useful Ukrainian-numbered donor:

`Output_Final/current_working_v25_my_fix_numbered_uk.md`

Earlier stable structural analysis:

`Output_Final/reference_keep/LECTURE_MASTER_TOC_v24.md`

Previous structural build used as base:

`Output_Final/full_book_v33_restored_20_39/farlou_full_book_v33_restored_20_39.md`

## Restoration Slices

### v33 Restoration

v33 was created to fix the broken 19 -> 42/43 jump.

The important donor slice was taken from:

`Output_Final/reference_keep/current_working_v25_my_fix_numbered.md`

Approximate donor lines:

- start: line 5532, lecture 20
- end: line 10866, just before lecture 40/41 boundary in the donor workflow

That donor slice covered lectures 20-39 and was merged between:

- front from the then-current repaired v32/v33 material through lecture 19;
- back from the cleaned later material containing lectures 40-47.

After this, v33 had the middle restored, but it still lacked clean early lecture numbering for 1, 2, 4, 8, 9, 10, 11.

### v34 Structure Completion

v34 started from:

`Output_Final/full_book_v33_restored_20_39/farlou_full_book_v33_restored_20_39.md`

The missing early lecture headings were recovered by comparing against:

`Output_Final/current_working_v25_my_fix_numbered_uk.md`

The key heading replacements in v34 were:

- `# ВСТУП...` -> `# Лекція 1. ...`
- `# ЗАДАЧІ ТИПУ ДИФУЗІЇ...` -> `# Лекція 2. ...`
- `# ВИВЕДЕННЯ РІВНЯННЯ ТЕПЛОПРОВІДНОСТІ` -> `# Лекція 4. ...`
- `# ПЕРЕТВОРЕННЯ СКЛАДНИХ РІВНЯНЬ...` -> `# Лекція 8. ...`
- `# РОЗВ'ЯЗАННЯ НЕОДНОРІДНИХ УЧП...` -> `# Лекція 9. ...`
- `# ІНТЕГРАЛЬНІ ПЕРЕТВОРЕННЯ...` -> `# Лекція 10. ...`
- `# РЯДИ І ПЕРЕТВОРЕННЯ ФУР'Є` -> `# Лекція 11. ...`

Then page breaks were inserted before every `# Лекція N...` heading.

## Verification Results

Current v34 verification:

- Markdown lecture headings: 47.
- Present lecture sequence: 1-47.
- Missing lecture numbers: none.
- Duplicate lecture numbers: none.
- Forced lecture page breaks: 47.
- PDF strict build: success.
- PDF pages: 242.
- Placeholder scan for `MATHBLK`, `MATHINL`, `IMGTOKEN`, `HIDE`, `PHC.`, `$$$`, `KOLIVNYA`: 0.

Verified lecture start pages from `pdftotext`:

1: 3
2: 8
3: 14
4: 21
5: 25
6: 32
7: 37
8: 45
9: 49
10: 56
11: 63
12: 68
13: 73
14: 82
15: 84
16: 90
17: 95
18: 101
19: 106
20: 108
21: 114
22: 116
23: 120
24: 127
25: 130
26: 135
27: 136
28: 137
29: 143
30: 150
31: 159
32: 166
33: 173
34: 179
35: 189
36: 196
37: 203
38: 208
39: 213
40: 217
41: 220
42: 223
43: 226
44: 231
45: 236
46: 237
47: 239

## Known Remaining Work

Do not treat v34 as final-for-teacher yet. It is the best structural baseline.

Remaining work:

- Clean residual Russian text, mostly in lectures 20-35.
- Normalize tables, especially where OCR/Markdown made raw arrays or awkward line breaks.
- Review formulas visually and mathematically.
- Inspect pages around:
  - lecture 20;
  - lecture 23;
  - lectures 25-35;
  - lecture 31 coordinate formulas;
  - Fourier/Laplace tables;
  - final numerical/variational method lectures.
- There are still compiled `\begin{array}` occurrences. They do not block PDF generation, but some may render poorly and should be normalized during visual review.

## Important Warning

Do not run a broad automatic Azure translation pass over the full book. A full residual pass previously started damaging math/raw-LaTeX blocks.

Safer workflow:

1. Work one lecture at a time.
2. Back up the Markdown before each lecture fix.
3. Mask math/images before translation if using Azure.
4. Rebuild PDF after each lecture or small group of lectures.
5. Render the affected pages with `pdftoppm` and inspect visually.

## Useful Commands

Strict rebuild:

```powershell
$env:Path = 'C:\Users\vital\AppData\Local\Pandoc;' + $env:Path
@'
from pathlib import Path
import book_translator as bt
root=Path('D:/CODEX')
out=root/'Output_Final'/'full_book_v34_complete_structure'
chunk_dir=root/'Output_Final'/'manual_help_pass_32_final'
images_dir=root/'Output_Final'/'images'
md_path=out/'farlou_full_book_v34_complete_structure.md'
md=md_path.read_text(encoding='utf-8')
prepared=bt._prepare_markdown_for_pdf(bt._remove_pdf_only_sections(md))
res_path=bt._build_resource_path(chunk_dir, images_dir)
pdf=bt._build_pdf_via_tex(
    md_text=prepared,
    output_stem='farlou_full_book_v34_complete_structure',
    output_dir=out,
    res_path=res_path,
    graphics_root_dir=images_dir.parent,
    allow_partial_output=False,
)
print(pdf)
'@ | .\.venv\Scripts\python.exe -X utf8 -
```

Lecture heading verification:

```powershell
$p='D:\CODEX\Output_Final\full_book_v34_complete_structure\farlou_full_book_v34_complete_structure.md'
$sel = Select-String -Path $p -Encoding UTF8 -Pattern '^#\s+Лекція\s+\d+'
$nums=@()
foreach($m in $sel){ if($m.Line -match '^#\s+Лекція\s+(\d+)'){ $nums += [int]$Matches[1] } }
'lecture_count=' + $sel.Count
'present=' + ($nums -join ',')
'missing=' + ((1..47 | Where-Object { $nums -notcontains $_ }) -join ',')
'duplicates=' + (($nums | Group-Object | Where-Object Count -gt 1 | ForEach-Object { $_.Name }) -join ',')
```

PDF page count:

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "from pypdf import PdfReader; p=r'D:\CODEX\Output_Final\full_book_v34_complete_structure\farlou_full_book_v34_complete_structure.pdf'; print(len(PdfReader(p).pages))"
```
