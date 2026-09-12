#!/usr/bin/env bash
# Poll the OCR run until it finishes (or stalls), then merge the pages into one markdown file.
set -u
cd /d/Book
PY=.venv-ocr/Scripts/python.exe
LOG=ocr_out_run.log
STALL_MIN=20      # log untouched this long => the run is stuck or dead
MAX_TICKS=340     # ~11h at 120s per tick

n=0
while [ $n -lt $MAX_TICKS ]; do
  if grep -q "^finished:" "$LOG" 2>/dev/null; then
    echo "STATUS: run reported finished (watched $((n * 2)) min)"
    break
  fi
  age=$(( ($(date +%s) - $(stat -c %Y "$LOG" 2>/dev/null || echo 0)) / 60 ))
  if [ "$age" -ge "$STALL_MIN" ]; then
    echo "STATUS: log has not moved for ${age} min - run stalled or died"
    break
  fi
  if [ $((n % 15)) -eq 0 ]; then
    echo "-- tick $n: $(ls ocr_out/pages 2>/dev/null | wc -l)/428 pages, log age ${age}m"
    tail -1 "$LOG"
  fi
  sleep 120
  n=$((n + 1))
done

echo "=== pages on disk: $(ls ocr_out/pages 2>/dev/null | wc -l) / 428 ==="
tail -3 "$LOG"
echo "=== slowest / looped pages from the log ==="
$PY - <<'PYEOF'
import json, pathlib
rows = []
for line in pathlib.Path("ocr_out/ocr_log.jsonl").read_text(encoding="utf-8").splitlines():
    try:
        rows.append(json.loads(line))
    except Exception:
        pass
ok = [r for r in rows if "secs" in r]
errs = [r for r in rows if "error" in r]
looped = sorted({r["page"] for r in ok if r.get("rep", 1) < 0.35})
if ok:
    secs = [r["secs"] for r in ok]
    print(f"pages logged: {len(ok)}  avg {sum(secs)/len(secs):.1f}s  max {max(secs):.1f}s")
print(f"looped pages ({len(looped)}): {looped}")
print(f"errors ({len(errs)}): {sorted({r['page'] for r in errs})}")
PYEOF
echo "=== merging ==="
$PY ocr/merge_pages.py --out-dir ocr_out --dest ocr_out/book_full_en.md
echo "=== final size ==="
wc -c ocr_out/book_full_en.md
