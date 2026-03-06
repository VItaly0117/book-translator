# 📚 PDF Book Translator (EN → UK)

Automated pipeline for translating mathematical/scientific PDF textbooks from English to Ukrainian, **preserving all LaTeX formulas and embedded images** using the DeepL API.

## ✨ Features

- **AI-powered OCR** via [marker-pdf](https://github.com/VikParuchuri/marker) (handles scanned PDFs, extracts LaTeX)
- **Formula protection** — all `$$...$$` and `$...$` LaTeX is masked before translation and restored after
- **Image link protection** — Markdown image references are preserved intact
- **DeepL API** translation with automatic text chunking for large documents
- **Intermediate files** saved at each stage for easy debugging
- **39 unit tests** — full coverage of masking, unmasking, chunking, and translation logic

## 🗂️ Project Structure

```
.
├── book_translator.py      # Main pipeline script
├── test_translator.py      # pytest test suite (39 tests)
├── requirements.txt        # Python dependencies
├── .env.template           # Environment variables template
├── input/                  # Put your PDF here (git-ignored)
├── output/                 # Translated Markdown output (git-ignored)
└── images/                 # Extracted images (git-ignored)
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
python3 book_translator.py --pdf "input/your_book.pdf" --parser marker

# Test with only 20 pages first:
python3 book_translator.py --pdf "input/your_book.pdf" --parser marker --max-pages 20

# Translate a text-based PDF (fast, no AI needed):
python3 book_translator.py --pdf "input/your_book.pdf"

# Use a pre-converted Markdown file (skip PDF parsing):
python3 book_translator.py --md "input/your_book.md"

# Prevent Mac from sleeping during long runs:
caffeinate -i python3 book_translator.py --pdf "input/your_book.pdf" --parser marker
```

## 🔧 CLI Options

| Option | Description |
|--------|-------------|
| `--pdf PATH` | Source PDF file |
| `--md PATH` | Pre-parsed Markdown (skips PDF stage) |
| `--parser` | `auto` / `pymupdf4llm` / `marker` |
| `--max-pages N` | Process only first N pages (for testing) |
| `--lang CODE` | DeepL target language (default: `UK`) |
| `--output PATH` | Output file path |

## 🔄 Pipeline Stages

```
PDF ──[marker OCR]──► raw.md ──[masking]──► masked.md ──[DeepL]──► translated_masked.md ──[unmasking]──► _uk.md
```

1. **Parse** — marker-pdf converts PDF pages to Markdown with LaTeX
2. **Mask** — LaTeX formulas and image links replaced with `MATHBLKXXXXX` / `MATHINLXXXXX` / `IMGTOKENXXXXX`
3. **Translate** — DeepL translates only the plain text (formulas untouched)
4. **Unmask** — Placeholders restored to original LaTeX and image links

## 🧪 Running Tests

```bash
pytest test_translator.py -v
# 39 passed ✅
```

## ⚠️ First Run Note

On the first run with `--parser marker`, the AI models (~3 GB) will be downloaded automatically to `~/.cache/datalab/`. Subsequent runs use the cached models and are much faster.

## 📋 Requirements

- Python 3.10+
- DeepL API key (free tier: 500k chars/month)
- ~4 GB disk space for AI models (marker-pdf)
