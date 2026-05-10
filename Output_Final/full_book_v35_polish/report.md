# v35 polish report

Дата среза: 2026-05-10

## База

- Рабочая версия: `Output_Final/full_book_v35_polish/farlou_full_book_v35_polish.md`
- PDF: `Output_Final/full_book_v35_polish/farlou_full_book_v35_polish.pdf`
- Текстовый слой PDF: `Output_Final/full_book_v35_polish/farlou_full_book_v35_polish.txt`
- Базовый ориентир: `Output_Final/full_book_v34_complete_structure/`
- Картинки берутся из: `Output_Final/images/`

## Что исправлено в v35

- Сохранён полный каркас из 47 лекций.
- Пересобран PDF: 244 страницы, то есть страниц не меньше, чем в v34.
- В `book_translator.py` уменьшены глобальные размеры изображений и увеличены отступы между float-объектами, формулами и текстом.
- Колонтитулы теперь получают `Лекція N. тема` для всех лекций 1-47, включая длинные и `texorpdfstring`-заголовки.
- Исправлены явные проблемы в лекциях 15-18 и рядом: сырой LaTeX на страницах 11, 96, 101, 109, 136 больше не виден.
- Убраны остаточные русские фрагменты из проверенных текстовых участков.
- Все найденные `\begin{array}` в v35 Markdown заменены на более устойчивые `aligned`/`cases`-конструкции.
- OCR-метки условий унифицированы: `РЧП`, `ГУ`, `ПУ` вместо `UBP/HV/HY/GU/NU`, `УЧП/НУ` и мусорных `???`.

## Проверки

- `pdfinfo`: 244 страницы.
- Markdown: 47 заголовков `# Лекція N.`.
- TeX после сборки: 47 `\markright{Лекція ...}`, пропусков по лекциям 1-47 нет.
- Markdown scan clean: `\begin{array}`, `\end{array}`, `MATHBLK`, `MATHINL`, `IMGTOKEN`, `HIDE`, `PHC.`, `KOLIVNYA`, `???` не найдены.
- PDF text scan clean: `[ыэёъ]`, `В лекции`, `где`, `можно`, `решение`, `уравнение`, `Дирихле`, `Ноймана`, `UBP/HV/HY/GU/NU`, `???` не найдены.
- Visual spotcheck: `Output_Final/full_book_v35_polish/rendered_spotcheck_final_after_arrays/v35_final_after_arrays_contact.png`.

## Резервные копии внутри pass

- `farlou_full_book_v35_polish.baseline_v34.pdf`
- `farlou_full_book_v35_polish.before_ru_cleanup.md`
- `farlou_full_book_v35_polish.before_ru_letters_cleanup.md`
- `farlou_full_book_v35_polish.before_array_cleanup.md`
- `farlou_full_book_v35_polish.before_label_cleanup.md`

## Важно для следующего прохода

- Сборка выполнялась штатным `_build_pdf_only_from_markdown`: raw strict pass падает на старых markdown-особенностях, prepared strict pass успешно собирает финальный PDF без safe/partial режима.
- Растровые подписи внутри старых изображений не переводились; если внутри картинки остался русский текст, это уже задача redraw/замены изображения.
- Следующий полезный этап: точечная сверка таблиц и формул с пользователем, особенно Fourier/Laplace, таблица 12.1, лекции 23-36 и хвостовые материалы.
