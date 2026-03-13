import sys
import re

def final_fix(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return

    # 1. ФИКС: Убираем знаки $ внутри блоков $$...$$ (Самая частая ошибка в логе)
    # Ищем блоки $$ ... $$, а затем внутри них удаляем все одиночные $
    def remove_nested_dollars(match):
        block = match.group(0)
        # Оставляем только внешние $$, внутренние одиночные $ удаляем
        content = block[2:-2]
        content = content.replace('$', '')
        return f"$${content}$$"
    
    text = re.sub(r'\$\$.*?\$\$', remove_nested_dollars, text, flags=re.DOTALL)

    # 2. ФИКС: Ошибка "Extra alignment tab" в таблицах (из вашего лога)
    # Когда в окружении cases слишком много &
    text = text.replace(r'& \text{Преобразование} & \text{Лапласа}', r'& \text{Преобразование Лапласа}')

    # 3. ФИКС: Двойные слэши в конце строк внутри $$ (unexpected control sequence \\)
    # XeLaTeX не любит \\ перед закрывающим $$
    text = re.sub(r'\\\\\s*\$\$', r'\n$$', text)
    
    # 4. ФИКС: Незакрытые aligned и cases
    def close_environments(match):
        content = match.group(0)
        for env in ['aligned', 'cases', 'bmatrix', 'cases']:
            opens = content.count(f'\\begin{{{env}}}')
            closes = content.count(f'\\end{{{env}}}')
            if opens > closes:
                content = content.replace('$$', f'\\end{{{env}}}\n$$')
        return content

    text = re.sub(r'\$\$.*?\$\$', close_environments, text, flags=re.DOTALL)

    # 5. ФИКС: Ошибка с \int\\limits (двойной слэш перед limits)
    text = text.replace(r'\\limits', r'\limits')

    # 6. ФИКС: Инлайн-формулы с запятыми, которые ломают парсинг
    # Пример: ", $0 < t < \infty$ $(M = 1, a = 0)$" -> выносим запятую
    text = re.sub(r'\$\s*,\s*', r', $', text)

    # 7. ФИКС: Убираем мусорные пустые блоки \begin{aligned} \end{aligned}
    text = re.sub(r'\\begin\{aligned\}\s*\\end\{aligned\}', '', text)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
        
    print("✅ ФИНАЛЬНЫЙ ФИКС ПРИМЕНЕН! Вложенные $ удалены, таблицы исправлены.")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else input("Введите путь к MD: ")
    final_fix(path)