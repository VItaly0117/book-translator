import sys

def pandoc_whisperer(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"❌ Ошибка чтения: {e}")
        return

    # 1. Убираем математические команды из \text{}, из-за которых парсер Pandoc падает
    replacements = {
        r"\text{\Gamma Y}": r"\Gamma Y",
        r"\text{\GammaY}": r"\Gamma Y",
        r"\text{\GammaV}": r"\Gamma V",
        r"\text{УЧ\Pi}": r"\text{УЧП}",
        r"\text{YH\Pi}": r"\text{УЧП}",
        r"\text{Y 4II}": r"\text{УЧП}",
        r"\text{YHII}": r"\text{УЧП}",
        r"\text{YUII}": r"\text{УЧП}",
        r"\text{Y\Pi\Pi}": r"\text{УЧП}",
        r"\text{Y\Pi}": r"\text{УЧП}",
        r"\text{Y\cdot\Pi}": r"\text{УЧП}",
        r"\text{Y \forall \Pi}": r"\text{УЧП}",
        r"(\forall \Pi \Pi)": r"(\text{УЧП})",
        r"(\forall \Pi)": r"(\text{УЧП})",
        r"(\forall \Psi)": r"(\text{НУ})",
        r"( H \forall )": r"(\text{НУ})"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # 2. Лечим точечные опечатки OCR (незакрытые скобки и двойные слеши), которые показал Pandoc
    text = text.replace(r"\ldots\},\ ", r"\ldots\}, ")
    text = text.replace(r"\ldots\},\n", r"\ldots\},\n")
    text = text.replace(r"\sqrt{\frac{\frac{2}{\pi}}{\frac{\sin \xi}{\xi}}", r"\sqrt{\frac{\frac{2}{\pi}}{\frac{\sin \xi}{\xi}}}")
    text = text.replace(r"e^{-\sqrt{\xi}/2\right)^2", r"e^{-\sqrt{\xi}/2}^2")
    text = text.replace(r"u_{x\,\text{v}}", r"u_{xx}")
    text = text.replace(r"u_{\text{vx}}", r"u_{xx}")
    text = text.replace(r"\int_0^\\infty", r"\int_0^\infty")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    print("✅ Скрытые ошибки парсера Pandoc устранены! Можно собирать PDF.")

if __name__ == "__main__":
    filepath = input("📄 Введите путь к .md файлу: ").strip() if len(sys.argv) < 2 else sys.argv[1]
    if filepath:
        pandoc_whisperer(filepath)