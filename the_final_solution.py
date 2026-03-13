import sys
import re

def nuclear_fix(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"❌ Помилка читання: {e}")
        return

    # --- 1. ТЕХНІЧНА ПІДГОТОВКА (Захист коду) ---
    code_blocks = []
    def save_code(m):
        code_blocks.append(m.group(0))
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"
    text = re.sub(r'```.*?```', save_code, text, flags=re.DOTALL)

    # --- 2. ВИПРАВЛЕННЯ ТИПОВИХ ПОМИЛОК OCR (Фізика/Математика) ---
    replacements = {
        r'u_i = u_{xx}': r'u_t = u_{xx}',
        r'u_1 = u_{xx}': r'u_t = u_{xx}',
        r'u_1 = ': r'u_t = ',
        r'u_{vx}': r'u_{xx}',
        r'u_{\lambda x}': r'u_{xx}',
        r'u_{00}': r'u_{\theta\theta}',
        r'u_{\lambda \lambda}': r'u_{xx}',
        r'сферичних воль': r'сферичних хвиль',
        r'\\int\\\\limits': r'\\int\\limits',
        r'\\int\\limits_0^\\\\infty': r'\\int\\limits_0^\\infty',
        r'\\infty': r'\infty',
        r'\textbf{I}': 't',
        r'u_t \equiv \frac{\partial u}{\partial t}, u_x \equiv \frac{\partial u}{\partial x}, u_{xx} \equiv \frac{\partial^2 u}{\partial x^2}': 
        r'u_t \equiv \frac{\partial u}{\partial t}, \quad u_x \equiv \frac{\partial u}{\partial x}, \quad u_{xx} \equiv \frac{\partial^2 u}{\partial x^2}'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # --- 3. ОЧИСТКА ТА БАЛАНСУВАННЯ БЛОКІВ $$ ... $$ ---
    def clean_math_block(match):
        content = match.group(1).strip()
        
        # ВИДАЛЯЄМО внутрішні $ (головна причина помилки KaTeX)
        content = content.replace('$', '')
        
        # ВИДАЛЯЄМО порожні рядки (XeLaTeX їх ненавидить)
        content = re.sub(r'\n\s*\n+', r'\n', content)
        
        # ВИПРАВЛЯЄМО таблиці cases/aligned (має бути лише ОДИН '&' на рядок)
        new_lines = []
        for line in content.split('\n'):
            if '&' in line:
                # Якщо в рядку більше одного &, лишаємо лише перший
                parts = line.split('&')
                if len(parts) > 2:
                    line = f"{parts[0]} & {' '.join(parts[1:])}"
            new_lines.append(line)
        content = '\n'.join(new_lines)

        # АВТОДОПИСУВАННЯ закриваючих тегів
        for env in ['aligned', 'cases', 'bmatrix', 'pmatrix', 'array']:
            opens = content.count(f'\\begin{{{env}}}')
            closes = content.count(f'\\end{{{env}}}')
            if opens > closes:
                content += (f'\n\\end{{{env}}}' * (opens - closes))
        
        # АВТОДОПИСУВАННЯ \right.
        lefts = content.count(r'\left')
        rights = content.count(r'\right')
        if lefts > rights:
            content += (r' \right.' * (lefts - rights))
            
        # Видалення висячих слэшів \\ в кінці блоку
        content = re.sub(r'\\+\s*$', '', content)
        
        return f"\n\n$$\n{content}\n$$\n\n"

    text = re.sub(r'\$\$(.*?)\$\$', clean_math_block, text, flags=re.DOTALL)

    # --- 4. ОЧИСТКА ІНЛАЙН-МАТЕМАТИКИ $ ... $ ---
    def clean_inline(match):
        content = match.group(1).strip()
        # Прибираємо переноси рядків всередині $...$
        content = content.replace('\n', ' ')
        # Прибираємо зайві пробіли
        content = re.sub(r'\s+', ' ', content)
        return f"${content}$"

    text = re.sub(r'(?<!\$)\$(?!\$)((?:(?!\n\n)[^\$])+?)(?<!\$)\$(?!\$)', clean_inline, text)

    # --- 5. ФІНАЛЬНА ЗАЧИСТКА ---
    text = re.sub(r'\$\$\s*\$\$', '', text) # Видаляємо порожні блоки
    text = re.sub(r'\n{3,}', '\n\n', text) # Прибираємо зайві пусті рядки в тексті

    # Відновлення коду
    for i, block in enumerate(code_blocks):
        text = text.replace(f"__CODE_BLOCK_{i}__", block)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
        
    print("🚀 NUCLEAR OPTION APPLIED!")
    print("✅ Вкладені $ видалено.")
    print("✅ OCR-помилки (u_i -> u_t) виправлено.")
    print("✅ Всі дужки \left та блоки \begin закрито автоматично.")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else input("Введіть шлях до файлу: ")
    nuclear_fix(path)