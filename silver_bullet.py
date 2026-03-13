import sys
import re

def silver_bullet(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return

    # 1. ГЛАВНЫЙ ФИКС: Убиваем пустые строки ВНУТРИ формул 
    # (XeLaTeX ненавидит \par внутри математического режима)
    def remove_blank_lines(match):
        content = match.group(0)
        # Заменяем двойные и тройные переносы строк на одинарные
        return re.sub(r'\n{2,}', '\n', content)
    
    text = re.sub(r'\$\$.*?\$\$', remove_blank_lines, text, flags=re.DOTALL)

    # 2. ИСПРАВЛЕНИЕ НЕЗАКРЫТЫХ \left\{
    # marker-pdf часто пишет \left\{ \begin{aligned} ... \end{aligned} без \right.
    def fix_left_brace(match):
        block = match.group(0)
        if r'\right.' not in block and r'\right\}' not in block:
            return block + r' \right.'
        return block
    
    text = re.sub(r'\\left\\\{\s*\\begin\{aligned\}.*?\\end\{aligned\}', fix_left_brace, text, flags=re.DOTALL)

    # 3. ИСПРАВЛЕНИЕ ВИСЯЩЕГО СЛЭША (eof error из логов)
    text = text.replace(r"\ldots\},\ ", r"\ldots\}, ")
    text = text.replace(r"\ldots\},\n", r"\ldots\},\n")
    text = re.sub(r'\\ldots\}\,\\', r'\\ldots\},', text)

    # 4. ЗАКРЫТИЕ ОБОРВАННОГО \begin{cases} В ТАБЛИЦЕ (из логов)
    text = re.sub(r'(\\mathcal\{L\}\^\{-1\}\[F\] = f\(t\) = )\\\\\s*\\mathcal\{L\}\^\{-1\}\[F\] = f\(t\) =.*?\$\$', 
                  r'\1\n\\end{cases}\n$$', text, flags=re.DOTALL)

    # 5. ИСПРАВЛЕНИЕ \ln\left= и \arg\left= (XeLaTeX падает от \left без закрывающей скобки)
    text = text.replace(r"\ln\left=", r"\ln=")
    text = text.replace(r"\arg\left=", r"\arg=")
    text = text.replace(r"\ln\left+", r"\ln+")
    text = text.replace(r"\arg\left+", r"\arg+")

    # 6. ЗАКРЫТИЕ ОБОРВАННОГО \begin{aligned} в задаче 47.1
    text = text.replace(r"1, & |x| \le 1. \end{cases}", r"1, & |x| \le 1. \end{cases} \end{aligned}")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
        
    print("✅ Silver Bullet применен! Пустые абзацы в формулах уничтожены, скобки закрыты.")

if __name__ == "__main__":
    filepath = input("📄 Введите путь к .md файлу: ").strip() if len(sys.argv) < 2 else sys.argv[1]
    if filepath:
        silver_bullet(filepath)