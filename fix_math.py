import re

def fix_pandoc_errors(file_path):
    print(f"Читаю файл: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # 1. Фікс критичної помилки з \mathrm (прибираємо екранування \$ та \_)
    text = text.replace(r'\$', '$')
    text = text.replace(r'\_', '_')

    # 2. Фікс висячих доларів з комами (часта помилка OCR: $, $ -> , )
    text = re.sub(r'\$,\s*\$', ', ', text)
    text = text.replace('$ , $', ', ')
    text = text.replace('$,', ',')

    # 3. Фікс переносів рядків перед закриваючим доларом (крашить парсер)
    text = re.sub(r'\n\s*\$', ' $', text)

    # 4. Фікс багаторядкових формул (Pandoc ненавидить \\ всередині одинарних $...$)
    # Примусово робимо системи рівнянь дисплейними (подвійні долари)
    text = re.sub(r'(?<!\$)\$\s*\\begin\{cases\}', r'$$ \\begin{cases}', text)
    text = re.sub(r'\\end\{cases\}\s*\$(?!\$)', r'\\end{cases} $$', text)
    text = re.sub(r'(?<!\$)\$\s*\\begin\{bmatrix\}', r'$$ \\begin{bmatrix}', text)
    text = re.sub(r'\\end\{bmatrix\}\s*\$(?!\$)', r'\\end{bmatrix} $$', text)

    # 5. Фікс випадкових # всередині або поруч з формулами
    text = re.sub(r'\$\s*###', '$\n###', text)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Готово! Усе сміття зачищено. Можна компілювати.")

# Твій шлях до файлу
file_to_fix = r"/Users/kalinicenkovitalijmikolajovic/Script_for_translate_book/output/2026-03-13_16-54-17_Friday/result.md"

fix_pandoc_errors(file_to_fix)