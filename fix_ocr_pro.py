import re
import sys
import os

class OCRCleaner:
    def __init__(self, input_file, output_file, log_file):
        self.input_file = input_file
        self.output_file = output_file
        self.log_file = log_file
        
        with open(input_file, 'r', encoding='utf-8') as f:
            self.text = f.read()
            
        self.logs = []
        self.warnings = []

    def get_line_num(self, index):
        """Возвращает номер строки по индексу символа в тексте"""
        return self.text.count('\n', 0, index) + 1

    def log(self, line_num, message):
        self.logs.append(f"[INFO] Строка {line_num}: {message}")

    def warn(self, line_num, message):
        warning_msg = f"[WARNING] Строка {line_num}: {message} <-- ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ!"
        self.logs.append(warning_msg)
        self.warnings.append(warning_msg)

    def fix_image_paths(self):
        """Исправление путей к картинкам"""
        def repl(match):
            line = self.get_line_num(match.start())
            self.log(line, "Исправлен путь к изображению (![](_page_ -> ![](images/_page_)")
            return r'![](images/_page_'
        
        self.text = re.sub(r'!\[\]\(_page_', repl, self.text)

    def clean_pandoc_bugs(self):
        """Лечим баги Pandoc (\\text и \\\\infty)"""
        # Исправляем двойные слеши
        def repl_slash(match):
            line = self.get_line_num(match.start())
            self.log(line, f"Убран лишний слеш: \\\\{match.group(1)} -> \\{match.group(1)}")
            return f"\\{match.group(1)}"
        
        self.text = re.sub(r'\\\\([a-zA-Z]+)', repl_slash, self.text)

        # Вытаскиваем макросы из \text
        def repl_text(match):
            line = self.get_line_num(match.start())
            macro = match.group(1)
            remaining_text = match.group(2).strip()
            self.log(line, f"Вынесен макрос из \\text: \\text{{\\{macro} ...}} -> \\{macro} \\text{{...}}")
            if remaining_text:
                return f"\\{macro} \\text{{{remaining_text}}}"
            return f"\\{macro}"
        
        self.text = re.sub(r'\\text\{\\([a-zA-Z]+)\s*(.*?)\}', repl_text, self.text)

    def amputate_tail(self):
        """Ампутация зацикленных таблиц в конце"""
        marker = r"ТАБЛИЦЫ ИНТЕГРАЛЬНЫХ ПРЕОБРАЗОВАНИЙ"
        match = re.search(marker, self.text)
        if match:
            line = self.get_line_num(match.start())
            self.log(line, f"АМПУТАЦИЯ: Начиная со строки {line} хвост документа обрезан (защита от галлюцинаций в таблицах).")
            self.text = self.text[:match.start()] + "\n\n# Приложения (вырезано из-за ошибок OCR)\n"

        # Если ампутация не сработала, чистим дикие амперсанды
        def repl_amp(match):
            line = self.get_line_num(match.start())
            self.log(line, "Сжата галлюцинация из множества амперсандов (& & & &...)")
            return r'& \dots &'
        
        self.text = re.sub(r'(&\s*){5,}', repl_amp, self.text)

    def process_math_blocks(self):
        """Умная обработка блоков $$ ... $$ с проверкой баланса скобок"""
        def repl_math(match):
            start_line = self.get_line_num(match.start())
            block = match.group(1)
            original_block = block
            
            # 1. Удаление пустых строк
            if '\n\n' in block:
                block = re.sub(r'\n{2,}', '\n', block)
                self.log(start_line, "Удалены пустые строки (разрывы абзацев) внутри формулы.")

            # 2. Замена array на aligned
            if r'\begin{array}' in block:
                block = re.sub(r'\\begin\{array\}\{[lcr|\s]+\}', r'\\begin{aligned}', block)
                block = block.replace(r'\end{array}', r'\end{aligned}')
                self.log(start_line, "Матрица array заменена на безопасный aligned.")

            # 3. Умная балансировка \begin и \end
            envs = re.findall(r'\\(begin|end)\{([a-zA-Z\*]+)\}', block)
            stack = []
            for action, env_name in envs:
                if action == 'begin':
                    stack.append(env_name)
                elif action == 'end':
                    if stack and stack[-1] == env_name:
                        stack.pop()

            while stack:
                env_to_close = stack.pop()
                block += f'\n\\end{{{env_to_close}}}'
                self.log(start_line, f"АВТОИСПРАВЛЕНИЕ: Дописан забытый тег \\end{{{env_to_close}}}.")

            # 4. ПРОВЕРКА БАЛАНСА ФИГУРНЫХ СКОБОК {} (Частая причина падения LaTeX)
            open_braces = block.count('{')
            close_braces = block.count('}')
            if open_braces != close_braces:
                self.warn(start_line, f"Дисбаланс фигурных скобок в формуле! Открыто: {open_braces}, Закрыто: {close_braces}.")

            return f'$${block}$$'

        self.text = re.sub(r'\$\$(.*?)\$\$', repl_math, self.text, flags=re.DOTALL)

    def run(self):
        print("Запуск анализатора и чистильщика OCR...")
        self.amputate_tail()
        self.fix_image_paths()
        self.clean_pandoc_bugs()
        self.process_math_blocks()

        # Сохранение очищенного файла
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(self.text)
            
        # Сохранение логов
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(self.logs))

        print(f"\nОчистка завершена!")
        print(f"✅ Результат сохранен в: {self.output_file}")
        print(f"📝 Лог исправлений сохранен в: {self.log_file}")
        
        if self.warnings:
            print(f"\n⚠️ ВНИМАНИЕ! Найдено потенциальных фатальных ошибок: {len(self.warnings)}")
            print("Пожалуйста, открой лог-файл и проверь эти строки вручную.")
            for w in self.warnings[:5]: # Показываем первые 5 в консоли
                print(w)
            if len(self.warnings) > 5:
                print("...и еще несколько (смотри лог).")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Использование: python fix_ocr_pro.py <входной_файл.md> <выходной_файл.md>")
        sys.exit(1)
        
    input_md = sys.argv[1]
    output_md = sys.argv[2]
    log_md = output_md.replace('.md', '_report.log')
    
    cleaner = OCRCleaner(input_md, output_md, log_md)
    cleaner.run()