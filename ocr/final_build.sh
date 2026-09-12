#!/usr/bin/env bash
# Rebuild every deliverable from the repaired pages: merge, map figures, audit, PDFs.
set -u
cd /d/Book
PY=.venv-ocr/Scripts/python.exe
PDF="book-pdf/partial_differential_equations_for_scientists_and_engineers_reprintnbsped.pdf"

echo "################ MERGE ################"
$PY ocr/merge_pages.py --out-dir ocr_out --dest ocr_out/book_full_en.md

echo ""
echo "################ FIGURES ################"
$PY ocr/map_figures.py --verify-captions

echo ""
echo "################ AUDITS ################"
$PY ocr/qa_report.py --out-dir ocr_out --dest ocr_out/QA_REPORT.md
echo ""
$PY ocr/verify_fidelity.py --pdf "$PDF" --pages-dir ocr_out/pages

echo ""
echo "################ PDF WITH FIGURES ################"
rm -rf ocr_out/pdf_chunks_fig
$PY ocr/build_pdf.py --md ocr_out/book_with_figures.md \
   --dest ocr_out/book_with_figures.pdf --work-dir ocr_out/pdf_chunks_fig \
   --pages-per-chunk 10

echo ""
echo "################ PDF TEXT ONLY ################"
rm -rf ocr_out/pdf_chunks
$PY ocr/build_pdf.py --md ocr_out/book_full_en.md \
   --dest ocr_out/book_full_en.pdf --work-dir ocr_out/pdf_chunks \
   --pages-per-chunk 10

echo ""
ls -l ocr_out/book_with_figures.pdf ocr_out/book_full_en.pdf
echo "FINAL_BUILD_DONE"
