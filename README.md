# 📚 PDF Book Translator (RU → UK)

Automated pipeline for translating mathematical/scientific PDF textbooks from Russian to Ukrainian, **preserving all LaTeX formulas, embedded images, and book layout** using the DeepL API.

## ✨ Features

- **AI-powered OCR** via [marker-pdf](https://github.com/VikParuchuri/marker) (handles scanned PDFs, extracts LaTeX)
- **OpenCV Image Enhancement** — automatically processes extracted math/graphics to remove dark backgrounds and fix scanned artefacts.
- **Robust OCR Artefact Cleanup** — cleans up marker-pdf Markdown output (formats equations, repairs broken sentences, inline formulas, and tabular data).
- **Formula & Page Number protection** — all `$$...$$` and `$...$` LaTeX, as well as page numbers, are masked before translation and restored after.
- **Image link protection** — Markdown image references are preserved intact.
- **Parallel DeepL API Translation** — fast threaded translation of text chunks.
- **Local SQLite Caching** — preserves translation progress directly to `cache.db` to survive disconnects and save API usage.
- **Multi-Format Export** — automatically exports translated Markdown into `.epub` and `.pdf` formats using `pandoc`.
- **Dynamic Run Directories** — isolates every run into a unique timestamped folder for clean output artifact tracking.
- **69 unit/integration tests** — full coverage of masking, unmasking, chunking, caching, translation, image processing, and formatting logic.

## 🗂️ Project Structure

```
.
├── book_translator.py      # Main pipeline script
├── test_translator.py      # pytest test suite (69 tests)
├── requirements.txt        # Python dependencies
├── .env.template           # Environment variables template
├── book_style.css          # Styling used for EPUB/PDF export
├── input/                  # Put your PDF here (git-ignored)
└── output/                 # Dinamically generated timestamped folders (e.g. 2026-03-07_15-30-00_Saturday)
```

## ⚙️ Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USER/book-translator.git
cd book-translator

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API key
cp .env.template .env
# Edit .env and add your DeepL API key
```

## 🚀 Usage

```bash
# Translate a scanned PDF (AI OCR via marker-pdf):
python3 book_translator.py --pdf "input/your_book.pdf"

# Test with only 20 pages first:
python3 book_translator.py --pdf "input/your_book.pdf" --max-pages 20

# Use a pre-parsed Markdown file (skip PDF parsing/OCR stage):
python3 book_translator.py --md "input/your_book.md"

# Интерактивное меню (new!):
# Просто запустите скрипт без флагов для вызова удобного текстового меню:
python3 book_translator.py

# Prevent Mac from sleeping during long runs:
caffeinate -i python3 book_translator.py --pdf "input/your_book.pdf" --parser marker
```

## 🔧 CLI Options

| Option | Description |
|--------|-------------|
| `--pdf PATH` | Source PDF file |
| `--md PATH` | Pre-parsed Markdown (skips PDF stage) |
| `--max-pages N` | Process only first N pages (for testing) |
| `--lang CODE` | DeepL target language (default: `UK`) |
| `--output PATH` | Output `.md` file path |

## 🔄 Pipeline Stages

```
PDF ──[marker OCR & OpenCV]──► raw.md ──[masking]──► masked.md ──[DeepL]──► translated_masked.md ──[unmasking & formatting cleanup]──► _uk.md ──[pandoc]──► .epub / .pdf
```

1. **Parse & Enhance** — marker-pdf converts Russian PDF pages to Markdown with LaTeX, and OpenCV cleans extracted charts/images.
2. **Mask** — LaTeX formulas, image links, and page numbers replaced with secure tokens.
3. **Translate** — DeepL translates only the plain text in parallel (utilizes SQLite caching).
4. **Unmask** — Placeholders restored to original LaTeX and image links, page numbers converted to page breaks.
5. **Format Cleanup** — Regex formatting fixes OCR gluing issues, inline formula artefacts, and table breaks.
6. **Export** — Pandoc converts the Markdown into professionally styled `.epub` and `.pdf` files inside a dedicated timestamped run directory.

## 🧪 Running Tests

```bash
pytest test_translator.py -v
# 69 passed ✅
```

## ⚠️ First Run Note

On the first run, `marker-pdf` AI models (~3 GB) will be downloaded automatically to `~/.cache/datalab/`. Subsequent runs use the cached models and are much faster.

Pandoc EPUB export works out of the box, but PDF export may require a valid XeLaTeX/PDFLaTeX installation on your system.

## 🛠 Особенности установки на Windows

1. **Версия Python**: Категорически **НЕЛЬЗЯ** использовать Python из MSYS2 или Microsoft Store. Скачайте официальный установщик (`.exe`) с [python.org](https://www.python.org/downloads/) и обязательно поставьте галочку "Add Python to PATH" при установке.
2. **Активация venv в PowerShell**: Если при команде `.\.venv\Scripts\activate` возникает ошибка о запрете выполнения сценариев, откройте PowerShell от имени Администратора и введите:
   ```powershell
   Set-ExecutionPolicy Unrestricted -Scope CurrentUser
   ```
3. **Генерация PDF (Pandoc & MiKTeX)**: Для успешного экспорта Markdown в PDF с кириллицей на Windows необходимо вручную скачать и установить:
   - [Pandoc](https://pandoc.org/installing.html) (убедитесь, что он добавлен в PATH).
   - [MiKTeX](https://miktex.org/download) (предоставляет движок XeLaTeX). Без него конвертация упадет с ошибкой "exitcode 43". Во время установки MiKTeX разрешите ему "скачивать отсутствующие пакеты "на лету" (install missing packages on-the-fly -> Yes)".
4. **Интерактивный запуск**: Для удобства вы можете просто запустить `python book_translator.py` без флагов, чтобы вызвать удобное интерактивное меню прямо в консоли.

## 📋 Requirements

- Python 3.10+
- DeepL API key (free tier: 500k chars/month)
- ~4 GB disk space for AI models (marker-pdf)
