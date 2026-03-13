#!/usr/bin/env python3
r"""
pandoc_fix_all.py  v5  — ФІНАЛЬНИЙ ФІКСЕР ДЛЯ PANDOC PDF
=========================================================

Причини "Missing $ inserted":
 A) Formuli-блоки $$ з пустими рядками всередині — pandoc/XeLaTeX ламає їх
 B) Рядки LaTeX що ВЗАГАЛІ не мали обгортки $$ — OCR їх записав без неї

Що виправляє (в порядку виконання):
 1. Розгортає прозаічні $$...$$ блоки (кирилиця без LaTeX)
 2. Видаляє порожні $$$$ блоки
 3. Розщеплює мега-блоки (формули + проза в одному $$)
 4. ★ Прибирає пусті рядки всередині $$...$$ (XeLaTeX не терпить \n\n в math)
 5. ★ Загортає голі LaTeX-рядки в $$ (рядки без $$ обгортки)
 6. Балансує незакриті окруження aligned/cases/array
 7. Виправляє хвостові артефакти (\\, , після \end{})
 8. Загортає кирилицю в \text{} всередині \begin{} оточень

Використання:
    python3 pandoc_fix_all.py file.md
    python3 pandoc_fix_all.py file.md --output fixed.md
    python3 pandoc_fix_all.py file.md --inplace
"""
from __future__ import annotations
import re, sys, shutil
from pathlib import Path

# ---------------------------------------------------------------------------
_LATEX_CMDS = re.compile(
    r'\\(?:frac|sum|int|sqrt|sin|cos|tan|cot|lim|log|exp|left|right|'
    r'alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|'
    r'mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega|'
    r'Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega|'
    r'partial|nabla|infty|leqslant|geqslant|leq|geq|neq|approx|equiv|'
    r'cdot|cdots|ldots|vdots|ddots|quad|qquad|pm|mp|times|div|'
    r'mathcal|mathrm|mathbf|mathit|boldsymbol|hat|bar|vec|tilde|'
    r'dot|ddot|overline|underline|overset|underset|begin|end|binom|'
    r'limits|displaystyle|hbar|ell|wp|Re|Im|arg|max|min|sup|inf|det|'
    r'to|gets|Rightarrow|Leftarrow|Leftrightarrow|rightarrow|leftarrow|'
    r'subset|supset|subseteq|supseteq|in|notin|cup|cap|bigcup|bigcap|'
    r'forall|exists|neg|wedge|vee|oplus|otimes|mathscr|mathbb|'
    r'sinh|cosh|tanh|arctan|arcsin|arccos|ln|deg|dim|text)\b'
)
_HAS_BEGIN   = re.compile(r'\\begin\{')
_CYRILLIC    = re.compile(r'[а-яА-ЯёЁіІїЇєЄ]{3,}')
_PURE_WS     = re.compile(r'^\s*$')
_ENVS = ['aligned','cases','array','matrix','pmatrix','bmatrix',
         'vmatrix','Vmatrix','split','gather','multline']

# ---------------------------------------------------------------------------
def _strip_text(s): return re.sub(r'\\text\s*\{[^}]*\}', '', s)
def _strip_inline(s): return re.sub(r'(?<!\$)\$(?!\$)[^$]+?(?<!\$)\$(?!\$)', 'INL', s)
def _has_block_formula(c): return bool(_HAS_BEGIN.search(_strip_inline(c)))
def _cyr_count(c): return len(re.findall(r'[а-яА-ЯёЁіІїЇєЄ]{4,}', _strip_text(c)))
def _is_formula_chunk(c): return bool(_LATEX_CMDS.search(c)) or bool(_HAS_BEGIN.search(c))

def _should_unwrap(content):
    if _PURE_WS.match(content): return False
    if _has_block_formula(content): return False
    if re.match(r'^\s*\(?\d+(?:\.\d+)?\)?\s*$', content.strip()): return True
    if _CYRILLIC.search(content) and not _LATEX_CMDS.search(content): return True
    stripped = _strip_text(content)
    if _CYRILLIC.search(stripped):
        no_inline = re.sub(r'(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)', '', stripped, flags=re.DOTALL)
        if _CYRILLIC.search(no_inline): return True
    return False

def _is_mega_block(c):
    return _has_block_formula(c) and _cyr_count(c) > 5

def _balance_environments(content):
    stack = []
    for m in re.finditer(r'\\(begin|end)\{(' + '|'.join(_ENVS) + r')\*?\}', content):
        action, env = m.group(1), m.group(2)
        if action == 'begin':
            stack.append(env)
        elif action == 'end':
            if stack and stack[-1] == env: stack.pop()
            elif env in stack:
                while stack and stack[-1] != env: stack.pop()
                if stack: stack.pop()
    if stack:
        closers = '\n'.join(f'\\end{{{e}}}' for e in reversed(stack))
        content = content.rstrip() + '\n' + closers + '\n'
    return content

def _fix_trailing(content):
    c = content.rstrip()
    c = re.sub(r'\\,\s*$', '', c)
    c = re.sub(r'(?<!\\)\\(?![a-zA-Z\\\{\(\[])\s*$', '', c)
    c = re.sub(r'(\\end\{[^}]+\})\s*,\s*$', r'\1', c)
    c = re.sub(r'([}\])])\s*,\s*$', r'\1', c)
    return c

def _wrap_cyrillic_in_text(content):
    def replace_cyr(chunk):
        return re.sub(
            r'([а-яА-ЯёЁіІїЇєЄ][а-яА-ЯёЁіІїЇєЄ\s\-\(\)\.,;:!?]*)',
            r'\\text{\1}', chunk)
    parts = re.split(r'(\\text\s*\{[^}]*\})', content)
    return ''.join(p if p.startswith('\\text') else replace_cyr(p) for p in parts)

def _split_mega_block(content):
    SEP_A = re.compile(r'(\\end\{[^}]+\})\s*\n{2,}(?=[а-яА-ЯёЁіІїЇєЄ\d(])')
    SEP_B = re.compile(r'\n{2,}(?=\\begin\{)')
    raw = SEP_A.split(content)
    merged, i = [], 0
    while i < len(raw):
        if i+1 < len(raw) and re.match(r'\\end\{', raw[i+1]):
            merged.append(raw[i] + raw[i+1]); i += 2
        else:
            merged.append(raw[i]); i += 1
    final = []
    for mp in merged:
        final.extend(SEP_B.split(mp))
    result = []
    for part in final:
        part = part.strip()
        if not part: continue
        if _has_block_formula(part) or (_is_formula_chunk(part) and not _CYRILLIC.search(_strip_text(part))):
            part = _balance_environments(part)
            part = _fix_trailing(part)
            result.append(f'\n\n$$\n{part}\n$$\n\n')
        else:
            result.append(f'\n\n{part}\n\n')
    return ''.join(result) if result else f'$${content}$$'


# ---------------------------------------------------------------------------
# Pass 1: fix $$ blocks
# ---------------------------------------------------------------------------
def _fix_blocks(text: str, stats: dict) -> str:
    result: list[str] = []
    last = 0
    for m in re.finditer(r'\$\$(.*?)\$\$', text, re.DOTALL):
        result.append(text[last:m.start()])
        last = m.end()
        content = m.group(1)

        if _PURE_WS.match(content):
            stats['removed_empty'] += 1
            continue

        if _should_unwrap(content):
            u = content.strip()
            if u: result.append('\n\n' + u + '\n\n')
            stats['unwrapped'] += 1
            continue

        if _is_mega_block(content):
            result.append(_split_mega_block(content))
            stats['mega_split'] += 1
            continue

        # ★ Прибираємо пусті рядки всередині блоку
        if '\n\n' in content or '\n \n' in content:
            c2 = re.sub(r'\n{2,}', '\n', content)
            c2 = re.sub(r'\n +\n', '\n', c2)
            if c2 != content:
                content = c2
                stats['blank_lines_removed'] += 1

        orig = content
        content = _balance_environments(content)
        if content != orig: stats['envs_balanced'] += 1

        orig = content
        content = _fix_trailing(content)
        if content != orig: stats['trailing_fixed'] += 1

        if _has_block_formula(content) and _cyr_count(content) > 0:
            orig = content
            content = _wrap_cyrillic_in_text(content)
            if content != orig: stats['cyrillic_wrapped'] += 1

        result.append(f'$${content}$$')

    result.append(text[last:])
    return ''.join(result)


# ---------------------------------------------------------------------------
# Pass 2: wrap naked LaTeX lines
# ---------------------------------------------------------------------------
def _wrap_naked_latex(text: str, stats: dict) -> str:
    """
    Знаходить рядки з LaTeX-командами що знаходяться поза будь-якими $$...$$
    (OCR написав їх без обгортки) і загортає в $$ ...\n $$.
    """
    # Маркуємо рядки, які вже всередині $$ блоків
    in_math_lines: set[int] = set()
    for m in re.finditer(r'\$\$(.*?)\$\$', text, re.DOTALL):
        sl = text[:m.start()].count('\n')
        el = text[:m.end()].count('\n')
        for ln in range(sl, el + 1):
            in_math_lines.add(ln)
    # інлайн $...$
    for m in re.finditer(r'(?<!\$)\$(?!\$)[^\n$]+(?<!\$)\$(?!\$)', text):
        in_math_lines.add(text[:m.start()].count('\n'))

    lines = text.split('\n')

    def _is_naked_latex_line(line: str, lineno: int) -> bool:
        if lineno in in_math_lines: return False
        l = line.strip()
        if not l: return False
        if l.startswith('#'): return False   # заголовки
        if l.startswith('!'): return False   # зображення
        if l.startswith('>'): return False   # цитати
        if l.startswith('-') or l.startswith('*'): return False  # списки
        if '$' in l: return False            # вже має $ обгортку
        if _CYRILLIC.search(l) and not _LATEX_CMDS.search(l): return False  # проза
        return bool(_LATEX_CMDS.search(l))

    # Групуємо суміжні naked-рядки
    out: list[str] = []
    i = 0
    wrapped_groups = 0
    while i < len(lines):
        if _is_naked_latex_line(lines[i], i):
            # Збираємо групу: naked LaTeX рядки + порожні між ними
            group: list[str] = []
            j = i
            while j < len(lines):
                if _is_naked_latex_line(lines[j], j):
                    group.append(lines[j])
                    j += 1
                elif not lines[j].strip() and j+1 < len(lines) and _is_naked_latex_line(lines[j+1], j+1):
                    group.append(lines[j])  # порожній рядок між формулами
                    j += 1
                else:
                    break

            # Загортаємо групу
            formula = '\n'.join(group).strip()
            if formula:
                formula = _balance_environments(formula)
                formula = _fix_trailing(formula)
                out.append(f'\n$$\n{formula}\n$$\n')
                wrapped_groups += 1

            # Оновлюємо in_math_lines для решти проходу (щоб не захопити двічі)
            # (Тут не критично — wrapped_groups достатньо)
            i = j
        else:
            out.append(lines[i])
            i += 1

    stats['naked_wrapped'] = wrapped_groups
    return '\n'.join(out)


# ---------------------------------------------------------------------------
def fix_markdown(text: str) -> tuple[str, dict]:
    stats = dict(
        blank_lines_removed=0,
        removed_empty=0,
        unwrapped=0,
        mega_split=0,
        trailing_fixed=0,
        envs_balanced=0,
        cyrillic_wrapped=0,
        naked_wrapped=0,
    )
    # Прохід 1: виправляємо $$ блоки
    text = _fix_blocks(text, stats)
    # Прохід 2: загортаємо голий LaTeX
    text = _wrap_naked_latex(text, stats)
    # Прибираємо зайві порожні рядки
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text, stats


# ---------------------------------------------------------------------------
def main():
    import argparse
    p = argparse.ArgumentParser(description='Pandoc MD → PDF fixer v5')
    p.add_argument('input')
    p.add_argument('--output', '-o', default=None)
    p.add_argument('--inplace', action='store_true')
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f'Файл не знайдено: {in_path}'); sys.exit(1)

    out_path = in_path if args.inplace else (
        Path(args.output) if args.output else in_path.with_stem(in_path.stem + '_fixed'))

    print(f'📖 Читаю: {in_path}')
    text = in_path.read_text(encoding='utf-8')
    orig_size = len(text)

    if args.inplace:
        bk = in_path.with_stem(in_path.stem + '_backup')
        shutil.copy2(in_path, bk)
        print(f'💾 Резервна копія: {bk}')

    print('🔧 Застосовую виправлення...')
    fixed, stats = fix_markdown(text)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(fixed, encoding='utf-8')

    print(f'\n✅ Готово! → {out_path}')
    print(f'   Розмір: {orig_size:,} → {len(fixed):,} символів')
    print(f'\n📊 Статистика:')
    labels = {
        'blank_lines_removed': '★  Прибрано пустих рядків в $$ блоках',
        'naked_wrapped':       '★  Загорнуто голих LaTeX-рядків в $$',
        'removed_empty':       '🗑️  Видалено порожніх $$ блоків',
        'unwrapped':           '📜 Розгорнуто прозаічних $$ блоків',
        'mega_split':          '✂️  Розщеплено мега-блоків',
        'trailing_fixed':      '🔧 Виправлено хвостових артефактів',
        'envs_balanced':       '🔒 Збалансовано оточень',
        'cyrillic_wrapped':    '📝 Кирилицю загорнуто в \\text{}',
    }
    for k, label in labels.items():
        print(f'   {label}: {stats[k]}')
    print(f'   ──────────────────────────────────')
    print(f'   РАЗОМ: {sum(stats.values())}')
    print(f'\n💡 Запустіть генерацію PDF:')
    print(f'   python3 book_translator.py --md "{out_path}" --rebuild-only')

if __name__ == '__main__':
    main()