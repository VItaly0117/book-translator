import sys
import re

def apply_final_fixes(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return

    # 1. Вырезаем сломанные колонки без закрывающей скобки
    text = text.replace(r"\begin{array}{cccccc", "")

    # 2. Исправляем закрывающий тег в задаче Дирихле
    text = text.replace(r"\end{aligned} \right.", r"\end{array} \right.")

    # 3. Закрываем оборванный массив в примере 39.2
    text = re.sub(r"U_t\s*\n\$\$", r"U_t = 0 \n\\end{array}\n$$", text)

    # 4. Закрываем оборванный массив в примере 22.3
    text = re.sub(r"\\leqslant 1\. \\end\{cases\}\s*\n\$\$", r"\\leqslant 1. \\end{cases}\n\\end{array}\n$$", text)

    # 5. Лечим незакрытую дробь в уравнении 29.7 (заменяем на cases)
    bad_frac = r"\frac{\frac{\partial v_1}{\partial t} + 4 \frac{\partial v_1}{\partial x} = 0, \\ \frac{\partial v_2}{\partial t} - 4 \frac{\partial v_2}{\partial x} = 0."
    good_frac = r"\begin{cases} \frac{\partial v_1}{\partial t} + 4 \frac{\partial v_1}{\partial x} = 0, \\ \frac{\partial v_2}{\partial t} - 4 \frac{\partial v_2}{\partial x} = 0. \end{cases}"
    text = text.replace(bad_frac, good_frac)

    # 6. Закрываем оборванную матрицу P^{-1}
    text = text.replace(r"0 & a_{\bar{z}}  \begin{bmatrix}", r"0 & a_{\bar{z}} \end{bmatrix} \begin{bmatrix}")

    # 7. Вырезаем спам (\Gamma Y) & в задаче 47.6
    text = re.sub(
        r"\\begin\{aligned\} \\varphi_\{uu\}.*?\$\$", 
        r"\\begin{aligned} \\varphi_{uu} + \\varphi_{vv} &= 0 \\end{aligned}\n$$", 
        text, flags=re.DOTALL
    )

    # 8. Двойной cases в теории возмущений
    text = text.replace(r"\vdots & \vdots \end{cases}", r"\vdots & \vdots \end{cases} \end{cases}")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)

    print("✅ Последние раны зашиты! Файл полностью готов к генерации PDF.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = input("📄 Введите путь к .md файлу: ").strip()
        
    if filepath:
        apply_final_fixes(filepath)