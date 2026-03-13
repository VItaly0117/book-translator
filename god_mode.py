import re
import sys

def god_mode_heal(text):
    # 1. АМПУТАЦИЯ ХВОСТА КНИГИ (Убивает ошибку "Missing $ inserted" в таблицах)
    # Отрезаем справочные таблицы и приложения в конце книги, которые сломала нейросеть
    cut_phrases = [
        "ТАБЛИЦА F. Преобразование Лапласа",
        "Таблица F. Преобразование Лапласа",
        "### Приложение 2",
        "ПРЕДСТАВЛЕНИЕ ЛАПЛАСИАНА"
    ]
    for phrase in cut_phrases:
        if phrase in text:
            text = text.split(phrase)[0]
            print(f"✂️ Отрезан сломанный хвост начиная с: '{phrase}'")
            break

    # 2. УБИЙЦА ОШИБКИ "Extra alignment tab"
    # Заменяем строгий array на всеядный aligned
    text = re.sub(r'\\begin\{array\}\{[^\}]*\}', r'\\begin{aligned}', text)
    text = text.replace(r'\end{array}', r'\end{aligned}')

    # 3. АВТО-БАЛАНСИРОВЩИК (Убивает ошибку "ended by \end{equation*}")
    # Дописывает недостающие закрывающие теги прямо перед $$
    def balance_math_block(match):
        block = match.group(0)
        
        cases_diff = block.count(r'\begin{cases}') - block.count(r'\end{cases}')
        aligned_diff = block.count(r'\begin{aligned}') - block.count(r'\end{aligned}')
        
        closures = ""
        for _ in range(max(0, cases_diff)): closures += r'\end{cases}' + '\n'
        for _ in range(max(0, aligned_diff)): closures += r'\end{aligned}' + '\n'
            
        left_braces = len(re.findall(r'\\left\\{', block))
        right_dots = len(re.findall(r'\\right\.', block)) + len(re.findall(r'\\right\\}', block))
        for _ in range(max(0, left_braces - right_dots)): closures += r'\right.' + '\n'

        if closures:
            block = block[:-2] + "\n" + closures + "$$"
            
        return block

    text = re.sub(r'\$\$.*?\$\$', balance_math_block, text, flags=re.DOTALL)

    # 4. ХИРУРГИЧЕСКАЯ ЗАЧИСТКА OCR МУСОРА
    text = text.replace("}}}", "}}")
    text = text.replace(r"\right)^2}", r"\right)^2")
    text = text.replace(r"{\rm ", r"\mathrm{")
    text = text.replace(r"\rm ", r"\mathrm{ ")
    text = text.replace(r"{\bf ", r"\mathbf{")
    text = text.replace(r"\bf ", r"\mathbf{ ")
    text = text.replace(r"{\it ", r"\mathit{")
    text = text.replace(r"\it ", r"\mathit{ ")
    
    return text

def main():
    print("="*60)
    print("🔥 God Mode Healer — Ультимативный фиксер для Pandoc")
    print("="*60)
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("📄 Введите путь к .md файлу: ").strip()
        
    if not file_path:
        return
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            md_text = f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return
        
    healed_text = god_mode_heal(md_text)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(healed_text)
        
    print("✅ Файл очищен! Поломанные таблицы ампутированы, матрицы переведены в aligned.")

if __name__ == "__main__":
    main()