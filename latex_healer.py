import re
import sys

def heal_latex(md_text):
    stats = {
        "arrays_cols_fixed": 0,
        "deprecated_fixed": 0,
        "brackets_fixed": 0,
        "unclosed_envs_fixed": 0
    }

    # 1. Умное закрытие незакрытых окружений (array, cases, split, bmatrix и т.д.)
    def balance_envs(match):
        block = match.group(0)
        envs = ['array', 'cases', 'split', 'aligned', 'matrix', 'pmatrix', 'bmatrix', 'vmatrix', 'Vmatrix']
        stack = []
        
        # Ищем все теги begin и end
        tags = re.finditer(r"\\(begin|end)\{(" + "|".join(envs) + r")\}", block)
        for tag in tags:
            action = tag.group(1)
            env = tag.group(2)
            if action == "begin":
                stack.append(env)
            elif action == "end":
                if stack and stack[-1] == env:
                    stack.pop()
                elif env in stack:
                    while stack and stack[-1] != env:
                        stack.pop()
                    if stack:
                        stack.pop()
        
        if stack:
            # Если после прохода остались незакрытые теги — закрываем их!
            stats["unclosed_envs_fixed"] += 1
            closing_tags = "\n" + "\n".join([f"\\end{{{env}}}" for env in reversed(stack)]) + "\n"
            if block.endswith("$$"):
                return block[:-2] + closing_tags + "$$"
            elif block.endswith("\\]"):
                return block[:-2] + closing_tags + "\\]"
        return block

    # Применяем балансировку ко всем формулам в тексте
    md_text = re.sub(r"\$\$.*?\$\$", balance_envs, md_text, flags=re.DOTALL)
    md_text = re.sub(r"\\\[.*?\\\]", balance_envs, md_text, flags=re.DOTALL)

    # 2. Ремонт колонок array (чтобы избежать ошибки Extra alignment tab)
    def fix_array_cols(match):
        stats["arrays_cols_fixed"] += 1
        return r"\begin{array}{llllllllll}"

    md_text = re.sub(r"\\begin\{array\}\{[lcr|]+\}", fix_array_cols, md_text)
    md_text = re.sub(r"\\begin\{array\}\{l{6,}[^\}]*\}?", fix_array_cols, md_text)

    # 3. Безопасная замена устаревших команд (без re.sub, чтобы не было ошибки \m)
    old_text = md_text
    md_text = md_text.replace(r"{\rm ", r"\mathrm{")
    md_text = md_text.replace(r"\rm ", r"\mathrm{ ")
    md_text = md_text.replace(r"{\bf ", r"\mathbf{")
    md_text = md_text.replace(r"\bf ", r"\mathbf{ ")
    md_text = md_text.replace(r"{\it ", r"\mathit{")
    md_text = md_text.replace(r"\it ", r"\mathit{ ")
    if old_text != md_text:
        stats["deprecated_fixed"] += 1

    # 4. Удаление лишних скобок (популярные OCR галлюцинации)
    old_text = md_text
    md_text = md_text.replace(r"}}}", r"}}")
    md_text = md_text.replace(r"\right)^2}", r"\right)^2")
    if old_text != md_text:
        stats["brackets_fixed"] += 1

    return md_text, stats

def main():
    print("="*60)
    print("🏥 LaTeX Healer — умный хирург для Markdown")
    print("="*60)
    
    file_path = ""
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
        
    print(f"\n📖 Читаю: {file_path}")
    print("🔧 Применяю исцеление...")
    
    healed_text, stats = heal_latex(md_text)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(healed_text)
        
    print("\n✅ Готово! Файл перезаписан. Статистика операций:")
    print(f"  - Незакрытых блоков (автоматически добавлено \\end{{...}}): {stats['unclosed_envs_fixed']}")
    print(f"  - Поломанных таблиц array исправлено: {stats['arrays_cols_fixed']}")
    print(f"  - Устаревших тегов заменено: {'Да' if stats['deprecated_fixed'] else 'Нет'}")
    print(f"  - Лишних скобок удалено: {'Да' if stats['brackets_fixed'] else 'Нет'}")

if __name__ == "__main__":
    main()