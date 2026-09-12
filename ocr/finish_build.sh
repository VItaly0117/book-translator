#!/usr/bin/env bash
# Wait for the page redo to end, then rebuild every text deliverable from scratch.
set -u
cd /d/Book
PY=.venv-ocr/Scripts/python.exe
PDF="book-pdf/partial_differential_equations_for_scientists_and_engineers_reprintnbsped.pdf"

n=0
while [ $n -lt 90 ]; do
  alive=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*redo_pages*' } | Measure-Object).Count" 2>/dev/null | tr -d '\r')
  [ "${alive:-0}" = "0" ] && { echo "redo finished"; break; }
  sleep 30
  n=$((n + 1))
done

echo ""
echo "################ MERGE ################"
$PY ocr/merge_pages.py --out-dir ocr_out --dest ocr_out/book_full_en.md

echo ""
echo "################ QA ################"
$PY ocr/qa_report.py --out-dir ocr_out --dest ocr_out/QA_REPORT.md

echo ""
echo "################ FIDELITY ################"
$PY ocr/verify_fidelity.py --pdf "$PDF" --pages-dir ocr_out/pages

echo ""
echo "################ PDF ################"
rm -rf ocr_out/pdf_chunks
$PY ocr/build_pdf.py --md ocr_out/book_full_en.md --dest ocr_out/book_full_en.pdf \
   --work-dir ocr_out/pdf_chunks --pages-per-chunk 10

echo ""
ls -l ocr_out/book_full_en.md ocr_out/book_full_en.pdf ocr_out/QA_REPORT.md
echo "FINISH_BUILD_DONE"
