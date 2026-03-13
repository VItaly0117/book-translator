import re

INPUT_FILE = "farlou_final_uk.md"
OUTPUT_FILE = "farlou_clean.md"


def clean_text(text):

    # удаляем мусорные символы
    text = text.replace("￼", "")
    text = text.replace("\ufeff", "")

    # нормализация переносов строк
    text = text.replace("\r\n", "\n")

    # удаление лишних пробелов
    text = re.sub(r"[ \t]+", " ", text)

    # удаляем пробелы в конце строк
    text = re.sub(r"[ \t]+\n", "\n", text)

    # убираем слишком много пустых строк
    text = re.sub(r"\n{3,}", "\n\n", text)

    # исправляем одиночные $
    text = re.sub(r'(?<!\$)\$(?!\$)', r'$$', text)

    # исправляем $$ блоки
    text = re.sub(r'\$\$\s*\n', '$$\n', text)
    text = re.sub(r'\n\s*\$\$', '\n$$', text)

    # исправляем broken LaTeX
    text = re.sub(r'\\\s+', r'\\', text)

    # исправляем индексы
    text = re.sub(r'_{2,}', '_', text)

    # исправляем степени
    text = re.sub(r'\^{2,}', '^', text)

    # удаляем странные markdown картинки
    text = re.sub(r'!\[\]\(.*?\)', '', text)

    # исправляем latex дроби
    text = re.sub(r'frac\s*{', r'\\frac{', text)

    # исправляем sqrt
    text = re.sub(r'sqrt\s*{', r'\\sqrt{', text)

    # исправляем частные производные
    text = text.replace("∂", r"\partial")

    # исправляем greek
    text = text.replace("α", r"\alpha")
    text = text.replace("β", r"\beta")
    text = text.replace("θ", r"\theta")
    text = text.replace("λ", r"\lambda")
    text = text.replace("π", r"\pi")

    return text


def balance_latex_blocks(text):

    lines = text.split("\n")
    fixed = []
    open_block = False

    for line in lines:

        if "$$" in line:

            count = line.count("$$")

            if count % 2 == 1:
                open_block = not open_block

        fixed.append(line)

    if open_block:
        fixed.append("$$")

    return "\n".join(fixed)


def main():

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        text = f.read()

    text = clean_text(text)
    text = balance_latex_blocks(text)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    print("✔ Файл очищен")
    print("✔ Сохранён как:", OUTPUT_FILE)


if __name__ == "__main__":
    main()