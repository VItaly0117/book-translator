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
# Просто запустите скрипт без флагов для вызова удобного текстового диалогового меню:
python3 book_translator.py
# Скрипт спросит:
# 👉 1. Введите путь к PDF или MD файлу (например, input/book.pdf):
# 👉 2. Сколько страниц перевести? (Оставьте пустым, чтобы перевести ВСЮ книгу):

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

## 🛠 Подробный гайд по установке для Windows (с нуля)

Если вы настраиваете скрипт на свежей системе Windows (например, по удаленке у друга), выполните эти шаги строго по порядку:

**Шаг 1: Установка базовых программ (Обязательно)**
1. **[Python (от 3.10 до 3.12)](https://www.python.org/downloads/)** — скачайте официальный `.exe` установщик. При установке **ОБЯЗАТЕЛЬНО** поставьте галочку внизу окна: **`Add Python to PATH`**! Без этого ничего не заработает.
2. **[Git для Windows](https://git-scm.com/download/win)** — скачайте и установите со стандартными настройками (нужен для клонирования кода).
3. **[Pandoc](https://pandoc.org/installing.html)** — скачайте `.msi` установщик и установите. Он отвечает за финальную генерацию документов и сам добавит себя в системный PATH.
4. **[MiKTeX](https://miktex.org/download)** — это LaTeX-движок, без которого не создастся PDF с формулами (будет ошибка exitcode 43). 
   - **Важно:** при установке MiKTeX вас спросят *"Install missing packages on-the-fly"*. Обязательно выберите **"Yes"** (чтобы он сам докачивал нужные шрифты и пакеты в процессе сборки).

*(После установки всех этих программ желательно **перезагрузить компьютер**, чтобы обновились системные пути PATH)*

**Шаг 2: Загрузка проекта**
Откройте **PowerShell** или встроенный терминал и выполните:
```powershell
git clone https://github.com/VItaly0117/book-translator.git
cd book-translator
```

**Шаг 3: Настройка окружения и зависимостей**
В терминале внутри папки проекта последовательно введите:
```powershell
# Если PowerShell ругается на скрипты, сначала выполните эту команду (от имени Администратора):
# Set-ExecutionPolicy Unrestricted -Scope CurrentUser

python -m venv venv
.\venv\Scripts\Activate.ps1
# (В начале строки должно появиться зеленое слово (venv))

pip install -r requirements.txt
# (Установка займет время, так как скачиваются тяжелые Torch и OpenCV)
```

**Шаг 4: Подготовка к запуску**
1. В папке с проектом создайте файл `.env`.
2. Впишите внутрь него ключ: `DEEPL_API_KEY=ваш_ключ_здесь`
3. Создайте папку `input` и положите туда вашу книгу (pdf или md).

**Шаг 5: Запуск**
```powershell
python book_translator.py
```
Скрипт откроет красивое интерактивное текстовое меню и сам спросит, какой файл переводить и сколько страниц!

## 📋 Requirements

- Python 3.10+
- DeepL API key (free tier: 500k chars/month)
- ~4 GB disk space for AI models (marker-pdf)
