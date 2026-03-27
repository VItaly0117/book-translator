import os
import sys
import re
import shutil
from pathlib import Path
import pypandoc

def clean_project(base_dir: Path):
    print("🧹 Очистка проекта от старых скриптов-костылей...")
    deleted_count = 0
    for script_name in GARBAGE_SCRIPTS:
        script_path = base_dir / script_name
        if script_path.exists():
            try:
                script_path.unlink()
                print(f"  🗑️ Удален: {script_name}")
                deleted_count += 1
            except Exception as e:
                print(f"  ❌ Не удалось удалить {script_name}: {e}")
    if deleted_count == 0:
        print("  ✨ Проект уже чист.")
    else:
        print(f"  ✅ Удалено файлов: {deleted_count}\n")


def prep_markdown_for_nonstop(md_text: str) -> str:
    """Делает базовую очистку, чтобы компилятор не подавился фатальными ошибками."""
    # Убиваем пустые строки внутри формул (главная причина падений LaTeX)
    md_text = re.sub(r'\$\$(.*?)\$\$', lambda m: '$$' + m.group(1).replace('\n\n', '\n') + '$$', md_text, flags=re.DOTALL)
    
    # Меняем строгие таблицы array на всеядный aligned (спасает от Extra alignment tab)
    md_text = re.sub(r'\\begin\{array\}\{[^\}]*\}', r'\\begin{aligned}', md_text)
    md_text = md_text.replace(r'\end{array}', r'\end{aligned}')
    
    # Снимаем экранирование с долларов и подчеркиваний перед математикой
    md_text = md_text.replace(r'\$', '$')
    md_text = md_text.replace(r'\_', '_')
    
    return md_text


def force_compile_pdf(md_path: Path):
    print(f"📖 Читаю файл: {md_path}")
    md_text = md_path.read_text(encoding="utf-8")
    
    print("🔧 Применяю базовую санитарию...")
    md_text = prep_markdown_for_nonstop(md_text)
    
    output_dir = md_path.parent
    pdf_path = output_dir / f"{md_path.stem}.pdf"
    
    # Настраиваем пути для картинок
    images_dir = output_dir / "images"
    res_path = os.pathsep.join([".", str(output_dir.absolute()), str(images_dir.absolute())])
    
    print("🚀 Запускаю Pandoc в режиме ТЕРМИНАТОРА (nonstopmode)...")
    
    # МАГИЯ ЗДЕСЬ: --pdf-engine-opt=-interaction=nonstopmode
    # Это заставит XeLaTeX игнорировать синтаксические ошибки формул и собирать PDF до конца.
    pdf_args = [
        "--pdf-engine=xelatex",
        "--pdf-engine-opt=-interaction=nonstopmode", # <--- УБОЛТЫВАЕМ КОМПИЛЯТОР
        f"--resource-path={res_path}",
        "-V", "graphics=true",
        "-V", "maxwidth=\\textwidth",
        "-V", "mainfont=Times New Roman",
        "-V", "monofont=Courier New",
        "-V", "sansfont=Arial",
        "-V", "geometry:margin=2.5cm",
        "-V", "lang=uk",
    ]
    
    try:
        pypandoc.convert_text(
            md_text,
            'pdf',
            format='markdown+raw_tex',
            outputfile=str(pdf_path),
            extra_args=pdf_args,
        )
        print(f"\n🎉 ПОБЕДА! PDF сгенерирован (ошибки формул были проигнорированы).")
        print(f"📁 Файл сохранен: {pdf_path}")
    except RuntimeError as e:
        # Pandoc все равно может выплюнуть Warning в консоль, но файл должен создаться
        if pdf_path.exists():
            print(f"\n⚠️ Pandoc ругался, НО благодаря nonstopmode PDF всё равно собран!")
            print(f"📁 Файл сохранен: {pdf_path}")
        else:
            print(f"\n❌ Критический сбой (не связанный с LaTeX): {e}")


if __name__ == "__main__":
    print("="*60)
    print("🔥 FORCE COMPILER & CLEANER 🔥")
    print("="*60)
    
    BASE_DIR = Path(__file__).parent
    
    # 1. Удаляем мусор
    clean_project(BASE_DIR)
    
    # 2. Спрашиваем путь к файлу
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = input("📄 Введите путь к финальному .md файлу:\n> ").strip()
        
    md_file = Path(file_path)
    if not md_file.exists() or not md_file.is_file():
        print("❌ Ошибка: файл не найден!")
        sys.exit(1)
        
    # 3. Принудительно собираем
    force_compile_pdf(md_file)