#!/usr/bin/env bash
# Build a complete review set at 06:30 from whatever the OCR run has finished by then,
# so there is something to look at at 07:00 even though the full run ends ~07:55.
# Writes to *_interim paths so it never collides with the final build.
set -u
cd /d/Book
PY=.venv-ocr/Scripts/python.exe
TARGET=1788924600     # 2026-09-09 06:30 local

while [ "$(date +%s)" -lt "$TARGET" ]; do
  remain=$(( (TARGET - $(date +%s)) / 60 ))
  if [ $((remain % 60)) -eq 0 ]; then
    echo "-- ${remain} min to interim build, $(ls ocr_out/pages 2>/dev/null | wc -l)/428 pages"
  fi
  sleep 300
done

echo "################ INTERIM BUILD $(date +%H:%M) ################"
echo "pages on disk: $(ls ocr_out/pages 2>/dev/null | wc -l) / 428"
tail -1 ocr_out_run.log

echo ""
echo "---- merge ----"
$PY ocr/merge_pages.py --out-dir ocr_out --dest ocr_out/book_interim.md

echo ""
echo "---- QA ----"
$PY ocr/qa_report.py --out-dir ocr_out --dest ocr_out/QA_REPORT_interim.md

echo ""
echo "---- figures ----"
$PY ocr/extract_figures.py \
    --pdf "book-pdf/partial_differential_equations_for_scientists_and_engineers_reprintnbsped.pdf" \
    --ocr-dir ocr_out/pages --out figures_interim --debug-overlay 2>&1 | tail -6

echo ""
echo "---- review PDF ----"
if $PY ocr/build_pdf.py --md ocr_out/book_interim.md \
      --dest ocr_out/book_interim.pdf --work-dir ocr_out/pdf_chunks_interim 2>&1 | tail -8; then
  echo "INTERIM_PDF: built"
else
  echo "INTERIM_PDF: failed"
fi

echo ""
ls -l ocr_out/book_interim.md ocr_out/book_interim.pdf ocr_out/QA_REPORT_interim.md 2>&1
echo "INTERIM_DONE"
