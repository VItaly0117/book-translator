#!/usr/bin/env bash
# Wait for the OCR run to finish, then merge, audit, and build the review PDF.
set -u
cd /d/Book
PY=.venv-ocr/Scripts/python.exe
LOG=ocr_out_run.log
STALL_MIN=25       # log untouched this long => the run is stuck or dead
MAX_TICKS=400      # ~13h at 120s per tick

n=0
while [ $n -lt $MAX_TICKS ]; do
  if grep -q "^finished:" "$LOG" 2>/dev/null; then
    echo "STATUS: OCR run reported finished after $((n * 2)) min of watching"
    break
  fi
  age=$(( ($(date +%s) - $(stat -c %Y "$LOG" 2>/dev/null || echo 0)) / 60 ))
  if [ "$age" -ge "$STALL_MIN" ]; then
    echo "STATUS: log has not moved for ${age} min - run stalled or died"
    break
  fi
  if [ $((n % 30)) -eq 0 ]; then
    echo "-- tick $n: $(ls ocr_out/pages 2>/dev/null | wc -l)/428 pages"
    tail -1 "$LOG"
  fi
  sleep 120
  n=$((n + 1))
done

# let any concurrent watcher finish its own merge first
sleep 180

echo ""
echo "################ FINAL STATE ################"
echo "pages on disk: $(ls ocr_out/pages 2>/dev/null | wc -l) / 428"
tail -3 "$LOG"

echo ""
echo "################ MERGE ################"
$PY ocr/merge_pages.py --out-dir ocr_out --dest ocr_out/book_full_en.md

echo ""
echo "################ QA AUDIT ################"
$PY ocr/qa_report.py --out-dir ocr_out --dest ocr_out/QA_REPORT.md

echo ""
echo "################ FIGURE EXTRACTION ################"
$PY ocr/extract_figures.py \
    --pdf "book-pdf/partial_differential_equations_for_scientists_and_engineers_reprintnbsped.pdf" \
    --ocr-dir ocr_out/pages --out figures_out --debug-overlay 2>&1 | tail -25

echo ""
echo "################ REVIEW PDF ################"
if $PY ocr/build_pdf.py --md ocr_out/book_full_en.md \
      --dest ocr_out/book_full_en.pdf --work-dir ocr_out/pdf_chunks; then
  echo "PDF_STATUS: built"
else
  echo "PDF_STATUS: failed - markdown remains the deliverable"
fi

echo ""
echo "################ DELIVERABLES ################"
ls -l ocr_out/book_full_en.md ocr_out/book_full_en.pdf ocr_out/QA_REPORT.md 2>&1
echo "NIGHT_RUN_DONE"
