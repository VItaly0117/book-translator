import re
import sys

def cure_ocr_hallucinations(md_text):
    # 1. Зачистка повторяющихся строк (когда нейросеть пишет одно и то же 100 раз подряд)
    lines = md_text.split('\n')
    cleaned_lines = []
    for line in lines:
        line_stripped = line.strip()
        # Если строка совпадает с двумя предыдущими - это глюк, удаляем
        if line_stripped and len(cleaned_lines) >= 2:
            if line_stripped == cleaned_lines[-1].strip() and line_stripped == cleaned_lines[-2].strip():
                continue
        cleaned_lines.append(line)
    md_text = '\n'.join(cleaned_lines)

    # 2. Зачистка бесконечных колонок в таблицах (&&&&&&&&&&&&)
    md_text = re.sub(r'(&\s*){5,}', r'& ', md_text)

    # 3. Зачистка сломанных \begin{array}{cccccccc...}
    md_text = re.sub(r'\\begin\{array\}\{[a-zA-Z\|]{10,}\}', r'\\begin{array}{lllll}', md_text)
    
    # 4. Зачистка "заевшей пластинки" на уровне фраз (когда циклится одно словосочетание)
    # Если любой кусок текста (от 5 до 150 символов) повторяется 4 и более раз подряд - оставляем только один
    md_text = re.sub(r'(.{5,150}?)\1{4,}', r'\1', md_text)
    
    # 5. Зачистка бесконечных пустых переносов строк \\ \\ \\ \\
    md_text = re.sub(r'(\\\\\s*){4,}', r'\\\\ ', md_text)

    return md_text

def main():
    print("="*60)
    print("🔪 OCR Hallucination Killer — Уничтожитель галлюцинаций ИИ")
    print("="*60)
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("📄 Введите путь к .md файлу: ").strip()
        
    if not file_path:
        print("❌ Ошибка: Путь не указан.")
        return
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            md_text = f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return
        
    print(f"\n📖 Лечим файл: {file_path}")
    
    healed_text = cure_ocr_hallucinations(md_text)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(healed_text)
        
    print("✅ Готово! Все зацикленные строки, амперсанды и сломанные массивы вырезаны.")

if __name__ == "__main__":
    main()