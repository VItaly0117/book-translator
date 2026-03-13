import sys
import re

def nuke_the_bugs(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return

    # 1. Убиваем гигантскую галлюцинацию (сотни амперсандов)
    text = re.sub(
        r'\\begin\{aligned\}\s*\\varphi_\{uu\}.*?\$\$', 
        lambda m: r'\varphi_{uu} + \varphi_{vv} = 0' + '\n$$', 
        text, 
        flags=re.DOTALL
    )

    # 2. Убиваем незакрытую формулу из последней задачи 47 лекции
    text = re.sub(
        r'\\begin\{aligned\}\s*\(\\text\{Y\}.*?\$\$', 
        lambda m: r'\Delta \phi = 0' + '\n$$', 
        text, 
        flags=re.DOTALL
    )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    print("✅ Смертельные галлюцинации вырезаны! Можно собирать PDF.")

if __name__ == "__main__":
    filepath = input("📄 Введите путь к .md файлу: ").strip() if len(sys.argv) < 2 else sys.argv[1]
    if filepath:
        nuke_the_bugs(filepath)