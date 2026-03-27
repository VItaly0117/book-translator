# Canonical Repair Workflow

## Canonical source of truth

All manual content fixes must be applied only in:

- `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/*.md`

For the current front section, the working files are:

- `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/farlou_rebuild_chunked_v6_p000-049.md`
- `Output_Final/farlou_rebuild_chunked_v6_pdf_chunks/farlou_rebuild_chunked_v6_p050-099.md`

## Review output

User review must be done only against:

- `Output_Final/manual_help_pass_01/farlou_manual_help_pass_01_p000-099_merged.pdf`

If this merged PDF is updated, the next review file should be created as a new pass directory:

- `Output_Final/manual_help_pass_02/...`

## Non-canonical files

These files and directories are not the source of truth and must not be used for new edits:

- `Output_Final/fixed_chunks/*`
- `Output_Final/*_FIXED.md`
- `Output_Final/*_PREV.md`
- `Output_Final/farlou_chunked_v1_pdf_chunks/*`
- `Output_Final/farlou_chunked_v2_pdf_chunks/*`
- `Output_Final/farlou_chunked_v3_pdf_chunks/*`
- `Output_Final/farlou_chunked_v4_pdf_chunks/*`
- `Output_Final/farlou_rebuild_chunked_v1*`
- `Output_Final/farlou_rebuild_chunked_v2*`
- `Output_Final/farlou_rebuild_chunked_v3*`
- `Output_Final/farlou_rebuild_chunked_v4*`
- `Output_Final/farlou_rebuild_chunked_v5*`

They may contain useful history, but they are not to be edited further.

## Repair loop

1. User reports a defect from the merged review PDF.
2. Defect report format:
   - page number in merged PDF
   - 1-3 lines of text immediately before the broken formula/block
   - optionally 1 line after it
3. Fix the corresponding canonical chunk `.md`.
4. Rebuild only the affected chunk PDF in strict mode.
5. Regenerate the merged review PDF from the updated canonical chunk PDFs.

## Important note

Some formulas were previously fixed in Markdown but re-broken by the PDF preparation pipeline.
When that happens, the correct fix is:

- repair the canonical `.md`, and
- if needed, adjust the PDF preparation logic so it stops rewriting already-valid math.
