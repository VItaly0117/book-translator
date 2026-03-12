# 📚 PDF Book Translator (RU → UK)

Автоматизований конвеєр (пайплайн) для перекладу математичних та наукових PDF-підручників з російської на українську мову, **зі збереженням усіх LaTeX-формул, вбудованих зображень та верстки книги**, використовуючи DeepL API.

## ✨ Особливості (Features)

- **ШІ-розпізнавання тексту (OCR)** через [marker-pdf](https://github.com/VikParuchuri/marker) (обробляє відскановані PDF, витягує LaTeX).
- **Покращення зображень через OpenCV** — автоматично обробляє витягнуту математику та графіку, щоб видалити темний фон і виправити артефакти сканування (ч/б бінаризація за Оцу).
- **Надійне очищення артефактів OCR** — виправляє згенерований marker-pdf Markdown-код (форматує рівняння, виправляє розірвані речення, інлайн-формули та табличні дані).
- **Захист формул та номерів сторінок** — усі LaTeX-вирази `$$...$$` та `$...$`, а також номери сторінок, маскуються перед перекладом і відновлюються після нього.
- **Захист посилань на зображення** — посилання на зображення у форматі Markdown залишаються недоторканими.
- **Паралельний переклад через DeepL API** — швидкий багатопотоковий переклад текстових блоків.
- **Локальне кешування в SQLite** — зберігає прогрес перекладу безпосередньо у `cache.db`, щоб пережити розриви зв'язку та зекономити ліміти API.
- **Експорт у мультиформати** — автоматично експортує перекладений Markdown у формати `.epub` та `.pdf` за допомогою `pandoc`.
- **Динамічні робочі папки** — ізолює результати кожного запуску в унікальну папку з відміткою часу для відстеження файлів без плутанини.
- **Режим пересборки** — можливість перегенерувати PDF/EPUB з готового Markdown без повторного перекладу.

## 🗂️ Структура проєкту

```text
.
├── book_translator.py      # Головний скрипт пайплайну
├── make_pdf.py            # Скрипт для генерації PDF/EPUB з готового MD
├── test_translator.py     # pytest тести
├── requirements.txt       # Залежності Python
├── .env.template          # Шаблон змінних середовища
├── book_style.css         # Стилі для експорту в EPUB/PDF
├── input/                 # Покладіть ваш PDF сюди (папка ігнорується git)
└── output/                # Динамічно згенеровані папки з датою і часом
```

## ⚙️ Початкове налаштування (Setup)

```bash
# 1. Клонувати репозиторій
git clone https://github.com/VItaly0117/book-translator.git
cd book-translator

# 2. Створити віртуальне середовище
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows

# 3. Встановити залежності
pip install -r requirements.txt

# 4. Налаштувати API ключ
cp .env.template .env
# Відкрийте .env файл і додайте ваш DeepL API ключ
```

## 🚀 Використання (Usage)

```bash
# Інтерактивне меню:
python3 book_translator.py

# Або через CLI аргументи:
python3 book_translator.py --pdf "input/your_book.pdf"
python3 book_translator.py --md "input/your_book.md"
python3 book_translator.py --pdf "input/your_book.pdf" --max-pages 20

# Режим пересборки (перегенерувати PDF/EPUB з готового MD без перекладу):
python3 book_translator.py --md "output/book_uk.md" --rebuild-only

# Для генерації PDF/EPUB з готового файлу:
python3 make_pdf.py "output/book_uk.md"
```

## 🔧 CLI Опції

| Опція | Опис |
|--------|-------------|
| `--pdf PATH` | Шлях до вхідного PDF файлу |
| `--md PATH` | Шлях до готового Markdown файлу |
| `--max-pages N` | Обробити лише перші N сторінок |
| `--lang CODE` | Цільова мова DeepL (за замовчуванням: `UK`) |
| `--rebuild-only` | Режим пересборки (без перекладу) |
| `--output PATH` | Шлях для вихідного `.md` файлу |

## 🔄 Етапи конвеєра (Pipeline Stages)

```text
PDF ──[marker OCR]──► raw.md ──[маскування]──► masked.md ──[DeepL]──► translated_masked.md ──[розмаскування та очищення]──► _uk.md ──[pandoc]──► .epub / .pdf
```

1. **Parse & Enhance** — marker-pdf конвертує PDF у Markdown з LaTeX, OpenCV очищує зображення.
2. **Mask** — LaTeX-формули та посилання на зображення замінюються на токени.
3. **Translate** — DeepL перекладає текст (з кешуванням SQLite).
4. **Unmask** — Токени відновлюються в оригінальний вигляд.
5. **Format Cleanup** — Regex виправляє артефакти OCR.
6. **Export** — Pandoc генерує `.epub` та `.pdf`.

## 🧪 Запуск тестів

```bash
pytest test_translator.py -v
```

## ⚠️ Примітка щодо першого запуску

Під час першого запуску ШІ-моделі `marker-pdf` (близько 3 ГБ) будуть завантажені автоматично у `~/.cache/datalab/`.

Експорт у PDF вимагає XeLaTeX (TeX Live або MiKTeX).

## 🛠 Встановлення для Windows

1. **[Python 3.10-3.12](https://www.python.org/downloads/)** — обов'язково поставте галочку `Add Python to PATH`
2. **[Git](https://git-scm.com/download/win)**
3. **[Pandoc](https://pandoc.org/installing.html)**
4. **[MiKTeX](https://miktex.org/download)** — виберіть "Yes" для "Install missing packages on-the-fly"

```powershell
git clone https://github.com/VItaly0117/book-translator.git
cd book-translator
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Створіть .env з DEEPL_API_KEY=ваш_ключ
python book_translator.py
```

## 📋 Вимоги (Requirements)

- Python 3.10+
- DeepL API ключ (free tier: 500k символів/місяць)
- ~4 ГБ дискового простору для моделей marker-pdf
- Pandoc + XeLaTeX для експорту в PDF
