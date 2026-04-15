"""
book_translator.py
==================
Automated pipeline to translate a mathematical physics textbook from English
to Ukrainian using the Azure Cognitive Services API, while preserving ALL LaTeX
formulas AND Markdown image links with 100 % fidelity.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
import datetime
import sqlite3
import hashlib
import concurrent.futures
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from tqdm import tqdm
import requests
from pypdf import PdfReader, PdfWriter

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------
load_dotenv()

AZURE_TRANSLATOR_KEY: str = os.getenv("AZURE_TRANSLATOR_KEY", "")
AZURE_TRANSLATOR_ENDPOINT: str = os.getenv("AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com/")
AZURE_TRANSLATOR_REGION: str = os.getenv("AZURE_TRANSLATOR_REGION", "")

if not AZURE_TRANSLATOR_KEY:
    log.error("Файл .env не найден или ключ AZURE_TRANSLATOR_KEY не заполнен!")

TARGET_LANG: str   = os.getenv("TARGET_LANG", "uk")

BASE_DIR   = Path(__file__).parent
INPUT_DIR  = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "Output_Final"
TEMP_CHUNKS_DIR = BASE_DIR / "temp_chunks"
TEMP_PDF_BUILD_DIR = BASE_DIR / "tmp" / "pdf_build"
IMAGES_DIR = OUTPUT_DIR / "images"

CHUNK_SIZE = 9000  # Safe size for Azure translation (Max 10000 characters)

# ---------------------------------------------------------------------------
# Placeholder templates
# ---------------------------------------------------------------------------
_PH_MATH_BLOCK  = "MATHBLK{idx:04d}X"   # display / block math
_PH_MATH_INLINE = "MATHINL{idx:04d}X"   # inline math
_PH_IMAGE       = "IMGTOKEN{idx:04d}X"  # Markdown image links

_BLOCK_MATH_PATTERNS: list[tuple[str, int]] = [
    (r"\$\$.*?\$\$",    re.DOTALL),   
    (r"\\\[.*?\\\]",    re.DOTALL),   
]

_INLINE_MATH_PATTERNS: list[tuple[str, int]] = [
    (r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", re.DOTALL),  
    (r"\\\(.*?\\\)",                        re.DOTALL),  
]

_IMAGE_PATTERN = (r"!\[[^\]]*\]\([^)]+\)", 0)


def _looks_like_placeholder_config_value(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        not lowered
        or lowered.startswith("your_")
        or lowered.endswith("_here")
        or lowered in {"changeme", "replace-me", "replace_me"}
    )

# ===========================================================================
# Chunking and Utilities
# ===========================================================================

def split_pdf(pdf_path: str | Path, chunk_dir: Path, chunk_size: int = 50) -> list[Path]:
    """Splits a PDF into physical chunks of `chunk_size` pages."""
    pdf_path = Path(pdf_path)
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    chunk_paths = []
    
    chunk_dir.mkdir(parents=True, exist_ok=True)
    
    for i in range(0, total_pages, chunk_size):
        writer = PdfWriter()
        end = min(i + chunk_size, total_pages)
        for j in range(i, end):
            writer.add_page(reader.pages[j])
            
        chunk_idx = i // chunk_size + 1
        chunk_path = chunk_dir / f"{pdf_path.stem}_chunk{chunk_idx:03d}.pdf"
        
        with open(chunk_path, "wb") as f:
            writer.write(f)
            
        chunk_paths.append(chunk_path)
        log.info("  Created chunk: %s (pages %d-%d)", chunk_path.name, i + 1, end)
        
    return chunk_paths

def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break

        split_pos = text.rfind("\n\n", int(start), int(end))
        if split_pos <= start:
            split_pos = text.rfind("\n", int(start), int(end))
        if split_pos <= start:
            split_pos = int(end) - 1

        while split_pos > start:
            chunk_so_far = text[start : split_pos + 1].rstrip()
            last_newline = int(chunk_so_far.rfind("\n"))
            last_line = chunk_so_far[last_newline + 1:] if last_newline != -1 else chunk_so_far
            if re.match(r"^#+\s", last_line):
                prev_split = int(text.rfind("\n", start, start + last_newline) if last_newline != -1 else -1)
                if prev_split <= start:
                    break
                split_pos = prev_split
            else:
                break

        chunks.append(text[int(start) : int(split_pos) + 1])
        start = int(split_pos) + 1

    log.info("  Splitting into %d API chunk(s) for translation.", len(chunks))
    return chunks

# ===========================================================================
# Markdown Formatting Cleanup
# ===========================================================================

def clean_markdown_formatting(md_text: str) -> str:
    """Очищает грязный Markdown, сгенерированный marker-pdf."""
    md_text = re.sub(
        r'\$\$\s*\n+\s*(!\[[^\]]*\]\([^)]+\))\s*\n+\s*\$\$',
        r'\n\n\1\n\n',
        md_text,
        flags=re.DOTALL,
    )
    md_text = re.sub(
        r'\$\$\s*(!\[[^\]]*\]\([^)]+\))\s*\$\$',
        r'\n\n\1\n\n',
        md_text,
        flags=re.DOTALL,
    )
    md_text = re.sub(
        r'([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\-]+)\s*\n+(!\[.*?\]\(.*?\))\s*\n+([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ])', 
        r'\1 \3\n\n\2\n\n', 
        md_text
    )

    md_text = re.sub(r'`\s*\$\$(.*?)\$\$\s*`', r'$$\1$$', md_text, flags=re.DOTALL)
    md_text = re.sub(r'`\s*\$(.*?)\$\s*`', r'$\1$', md_text)
    md_text = re.sub(r'([а-яА-ЯёЁіІїЇєЄґҐ])\$', r'\1 $', md_text)
    md_text = re.sub(r'\$([а-яА-ЯёЁіІїЇєЄґҐ])', r'$ \1', md_text)
    md_text = re.sub(r'\bxit\b', '$x$ і $t$', md_text)
    md_text = re.sub(r'r,\s*\\theta\s*it\b', '$r$, $\\theta$ і $t$', md_text)
    md_text = md_text.replace('$x~i~t$', '$x$ і $t$')
    md_text = md_text.replace('$r,\\theta i~t$', '$r$, $\\theta$ і $t$')
    
    md_text = re.sub(r'\n+\s*(\$[^$\n]+\$)\s*\n+', r' \1 ', md_text)
    md_text = re.sub(r'\n+\s*(i|і|та|або|а)\s*\n+', r' \1 ', md_text)
    md_text = re.sub(r'\s*\n+\s*([\,\.\;\:\)])', r'\1', md_text)
    md_text = re.sub(r'([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\-]+)\n([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\-])', r'\1 \2', md_text)
    md_text = re.sub(r',{3,}', ' ', md_text)
    md_text = re.sub(r'^[ \t\,]+$', '', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'^[ \t]+(\$\$)', r'\1', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'\s*(!\[.*?\]\(.*?\))\s*', r'\n\n\1\n\n', md_text)
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    # Collapse only malformed patterns like "# # Heading", but preserve
    # legitimate deeper headings such as "## Lecture 27".
    md_text = re.sub(r'^(#+)\s+#\s*', r'\1 ', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'(?:\$\$\s*){2,}', '$$ ', md_text)
    md_text = re.sub(r'\$\$\s*\$\$', '', md_text)
    
    md_text = md_text.replace(r"\rm ", r"\mathrm{ }").replace(r"\rm", r"\mathrm")
    md_text = md_text.replace(r"\Праворуч", r"\Rightarrow")
    md_text = md_text.replace(r"\Правостріла", r"\Rightarrow")
    md_text = md_text.replace(r"\Правострелка", r"\Rightarrow")
    
    def fix_cases_dollars(match):
        content = match.group(1).replace('$', '')
        return r'\begin{cases}' + content + r'\end{cases}'
    
    md_text = re.sub(r'\\begin\{cases\}(.*?)\\end\{cases\}', fix_cases_dollars, md_text, flags=re.DOTALL)
    
    return md_text

# ===========================================================================
# Stage 1 – PDF → Markdown
# ===========================================================================

def parse_pdf_to_md(
    pdf_path: str | Path,
    images_dir: Optional[Path] = None,
    image_prefix: str = "",
) -> str:
    pdf_path   = Path(pdf_path)
    images_dir = images_dir or IMAGES_DIR
    images_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    log.info("Stage 1 – Parsing PDF (marker): %s", pdf_path)

    try:
        from marker.converters.pdf import PdfConverter      
        from marker.models import create_model_dict         
        from marker.config.parser import ConfigParser       

        log.info("  Detected marker-pdf v1.x API")
        cfg: dict = {"languages": ["Russian"]}
        config_parser = ConfigParser(cfg)
        converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            llm_service=None,
        )
        rendered = converter(str(pdf_path))
        full_text = rendered.markdown

        for img_name, img_obj in rendered.images.items():
            new_img_name = f"{image_prefix}{img_name}" if image_prefix else img_name
            dest = images_dir / new_img_name
            img_obj.save(str(dest))
            full_text = full_text.replace(img_name, new_img_name)
            log.info("  Saved image: %s", dest)

    except ImportError:
        try:
            from marker.convert import convert_single_pdf  
            from marker.models import load_all_models       

            log.info("  Detected marker-pdf v0.x API")
            models = load_all_models()
            full_text, images, _meta = convert_single_pdf(
                str(pdf_path),
                models,
                langs=["Russian"],
                batch_multiplier=1,
            )
            for img_name, img_obj in images.items():
                new_img_name = f"{image_prefix}{img_name}" if image_prefix else img_name
                dest = images_dir / new_img_name
                img_obj.save(str(dest))
                full_text = full_text.replace(img_name, new_img_name)
                log.info("  Saved image: %s", dest)

        except ImportError:
            raise ImportError(
                "marker-pdf is not installed.\n"
                "  Run: pip install marker-pdf"
            )

    log.info("Stage 1 complete – %d characters extracted.", len(full_text))
    return full_text

# ===========================================================================
# Stage 2 – Masking (formulas + images)
# ===========================================================================


def rescue_broken_latex(md_text: str) -> str:
    """
    Сканирует текст и принудительно оборачивает "потерянные" математические конструкции
    в блочные теги $$...$$, если они еще ими не обернуты.
    """
    hidden_math: dict[str, str] = {}

    typo_fixes = {
        r'\begin{case}': r'\begin{cases}',
        r'\end{case}': r'\end{cases}',
        r'\begin{align}': r'\begin{aligned}',
        r'\end{align}': r'\end{aligned}',
    }

    def hide_math(match):
        uid = f"HIDE{uuid.uuid4().hex}X"
        hidden_math[uid] = match.group(0)
        return uid

    temp_text = md_text
    for broken, fixed in typo_fixes.items():
        temp_text = temp_text.replace(broken, fixed)
    
    # 1. Прячем уже обернутую математику
    for pattern, flags in _BLOCK_MATH_PATTERNS:
        temp_text = re.sub(pattern, hide_math, temp_text, flags=flags)
    for pattern, flags in _INLINE_MATH_PATTERNS:
        temp_text = re.sub(pattern, hide_math, temp_text, flags=flags)

    # 2. Паттерн А: Математические окружения
    env_names = (
        "array",
        "cases",
        "aligned",
        "split",
        "matrix",
        "pmatrix",
        "bmatrix",
        "vmatrix",
        "Vmatrix",
        "equation",
        "eqnarray",
    )
    env_pattern = "|".join(re.escape(env_name) for env_name in env_names)
    pattern_a = rf"(\\begin\{{(?P<env>{env_pattern})\}}.*?\\end\{{(?P=env)\}})"

    def wrap_environment(match: re.Match) -> str:
        return f"\n\n$$\n{match.group(1)}\n$$\n\n"

    temp_text = re.sub(pattern_a, wrap_environment, temp_text, flags=re.DOTALL)
    
    # 3. Паттерн Б: Изолированные строки с жесткой математикой
    math_triggers = [r"\\frac", r"\\partial", r"\\int", r"\\sum", r"\\infty", r"\\nabla", r"\^", r"_", r"="]
    cyrillic_pattern = re.compile(r'[а-яА-ЯёЁіІїЇєЄґҐ]')
    
    lines = temp_text.split('\n')
    rescued_lines = []
    for line in lines:
        if not line.strip():
            rescued_lines.append(line)
            continue
            
        if not cyrillic_pattern.search(line):
            if any(re.search(trigger, line) for trigger in math_triggers):
                # Исключаем строки, которые содержат только дефисы (разделители таблиц)
                if re.fullmatch(r'[\s|\-]+', line):
                    rescued_lines.append(line)
                    continue
                rescued_lines.append(f"$$\n{line.strip()}\n$$")
                continue
        rescued_lines.append(line)
        
    temp_text = '\n'.join(rescued_lines)
    
    # 4. Возвращаем спрятанную математику
    for uid, original_math in hidden_math.items():
        temp_text = temp_text.replace(uid, original_math)
        
    return temp_text


_SECOND_PASS_PHRASE_REPLACEMENTS: dict[str, str] = {
    "с частными производными": "з частинними похідними",
    "частных производных": "частинних похідних",
    "граничные условия": "граничні умови",
    "граничное условие": "гранична умова",
    "начальные условия": "початкові умови",
    "начальное условие": "початкова умова",
    "собственные функции": "власні функції",
    "собственная функция": "власна функція",
    "интегральные преобразования": "інтегральні перетворення",
    "интегральных преобразований": "інтегральних перетворень",
    "уравнения теплопроводности": "рівняння теплопровідності",
    "уравнение теплопроводности": "рівняння теплопровідності",
    "волновое уравнение": "хвильове рівняння",
    "уравнение лапласа": "рівняння Лапласа",
    "уравнение пуассона": "рівняння Пуассона",
    "метод разделения переменных": "метод поділу змінних",
    "метод интегральных преобразований": "метод інтегральних перетворень",
    "метод преобразования координат": "метод перетворення координат",
    "численные методы": "чисельні методи",
}

_SECOND_PASS_WORD_REPLACEMENTS: dict[str, str] = {
    "если": "якщо",
    "что": "що",
    "только": "лише",
    "также": "також",
    "после": "після",
    "прежде": "перш ніж",
    "например": "наприклад",
    "следовательно": "отже",
    "этого": "цього",
    "этой": "цієї",
    "этом": "цьому",
    "этих": "цих",
    "этот": "цей",
    "эта": "ця",
    "это": "це",
    "которые": "які",
    "который": "який",
    "которая": "яка",
    "которое": "яке",
    "должны": "повинні",
    "должен": "повинен",
    "будет": "буде",
    "были": "були",
    "было": "було",
    "можно": "можна",
    "нужно": "потрібно",
    "называется": "називається",
    "называются": "називаються",
    "функция": "функція",
    "функции": "функції",
    "функций": "функцій",
    "решение": "розв'язок",
    "решения": "розв'язки",
    "производными": "похідними",
    "производных": "похідних",
    "переменных": "змінних",
    "переменные": "змінні",
    "переменными": "змінними",
    "коэффициенты": "коефіцієнти",
    "коэффициент": "коефіцієнт",
    "коэффициентов": "коефіцієнтів",
    "температуры": "температури",
    "границы": "межі",
    "волны": "хвилі",
    "системы": "системи",
    "выражение": "вираз",
    "выражения": "вирази",
    "вычисления": "обчислення",
    "вычислить": "обчислити",
}

_RESIDUAL_RUSSIAN_MARKERS: tuple[str, ...] = (
    "если",
    "что",
    "только",
    "также",
    "после",
    "например",
    "решение",
    "функция",
    "который",
    "которая",
    "которые",
    "можно",
    "нужно",
    "цель",
    "лекции",
    "задачи",
    "замечания",
    "решите",
    "рис",
    "преобразование",
    "преобразования",
    "ряды",
    "ряд",
    "фурье",
    "лапласа",
    "колебания",
    "струны",
    "волнового",
    "волновое",
    "показать",
    "ввести",
    "рассмотрим",
    "предположим",
    "поскольку",
    "теперь",
    "поперечные",
    "смещение",
)
_RESIDUAL_SHORT_BLOCK_PREFIX_PATTERN = re.compile(
    r'^(?:#{1,6}\s+|РИС[., ]|ЦЕЛЬ ЛЕКЦИИ:|ЗАДАЧИ\b|ЗАМЕЧАНИЯ\b|ШАГ\s+\d+|Лекция\s+\d+)',
    flags=re.IGNORECASE,
)
_RUSSIAN_SPECIFIC_LETTERS_PATTERN = re.compile(r'[ЫыЭэЁёЪъ]')
_CYRILLIC_TEXT_PATTERN = re.compile(r'[А-Яа-яІіЇїЄєҐґ]')
_LIKELY_RUSSIAN_WORD_PATTERN = re.compile(
    r'\b(?:'
    r'уравнени(?:е|я)|определени(?:е|я)|решени(?:е|я)|рис(?:\.|унок)?|'
    r'свободно|опирающ|займемся|получаем|находится|сначала|вспомним|'
    r'пусть|покажем|рассмотрим|построение|общей|случае|метод|'
    r'преобразование|лекция|задачи|замечания'
    r')\b',
    flags=re.IGNORECASE,
)


def _preserve_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source.istitle():
        return replacement.capitalize()
    return replacement


def _needs_residual_translation(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if stripped.startswith(("```", "~~~", "#", "![](")):
        if not stripped.startswith("#"):
            return False

    lowered = stripped.lower()
    marker_hits = sum(
        len(re.findall(rf'\b{re.escape(marker)}\b', lowered))
        for marker in _RESIDUAL_RUSSIAN_MARKERS
    )
    has_russian_specific_letters = _RUSSIAN_SPECIFIC_LETTERS_PATTERN.search(stripped) is not None
    has_cyrillic_text = _CYRILLIC_TEXT_PATTERN.search(stripped) is not None
    has_likely_russian_words = _LIKELY_RUSSIAN_WORD_PATTERN.search(stripped) is not None
    is_heading_or_caption = stripped.startswith("#") or stripped.lower().startswith(("рис", "fig.", "lecture", "лекция"))

    if len(stripped) >= 80:
        return marker_hits >= 2 or has_russian_specific_letters or has_likely_russian_words

    if len(stripped) >= 35 and marker_hits >= 2:
        return True

    if is_heading_or_caption and has_cyrillic_text:
        return marker_hits >= 1 or has_russian_specific_letters or has_likely_russian_words

    if len(stripped) >= 8 and _RESIDUAL_SHORT_BLOCK_PREFIX_PATTERN.search(stripped):
        return has_russian_specific_letters or has_likely_russian_words or (has_cyrillic_text and marker_hits >= 1)

    return False


def retranslate_residual_russian_paragraphs(
    md_text: str,
    api_key: str,
    endpoint: str,
    region: str,
    target_lang: str = TARGET_LANG,
) -> str:
    if (
        _looks_like_placeholder_config_value(api_key)
        or _looks_like_placeholder_config_value(endpoint)
        or _looks_like_placeholder_config_value(region)
    ):
        log.info("Stage 4c – Residual translation skipped because Azure credentials are placeholders.")
        return md_text

    masked_text, elements = mask_elements(md_text)
    parts = re.split(r'(\n\s*\n+)', masked_text)
    translated_count = 0
    candidate_indices = [
        index
        for index, part in enumerate(parts)
        if part and not part.isspace() and _needs_residual_translation(part)
    ]

    def flush_batch(batch_items: list[tuple[int, str]]) -> None:
        nonlocal translated_count

        if not batch_items:
            return

        token_map: list[tuple[str, int]] = [
            (f"SEGMENTTOKEN{position:04d}XYZ", part_index)
            for position, (part_index, _segment_text) in enumerate(batch_items)
        ]
        batch_text = "\n\n".join(
            f"{token}\n{segment_text}"
            for (token, _part_index), (_batch_index, segment_text) in zip(token_map, batch_items)
        )

        try:
            translated_batch = translate_text_azure(
                text=batch_text,
                api_key=api_key,
                endpoint=endpoint,
                region=region,
                target_lang=target_lang,
                chunk_size=CHUNK_SIZE,
            )
        except Exception as exc:
            log.warning("  Residual batch could not be retranslated: %s", exc)
            for part_index, segment_text in batch_items:
                try:
                    translated_part = translate_text_azure(
                        text=segment_text,
                        api_key=api_key,
                        endpoint=endpoint,
                        region=region,
                        target_lang=target_lang,
                        chunk_size=CHUNK_SIZE,
                    )
                except Exception as segment_exc:
                    log.warning("  Residual paragraph %d could not be retranslated: %s", part_index, segment_exc)
                    continue

                if translated_part.strip():
                    parts[part_index] = translated_part
                    translated_count += 1
            return

        positions: list[tuple[str, int, int]] = []
        for token, part_index in token_map:
            token_offset = translated_batch.find(token)
            if token_offset == -1:
                positions = []
                break
            positions.append((token, part_index, token_offset))

        if not positions:
            log.warning("  Residual batch markers were not preserved; retrying the affected segments one by one.")
            for part_index, segment_text in batch_items:
                try:
                    translated_part = translate_text_azure(
                        text=segment_text,
                        api_key=api_key,
                        endpoint=endpoint,
                        region=region,
                        target_lang=target_lang,
                        chunk_size=CHUNK_SIZE,
                    )
                except Exception as segment_exc:
                    log.warning("  Residual paragraph %d could not be retranslated: %s", part_index, segment_exc)
                    continue

                if translated_part.strip():
                    parts[part_index] = translated_part
                    translated_count += 1
            return

        positions.sort(key=lambda item: item[2])
        for current_index, (token, part_index, token_offset) in enumerate(positions):
            next_offset = positions[current_index + 1][2] if current_index + 1 < len(positions) else len(translated_batch)
            translated_part = translated_batch[token_offset + len(token):next_offset].strip()
            if translated_part:
                parts[part_index] = translated_part
                translated_count += 1

    max_batch_chars = max(600, min(CHUNK_SIZE // 2, 3500))
    batch_items: list[tuple[int, str]] = []
    batch_chars = 0

    for part_index in candidate_indices:
        segment_text = parts[part_index].strip()
        projected_chars = batch_chars + len(segment_text) + 32
        if batch_items and projected_chars > max_batch_chars:
            flush_batch(batch_items)
            batch_items = []
            batch_chars = 0

        batch_items.append((part_index, segment_text))
        batch_chars += len(segment_text) + 32

    flush_batch(batch_items)

    if translated_count == 0:
        log.info("Stage 4c – No residual Russian paragraphs detected after masking.")
        return md_text

    merged_text = "".join(parts)
    unmasked_text = unmask_elements(merged_text, elements)
    cleaned_text = clean_markdown_formatting(unmasked_text)
    log.info("Stage 4c – Residual Russian paragraphs retranslated: %d.", translated_count)
    return cleaned_text


def _chunk_has_residual_translation_candidates(md_text: str) -> bool:
    parts = re.split(r'(\n\s*\n+)', md_text)
    return any(
        part and not part.isspace() and _needs_residual_translation(part)
        for part in parts
    )


def _maybe_retranslate_chunk_text(md_text: str) -> str:
    if not _chunk_has_residual_translation_candidates(md_text):
        return md_text

    try:
        updated_text = retranslate_residual_russian_paragraphs(
            md_text,
            api_key=AZURE_TRANSLATOR_KEY,
            endpoint=AZURE_TRANSLATOR_ENDPOINT,
            region=AZURE_TRANSLATOR_REGION,
            target_lang=TARGET_LANG,
        )
    except Exception as exc:
        log.warning("Chunk-level residual translation skipped after error: %s", exc)
        return md_text

    return updated_text if updated_text.strip() else md_text


def second_pass_cleanup(md_text: str) -> str:
    rescued_text = rescue_broken_latex(md_text)
    masked_text, elements = mask_elements(rescued_text)
    normalized = masked_text

    normalized = re.sub(r'^(#+)(\S)', r'\1 \2', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*ЦЕЛЬ ЛЕКЦИИ:\s*', 'МЕТА ЛЕКЦІЇ: ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*(#+)\s*ЗАДАЧИ\s*$', r'\1 ЗАДАЧІ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*(#+)\s*ЗАМЕЧ\s*АНИЯ\s*$', r'\1 ЗАУВАЖЕННЯ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*ЗАДАЧИ\s*$', 'ЗАДАЧІ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*ЗАМЕЧ\s*АНИЯ\s*$', 'ЗАУВАЖЕННЯ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*РИС(?:[.,]|\s)+\s*', 'Рис. ', normalized, flags=re.MULTILINE | re.IGNORECASE)
    normalized = re.sub(r'^\s*ТАБЛИЦА\s*', 'Таблиця ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*Лекция\s+(\d+)\s*$', r'Лекція \1', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*ЗАДАЧИ\s*$', 'Задачі', normalized, flags=re.MULTILINE)
    normalized = normalized.replace(
        "3) трехмерные волны называются сферическими волнами.",
        "3) тривимірні хвилі називаються сферичними хвилями.",
    )
    normalized = normalized.replace(
        "Запишем систему уравнений в матричной форме",
        "Запишемо систему рівнянь у матричній формі",
    )
    normalized = normalized.replace(
        "равно диагональной матрице",
        "дорівнює діагональній матриці",
    )
    normalized = normalized.replace(
        "где 1-единичная матрица.",
        "де I - одинична матриця.",
    )
    normalized = normalized.replace(
        "Некоторые собственные значения могут совпадать.",
        "Деякі власні значення можуть збігатися.",
    )
    normalized = re.sub(r'\bУ\s+равнение\b', 'Рівняння', normalized)
    normalized = re.sub(r'\bвытекающий\b', 'витікаючий', normalized)
    normalized = re.sub(r'\bравен\b', 'дорівнює', normalized)
    normalized = re.sub(r'\bкоэффициент диффузии\b', 'коефіцієнт дифузії', normalized, flags=re.IGNORECASE)

    for source, replacement in sorted(
        _SECOND_PASS_PHRASE_REPLACEMENTS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = re.compile(rf'(?<!\w){re.escape(source)}(?!\w)', flags=re.IGNORECASE)
        normalized = pattern.sub(
            lambda match, repl=replacement: _preserve_case(match.group(0), repl),
            normalized,
        )

    for source, replacement in _SECOND_PASS_WORD_REPLACEMENTS.items():
        pattern = re.compile(rf'\b{re.escape(source)}\b', flags=re.IGNORECASE)
        normalized = pattern.sub(
            lambda match, repl=replacement: _preserve_case(match.group(0), repl),
            normalized,
        )

    normalized = re.sub(r'[ \t]{2,}', ' ', normalized)
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)

    unmasked = unmask_elements(normalized, elements)
    return clean_markdown_formatting(unmasked)


def _apply_stable_text_normalizations(md_text: str) -> str:
    normalized = md_text

    # These replacements are intentionally conservative and avoid touching
    # free-form prose inside math blocks.
    normalized = re.sub(r'^\s*ЦЕЛЬ ЛЕКЦИИ:\s*', 'МЕТА ЛЕКЦІЇ: ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*(#+)\s*ЗАДАЧИ\s*$', r'\1 ЗАДАЧІ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*(#+)\s*ЗАМЕЧ\s*АНИЯ\s*$', r'\1 ЗАУВАЖЕННЯ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*ЗАДАЧИ\s*$', 'ЗАДАЧІ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*ЗАМЕЧ\s*АНИЯ\s*$', 'ЗАУВАЖЕННЯ', normalized, flags=re.MULTILINE)
    normalized = re.sub(r'^\s*РИС(?:[.,]|\s)+\s*', 'Рис. ', normalized, flags=re.MULTILINE | re.IGNORECASE)

    stable_replacements = {
        "3) трехмерные волны называются сферическими волнами.": "3) тривимірні хвилі називаються сферичними хвилями.",
        "Запишем систему уравнений в матричной форме": "Запишемо систему рівнянь у матричній формі",
        "равно диагональной матрице": "дорівнює діагональній матриці",
        "где 1-единичная матрица.": "де I - одинична матриця.",
        "Некоторые собственные значения могут совпадать.": "Деякі власні значення можуть збігатися.",
    }
    for source, replacement in stable_replacements.items():
        normalized = normalized.replace(source, replacement)

    return clean_markdown_formatting(normalized)


def _safe_second_pass_cleanup(md_text: str) -> str:
    cleaned = second_pass_cleanup(md_text)
    if "HIDE" in cleaned or _UNRESOLVED_PLACEHOLDER_PATTERN.search(cleaned):
        log.warning(
            "  Second-pass cleanup produced unresolved placeholders; reverting to formatting-only cleanup for this pass."
        )
        return _apply_stable_text_normalizations(md_text)
    return _apply_stable_text_normalizations(cleaned)


def _repair_known_source_markdown_artifacts(md_text: str) -> str:
    text = md_text

    direct_replacements: dict[str, str] = {
        (
            "де $\\alpha(x) = \\begin{cases} \\alpha_1 & \\text{(коэффициент диффузии в меди)}, "
            "\\quad 0 < x < L/2, \\\\ \\alpha_2 & \\text{(коэффициент диффузии в стали)}, "
            "\\quad L/2 < x < L. \\end{cases}$ # ЗАВДАННЯ"
        ): (
            "де\n\n$$\n"
            "\\alpha(x) = \\begin{cases}\n"
            "\\alpha_1, & \\text{коефіцієнт дифузії в міді}, \\quad 0 < x < L/2, \\\\\n"
            "\\alpha_2, & \\text{коефіцієнт дифузії в сталі}, \\quad L/2 < x < L.\n"
            "\\end{cases}\n"
            "$$\n\n# ЗАВДАННЯ"
        ),
        "$$u(0, t) = 0,$$ $u(1, t) = 0,$ Тоді як поводитиметься температура в стрижні U(x, t) при T > 0?": (
            "$$\n"
            "u(0, t) = 0, \\qquad u(1, t) = 0.\n"
            "$$\n\n"
            "Тоді як поводитиметься температура в стрижні $U(x, t)$ при $t > 0$?"
        ),
        (
            "$$(3.6) \\qquad \\begin{array}{ll} (\\mathrm{Y}\\mathrm{H}\\Pi) & u_t = \\alpha^2 u_{xx}, "
            "& 0 < x < 200, & 0 < t < \\infty, \\\\ u_x (0, \\, t) = 0, & \\\\ "
            "u_x (200, \\, t) = -\\frac{h}{k} \\left[ u \\, (200, \\, t) - 20 \\right], "
            "& 0 < t < \\infty, \\\\ (\\mathrm{HY}) & u \\, (x, \\, 0) = 0 \\, "
            "^{\\mathrm{o}}\\mathrm{C}, & 0 \\leqslant x \\leqslant 200, & \\end{array}$$"
        ): (
            "$$(3.6)\n"
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 200,\\ 0 < t < \\infty, \\\\\n"
            "(\\text{ГУ})\\quad & u_x(0,t) = 0, && 0 < t < \\infty, \\\\\n"
            "& u_x(200,t) = -\\frac{h}{k}\\left[u(200,t) - 20\\right], && 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = 0^\\circ\\mathrm{C}, && 0 \\leqslant x \\leqslant 200.\n"
            "\\end{aligned}\n"
            "$$"
        ),
        (
            "$$\\begin{array}{lll} (\\text{YHII}) & u_t = \\alpha^2 u_{xx}, & 0 < x < 1, & 0 < t < \\infty, "
            "\\\\ (\\text{FY}) & \\begin{cases} u\\left(0,\\,t\\right) = 0, \\\\ "
            "u_x\\left(1,\\,t\\right) = 1, \\\\ u\\left(x,\\,0\\right) = \\sin\\left(\\pi x\\right), "
            "& 0 \\leqslant x \\leqslant 1. \\\\ \\end{cases}$$"
        ): (
            "$$\n"
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
            "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u_x(1,t) = 1, && 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = \\sin(\\pi x), && 0 \\leqslant x \\leqslant 1.\n"
            "\\end{aligned}\n"
            "$$"
        ),
        (
            "$$\\begin{array}{lll} (\\text{УЧП}) & u_t = \\alpha^2 u_{xx}, & 0 < x < 1, & 0 < t < \\infty, "
            "\\\\ (\\text{ГУ}) & \\begin{cases} u_x \\, (0, \\, t) = 0, & 0 < t < \\infty, \\\\ "
            "u_x \\, (1, \\, t) = 0, & 0 < t < \\infty, \\end{cases} \\\\ "
            "(\\text{НУ}) & u \\, (x, \\, 0) = \\sin (\\pi x), & 0 \\leqslant x \\leqslant 1? \\\\ "
            "\\end{array}$$"
        ): (
            "$$\n"
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
            "(\\text{ГУ})\\quad & u_x(0,t) = 0,\\quad u_x(1,t) = 0, && 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = \\sin(\\pi x), && 0 \\leqslant x \\leqslant 1.\n"
            "\\end{aligned}\n"
            "$$"
        ),
        "$$ або $$": "або",
        (
            "$$\n\n\\alpha u_x(0, t) + \\beta u(0, t) = 0,\n\n$$ $\\gamma u_x(1, t) + \\delta u(1, t) = 0,$ "
            "де $\\alpha$ , $\\beta$ , $\\gamma$ і $\\delta$ — константи "
            "(граничні умови, задані в такій формі, називаються лінійними однорідними граничними умовами)."
        ): (
            "$$\n"
            "\\alpha u_x(0, t) + \\beta u(0, t) = 0, \\qquad "
            "\\gamma u_x(1, t) + \\delta u(1, t) = 0.\n"
            "$$\n\n"
            "де $\\alpha$, $\\beta$, $\\gamma$ і $\\delta$ — константи "
            "(граничні умови, задані в такій формі, називаються лінійними однорідними граничними умовами)."
        ),
        "$$\\{\\sin(n\\pi x); n=1, 2, \\ldots\\},\\$$": "$$\\{\\sin(n\\pi x)\\}_{n=1}^{\\infty}.$$",
        (
            "$$\\begin{array}{ll} (\\text{УЧП}) & u_t - a^2 u_{xx} = f\\left(x, \\ t\\right) & \\frac{\\beta_t}{97} "
            "\\\\ (\\text{ГУ}) & \\begin{cases} \\alpha_1 u_x\\left(0, \\ t\\right) + \\beta_1 "
            "u\\left(0, \\ t\\right) = g_1\\left(t\\right), \\\\ a_2 u_x\\left(L, \\ t\\right) + \\beta_2 "
            "u\\left(L, \\ t\\right) = g_2\\left(t\\right), \\end{cases} \\\\ "
            "(\\text{HУ}) & u\\left(x, \\ 0\\right) = \\varphi\\left(x\\right) \\end{array}$$"
        ): (
            "$$\n"
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t - a^2 u_{xx} = f(x,t), \\\\\n"
            "(\\text{ГУ})\\quad & \\alpha_1 u_x(0,t) + \\beta_1 u(0,t) = g_1(t), \\\\\n"
            "& \\alpha_2 u_x(L,t) + \\beta_2 u(L,t) = g_2(t), \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = \\varphi(x).\n"
            "\\end{aligned}\n"
            "$$"
        ),
        (
            "\\begin{array}{ll} (\\text{УЧП}) & u_t = u_{xx}, & 0 < x < 1, \\\\ "
            "(\\Gamma \\text{У}) & \\begin{cases} u_x(0, t) = 0, \\\\ u_x(1, t) + hu(1, t) = 1, "
            "\\\\ (\\text{HY}) & u(x, 0) = \\sin(\\pi x), \\end{cases} & 0 < x < 1, \\\\ "
            "0 < t < \\infty, \\\\ 0 \\le x \\le 1, \\end{array}"
        ): (
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t = u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
            "(\\text{ГУ})\\quad & u_x(0,t) = 0,\\quad u_x(1,t) + h u(1,t) = 1, && 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = \\sin(\\pi x), && 0 \\le x \\le 1.\n"
            "\\end{aligned}"
        ),
        (
            "\\begin{array}{lll} (\\mathrm{УЧ}\\Pi) & u_t = \\alpha^2 u_{xx}, & 0 < x < 1, & 0 < t < \\infty, "
            "\\\\ (7.1) & (\\Gamma\\mathrm{У}) & \\begin{cases} u_t(0, t) = 0 \\\\ "
            "u_x(1, t) + hu_t(1, t) = 0 \\end{cases} & \\text{(однородные } \\Gamma\\mathrm{У}), "
            "\\\\ (\\mathrm{H}\\mathrm{У}) & u_t(x, 0) = x, & 0 \\leq x \\leq 1. \\end{array}"
        ): (
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
            "(7.1)\\ (\\text{ГУ})\\quad & u(0,t) = 0,\\quad u_x(1,t) + h u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = x, && 0 \\leq x \\leq 1.\n"
            "\\end{aligned}"
        ),
        (
            "$$ \\begin{array}{ll} (\\text{УЧП}) & u_t = \\alpha^2 u_{xx} - \\beta u_x - \\gamma u, "
            "\\quad 0 < x < 1, \\quad 0 < t < \\infty \\\\ (\\text{ГУ}) & \\left\\{ \\begin{array}{ll} "
            "u\\left(0,\\ t\\right) = f\\left(t\\right), & 0 < t < \\infty, \\\\ "
            "u\\left(1,\\ t\\right) = g\\left(t\\right), & 0 < t < \\infty, \\\\ "
            "u\\left(x,\\ 0\\right) = \\varphi\\left(x\\right), & 0 \\leqslant x \\leqslant 1. "
            "\\end{array}\n$$"
        ): (
            "$$\n"
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx} - \\beta u_x - \\gamma u, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
            "(\\text{ГУ})\\quad & u(0,t) = f(t),\\quad u(1,t) = g(t), && 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 \\leqslant x \\leqslant 1.\n"
            "\\end{aligned}\n"
            "$$"
        ),
        (
            "$$\\begin{vmatrix} \\frac{dy}{dx} = -[\\xi_x/\\xi_y] = \\frac{B - \\sqrt{B^2 - 4AC}}{2A} = -2, "
            "\\\\ \\frac{dy}{dx} = -[\\eta_x/\\eta_y] = \\frac{B^{\\frac{1}{2}} + \\sqrt{B^2 - 4AC}}{2A} = 2.$$"
        ): (
            "$$\n"
            "\\begin{aligned}\n"
            "\\frac{dy}{dx} &= -\\frac{\\xi_x}{\\xi_y} = \\frac{B - \\sqrt{B^2 - 4AC}}{2A} = -2, \\\\\n"
            "\\frac{dy}{dx} &= -\\frac{\\eta_x}{\\eta_y} = \\frac{B + \\sqrt{B^2 - 4AC}}{2A} = 2.\n"
            "\\end{aligned}\n"
            "$$"
        ),
        (
            "$$(\\text{УЧП}) \\qquad u_{tt} = u_{x+}, \\quad -\\infty < x < \\infty, \\quad 0 < t < \\infty, "
            "\\\\ (\\text{HV}) \\qquad \\left\\{ \\begin{array}{ll} u(x, \\ 0) = e^{-x^2} \\\\ "
            "u_t(x, \\ 0) = 0. \\end{array} \\right. \\quad -\\infty < x < \\infty, \\\\ \\end{array}$$"
        ): (
            "$$\n"
            "\\begin{aligned}\n"
            "(\\text{УЧП})\\quad & u_{tt} = u_{xx}, && -\\infty < x < \\infty,\\ 0 < t < \\infty, \\\\\n"
            "(\\text{НУ})\\quad & u(x,0) = e^{-x^2},\\quad u_t(x,0) = 0, && -\\infty < x < \\infty.\n"
            "\\end{aligned}\n"
            "$$"
        ),
        "$$u_n(x, t) = R_n \\sin(n\\pi x/L) \\cos(n\\pi\\alpha (t - \\delta_n)/L],$$": (
            "$$u_n(x, t) = R_n \\sin\\left(\\frac{n\\pi x}{L}\\right) "
            "\\cos\\left(\\frac{n\\pi\\alpha (t - \\delta_n)}{L}\\right).$$"
        ),
        "\n \\right.\n": "\n",
    }

    for source, replacement in direct_replacements.items():
        text = text.replace(source, replacement)

    text = _replace_section_between_markers(
        text,
        "які задовольняють граничні умови",
        "![](images/_page_38_Figure_3.jpeg)",
        (
            "які задовольняють граничні умови\n\n"
            "$$\n"
            "u(0, t) = 0, \\qquad u(1, t) = 0.\n"
            "$$\n\n"
            "Для цього підставляємо розв'язки (5.1) у ці граничні умови. У результаті отримуємо\n\n"
            "$$\n"
            "u(0, t) = B e^{-\\lambda^2 \\alpha^2 t} = 0 \\Rightarrow B = 0,\n"
            "$$\n\n"
            "$$\n"
            "u(1, t) = A e^{-\\lambda^2 \\alpha^2 t}\\sin \\lambda = 0 \\Rightarrow \\sin \\lambda = 0.\n"
            "$$\n\n"
            "Отже,\n\n"
            "$$\n"
            "\\lambda_n = n\\pi, \\qquad n = 1, 2, \\ldots\n"
            "$$\n\n"
            "Зверніть увагу, що друга гранична умова могла б виконуватися і при $A=0$, "
            "але тоді розв'язок (5.1) був би тривіально нульовим.\n\n"
        ),
    )

    text = _replace_section_between_markers(
        text,
        "Ми отримаємо",
        "де $\\overline{\\phi}(x)$ — нова, але відома початкова умова.",
        (
            "Ми отримаємо\n\n"
            "(6.4)\n\n"
            "$$\n"
            "\\begin{aligned}\n"
            "U_t &= \\alpha^2 U_{xx}, && 0 < x < L, \\\\\n"
            "U(0,t) &= 0,\\quad U(L,t) = 0, && 0 < t < \\infty, \\\\\n"
            "U(x,0) &= \\varphi(x) - \\left[k_1 + \\frac{x}{L}(k_2 - k_1)\\right] = \\overline{\\varphi}(x).\n"
            "\\end{aligned}\n"
            "$$\n\n"
        ),
    )

    return text

def mask_elements(md_text: str, emit_log: bool = True) -> tuple[str, dict[str, str]]:
    elements_dict: dict[str, str] = {}
    block_idx  = 0
    inline_idx = 0
    image_idx  = 0

    result = md_text

    def _replace_block(match: re.Match) -> str:
        nonlocal block_idx
        ph = _PH_MATH_BLOCK.format(idx=block_idx)
        elements_dict[ph] = match.group(0)
        block_idx += 1
        return f"\n\n{ph}\n\n"

    for pattern, flags in _BLOCK_MATH_PATTERNS:
        result = re.sub(pattern, _replace_block, result, flags=flags)

    def _replace_inline(match: re.Match) -> str:
        nonlocal inline_idx
        ph = _PH_MATH_INLINE.format(idx=inline_idx)
        elements_dict[ph] = match.group(0)
        inline_idx += 1
        return f" {ph} "

    for pattern, flags in _INLINE_MATH_PATTERNS:
        result = re.sub(pattern, _replace_inline, result, flags=flags)

    def _replace_image(match: re.Match) -> str:
        nonlocal image_idx
        ph = _PH_IMAGE.format(idx=image_idx)
        elements_dict[ph] = match.group(0)
        image_idx += 1
        return f"\n\n{ph}\n\n"

    img_pattern, img_flags = _IMAGE_PATTERN
    result = re.sub(img_pattern, _replace_image, result, flags=img_flags)

    if emit_log:
        log.info(
            "Stage 2 – Masked %d block-math, %d inline-math, %d image(s).",
            block_idx, inline_idx, image_idx,
        )
    return result, elements_dict

def mask_math(md_text: str) -> tuple[str, dict[str, str]]:
    return mask_elements(md_text)

# ===========================================================================
# Stage 3 – Azure Translation
# ===========================================================================

def translate_text_azure(
    text: str,
    api_key: str,
    endpoint: str,
    region: str,
    target_lang: str = TARGET_LANG,
    chunk_size: int  = CHUNK_SIZE,
    retry_attempts: int   = 3,
    retry_delay:    float = 5.0,
) -> str:
    if _looks_like_placeholder_config_value(api_key) or _looks_like_placeholder_config_value(region):
        raise ValueError(
            "AZURE_TRANSLATOR_KEY or AZURE_TRANSLATOR_REGION is not configured with real values. "
            "Copy .env.template to .env and replace the placeholder values."
        )

    chunks = _chunk_text(text, chunk_size)

    db_path = BASE_DIR / "cache.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS translation_cache (md5 TEXT PRIMARY KEY, translated_text TEXT)"
        )

    constructed_url = endpoint.rstrip("/") + "/translate"
    params = {
        'api-version': '3.0',
        'from': 'ru',
        'to': target_lang,
        'textType': 'plain'
    }
    headers = {
        'Ocp-Apim-Subscription-Key': api_key,
        'Ocp-Apim-Subscription-Region': region,
        'Content-type': 'application/json',
    }

    def _parse_retry_after(header_value: Optional[str]) -> Optional[int]:
        if header_value is None:
            return None

        try:
            return max(int(float(header_value)), 0)
        except (TypeError, ValueError):
            return None

    def _translate_chunk(args_tuple) -> str:
        i, chunk = args_tuple
        chunk_md5 = hashlib.md5(chunk.encode('utf-8')).hexdigest()
        
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT translated_text FROM translation_cache WHERE md5 = ?", (chunk_md5,))
            row = cursor.fetchone()
            if row:
                cached_text = row[0]
                if any(token in cached_text for token in ("HIDE", "MATHBLK", "MATHINL")):
                    log.warning("  Chunk %d/%d – Ignoring poisoned cache entry and retranslating.", i, len(chunks))
                    conn.execute("DELETE FROM translation_cache WHERE md5 = ?", (chunk_md5,))
                else:
                    log.info("  Chunk %d/%d – Loaded from cache", i, len(chunks))
                    return cached_text

        log.info("  Chunk %d/%d – Transmitting %d chars …", i, len(chunks), len(chunk))
        for attempt in range(1, retry_attempts + 1):
            try:
                request_headers = headers.copy()
                request_headers['X-ClientTraceId'] = str(uuid.uuid4())
                body = [{'text': chunk}]

                response = requests.post(constructed_url, params=params, headers=request_headers, json=body, timeout=30)
                if response.status_code == 429:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    wait_seconds = retry_after + 5 if retry_after is not None else 20
                    log.warning("  [429] Rate limit hit! Waiting %d seconds...", wait_seconds)
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                res_data = response.json()
                res_text = res_data[0]['translations'][0]['text']
                
                with sqlite3.connect(db_path, timeout=10) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO translation_cache (md5, translated_text) VALUES (?, ?)", 
                        (chunk_md5, res_text)
                    )
                time.sleep(3.0)
                return res_text
                
            except Exception as exc:
                log.warning("  Chunk %d – attempt %d/%d failed: %s", i, attempt, retry_attempts, exc)
                if attempt == retry_attempts:
                    raise
                time.sleep(retry_delay * (2 ** (attempt - 1)))
        return ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        results = executor.map(_translate_chunk, enumerate(chunks, start=1))
        translated = list(results)

    log.info("Stage 3 – Translation complete.")
    return "\n\n".join(translated)

# ===========================================================================
# Stage 4 – Unmasking
# ===========================================================================

def unmask_elements(
    translated_text: str,
    elements_dict: dict[str, str],
) -> str:
    result = translated_text

    for placeholder, original in elements_dict.items():
        escaped = re.escape(placeholder)
        pattern = rf"\s*{escaped}\s*"

        is_block = (
            placeholder.startswith("MATHBLK")
            or placeholder.startswith("IMGTOKEN")
        )
        replacement = f"\n\n{original}\n\n" if is_block else f" {original} "

        result = re.sub(pattern, lambda _m, r=replacement: r, result)

    result = re.sub(r"\n{3,}", "\n\n", result)

    log.info("Stage 4 – Unmasking complete. %d element(s) restored.", len(elements_dict))
    return result

def unmask_math(translated_text: str, math_dict: dict[str, str]) -> str:
    return unmask_elements(translated_text, math_dict)

# ===========================================================================
# Stage 5 – Exporting via Pandoc
# ===========================================================================

_PDF_ENV_PATTERN = re.compile(r'\\(begin|end)\{([A-Za-z*]+)\}')
_INLINE_ENV_MATH_PATTERN = re.compile(
    r'(?<!\$)\$(?!\$)(?P<content>[^\n$]*\\begin\{[A-Za-z*]+\}.*?\\end\{[A-Za-z*]+\}[^\n$]*)'
    r'(?<!\$)\$(?!\$)'
)
_INLINE_DOLLAR_MATH_PATTERN = re.compile(r'(?<!\$)\$(?!\$)([^\n$]+?)(?<!\$)\$(?!\$)')
_INLINE_PAREN_MATH_PATTERN = re.compile(r'\\\(([^(\n]*?)\\\)')
_BARE_ENV_NAME_PATTERN = re.compile(
    r'\\begin\{(?:array|cases|aligned|split|matrix|pmatrix|bmatrix|vmatrix|Vmatrix|equation|eqnarray)\}'
)
_BARE_ARRAY_BEGIN_PATTERN = re.compile(r'\\begin\{array\}\{[^\}]*\}')
_MARKDOWN_IMAGE_LINK_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
_PAGE_MARKER_PATTERN = re.compile(r'images/_page_(?P<page>\d+)_')
_HEADING_LINE_PATTERN = re.compile(r'^\s*#{1,6}\s+')
_CHUNKED_IMAGE_FILENAME_PATTERN = re.compile(
    r'^chunk(?P<chunk>\d+)__page_(?P<page>\d+)_(?P<rest>.+)$'
)
_EXISTING_INLINE_OR_CODE_PATTERN = re.compile(
    r'(`[^`\n]+`|\\\([^\n]*?\\\)|(?<!\$)\$(?!\$)[^\n$]+?(?<!\$)\$(?!\$))'
)
_BARE_LEFT_RIGHT_INLINE_PATTERN = re.compile(
    r'(?P<expr>(?:[A-Za-z][A-Za-z0-9]*)?\\left\([^\\\n]{0,120}?\\right\)'
    r'(?:\s*=\s*[A-Za-z0-9\\{}_^(),.=+\-*/<>~ ]{1,120})?)'
)
_BARE_FRAC_INLINE_PATTERN = re.compile(
    r'(?P<expr>(?:[A-Za-z][A-Za-z0-9]*)?\s*=*\s*\\frac\{[^{}\n]{1,80}\}\{[^{}\n]{1,80}\}'
    r'(?:[A-Za-z0-9\\{}_^(),.=+\-*/<>~ ]{0,80})?)'
)
_BARE_FUNCTION_INLINE_PATTERN = re.compile(
    r'(?P<expr>\b[A-Za-z]\s*\([A-Za-z0-9,.\-+/=<>~ ]{1,40}\))'
)
_BARE_SUBSCRIPT_INLINE_PATTERN = re.compile(
    r'(?P<expr>\b[A-Za-z](?:_[A-Za-z0-9]+|_\{[^{}\n]{1,40}\}|\^\{[^{}\n]{1,40}\}|\'{1,2})+'
    r'(?:\s*=\s*[A-Za-z0-9\\{}_^(),.=+\-*/<>~ ]{1,80})?)'
)
_UNRESOLVED_PLACEHOLDER_PATTERN = re.compile(r'\b(?:MATHBLK|MATHINL|IMGTOKEN)\d{4}X\b')
_CROSSWORD_SECTION_PATTERN = re.compile(
    r'(?ms)^#+\s+\*{0,2}(?:КРОССВОРД|КРОСВОРД)\*{0,2}\s*$.*?(?=^#\s+|\Z)'
)
_INTEGRAL_TRANSFORM_APPENDIX_HEADING_PATTERN = re.compile(
    r'(?m)^#\s+ТАБЛИЦ[ІЫ]\s+ІНТЕГРАЛЬН(?:ИХ|ЫХ)\s+ПЕРЕТВОРЕНЬ\s*$'
)
_LAPLACE_APPENDIX_HEADING_PATTERN = re.compile(
    r'(?m)^\s*ТАБЛИЦ[ЯА]\s*F\.\s*(?:Перетворення|Преобразование)\s+Лапласа\s*$'
)
_END_MATTER_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sources", re.compile(r'(?m)^#\s+(?:Джерела|ДЖЕРЕЛА|Література|ЛІТЕРАТУРА|Источники|ИСТОЧНИКИ)\b.*$')),
    ("name index", re.compile(r'(?m)^#\s+ІНДЕКС\s+ІМЕН[ІI]?\b.*$')),
    ("subject index", re.compile(r'(?m)^#\s+ІНДЕКС\s+ПРЕДМЕТІВ\b.*$')),
    ("contents", re.compile(r'(?m)^#\s+ЗМІСТ\b.*$')),
)
_TAIL_SECTION_PAGE_MARGIN = 60
_BARE_TEX_EXPRESSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'(?P<expr>\([^()\n]{1,20}\)\(x\)\s*=\s*\\frac[^\n]+)'),
    re.compile(r'(?P<expr>J\[[^\]\n]+\]\s*=\s*\\i?int[^\n.]+)'),
    re.compile(r'(?P<expr>\\overline\{[^{}\n]+\}\([^()\n]{0,40}\)\s*=\s*\\[A-Za-z]+(?:\s*[A-Za-z0-9]+)?)'),
    re.compile(r'(?P<expr>\\overline\{[^{}\n]+\}\([^()\n]{0,40}\))'),
    re.compile(r'(?P<expr>\\overline\{[^{}\n]+\})'),
    re.compile(r'(?P<expr>\\bar\{[^{}\n]+\}(?:_\{?[^{}\s]+\}?)?)'),
    re.compile(r'(?P<expr>\\(?:alpha|beta|gamma|delta|theta|phi|varphi|omega|pi|Delta)\b)'),
)


def _resolve_image_target(target: str, images_dir: Path) -> Optional[str]:
    normalized_target = target.strip().replace("\\", "/")
    basename = Path(normalized_target).name

    direct_candidates = [normalized_target, basename]
    for candidate in direct_candidates:
        if (images_dir / candidate).exists():
            return candidate

    match = _CHUNKED_IMAGE_FILENAME_PATTERN.fullmatch(basename)
    if not match:
        return None

    chunk_index = int(match.group("chunk"))
    page_index = int(match.group("page"))
    global_page_index = (chunk_index - 1) * 50 + page_index
    candidate = f"_page_{global_page_index}_{match.group('rest')}"
    if (images_dir / candidate).exists():
        return candidate

    return None


def _normalize_image_links(md_text: str, images_dir: Path) -> str:
    def replace_link(match: re.Match[str]) -> str:
        alt_text, target = match.groups()
        normalized_target = target.strip().replace("\\", "/")
        lowered_target = normalized_target.lower()

        if (
            "://" in normalized_target
            or normalized_target.startswith(("images/", "./images/", "../", "/"))
            or lowered_target.startswith("data:")
        ):
            return f"![{alt_text}]({normalized_target})"

        resolved_target = _resolve_image_target(normalized_target, images_dir)
        if resolved_target is not None:
            return f"![{alt_text}](images/{resolved_target})"

        return match.group(0)

    return _MARKDOWN_IMAGE_LINK_PATTERN.sub(replace_link, md_text)


def _restore_unresolved_placeholders(md_text: str, source_md_text: str) -> str:
    unresolved = sorted(set(_UNRESOLVED_PLACEHOLDER_PATTERN.findall(md_text)))
    if not unresolved:
        return md_text

    rescued_source = rescue_broken_latex(source_md_text)
    _, elements_dict = mask_elements(rescued_source, emit_log=False)

    healed_text = md_text
    restored_count = 0
    missing_placeholders: list[str] = []

    for placeholder in unresolved:
        original = elements_dict.get(placeholder)
        if original is None:
            missing_placeholders.append(placeholder)
            continue

        replacement = (
            f"\n\n{original}\n\n"
            if placeholder.startswith(("MATHBLK", "IMGTOKEN"))
            else f" {original} "
        )
        occurrences = healed_text.count(placeholder)
        if occurrences:
            healed_text = healed_text.replace(placeholder, replacement)
            restored_count += occurrences

    if restored_count:
        log.info("  Restored %d unresolved placeholder occurrence(s) from the source Markdown.", restored_count)
    if missing_placeholders:
        log.warning("  Could not restore %d placeholder(s) because they were not found in the source map.", len(missing_placeholders))

    return healed_text


def _wrap_bare_inline_math_fragments(line: str) -> str:
    if not line.strip() or line.lstrip().startswith(("```", "~~~", "![](", "|")):
        return line

    placeholders: dict[str, str] = {}

    def stash(match: re.Match[str]) -> str:
        placeholder = f"PDFRAWPLACEHOLDER{len(placeholders):04d}"
        placeholders[placeholder] = match.group(0)
        return placeholder

    def wrap_candidate(match: re.Match[str]) -> str:
        original = match.group("expr")
        candidate = original.strip()

        if not candidate or "`" in candidate or "$" in candidate:
            return original
        if re.search(r'[А-Яа-яІіЇїЄєҐґ]{2,}', candidate):
            return original
        if not (
            "\\" in candidate
            or "_" in candidate
            or "^" in candidate
            or "=" in candidate
            or re.search(r'\b[A-Za-z]\s*\([^()\n]{1,40}\)', candidate)
        ):
            return original

        trailing = ""
        while candidate and candidate[-1] in ".,;:":
            trailing = candidate[-1] + trailing
            candidate = candidate[:-1].rstrip()

        if not candidate:
            return original

        return f"${candidate}$" + trailing

    working = _EXISTING_INLINE_OR_CODE_PATTERN.sub(stash, line)

    for pattern in (
        _BARE_LEFT_RIGHT_INLINE_PATTERN,
        _BARE_FRAC_INLINE_PATTERN,
        _BARE_SUBSCRIPT_INLINE_PATTERN,
        _BARE_FUNCTION_INLINE_PATTERN,
    ):
        working = pattern.sub(wrap_candidate, working)

    for placeholder, value in placeholders.items():
        working = working.replace(placeholder, value)

    return working


def _repair_unbalanced_math_environments(content: str) -> str:
    repaired = content
    env_patterns: tuple[tuple[str, str], ...] = (
        ("array", r'\\begin\{array\}\{[^\}]*\}'),
        ("cases", r'\\begin\{cases\}'),
        ("aligned", r'\\begin\{aligned\}'),
        ("split", r'\\begin\{split\}'),
        ("matrix", r'\\begin\{matrix\}'),
        ("pmatrix", r'\\begin\{pmatrix\}'),
        ("bmatrix", r'\\begin\{bmatrix\}'),
        ("vmatrix", r'\\begin\{vmatrix\}'),
        ("Vmatrix", r'\\begin\{Vmatrix\}'),
        ("equation", r'\\begin\{equation\}'),
        ("eqnarray", r'\\begin\{eqnarray\}'),
    )

    for env_name, begin_pattern in env_patterns:
        begin_count = len(re.findall(begin_pattern, repaired))
        end_count = len(re.findall(rf'\\end\{{{env_name}\}}', repaired))
        if end_count >= begin_count:
            continue

        # Only auto-close environments that already contain meaningful math content.
        if env_name == "array":
            has_meaningful_body = bool(re.search(r'&|\\\\', repaired))
        else:
            has_meaningful_body = len(repaired.strip()) > len(env_name) + 20

        if not has_meaningful_body:
            continue

        repaired += "".join(f" \\end{{{env_name}}}" for _ in range(begin_count - end_count))

    return repaired


def _normalize_array_column_specs(content: str) -> str:
    def replace_array(match: re.Match[str]) -> str:
        spec = match.group("spec")
        body = match.group("body")

        rows = [row for row in re.split(r'\\\\', body) if row.strip()]
        max_columns = max((row.count("&") + 1 for row in rows), default=1)
        current_columns = len(re.findall(r'[lcr]', spec))

        if max_columns <= current_columns:
            return match.group(0)

        return f"\\begin{{array}}{{{'l' * max_columns}}}{body}\\end{{array}}"

    return re.sub(
        r'\\begin\{array\}\{(?P<spec>[^\}]*)\}(?P<body>.*?)\\end\{array\}',
        replace_array,
        content,
        flags=re.DOTALL,
    )


def _normalize_pdf_math_content(content: str) -> str:
    normalized = content.strip()
    normalized = normalized.replace("`", "")
    normalized = normalized.replace(r'\$', '$').replace(r'\_', '_')
    normalized = _INLINE_PAREN_MATH_PATTERN.sub(lambda match: match.group(1), normalized)
    normalized = _INLINE_DOLLAR_MATH_PATTERN.sub(lambda match: match.group(1), normalized)
    normalized = normalized.replace(r'\[', '').replace(r'\]', '')
    normalized = _normalize_array_column_specs(normalized)
    normalized = _repair_unbalanced_math_environments(normalized)
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)
    return normalized


def _render_pdf_code_block(content: str) -> str:
    stripped = content.strip("\n")
    if not stripped:
        return "\n\n"

    safe_content = stripped.replace("~~~", "~~")
    return f"\n\n~~~\n{safe_content}\n~~~\n\n"


def _is_malformed_pdf_math(content: str) -> bool:
    if "MATHBLK" in content or "MATHINL" in content or "HIDE" in content:
        return True

    commands_with_cyrillic = re.search(r'\\[А-Яа-яІіЇїЄєҐґ]+', content)
    if commands_with_cyrillic:
        return True

    stripped_array_body = _BARE_ARRAY_BEGIN_PATTERN.sub("", content).replace(r"\end{array}", "").strip()
    if r"\begin{array}" in content and not stripped_array_body:
        return True

    # A valid multiline math environment such as \begin{cases}...\end{cases}
    # often starts with a standalone begin-line. Treat only a lone unmatched
    # begin-line as malformed; otherwise the balance check below should decide.
    if re.fullmatch(r'\s*\\begin\{[A-Za-z*]+\}\s*', content):
        return True

    if re.search(r'^\s*(#|- |\d+\.)', content, flags=re.MULTILINE):
        return True

    if content.count("{") != content.count("}"):
        return True

    env_balance: dict[str, int] = {}
    for kind, env in _PDF_ENV_PATTERN.findall(content):
        env_balance.setdefault(env, 0)
        env_balance[env] += 1 if kind == "begin" else -1

    return any(balance != 0 for balance in env_balance.values())


def _render_pure_pdf_math_or_code(content: str) -> str:
    if not content:
        return "\n\n"

    if _is_malformed_pdf_math(content):
        # Broken OCR math should not be allowed to kill the whole PDF build.
        return _render_pdf_code_block(content)

    # Pandoc handles Markdown display-math fences more reliably than raw \[...\]
    # blocks when the surrounding paragraph structure is noisy after OCR cleanup.
    return f"\n\n$$\n{content}\n$$\n\n"


def _looks_like_math_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    # If a line was explicitly neutralized as inline code, keep it out of the
    # math heuristics so later PDF cleanup does not re-promote it into TeX.
    if re.fullmatch(r'`[^`\n]+`', stripped):
        return False

    if stripped.startswith(("![](", "|", "#")):
        return False

    if re.fullmatch(r"\(?\d+(?:\.\d+)?\)?", stripped):
        return False

    if "$" in stripped:
        return False

    outside_text = re.sub(r'\\text\{.*?\}', '', stripped)
    outside_text = re.sub(r'\\[A-Za-z]+', '', outside_text)
    if re.search(r'[А-Яа-яІіЇїЄєҐґ]{2,}', outside_text):
        return False

    cyrillic_words = re.findall(r"[А-Яа-яІіЇїЄєҐґ]{3,}", outside_text)
    if len(cyrillic_words) >= 4:
        return False

    return bool(re.search(r'\\[A-Za-z]+|[=_^{}]|[<>]|(?:\d+\s*[+\-*/=])', stripped))


def _split_mixed_pdf_block(content: str) -> str:
    parts: list[str] = []
    math_buffer: list[str] = []

    def flush_math_buffer() -> None:
        if not math_buffer:
            return
        math_content = "\n".join(math_buffer).strip()
        parts.append(_render_pure_pdf_math_or_code(math_content))
        math_buffer.clear()

    def append_prose_line(raw_line: str) -> None:
        cleaned = re.sub(r'(?<!\$)\$(?!\$)', '', raw_line.strip())
        if not cleaned:
            parts.append("\n")
            return

        if re.search(r'\\[A-Za-z]+', cleaned):
            parts.append(_render_pdf_code_block(cleaned))
            return

        parts.append(f"{cleaned}\n\n")

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if _looks_like_math_line(line):
            math_buffer.append(line)
            continue

        flush_math_buffer()
        append_prose_line(line)

    flush_math_buffer()
    return "".join(parts)


def _render_pdf_math_or_code(content: str) -> str:
    normalized = _normalize_pdf_math_content(content)
    if not normalized:
        return "\n\n"

    lines = normalized.splitlines()
    has_math_lines = any(_looks_like_math_line(line) for line in lines)
    has_prose_lines = any(line.strip() and not _looks_like_math_line(line) for line in lines)

    if has_math_lines and has_prose_lines:
        return f"\n\n{_split_mixed_pdf_block(normalized).strip()}\n\n"

    if has_prose_lines and not has_math_lines:
        return f"\n\n{_split_mixed_pdf_block(normalized).strip()}\n\n"

    return _render_pure_pdf_math_or_code(normalized)


def _render_inline_pdf_math_or_code(content: str) -> str:
    normalized = _normalize_pdf_math_content(content)
    normalized_single_line = re.sub(r"\s+", " ", normalized).strip()
    if not normalized_single_line:
        return ""

    if (
        "\n" in normalized
        or r"\begin{" in normalized_single_line
        or r"\end{" in normalized_single_line
        or r"\\" in normalized_single_line
        or len(normalized_single_line) > 180
    ):
        return _render_pdf_math_or_code(normalized_single_line).strip()

    if _is_malformed_pdf_math(normalized_single_line):
        safe_text = normalized_single_line.replace("`", "'")
        return f"`{safe_text}`"

    return f"${normalized_single_line}$"


def _sanitize_inline_pdf_math_line(line: str) -> str:
    if _looks_like_math_line(line):
        return line

    placeholders: dict[str, str] = {}
    placeholder_index = 0

    def stash(value: str) -> str:
        nonlocal placeholder_index
        placeholder = f"PDFINLINEPLACEHOLDER{placeholder_index:04d}"
        placeholders[placeholder] = value
        placeholder_index += 1
        return placeholder

    line = _wrap_bare_inline_math_fragments(line)

    sanitized = _INLINE_PAREN_MATH_PATTERN.sub(
        lambda match: stash(_render_inline_pdf_math_or_code(match.group(1))),
        line,
    )
    sanitized = _INLINE_DOLLAR_MATH_PATTERN.sub(
        lambda match: stash(_render_inline_pdf_math_or_code(match.group(1))),
        sanitized,
    )
    sanitized = re.sub(r'(?<!\$)\$(?!\$)', '', sanitized)

    for placeholder, value in placeholders.items():
        sanitized = sanitized.replace(placeholder, value)

    return sanitized


def _sanitize_inline_pdf_math(text: str) -> str:
    lines = text.splitlines()
    sanitized_lines: list[str] = []
    in_code_block = False
    in_display_math = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            sanitized_lines.append(line)
            continue

        if stripped == "$$":
            in_display_math = not in_display_math
            sanitized_lines.append(line)
            continue

        if stripped == r"\[":
            in_display_math = True
            sanitized_lines.append(line)
            continue

        if stripped == r"\]":
            sanitized_lines.append(line)
            in_display_math = False
            continue

        if in_code_block or in_display_math or line.startswith("    "):
            sanitized_lines.append(line)
            continue

        sanitized_lines.append(_sanitize_inline_pdf_math_line(line))

    return "\n".join(sanitized_lines)


def _wrap_remaining_tex_fragments(text: str) -> str:
    lines = text.splitlines()
    wrapped_lines: list[str] = []
    in_code_block = False
    in_display_math = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            wrapped_lines.append(line)
            continue

        if stripped == "$$":
            in_display_math = not in_display_math
            wrapped_lines.append(line)
            continue

        if in_code_block or in_display_math or not stripped or "$" in line or line.lstrip().startswith("![]("):
            wrapped_lines.append(line)
            continue

        if _looks_like_math_line(line):
            wrapped_lines.append(line)
            continue

        placeholders: dict[str, str] = {}
        placeholder_index = 0

        def stash(match: re.Match[str]) -> str:
            nonlocal placeholder_index
            placeholder = f"PDFTEXPLACEHOLDER{placeholder_index:04d}"
            placeholders[placeholder] = match.group(0)
            placeholder_index += 1
            return placeholder

        working_line = _EXISTING_INLINE_OR_CODE_PATTERN.sub(stash, line)

        for pattern in _BARE_TEX_EXPRESSION_PATTERNS:
            working_line = pattern.sub(lambda match: f"${match.group('expr').strip()}$", working_line)

        for placeholder, original in placeholders.items():
            working_line = working_line.replace(placeholder, original)

        wrapped_lines.append(working_line)

    return "\n".join(wrapped_lines)


def _looks_like_dangerous_safe_pdf_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    if stripped.startswith(("![](", "#", "|", "```", "~~~", ">")):
        return False

    body = stripped
    list_match = re.match(r'^(?:[-*+]|\d+\.)\s+(?P<body>.*)$', stripped)
    if list_match:
        body = list_match.group("body").strip()

    if not body or (body.startswith("`") and body.endswith("`")):
        return False

    if (
        r"\begin{" in body
        or r"\end{" in body
        or r"\left" in body
        or r"\right" in body
        or r"\qquad" in body
        or r"\Delta" in body
        or r"\Дельта" in body
    ):
        return True

    if re.search(r'[A-Za-zА-Яа-я0-9)\]}]+\\[A-Za-zА-Яа-я]+', body):
        return True

    return _looks_like_math_line(body) and bool(re.search(r'\\[A-Za-zА-Яа-я]+', body))


def _neutralize_residual_safe_pdf_tex(text: str) -> str:
    lines = text.splitlines()
    neutralized_lines: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code_block = not in_code_block
            neutralized_lines.append(line)
            continue

        if in_code_block or not _looks_like_dangerous_safe_pdf_line(line):
            neutralized_lines.append(line)
            continue

        indent_match = re.match(r'^\s*', line)
        indent = indent_match.group(0) if indent_match else ""
        body = line[len(indent):].strip().replace("`", "'")
        neutralized_lines.append(f"{indent}`{body}`")

    return "\n".join(neutralized_lines)


def _replace_section_between_markers(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> str:
    start_index = text.find(start_marker)
    if start_index == -1:
        return text

    end_index = text.find(end_marker, start_index)
    if end_index == -1 or end_index <= start_index:
        return text

    cleaned_replacement = replacement.rstrip() + "\n\n"
    return text[:start_index] + cleaned_replacement + text[end_index:]


def _replace_nearest_section_before_marker(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    *,
    max_distance: int,
) -> str:
    """
    Replaces the nearest matching section before ``end_marker``.

    This is used for late-book repair snippets where a generic heading like
    ``# ЗАДАЧИ`` may appear many times across the manuscript; blindly replacing
    from the first occurrence can wipe large portions of the book.
    """
    end_index = text.find(end_marker)
    if end_index == -1:
        return text

    start_index = text.rfind(start_marker, 0, end_index)
    if start_index == -1:
        return text

    if end_index - start_index > max_distance:
        return text

    cleaned_replacement = replacement.rstrip() + "\n\n"
    return text[:start_index] + cleaned_replacement + text[end_index:]


def _repair_known_pdf_math_artifacts(text: str) -> str:
    text = text.replace("(чорт)(x)", "(f * g)(x)")
    text = text.replace(r"\sqrt{2$\pi$}", r"\sqrt{2\pi}")
    text = text.replace(r"\begin{array}{ll}", r"\begin{array}{lll}")
    text = text.replace(r"\begin{array}{lll}", r"\begin{array}{llll}")
    text = text.replace(r"\Лямбда", r"\Lambda")
    text = text.replace(r"r_\лямбда", r"r_x")
    text = text.replace(r"\Дельта", r"\Delta")
    text = text.replace(r"(\text{\GammaY})", r"(\text{ГУ})")
    text = text.replace(r"(\text{YUII})", r"(\text{УЧП})")
    text = text.replace(r"\left( \Gamma \text{Y} \right)", r"(\text{ГУ})")
    text = text.replace(r"(\text{UCH}\Pi)", r"(\text{УЧП})")
    text = text.replace(r"(\text{UBP})", r"(\text{УЧП})")
    text = text.replace(r"(\text{HY})", r"(\text{НУ})")
    text = text.replace(r"(HY)", r"(\text{НУ})")
    text = re.sub(
        r"5\.\s*Перевірити, чи можна записати згортку двох функцій f і g у двох еквівалентних формах\s*"
        r"\(f \* g\)\(x\)\s*=\s*\\frac\{1\}\{\\sqrt\{2\\pi\}\}\s*\\int_\{-\\infty\}\^\{\+\\infty\}\s*f\(\\xi\)\s*g\(x\s*-\s*\\xi\)\s*d\\xi\s*"
        r"или\s*"
        r"\(f \* g\)\(x\)\s*=\s*\\frac\{1\}\{\\sqrt\{2\\pi\}\}\s*\\int_\{-\\infty\}\^\{\+\\infty\}\s*f\(x-\\xi\)\s*g\(\\xi\)\s*d\\xi\.",
        lambda _match: (
            "5. Перевірити, чи можна записати згортку двох функцій $f$ і $g$ у двох еквівалентних формах:\n\n"
            "$$\n"
            "(f * g)(x) = \\frac{1}{\\sqrt{2\\pi}} \\int_{-\\infty}^{+\\infty} f(\\xi) g(x - \\xi)\\, d\\xi\n"
            "$$\n\n"
            "або\n\n"
            "$$\n"
            "(f * g)(x) = \\frac{1}{\\sqrt{2\\pi}} \\int_{-\\infty}^{+\\infty} f(x-\\xi) g(\\xi)\\, d\\xi.\n"
            "$$"
        ),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"- 1\. Які з цих параболічних і еліптичних рівнянь записуються у канонічній формі:\s*"
        r"- a\)\s*u_t = u_\{xx\} hu\s*,\s*"
        r"- 6\)\s*u_\{xy\} \+ u_\{xx\} \+ 3u = \\sin x\s*,\s*"
        r"- \\mathbf\{B\}\)\s*\\ \\hat\{u_\{xx\}\} \+ 2\\hat\{u_\{yy\}\} = 0,\s*- \\mathbf\{r\}\)\s*\\ u_\{xx\} = \\sin\^{}2 x \?",
        lambda _match: (
            "- 1. Які з цих параболічних і еліптичних рівнянь записані у канонічній формі:\n\n"
            "a) $u_t = u_{xx} + hu$,\n\n"
            "б) $u_{xy} + u_{xx} + 3u = \\sin x$,\n\n"
            "в) $u_{xx} + 2u_{yy} = 0$,\n\n"
            "г) $u_{xx} = \\sin^2 x$ ?"
        ),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\\\[\s*u\\left\(x,\\,t\\right\)=\s*\\\]\s*"
        r"стаціонарна \+ тимчасова = \\uparrow \\uparrow .*?"
        r"U\\left\( x,\\,t\\right\) \. Заміна",
        lambda _match: (
            "Стаціонарна + тимчасова. Частина розв'язку, що залежить від початкової умови, "
            "прямує до нуля при $t \\\\to \\\\infty$. Тому покладемо\n\n"
            "\\[\n"
            "u(x, t) = \\left[k_1 + \\frac{x}{L}(k_2 - k_1)\\right] + U(x, t).\n"
            "\\]\n\n"
            "У цьому випадку наше завдання — знайти перехідну температуру \\(U(x, t)\\). Заміна"
        ),
        text,
        flags=re.DOTALL,
    )

    text = text.replace(
        "с вероятностью`\\frac{1}{2(1+\\sin`x_j`)} , (i, j-1)`"
        "с вероятностью`\\frac{1}{2(1+\\sin`x_j`)} , (i+1, j)`"
        "с вероятностью`\\frac{\\sin`x_j$}{2(1+\\sin$x_j`)} , (i-1, j)`"
        "с вероятностью`\\frac{\\sin`x_j$}{2(1+\\sin$x_j`)}`.",
        "з імовірністю $\\frac{1}{2(1+\\sin x_j)}$ у точку $(i, j-1)$, "
        "з імовірністю $\\frac{1}{2(1+\\sin x_j)}$ у точку $(i+1, j)$, "
        "з імовірністю $\\frac{\\sin x_j}{2(1+\\sin x_j)}$ у точку $(i-1, j)$ "
        "і з імовірністю $\\frac{\\sin x_j}{2(1+\\sin x_j)}$.",
    )

    text = text.replace(
        "u\\left(1 +$\\frac{1}{4}\\sin\\theta, \\theta\\right) = \\cos\\theta$.### Лекція 47",
        "\\(u\\left(1 + \\frac{1}{4}\\sin\\theta, \\theta\\right) = \\cos\\theta\\).\n\n### Лекція 47",
    )
    text = re.sub(
        r'J\{\[\}(.*?)\{\]\}',
        lambda match: f"J[{match.group(1)}]",
        text,
    )
    text = text.replace(
        r"u(x, t) = \left\{ g_1(t) + \frac{x}{L} \left\right\} + U(x, t).",
        r"u(x, t) = \left[g_1(t) + \frac{x}{L}\bigl(g_2(t) - g_1(t)\bigr)\right] + U(x, t).",
    )

    text = text.replace(
        "Частотный спектр служит мерой вклада частоты 🕇 в функ-",
        "Частотний спектр є мірою внеску частоти $\\xi$ у функ-",
    )
    text = text.replace(
        "<b>≢Tection</b>",
        "<b>Розділ</b>",
    )

    integral_transform_table = (
            "Таблиця 10.1. Деякі пари інтегральних перетворень\n\n"
            "1. Синус-перетворення Фур'є:\n\n"
            "\\[\n"
            "\\mathcal{F}_s[f](\\omega) = \\frac{2}{\\pi}\\int_0^\\infty f(t)\\sin(\\omega t)\\,dt,\n"
            "\\]\n\n"
            "\\[\n"
            "\\mathcal{F}_s^{-1}[F](t) = \\int_0^\\infty F(\\omega)\\sin(\\omega t)\\,d\\omega.\n"
            "\\]\n\n"
            "2. Косинус-перетворення Фур'є:\n\n"
            "\\[\n"
            "\\mathcal{F}_c[f](\\omega) = \\frac{2}{\\pi}\\int_0^\\infty f(t)\\cos(\\omega t)\\,dt,\n"
            "\\]\n\n"
            "\\[\n"
            "\\mathcal{F}_c^{-1}[F](t) = \\int_0^\\infty F(\\omega)\\cos(\\omega t)\\,d\\omega.\n"
            "\\]\n\n"
            "3. Перетворення Фур'є:\n\n"
            "\\[\n"
            "\\mathcal{F}[f](\\omega) = \\frac{1}{\\sqrt{2\\pi}}\\int_{-\\infty}^{\\infty} f(x)e^{-i\\omega x}\\,dx,\n"
            "\\]\n\n"
            "\\[\n"
            "\\mathcal{F}^{-1}[F](x) = \\frac{1}{\\sqrt{2\\pi}}\\int_{-\\infty}^{\\infty} F(\\omega)e^{i\\omega x}\\,d\\omega.\n"
            "\\]\n\n"
            "4. Скінченне синус-перетворення:\n\n"
            "\\[\n"
            "S_n = \\frac{2}{L}\\int_0^L f(x)\\sin\\!\\left(\\frac{n\\pi x}{L}\\right) dx,\n"
            "\\]\n\n"
            "\\[\n"
            "f(x) = \\sum_{n=1}^{\\infty} S_n \\sin\\!\\left(\\frac{n\\pi x}{L}\\right).\n"
            "\\]\n\n"
            "5. Скінченне косинус-перетворення:\n\n"
            "\\[\n"
            "C_n = \\frac{2}{L}\\int_0^L f(x)\\cos\\!\\left(\\frac{n\\pi x}{L}\\right) dx,\n"
            "\\]\n\n"
            "\\[\n"
            "f(x) = \\frac{C_0}{2} + \\sum_{n=1}^{\\infty} C_n \\cos\\!\\left(\\frac{n\\pi x}{L}\\right).\n"
            "\\]\n\n"
            "6. Перетворення Лапласа:\n\n"
            "\\[\n"
            "\\mathcal{L}[f](s) = \\int_0^\\infty e^{-st}f(t)\\,dt,\n"
            "\\]\n\n"
            "\\[\n"
            "\\mathcal{L}^{-1}[F](t) = \\frac{1}{2\\pi i}\\int_{\\gamma-i\\infty}^{\\gamma+i\\infty} e^{st}F(s)\\,ds.\n"
            "\\]\n\n"
            "7. Перетворення Ханкеля:\n\n"
            "\\[\n"
            "H\\{f\\}(\\xi) = F_n(\\xi) = \\int_0^\\infty r J_n(\\xi r) f(r)\\,dr,\n"
            "\\]\n\n"
            "\\[\n"
            "H^{-1}[F_n](r) = \\int_0^\\infty \\xi J_n(\\xi r) F_n(\\xi)\\,d\\xi.\n"
            "\\]\n\n"
            "Однак перед тим, як перейти до вивчення інтегральних перетворень,"
    )
    text = re.sub(
        r"Таблиця 10\.1 Деякі пари інтегральних перетворень.*?Однак перед тим, як перейти до вивчення інтегральних перетворень,",
        lambda _match: integral_transform_table,
        text,
        flags=re.DOTALL,
    )

    green_function_block = (
        "1. Початкової температури $\\phi(\\xi)$,\n\n"
        "2. Функції\n\n"
        "$$\n"
        "G(x, t) = \\frac{1}{2\\alpha \\sqrt{\\pi t}} e^{-(x-\\xi)^2/4\\alpha^2 t},\n"
        "$$\n\n"
        "яка називається функцією Гріна або функцією джерела.\n\n"
        "Можна показати, що функція джерела $G(x, t)$ описує відгук системи на початковий "
        "одиничний температурний імпульс у точці $x=\\xi$.\n\n"
        "![](images/_page_94_Figure_9.jpeg)\n\n"
        "Рис. 12.2. Відгук $G(x,t)$ на температурний імпульс у точці $x=\\xi$. Графік "
        "$G(x,t)$ подібний до кривої нормального розподілу; час відіграє роль "
        "середньоквадратичного відхилення: при малих $t$ функція вузька, а зі зростанням $t$ "
        "помітно розширюється.\n\n"
        "Іншими словами, функція $G(x, t)$ описує розподіл температури в стрижні в момент часу "
        "$t$, якщо на точку $x=\\xi$ подіяв одиничний тепловий імпульс (див. рис. 12.2).\n\n"
        "Тепер формулі (12.9) можна дати таку інтерпретацію: початкову температуру "
        "$u(x,0)=\\phi(x)$ можна розглядати як неперервну сукупність точкових імпульсів "
        "величини $\\phi(\\xi)$ у точці $x=\\xi$. Кожен точковий імпульс дає розподіл "
        "температури $\\phi(\\xi)G(x,t)$. Підсумковий розподіл знаходиться сумуванням "
        "(інтегруванням) температур від точкових джерел за формулою (12.9). Пізніше ми "
        "побачимо, що це один із проявів загального принципу суперпозиції."
    )
    text = _replace_section_between_markers(
        text,
        "1. Начальной температуры $q(x)$,",
        "# ЗАМЕЧАНИЕ",
        green_function_block,
    )

    heat_halfspace_problem = (
        "(13.6)\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx}, && 0 < x < \\infty,\\; 0 < t < \\infty, \\\\\n"
        "(\\Gamma \\text{У})\\quad & u_x(0,t) - u(0,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = u_0, && 0 < x < \\infty.\n"
        "\\end{aligned}\n"
        "$$"
    )
    text = re.sub(
        r"\(13\.6\)\s*\n+\$\$\s*\\begin\{array\}\{lll\}.*?\\end\{array\}\s*\$\$",
        lambda _match: heat_halfspace_problem,
        text,
        flags=re.DOTALL,
    )

    canonical_tasks_block = (
        "# ЗАВДАННЯ\n\n"
        "1. Які з цих параболічних і еліптичних рівнянь записані у канонічній формі?\n\n"
        "a) $u_t = u_{xx} + hu$,\n\n"
        "б) $u_{xy} + u_{xx} + 3u = \\sin x$,\n\n"
        "в) $u_{xx} + 2u_{yy} = 0$,\n\n"
        "г) $u_{xx} = \\sin^2 x$?\n\n"
        "2. Перетворіть параболічне рівняння $u_{xx} + 2u_{xy} + u_{yy} + u = 2$ "
        "до канонічної форми.\n\n"
        "3. Перетворіть еліптичне рівняння "
        "$u_{xx} + 2u_{yy} + x^2 u_x = e^{-x^2/2}$ до канонічної форми."
    )
    text = re.sub(
        r"# ЗАВДАННЯ\s*\n+\- 1\. Які з цих параболічних і еліптичних рівнянь.*?(?=# МЕТОД МОНТЕ-КАРЛО \(ВСТУП\))",
        lambda _match: canonical_tasks_block + "\n\n",
        text,
        flags=re.DOTALL,
    )

    variational_intro_block = (
        "# КАЛЬКУЛЮС ВАРІАЦІЙ (РІВНЯННЯ ЕЙЛЕРА-ЛАГРАНЖА)\n\n"
        "МЕТА ЛЕКЦІЇ: Ввести поняття функціоналу, тобто функції від функції, і пояснити, "
        "як функціонали природно виникають у фізиці. Типовим функціоналом є інтеграл\n\n"
        "$$\n"
        "J[y] = \\int_a^b F(x, y, y')\\,dx,\n"
        "$$\n\n"
        "який є функцією від функції $y$ (при цьому вважається, що підінтегральна функція "
        "$F(x, y, y')$ задана). Приклад функціоналу:\n\n"
        "$$\n"
        "J[y] = \\int_0^1 \\left[y^2(x) + y'^2(x)\\right] dx.\n"
        "$$\n\n"
        "Ми покажемо, як знайти функцію $\\overline{y}(x)$, що мінімізує функціонал $J[y]$. "
        "Виявляється, що мінімізуюча функція $\\overline{y}$ повинна задовольняти так зване "
        "рівняння Ейлера-Лагранжа. Воно відіграє ту саму роль, що й необхідна умова мінімуму\n\n"
        "$$\n"
        "\\frac{df(x)}{dx} = 0\n"
        "$$\n\n"
        "для функції $f(x)$ у точці $x$ в диференціальному численні.\n\n"
        "Варіаційне числення тісно пов'язане з диференціальними рівняннями, але, на жаль, "
        "більшість студентів його не вивчає. У цій лекції (і наступній) подається вступ до "
        "варіаційного числення та показано, як можна розв'язувати диференціальні рівняння в "
        "частинних похідних на основі варіаційних принципів.\n\n"
        "Варіаційне числення виникло одночасно з математичним аналізом у зв'язку з "
        "розв'язанням задач максимізації та мінімізації функцій від функцій, тобто "
        "функціоналів. Першою задачею варіаційного числення була задача про брахістохрону, "
        "сформульована Йоганном Бернуллі у 1696 році. У цій задачі потрібно знайти криву "
        "$y(x)$ так, щоб мінімізувати час спуску без тертя з однієї точки в іншу "
        "(див. рис. 44.1).\n\n"
        "Бернуллі показав, що час спуску записується у вигляді\n\n"
        "$$\n"
        "T = \\int_0^T dt = \\int_a^L \\frac{dt}{ds}\\,ds = \\int_0^L \\frac{ds}{v}\n"
        "= \\frac{1}{\\sqrt{2mg}} \\int_0^L \\frac{ds}{\\sqrt{y}}\n"
        "= \\frac{1}{\\sqrt{2mg}} \\int_a^b \\sqrt{\\frac{1+y'^2}{y}}\\,dy\n"
        "$$\n\n"
        "і, отже, є функціоналом $T\\{y\\}$ від функції. Оскільки багато функціоналів мають "
        "подібну будову, ми зосередимося на вивченні функціоналу загального вигляду\n\n"
        "(44.1)\n"
        "$$\n"
        "J[y] = \\int_a^b F(x, y, y')\\,dx.\n"
        "$$\n\n"
        "Тепер сформулюємо головну мету лекції: знайти функцію, яка доставляє мінімум "
        "(або максимум) функціоналу (44.1). Стратегія пошуку буде такою ж, як і при "
        "пошуку мінімуму функції у звичайному диференціальному численні. Там ми шукали "
        "критичні точки з умови $f'(x)=0$. У варіаційному численні все дещо складніше, "
        "бо аргументом є не число, а функція. Проте загальний підхід той самий: "
        "ми обчислимо функціональну похідну за функцією $y(x)$ і прирівняємо її до нуля. "
        "Нове рівняння буде аналогом умови $df(x)/dx = 0$, але тепер це буде звичайне "
        "диференціальне рівняння, відоме як рівняння Ейлера-Лагранжа.\n\n"
        "Мінімізація функціоналу\n\n"
        "$$\n"
        "J[y] = \\int_a^b F(x, y, y')\\,dx\n"
        "$$\n\n"
        "Розглянемо задачу знаходження функції $y(x)$, яка мінімізує цей функціонал у "
        "класі гладких функцій, що задовольняють граничним умовам\n\n"
        "$$\n"
        "y(a) = A, \\qquad y(b) = B.\n"
        "$$\n\n"
        "(див. рис. 44.2).\n\n"
        "Нехай шукана функція $y = \\overline{y}(x)$ існує, і розглянемо малу варіацію "
        "цієї функції, тобто функцію $\\overline{y} + \\varepsilon\\eta(x)$, де "
        "$\\varepsilon$ — мале число, а $\\eta(x)$ — гладка функція, яка задовольняє "
        "граничним умовам $\\eta(a)=\\eta(b)=0$.\n\n"
        "Тоді, якщо обчислити інтеграл $J$ для близької функції "
        "$\\overline{y} + \\varepsilon\\eta$, функціонал зросте, тобто\n\n"
        "$$\n"
        "J[\\overline{y}] \\leqslant J[\\overline{y} + \\varepsilon\\eta]\n"
        "$$\n\n"
        "для всіх $\\varepsilon$. Іншими словами, графік "
        "$\\varphi(\\varepsilon)=J[\\overline{y}+\\varepsilon\\eta]$ як функції "
        "$\\varepsilon$ має вигляд, показаний на рис. 44.3.\n\n"
        "![](images/_page_329_Figure_5.jpeg)\n\n"
        "Рис. 44.1. Задача про брахістохрону (з цієї задачі почалося варіаційне числення).\n\n"
        "![](images/_page_329_Figure_7.jpeg)\n\n"
        "Рис. 44.2. Варіація функції: a — варіація функції "
        "$\\overline{y}(x)+\\varepsilon\\eta(x)$; б — мінімізуюча функція "
        "$\\overline{y}(x)$.\n\n"
        "З рис. 44.3 видно, що тут потрібно обчислити похідну від\n\n"
        "$$\n"
        "\\varphi(\\varepsilon) = J[\\overline{y} + \\varepsilon\\eta]\n"
        "$$\n\n"
        "за $\\varepsilon$, покласти $\\varepsilon = 0$ і прирівняти отриманий вираз до нуля, "
        "тобто\n\n"
        "$$\n"
        "\\frac{d\\varphi(\\varepsilon)}{d\\varepsilon}\n"
        "= \\frac{d}{d\\varepsilon} J[\\overline{y} + \\varepsilon\\eta]\\bigg|_{\\varepsilon=0}\n"
        "= \\int_a^b \\left[\n"
        "\\frac{\\partial F}{\\partial \\overline{y}}\\eta(x)\n"
        "+ \\frac{\\partial F}{\\partial \\overline{y'}}\\eta'(x)\n"
        "\\right] dx = 0.\n"
        "$$\n\n"
        "(Читач має виконати це обчислення самостійно.) Інтегруючи частинами, дістаємо\n\n"
        "$$\n"
        "\\frac{d\\varphi(\\varepsilon)}{d\\varepsilon}\n"
        "\\equiv \\int_a^b \\left\\{\n"
        "\\frac{\\partial F}{\\partial \\overline{y}} - "
        "\\frac{d}{dx}\\left[\\frac{\\partial F}{\\partial \\overline{y'}}\\right]\n"
        "\\right\\} \\eta(x)\\,dx = 0.\n"
        "$$\n\n"
        "Оскільки цей інтеграл дорівнює нулю для будь-якої функції $\\eta(x)$, яка "
        "задовольняє граничним умовам $\\eta(a)=\\eta(b)=0$, то підінтегральний вираз "
        "має дорівнювати нулю, тобто\n\n"
        "![](images/_page_330_Figure_6.jpeg)\n\n"
        "Рис. 44.3. Графік функції $J[y+\\varepsilon\\eta]$ в околі $\\varepsilon=0$.\n\n"
        "(44.2)\n"
        "$$\n"
        "\\frac{\\partial F}{\\partial \\overline{y}} - "
        "\\frac{d}{dx}\\left[\\frac{\\partial F}{\\partial \\overline{y'}}\\right] = 0\n"
        "$$\n\n"
        "(рівняння Ейлера-Лагранжа).\n\n"
        "Рівняння (44.2) називається рівнянням Ейлера-Лагранжа. Хоча в загальному вигляді "
        "воно здається складним, після підстановки конкретної функції $F(x,y,y')$ воно "
        "перетворюється на звичайне диференціальне рівняння другого порядку відносно "
        "невідомої функції $\\overline{y}(x)$. Отже, щоб визначити мінімізуючу функцію "
        "$\\overline{y}$, треба розв'язати рівняння Ейлера-Лагранжа.\n\n"
        "Отже, ми показали, що якщо функція $y(x)$ мінімізує функціонал "
        "$J[y] = \\int_a^b F(x,y,y')\\,dx$ у класі гладких функцій із граничними умовами "
        "$y(a)=A$ і $y(b)=B$, то вона повинна задовольняти рівнянню\n\n"
        "$$\n"
        "\\frac{\\partial F}{\\partial y} - \\frac{d}{dx}\\left[\\frac{\\partial F}{\\partial y'}\\right] = 0.\n"
        "$$\n\n"
        "(Для спрощення позначень ми прибрали риску над $\\overline{y}$.) Для ілюстрації "
        "теорії розглянемо приклад.\n"
    )
    text = re.sub(
        r"# КАЛЬКУЛЮС ВАРІАЦІЙ \(РІВНЯННЯ ЕЙЛЕРА[–-]ЛАГРАНЖА\).*?(?=(?:Пошук мінімальної функціональності|Нахождение минимума функционала)\s+\$J\[y\])",
        lambda _match: variational_intro_block + "\n\n",
        text,
        flags=re.DOTALL,
    )

    fourier_sine_second_derivative_block = (
        "Для члена $\\mathcal{F}_s[u_{xx}]$ маємо\n\n"
        "$$\n"
        "\\mathcal{F}_s[u_{xx}] = \\frac{2}{\\pi}\\omega u(0,t) - \\omega^2 \\mathcal{F}_s[u]\n"
        "= \\frac{2A\\omega}{\\pi} - \\omega^2 U(t).\n"
        "$$\n\n"
    )
    text = _replace_section_between_markers(
        text,
        ". ${\\mathscr F}_s[u_{xx}]$ : Для цього елемента дійсні наступні рівняння:",
        "Зверніть увагу, що при виведенні відношень (10.1)",
        fourier_sine_second_derivative_block,
    )

    text = text.replace(
        "~~~\n|F(\\xi)| = \\sqrt{\\frac{1}{2\\pi(1+\\xi^2)}}\n~~~",
        "$$\n\\left|F(\\xi)\\right| = \\sqrt{\\frac{1}{2\\pi(1+\\xi^2)}}\n$$",
    )
    text = text.replace(
        "$$\n|F(\\xi)| = \\sqrt{\\frac{1}{2\\pi(1+\\xi^2)}}\n$$",
        "$$\n\\left|F(\\xi)\\right| = \\sqrt{\\frac{1}{2\\pi(1+\\xi^2)}}\n$$",
    )
    text = text.replace(
        "|F(\\xi)| = \\sqrt{\\frac{1}{1+\\xi^2}}.",
        "$$\n\\left|F(\\xi)\\right| = \\sqrt{\\frac{1}{1+\\xi^2}}\n$$",
    )

    text = re.sub(
        r"\$\$\s*u\(0,t\)=0\s*\\left\(.*?Рис\. 14\.1\. Часово-залежні граничні умови\.",
        (
            "На лівому кінці підтримується умова $u(0,t)=0$, а на правому кінці "
            "температура задається функцією $f(t)$.\n\n"
            "Рис. 14.1. Граничні умови, що залежать від часу."
        ),
        text,
        flags=re.DOTALL,
    )

    elliptic_transition_block = (
        "(15.4)\n\n"
        "$$\n"
        "u(x, t) = \\begin{cases} "
        "\\frac{1}{2} \\left[ 1 + \\operatorname{erf}\\left(\\frac{Vt - x}{2\\sqrt{Dt}}\\right) \\right], & Vt > x, \\\\ "
        "\\frac{1}{2} \\operatorname{erfc}\\left(\\frac{x - Vt}{2\\sqrt{Dt}}\\right), & Vt \\leq x. "
        "\\end{cases}\n"
        "$$\n\n"
        "Перед нами розв'язок задачі конвективної дифузії (15.2). Профіль концентрації "
        "рухається праворуч зі швидкістю $V$ і водночас розмивається дифузією з "
        "коефіцієнтом $D$.\n\n"
        "#### ЗАВДАННЯ\n\n"
        "1. Розв'яжіть задачу Коші\n\n"
        "$$\n"
        "\\begin{array}{ll} "
        "u_t = u_{xx} - 2u_x, & -\\infty < x < \\infty, \\ 0 < t < \\infty, \\\\ "
        "u(x, 0) = \\sin x, & -\\infty < x < \\infty. "
        "\\end{array}\n"
        "$$\n\n"
        "2. Знайдіть розв'язок задачі Коші для рівняння конвективної дифузії\n\n"
        "$$\n"
        "\\begin{array}{ll} "
        "u_t = u_{xx} - 2u_x, & -\\infty < x < \\infty, \\ 0 < t < \\infty, \\\\ "
        "u(x, 0) = e^x \\sin x, & -\\infty < x < \\infty. "
        "\\end{array}\n"
        "$$\n\n"
        "3. Знайдіть розв'язок задачі переносу, використовуючи перетворення координат з лекції 8.\n\n"
        "## Приведення еліптичних рівнянь до канонічної форми\n\n"
        "Розглянемо загальне рівняння\n\n"
        "$$\n"
        "Au_{xx} + Bu_{xy} + Cu_{yy} + Du_x + Eu_y + Fu = G\n"
        "$$\n\n"
        "але тепер у випадку $B^2 - 4AC < 0$. Переходом до нових незалежних змінних "
        "ми хочемо звести його до форми\n\n"
        "$$\n"
        "u_{\\xi\\xi} + u_{\\eta\\eta} = \\varphi(\\xi, \\eta, u, u_{\\xi}, u_{\\eta}).\n"
        "$$\n\n"
        "Щоб знайти ці нові змінні, виконуємо ті самі обчислення, що й у двох попередніх "
        "випадках, отримуємо перетворене рівняння\n\n"
        "$$\n"
        "\\overline{A}u_{\\xi\\xi} + \\overline{B}u_{\\xi\\eta} + \\overline{C}u_{\\eta\\eta} + "
        "\\overline{D}u_{\\xi} + \\overline{E}u_{\\eta} + \\overline{F}u = \\overline{G},\n"
        "$$\n\n"
        "і вимагаємо, щоб $\\xi$ та $\\eta$ задовольняли умовам "
        "$\\overline{A} = \\overline{C}$ і $\\overline{B} = 0$. Безпосередньо знайти "
        "$\\xi$ та $\\eta$ тут складніше, тому шукаємо перетворення як композицію двох кроків.\n\n"
        "# Перетворення 1\n\n"
        "Спочатку введемо комплексні координати $\\xi$ та $\\eta$, щоб надати рівнянню вигляду\n\n"
        "$$\n"
        "u_{\\xi\\eta} = \\psi(\\xi, \\eta, u, u_{\\xi}, u_{\\eta}).\n"
        "$$\n\n"
        "Для цього розв'язуємо характеристичні рівняння\n\n"
        "$$\n"
        "\\frac{dy}{dx} = \\frac{B - \\sqrt{B^2 - 4AC}}{2A},\n"
        "$$\n\n"
        "де $B^2 - 4AC < 0$, і отримуємо\n\n"
        "$$\n"
        "\\xi(x, y) = \\text{const}, \\qquad \\eta(x, y) = \\text{const}.\n"
        "$$\n\n"
        "# Перетворення 2\n\n"
        "Далі переходимо від $(\\xi,\\eta)$ до $(\\alpha,\\beta)$ за формулами\n\n"
        "$$\n"
        "\\alpha = \\frac{\\xi + \\eta}{2}, \\qquad \\beta = \\frac{\\xi - \\eta}{2i}.\n"
        "$$\n\n"
        "У результаті отримуємо канонічну форму еліптичного рівняння.\n\n"
    )
    text = _replace_section_between_markers(
        text,
        "(15.4)",
        "# Зведення рівняння y^2u_{xx} + x^2u_{yy} = 0 до його канонічної форми",
        elliptic_transition_block,
    )

    standing_waves_block = (
        "Подстановка (20.2) в граничные условия $u(0, t) = u(L, t) = 0$ дает\n\n"
        "$$\n"
        "u(0, t) = X(0)T(t) = D\\bigl[A\\sin(\\alpha\\beta t) + B\\cos(\\alpha\\beta t)\\bigr] = 0 "
        "\\Rightarrow D = 0,\n"
        "$$\n\n"
        "и\n\n"
        "$$\n"
        "u(L, t) = X(L)T(t) = C\\sin(\\beta L)\\bigl[A\\sin(\\alpha\\beta t) + B\\cos(\\alpha\\beta t)\\bigr] = 0 "
        "\\Rightarrow \\sin(\\beta L) = 0.\n"
        "$$\n\n"
        "Другими словами, константа разделения $\\beta$ должна удовлетворять уравнению "
        "$\\sin(\\beta L) = 0$, откуда\n\n"
        "$$\n"
        "\\beta_n = \\frac{n\\pi}{L}, \\qquad n = 0, 1, 2, \\ldots\n"
        "$$\n\n"
        "Заметим, что если во втором уравнении (20.3) положить $C=0$, то получится "
        "тривиальное решение $X(x)T(t) \\equiv 0$. Следовательно, мы нашли последовательность "
        "элементарных колебаний струны:\n\n"
        "$$\n"
        "u_n(x, t) = X_n(x)T_n(t) = \\sin\\!\\left(\\frac{n\\pi x}{L}\\right)"
        "\\left[a_n \\sin\\!\\left(\\frac{n\\pi \\alpha t}{L}\\right) + "
        "b_n \\cos\\!\\left(\\frac{n\\pi \\alpha t}{L}\\right)\\right].\n"
        "$$\n\n"
        "(20.4)\n\n"
        "або\n\n"
        "$$\n"
        "u_n(x, t) = R_n \\sin\\!\\left(\\frac{n\\pi x}{L}\\right)"
        "\\cos\\!\\left(\\frac{n\\pi \\alpha (t - \\delta_n)}{L}\\right).\n"
        "$$\n\n"
        "Тут $a_n$, $b_n$, $R_n$ і $\\delta_n$ — довільні сталі. Кожне таке елементарне "
        "коливання є стоячою хвилею.\n\n"
        "![](images/_page_150_Picture_5.jpeg)\n\n"
        "Рис. 20.3. Стоячі хвилі $u_n(x, t) = X_n(x)T_n(t)$.\n\n"
    )
    text = _replace_section_between_markers(
        text,
        "Подстановка (20.2) в граничные условия u(0, t) = u(L, t) = 0 дает",
        "В нашей задаче уравнение и граничные условия линейны и однородны",
        standing_waves_block,
    )

    text = text.replace(
        "$$\n\\begin{array}{ll} (\\text{YUII}) & u_t = u_{xx} + \\sin{(\\pi x)} + \\sin{(2\\pi x)}, & 0 < x < 1, & 0 <t < \\infty, \\\\ (\\text{\\GammaY}) & \\begin{cases} u\\left(0,\\ t\\right) = 0, \\\\ u\\left(1,\\ t\\right) = 0, \\end{cases} & 0 < t < \\infty, \\\\ (\\text{HY}) & u\\left(x,\\ 0\\right) = 0, & 0 \\leqslant x \\leqslant 1. \\end{array}\n$$",
        "$$\n\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx} + \\sin(\\pi x) + \\sin(2\\pi x), && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = 0, && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n$$",
    )
    text = text.replace(
        "$$\n\\begin{array}{ll} (\\text{YHII}) & u_t = u_{xx} + \\sin{(\\lambda_1 x)}, & 0 < x < 1, & 0 <t < \\infty, \\\\ (\\text{\\GammaY}) & \\begin{cases} u\\left(0, \\ t\\right) = 0, \\\\ u_x\\left(1, \\ t\\right) + u\\left(1, \\ t\\right) = 0, \\\\ 0 < t < \\infty, \\end{cases} \\\\ (\\text{HY}) & u\\left(x, \\ 0\\right) = 0, & 0 \\leqslant x \\leqslant 1 \\end{array}\n$$",
        "$$\n\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx} + \\sin(\\lambda_1 x), && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u_x(1,t) + u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = 0, && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n$$",
    )
    text = text.replace(
        "$$\n\\begin{array}{ll} (\\text{УЧП}) & u_t = u_{xx} & 0 < x < 1, \\quad 0 < t < \\infty, \\\\ (\\Gamma \\text{У}) & \\begin{cases} u(0, t) = 0, \\\\ u(1, t) = \\cos t, \\end{cases} & 0 < t < \\infty, \\\\ (\\text{HY}) & u(x, 0), \\quad 0 \\leqslant x \\leqslant 1, \\end{array}\n$$",
        "$$\n\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = \\cos t, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n$$",
    )

    mixed_problem_block = (
        "2. Як би ви інтерпретували наступне змішане завдання?\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u_x(1,t) = 1, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\sin(\\pi x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "Чи можете ви графічно показати рішення цієї проблеми в різні моменти часу? "
        "Чи буде це рішення, як правило, стаціонарним? Це очевидно?"
    )
    text = _replace_section_between_markers(
        text,
        "2. Як би ви інтерпретували наступне змішане завдання?",
        "3. Яку фізичну інтерпретацію ви можете дати проблемі",
        mixed_problem_block,
    )

    separation_problem_block = (
        "Наступного завдання:\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 < x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "Наступного завдання:",
        "Пошукаємо розв'язки, які представлені у вигляді",
        separation_problem_block,
    )

    nonhomogeneous_boundary_block = (
        "Розглянемо проблему поширення тепла в термоізольованому стрижні, кінці якого "
        "підтримуються при сталих температурах $k_1$ і $k_2$, тобто\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < L,\\ 0 < t < \\infty, \\\\\n"
        "(6.3)\\ (\\text{ГУ})\\quad & u(0,t) = k_1,\\quad u(L,t) = k_2, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 \\leqslant x \\leqslant L.\n"
        "\\end{aligned}\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "Розглянемо проблему поширення тепла в термоізольованому стрижні, кінці якого підтримуються при сталих температурах",
        "Складність цієї задачі полягає",
        nonhomogeneous_boundary_block,
    )

    third_boundary_task_block = (
        "3. Завдання\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u_x(0,t) = 0,\\quad u_x(1,t) + h u(1,t) = 1, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\sin(\\pi x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "3. Завдання",
        "Перетворимо на задачу з нульовими граничними умовами.",
        third_boundary_task_block,
    )

    eigenfunction_tasks_block = (
        "4. Найдите решение задачи\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx} + \\sin(\\lambda_1 x), && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u_x(1,t) + u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = 0, && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "методом разложения по собственным функциям, если $\\lambda_1$ — первый корень "
        "уравнения $\\operatorname{tg}\\lambda = -\\lambda$. Каковы собственные функции этой задачи?\n\n"
        "# 5. Решите задачу\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = \\cos t, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "Спочатку перетворивши граничні умови в нуль. Отримана задача розв'язується методом "
        "розкладу за власними функціями."
    )
    text = _replace_section_between_markers(
        text,
        "4. Найдите решение задачи",
        "# ІНТЕГРАЛЬНІ ПЕРЕТВОРЕННЯ",
        eigenfunction_tasks_block,
    )

    text = text.replace(
        "\\textbar F(\\xi)\\textbar{} = \\sqrt{\\frac{1}{2$\\pi$(1+\\xi^2)}}",
        "$$|F(\\xi)| = \\sqrt{\\frac{1}{2\\pi(1+\\xi^2)}}$$",
    )
    text = text.replace(
        "| 2. $f(x) = \\begin{cases} 1, & -1 < x < 1, \\\\ 0, & x \\le -1, x \\ge 1 \\end{cases}$ | $F(\\xi) = \\sqrt{\\frac{\\frac{2}{\\pi}}{\\frac{\\sin \\xi}{\\xi}}}$ (Beg.ectronnal (yul.ung). |",
        "| 2. $f(x) = \\begin{cases} 1, & -1 < x < 1, \\\\ 0, & x \\le -1, x \\ge 1 \\end{cases}$ | $F(\\xi) = \\sqrt{\\frac{2}{\\pi}}\\,\\frac{\\sin \\xi}{\\xi}$ |",
    )
    text = text.replace(
        "| 3. $f(x) = e^{-x^2}$ | $F\\left(\\xi\\right)=\\frac{1}{\\sqrt{2}}e^{-\\sqrt{\\xi}/2\\right)^2}$ (основна синя функція). |",
        "| 3. $f(x) = e^{-x^2}$ | $F(\\xi) = \\frac{1}{\\sqrt{2}} e^{-\\xi^2/4}$ |",
    )

    cauchy_problem_block = (
        "Цю задачу зазвичай називають задачею Коші для рівняння теплопровідності або задачею "
        "початкових умов.\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && -\\infty < x < \\infty,\\ 0 < t < \\infty, \\\\\n"
        "(12.6)\\ (\\text{НУ})\\quad & u(x,0) = \\varphi(x), && -\\infty < x < \\infty.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "Рішення задачі можна розбити на три основні кроки.\n\n"
        "ШАГ 1 (Преобразование задачи).\n\n"
        "Оскільки просторова змінна $x$ змінюється в межах від $-\\infty$ до $+\\infty$, "
        "застосуємо до рівняння та початкової умови (12.6) перетворення Фур'є за змінною $x$. "
        "Тоді отримуємо\n\n"
        "$$\n"
        "\\mathcal{F}[u_t] = \\alpha^2 \\mathcal{F}[u_{xx}], \\qquad "
        "\\mathcal{F}[u(x,0)] = \\mathcal{F}[\\varphi(x)].\n"
        "$$\n\n"
        "Використовуючи властивості перетворення Фур'є, маємо\n\n"
        "$$\n"
        "\\frac{dU}{dt} = -\\alpha^2 \\xi^2 U(t), \\qquad U(0) = \\Phi(\\xi),\n"
        "$$\n\n"
        "де $U(t) = \\mathcal{F}[u(x,t)]$, а $\\Phi(\\xi) = \\mathcal{F}[\\varphi(x)]$.\n\n"
        "ШАГ 2 (Решение преобразованной задачи).\n\n"
        "Розв'язок задачі (12.7) має вигляд\n\n"
        "(12.8)\n"
        "$$\n"
        "U(t) = \\Phi(\\xi) e^{-\\alpha^2 \\xi^2 t}.\n"
        "$$\n\n"
        "ШАГ 3 (Нахождение обратного преобразования).\n\n"
        "Шукане рішення визначається формулою\n\n"
        "$$\n"
        "u(x,t) = \\mathcal{F}^{-1}[U(\\xi,t)] = \\mathcal{F}^{-1}[\\Phi(\\xi)e^{-\\alpha^2\\xi^2 t}].\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "Цю задачу зазвичай називають задачою Коші для рівняння теплопровідності або задачою початкових умов",
        "Предполагается, что преобразование Фурье этих функций существует. Прим. ред.",
        cauchy_problem_block,
    )

    laplace_tasks_block = (
        "2. Використати перетворення Лапласа для розв'язання задачі Коші\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && -\\infty < x < \\infty,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\sin x, && -\\infty < x < \\infty.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "3. За допомогою перетворення Лапласа за змінною $t$ розв'язати задачу\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx}, && 0 < x < \\infty,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = \\sin t, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = 0, && 0 \\leqslant x < \\infty.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "Дайте фізичну інтерпретацію цієї задачі."
    )
    text = _replace_section_between_markers(
        text,
        "2. Використати перетворення Лаціаса для розв'язання задачі Коші",
        "4. Розв'язати задачу з граничним значенням",
        laplace_tasks_block,
    )

    note_problem_block = (
        "1. Вирішити проблему\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "u_t &= u_{xx} - u, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "u(0,t) &= 0,\\quad u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "u(x,0) &= \\sin(\\pi x) + 0.5\\sin(3\\pi x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "1. Вирішити проблему",
        "За методом, описаним вище, ми",
        note_problem_block,
    )

    text = text.replace(
        "$$ \\begin{array}{ll} (n=1) & T_1' + (\\pi\\alpha)^2 T_1 = 0 \\\\ T_1(0) = 1 & \\Rightarrow T_1(t) = e^{-(\\pi\\alpha)^2 t}, \\\\ (n=2) & T_2' + (2\\pi\\alpha)^2 T_2 = 0 \\T_2\\  (0) = 0 & \\Rightarrow T_2(t) = 0, \\\\ (n=3) & T_3' + (3\\pi\\alpha)^2 T_3 = 4 \\\\ T_3(0) = 0 & \\Rightarrow T_3(t) = \\frac{1}{(3\\pi\\alpha)^2} \\left[1 - e^{-(3\\ pi\\alpha)^2 t}\\right], \\\\ (n \\geqslant 4) & T_n' + (n\\pi\\alpha)^2 T_n = 0 \\\\ T_n(0) = 0 & \\Rightarrow T_n(0) = 0. \\end{array}\n$$",
        "$$\n\\begin{aligned}\n"
        "(n=1)\\quad & T_1' + (\\pi\\alpha)^2 T_1 = 0, && T_1(0) = 1, && T_1(t) = e^{-(\\pi\\alpha)^2 t}, \\\\\n"
        "(n=2)\\quad & T_2' + (2\\pi\\alpha)^2 T_2 = 0, && T_2(0) = 0, && T_2(t) = 0, \\\\\n"
        "(n=3)\\quad & T_3' + (3\\pi\\alpha)^2 T_3 = 4, && T_3(0) = 0, && T_3(t) = \\frac{1}{(3\\pi\\alpha)^2}\\left[1 - e^{-(3\\pi\\alpha)^2 t}\\right], \\\\\n"
        "(n\\geqslant 4)\\quad & T_n' + (n\\pi\\alpha)^2 T_n = 0, && T_n(0) = 0, && T_n(t) = 0.\n"
        "\\end{aligned}\n$$",
    )

    sine_cosine_transform_task = (
        "- 3. Використайте синусоїдальне або косинусне перетворення для розв'язання задачі\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < \\infty,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u_x(0,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = H(1-x), && 0 \\leqslant x < \\infty.\n"
        "\\end{aligned}\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "- 3. Використайте синусоїдальне або коспусне перетворення для розв'язання",
        "де H(x) — функція Хевісайду",
        sine_cosine_transform_task,
    )

    text = text.replace(
        "\\textbar F(\\xi)\\textbar{} = \\sqrt{\\frac{1}{2$\\pi$(1+\\xi^2)}}",
        "$$|F(\\xi)| = \\sqrt{\\frac{1}{2\\pi(1+\\xi^2)}}$$",
    )

    lecture_8_tasks_and_lecture_9_intro = (
        "1. Розв'язати задачу конвективної дифузії\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx} - u_x, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = e^{x/2}, && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "методом перетворення до простішого рівняння. На що схожий розв'язок? "
        "Можна дати таку інтерпретацію цієї задачі: $u(x,t)$ — концентрація деякої речовини "
        "в рухомому середовищі, яке рухається зліва направо зі швидкістю $v = 1$; початковий "
        "розподіл концентрації задається функцією $e^{x/2}$, а на межах концентрація підтримується "
        "нульовою. Чи відповідає ваш розв'язок такій інтерпретації?\n\n"
        "2. Розв'язати задачу\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx} - u + x, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = 1, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = 0, && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "- а) перетворивши неоднорідні граничні умови на однорідні;\n"
        "- б) перетворивши вихідне рівняння на нове рівняння без члена $-u$;\n"
        "- в) розв'язавши задачу, що виникає після цих перетворень.\n\n"
        "3. Розв'язати задачу\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = u_{xx} - u, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & u(0,t) = 0,\\quad u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\sin(\\pi x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "застосовуючи метод розділення змінних безпосередньо до вихідного рівняння, не виконуючи "
        "жодних попередніх перетворень. Чи збігається отриманий розв'язок з розв'язком, знайденим "
        "раніше після заміни\n\n"
        "$$\n"
        "u(x,t) = e^{-t}w(x,t)\n"
        "$$\n\n"
        "?\n\n"
        "# РОЗВ'ЯЗАННЯ НЕОДНОРІДНИХ УЧП МЕТОДОМ РОЗКЛАДУ ЗА ВЛАСНИМИ ФУНКЦІЯМИ\n\n"
        "ЦІЛЬ ЛЕКЦІЇ: Навчитися розв'язувати змішані задачі вигляду\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx} + f(x,t), && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & \\alpha_1 u_x(0,t) + \\beta_1 u(0,t) = 0, && 0 < t < \\infty, \\\\\n"
        "& \\alpha_2 u_x(1,t) + \\beta_2 u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "Розв'язок неоднорідного УЧП можна шукати у вигляді ряду\n\n"
        "$$\n"
        "u(x,t) = \\sum_{n=1}^{\\infty} T_n(t) X_n(x).\n"
        "$$\n\n"
        "де $X_n(x)$ — власні функції відповідної однорідної задачі\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "(\\text{УЧП})\\quad & u_t = \\alpha^2 u_{xx}, && 0 < x < 1,\\ 0 < t < \\infty, \\\\\n"
        "(\\text{ГУ})\\quad & \\alpha_1 u_x(0,t) + \\beta_1 u(0,t) = 0, && 0 < t < \\infty, \\\\\n"
        "& \\alpha_2 u_x(1,t) + \\beta_2 u(1,t) = 0, && 0 < t < \\infty, \\\\\n"
        "(\\text{НУ})\\quad & u(x,0) = \\varphi(x), && 0 \\leqslant x \\leqslant 1.\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "А функції $T_n(t)$ визначаються як розв'язки деяких звичайних диференціальних рівнянь.\n\n"
    )
    text = _replace_section_between_markers(
        text,
        "1. Розв'язати проблему конвективної дифузії",
        "На лекції 6 ми ознайомилися з тим, як перетворювати неоднорідні граничні умови на однорідні.",
        lecture_8_tasks_and_lecture_9_intro,
    )

    lecture_46_tail = (
        "# ЗАДАЧИ\n\n"
        "1. Подставьте разложение (46.8) в задачу (46.7) и получите последовательность "
        "задач $P_0,\\ P_1,\\ P_2,\\ \\dots$.\n\n"
        "2. Покажите, что нелинейную задачу\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "\\Delta u + u^2 &= 0, && 0 \\leqslant r < 1,\\ 0 \\leqslant \\theta < 2\\pi, \\\\\n"
        "u(1,\\theta) &= \\cos\\theta, && 0 \\leqslant \\theta < 2\\pi,\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "можно свести к последовательности линейных задач $P_0,\\ P_1,\\ P_2$.\n\n"
        "3. Подставьте приближенное решение (46.5) в нелинейную задачу 2 и оцените его точность.\n\n"
        "4. Решите задачу $P_1$ из примера с возмущенной границей и проверьте, насколько хорошо "
        "приближенное решение\n\n"
        "$$\n"
        "u(r,\\theta) = u_0(r,\\theta) + \\frac{1}{4}u_1(r,\\theta)\n"
        "$$\n\n"
        "удовлетворяет соотношениям\n\n"
        "$$\n"
        "\\Delta u = 0,\n"
        "$$\n\n"
        "$$\n"
        "u\\left(1 + \\frac{1}{4}\\sin\\theta,\\ \\theta\\right) = \\cos\\theta.\n"
        "$$"
    )
    text = _replace_nearest_section_before_marker(
        text,
        "# ЗАДАЧИ",
        "# Лекція 47",
        lecture_46_tail,
        max_distance=1500,
    )

    lecture_46_parameter_tail = (
        "Якщо розглянути рівняння з параметром\n\n"
        "(46.11)\n"
        "$$\n"
        "u_t = (1 + \\varepsilon x) u_{xx},\n"
        "$$\n\n"
        "і шукати його розв'язок у вигляді\n\n"
        "$$\n"
        "u = u_0 + \\varepsilon u_1 + \\varepsilon^2 u_2 + \\cdots,\n"
        "$$\n\n"
        "то після підстановки отримуємо послідовність задач\n\n"
        "$$\n"
        "P_0:\\ \\begin{cases}\n"
        "\\dfrac{\\partial u_0}{\\partial t} = \\dfrac{\\partial^2 u_0}{\\partial x^2}, \\\\\n"
        "u_0(x,0) = \\varphi(x),\n"
        "\\end{cases}\n"
        "\\qquad\n"
        "P_1:\\ \\begin{cases}\n"
        "\\dfrac{\\partial u_1}{\\partial t} - \\dfrac{\\partial^2 u_1}{\\partial x^2} = x\\,\\dfrac{\\partial^2 u_0}{\\partial x^2}, \\\\\n"
        "u_1(x,0) = 0.\n"
        "\\end{cases}\n"
        "$$\n\n"
        "Зауважимо, що в перших двох задачах коефіцієнти сталі. Параметр $\\varepsilon$ "
        "має бути достатньо малим, інакше нескінченний ряд може виявитися розбіжним.\n\n"
        "#### ЗАДАЧИ\n\n"
        "1. Подставьте разложение (46.8) в задачу (46.7) и получите последовательность задач "
        "$P_0,\\ P_1,\\ P_2,\\ \\dots$.\n\n"
        "2. Покажите, что нелинейную задачу\n\n"
        "$$\n"
        "\\begin{aligned}\n"
        "\\Delta u + u^2 &= 0, && 0 \\leqslant r < 1,\\ 0 \\leqslant \\theta < 2\\pi, \\\\\n"
        "u(1,\\theta) &= \\cos\\theta, && 0 \\leqslant \\theta < 2\\pi,\n"
        "\\end{aligned}\n"
        "$$\n\n"
        "можно свести к последовательности линейных задач $P_0,\\ P_1,\\ P_2$.\n\n"
        "3. Подставьте приближенное решение (46.5) в нелинейную задачу 2 и оцените его точность.\n\n"
        "4. Решите задачу $P_1$ из примера с возмущенной границей и проверьте, насколько хорошо "
        "приближенное решение\n\n"
        "$$\n"
        "u(r,\\theta) = u_0(r,\\theta) + \\frac{1}{4}u_1(r,\\theta)\n"
        "$$\n\n"
        "удовлетворяет соотношениям\n\n"
        "$$\n"
        "\\Delta u = 0,\n"
        "$$\n\n"
        "$$\n"
        "u\\left(1 + \\frac{1}{4}\\sin\\theta,\\ \\theta\\right) = \\cos\\theta.\n"
        "$$"
    )
    text = _replace_section_between_markers(
        text,
        "u_1 = (1 + \\varepsilon_1) u_{xx}",
        "# Лекція 47",
        lecture_46_parameter_tail,
    )

    return text


def _normalize_display_math_fences(text: str) -> str:
    """
    Normalize OCR-heavy display math markers before the PDF-specific math
    splitter runs.

    The source manuscript often contains stray standalone ``$$`` lines and
    broken ``$$ content`` line prefixes. We keep already valid ``$$...$$``
    blocks intact and only trim genuinely broken fence lines so later math
    heuristics can wrap the surviving content into proper display math blocks
    without destroying correct display math.
    """

    normalized_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped == "$$":
            continue

        if stripped.startswith("$$") and stripped.endswith("$$"):
            normalized_lines.append(line)
            continue

        if stripped.startswith("$$"):
            line = re.sub(r'^\s*\${2,}\s*', '', line)

        if stripped.endswith("$$"):
            line = re.sub(r'\s*\${2,}\s*$', '', line)

        normalized_lines.append(line)

    return "\n".join(normalized_lines)


def _collect_page_markers(text: str) -> list[tuple[int, int]]:
    markers: list[tuple[int, int]] = []
    for match in _PAGE_MARKER_PATTERN.finditer(text):
        markers.append((match.start(), int(match.group("page"))))
    return markers


def _page_index_for_offset(offset: int, page_markers: list[tuple[int, int]]) -> int:
    page_index = 0
    for marker_offset, marker_page in page_markers:
        if marker_offset > offset:
            break
        page_index = max(page_index, marker_page)
    return page_index


def _tail_page_cutoff(page_markers: list[tuple[int, int]]) -> int:
    if not page_markers:
        return 0
    max_page = max(page for _, page in page_markers)
    return max(1, max_page - _TAIL_SECTION_PAGE_MARGIN)


def _next_end_matter_start(text: str, offset: int) -> Optional[int]:
    candidates: list[int] = []
    for _, pattern in _END_MATTER_HEADING_PATTERNS:
        match = pattern.search(text, offset)
        if match is not None:
            candidates.append(match.start())
    return min(candidates) if candidates else None


def _collect_tail_only_removal_ranges(text: str) -> list[tuple[int, int, str]]:
    page_markers = _collect_page_markers(text)
    tail_page_cutoff = _tail_page_cutoff(page_markers)
    removal_ranges: list[tuple[int, int, str]] = []

    for match in _CROSSWORD_SECTION_PATTERN.finditer(text):
        page_index = _page_index_for_offset(match.start(), page_markers)
        if page_index < tail_page_cutoff:
            continue
        removal_ranges.append((match.start(), match.end(), "crossword"))

    appendix_heading_patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("laplace appendix tail", _LAPLACE_APPENDIX_HEADING_PATTERN),
    )
    for label, pattern in appendix_heading_patterns:
        for match in pattern.finditer(text):
            page_index = _page_index_for_offset(match.start(), page_markers)
            if page_index < tail_page_cutoff:
                continue
            end_matter_start = _next_end_matter_start(text, match.end())
            removal_ranges.append((match.start(), end_matter_start or len(text), label))

    tail_cut_candidates: list[tuple[int, str]] = []
    for label, pattern in _END_MATTER_HEADING_PATTERNS:
        for match in pattern.finditer(text):
            page_index = _page_index_for_offset(match.start(), page_markers)
            if page_index < tail_page_cutoff:
                continue
            tail_cut_candidates.append((match.start(), label))

    if tail_cut_candidates:
        tail_start, tail_label = min(tail_cut_candidates, key=lambda item: item[0])
        removal_ranges.append((tail_start, len(text), f"tail {tail_label}"))

    return removal_ranges


def _merge_removal_ranges(
    ranges: list[tuple[int, int, str]],
) -> list[tuple[int, int, list[str]]]:
    if not ranges:
        return []

    merged: list[tuple[int, int, list[str]]] = []
    for start, end, label in sorted(ranges, key=lambda item: (item[0], item[1])):
        if not merged or start > merged[-1][1]:
            merged.append((start, end, [label]))
            continue

        prev_start, prev_end, prev_labels = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end), prev_labels + [label])

    return merged


def _remove_pdf_only_sections(text: str) -> str:
    removal_ranges = _merge_removal_ranges(_collect_tail_only_removal_ranges(text))
    if not removal_ranges:
        return text

    cleaned_parts: list[str] = []
    cursor = 0

    for start, end, labels in removal_ranges:
        if cursor < start:
            cleaned_parts.append(text[cursor:start])
        log.info(
            "  Removed PDF-only tail range [%d:%d] (%s).",
            start,
            end,
            ", ".join(labels),
        )
        cursor = end

    if cursor < len(text):
        cleaned_parts.append(text[cursor:])

    cleaned_text = "".join(cleaned_parts)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip() + "\n"


def _build_resource_path(output_dir: Path, images_dir: Path) -> str:
    resource_dirs = [
        ".",
        output_dir.absolute().as_posix(),
        images_dir.absolute().as_posix(),
    ]
    return os.pathsep.join(resource_dirs)


def _build_pdf_only_from_markdown(
    md_text: str,
    output_stem: str,
    output_dir: Path,
    images_dir: Path,
) -> Path:
    export_md_text = _remove_pdf_only_sections(md_text)
    res_path = _build_resource_path(output_dir, images_dir)

    try:
        generated_pdf = _build_pdf_via_tex(
            md_text=export_md_text,
            output_stem=output_stem,
            output_dir=output_dir,
            res_path=res_path,
            graphics_root_dir=images_dir.parent,
            input_format="markdown+raw_tex+tex_math_dollars",
        )
        log.info("  Generated PDF: %s", generated_pdf)
        return generated_pdf
    except Exception as exc:
        log.warning("  Raw strict PDF generation failed, retrying with prepared markdown: %s", exc)
        pdf_md_text = _prepare_markdown_for_pdf(export_md_text)
        try:
            generated_pdf = _build_pdf_via_tex(
                md_text=pdf_md_text,
                output_stem=output_stem,
                output_dir=output_dir,
                res_path=res_path,
                graphics_root_dir=images_dir.parent,
                input_format="markdown+raw_tex+tex_math_dollars",
            )
            log.info("  Generated PDF after markdown preparation: %s", generated_pdf)
            return generated_pdf
        except Exception as prepared_exc:
            log.warning("  Prepared strict PDF generation failed, retrying in safe-text mode: %s", prepared_exc)
        safe_pdf_md_text = _prepare_markdown_for_safe_pdf(export_md_text)
        generated_safe_pdf = _build_pdf_via_tex(
            md_text=safe_pdf_md_text,
            output_stem=f"{output_stem}_safe",
            output_dir=output_dir,
            res_path=res_path,
            graphics_root_dir=images_dir.parent,
            allow_partial_output=True,
            input_format="markdown+raw_tex+tex_math_dollars",
        )
        final_pdf_path = output_dir / f"{output_stem}.pdf"
        shutil.copy2(generated_safe_pdf, final_pdf_path)
        log.info("  Generated PDF in safe-text mode: %s", final_pdf_path)
        return final_pdf_path


def _split_markdown_into_page_chunks(
    md_text: str,
    pages_per_chunk: int = 50,
) -> list[tuple[int, int, str]]:
    cleaned_text = _remove_pdf_only_sections(md_text)
    lines = cleaned_text.splitlines(keepends=True)
    if not lines:
        return []

    chunks: list[tuple[int, int, str]] = []
    chunk_start_idx = 0
    chunk_start_page = 0
    next_boundary = pages_per_chunk
    max_seen_page = 0

    def choose_split_idx(preferred_idx: int) -> int:
        window_start = max(chunk_start_idx + 1, preferred_idx - 120)
        min_chunk_lines = 3

        for idx in range(preferred_idx, window_start - 1, -1):
            if _HEADING_LINE_PATTERN.match(lines[idx]):
                if idx > chunk_start_idx + min_chunk_lines:
                    return idx

        for idx in range(preferred_idx, window_start - 1, -1):
            if not lines[idx].strip() and idx + 1 > chunk_start_idx + min_chunk_lines:
                return idx + 1

        return preferred_idx

    for idx, line in enumerate(lines):
        page_matches = [int(match) for match in _PAGE_MARKER_PATTERN.findall(line)]
        if not page_matches:
            continue

        line_page = max(page_matches)
        max_seen_page = max(max_seen_page, line_page)

        if line_page < next_boundary:
            continue

        split_idx = choose_split_idx(idx)
        chunk_text = "".join(lines[chunk_start_idx:split_idx]).strip()
        if chunk_text:
            chunks.append((chunk_start_page, next_boundary - 1, chunk_text))

        chunk_start_idx = split_idx
        chunk_start_page = next_boundary
        next_boundary += pages_per_chunk

    tail_text = "".join(lines[chunk_start_idx:]).strip()
    if tail_text:
        tail_end_page = max_seen_page if max_seen_page >= chunk_start_page else chunk_start_page + pages_per_chunk - 1
        chunks.append((chunk_start_page, tail_end_page, tail_text))

    return chunks


def _prepare_markdown_for_chunk_grouping(md_text: str) -> str:
    prepared = _remove_pdf_only_sections(md_text)
    prepared = clean_markdown_formatting(prepared)
    prepared = re.sub(
        r"\s*(!\[[^\]]*\]\([^)]+\))\s*",
        r"\n\n\1\n\n",
        prepared,
    )
    prepared = re.sub(
        r"(?<!\n)(?=#(?:\s|[A-Za-zА-Яа-яІіЇїЄєҐґ]))",
        "\n\n",
        prepared,
    )
    prepared = re.sub(r"\n{3,}", "\n\n", prepared)
    return prepared


def _drop_formula_handbook_blocks(blocks: list[str]) -> list[str]:
    table_heading_pattern = re.compile(
        r"^#\s*(?:ТАБЛИЦ(?:Я|А|І)|ПРИЙНЯТІ ПОЗНАЧЕННЯ|ПРИНЯТЫЕ ОБОЗНАЧЕНИЯ)\b",
        re.IGNORECASE,
    )
    heading_pattern = re.compile(r"^#\s+")
    filtered_blocks: list[str] = []
    skip_table_section = False

    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue

        if skip_table_section:
            if heading_pattern.match(stripped) and not table_heading_pattern.match(stripped):
                skip_table_section = False
            else:
                continue

        if table_heading_pattern.match(stripped):
            skip_table_section = True
            continue

        filtered_blocks.append(block)

    return filtered_blocks


def _group_markdown_into_page_chunks(
    md_text: str,
    pages_per_chunk: int = 50,
) -> list[tuple[int, int, str]]:
    """
    Group markdown blocks into page windows based on the page markers they
    actually contain, instead of trusting the marker order in the file.

    Some OCR repair passes can paste earlier lecture fragments into later
    regions, which makes `_page_XXX_` markers non-monotonic. For chunked PDF
    export we therefore assign each markdown block to the bucket implied by its
    own page marker; blocks without an explicit page marker inherit the most
    recent seen page so surrounding text stays attached to the nearest figure.
    """
    prepared_text = _prepare_markdown_for_chunk_grouping(md_text)
    raw_blocks = re.split(r"\n\s*\n+", prepared_text)
    blocks = [block.strip() for block in raw_blocks if block.strip()]
    blocks = _drop_formula_handbook_blocks(blocks)
    if not blocks:
        return []

    bucketed_blocks: dict[int, list[str]] = defaultdict(list)
    last_seen_page: Optional[int] = None
    max_seen_page = 0

    for block in blocks:
        page_refs = sorted(
            {
                int(match.group("page"))
                for match in _PAGE_MARKER_PATTERN.finditer(block)
            }
        )
        if page_refs:
            bucket_starts = {
                (page // pages_per_chunk) * pages_per_chunk
                for page in page_refs
            }
            for bucket_start in sorted(bucket_starts):
                bucketed_blocks[bucket_start].append(block)
            last_seen_page = page_refs[-1]
            max_seen_page = max(max_seen_page, page_refs[-1])
            continue

        inherited_page = last_seen_page if last_seen_page is not None else 0
        inherited_bucket = (inherited_page // pages_per_chunk) * pages_per_chunk
        bucketed_blocks[inherited_bucket].append(block)

    if max_seen_page == 0 and not bucketed_blocks:
        return []

    chunk_specs: list[tuple[int, int, str]] = []
    for chunk_start_page in range(0, max_seen_page + 1, pages_per_chunk):
        chunk_text = _join_markdown_segments(bucketed_blocks.get(chunk_start_page, []))
        if not chunk_text:
            continue
        chunk_end_page = min(chunk_start_page + pages_per_chunk - 1, max_seen_page)
        chunk_specs.append((chunk_start_page, chunk_end_page, chunk_text))

    return chunk_specs


def _join_markdown_segments(segments: list[str]) -> str:
    normalized_segments = [segment.strip() for segment in segments if segment and segment.strip()]
    text = "\n\n".join(normalized_segments)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n" if text.strip() else ""


def _filter_chunk_by_local_page_monotonicity(
    chunk_text: str,
    *,
    max_backward_jump: int = 10,
) -> str:
    parts = re.split(r"(\n\s*\n+)", chunk_text)
    filtered_parts: list[str] = []
    max_seen_page = -1
    suppress_unmarked_parts = False

    for part in parts:
        if re.fullmatch(r"\n\s*\n+", part):
            if filtered_parts and not re.fullmatch(r"\n\s*\n+", filtered_parts[-1]):
                filtered_parts.append("\n\n")
            continue

        page_refs = [int(match.group("page")) for match in _PAGE_MARKER_PATTERN.finditer(part)]
        if page_refs:
            block_page = max(page_refs)
            if max_seen_page >= 0 and block_page < max_seen_page - max_backward_jump:
                suppress_unmarked_parts = True
                continue
            max_seen_page = max(max_seen_page, block_page)
            suppress_unmarked_parts = False
            filtered_parts.append(part)
            continue

        if suppress_unmarked_parts:
            continue

        filtered_parts.append(part)

    return _join_markdown_segments(filtered_parts)


def _drop_transform_table_contamination(
    chunk_text: str,
    *,
    start_page: int,
) -> str:
    if start_page < 150:
        return chunk_text

    contamination_pattern = re.compile(
        r'(?:S_n\s*=|C_n\s*=|F\(\s*\\?omega\s*\)|\\frac\{2\}\{\\pi\}|\\sin\(nx\)|\\cos\(nx\)|'
        r'ТАБЛИЦ[ЯАІ]|ПЕРЕТВОРЕННЯ\s+ФУР.?Є|ПРЕОБРАЗОВАНИЯ\s+ФУРЬЕ)',
        re.IGNORECASE,
    )
    parts = re.split(r"(\n\s*\n+)", chunk_text)
    filtered_parts: list[str] = []

    for part in parts:
        if re.fullmatch(r"\n\s*\n+", part):
            if filtered_parts and not re.fullmatch(r"\n\s*\n+", filtered_parts[-1]):
                filtered_parts.append("\n\n")
            continue
        if contamination_pattern.search(part):
            continue
        filtered_parts.append(part)

    return _join_markdown_segments(filtered_parts)


def _normalize_chunk_export_style(chunk_text: str) -> str:
    text = chunk_text
    text = re.sub(
        r'^(#+\s+.+?)\s+(МЕТА ЛЕКЦІЇ:|ЦЕЛЬ ЛЕКЦИИ:)\s*(.+)$',
        lambda m: f"{m.group(1).strip()}\n\n{m.group(2)} {m.group(3).strip()}",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r'^\s*#TASKS:\s*', '# ЗАВДАННЯ\n\n', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*Лекция\s+(\d+)\s*$', r'## Лекція \1', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*Рис(?:унок)?[.\s]+', 'Рис. ', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^\s*FIG\.\s*', 'Рис. ', text, flags=re.MULTILINE)
    text = re.sub(r'\bSHCHAG\b', 'КРОК', text)
    text = re.sub(r'\bCROC\b', 'КРОК', text)
    text = text.replace('P И С', '')
    text = text.replace('Retelno proanalizite vidpovid\'.', 'Ретельно проаналізуйте відповідь.')

    heading_replacements = {
        '# Уравнение Пуассона в круге': '# Рівняння Пуассона в крузі',
        '# Определение функции источника': '# Означення функції джерела',
        '# Построение решения': '# Побудова розвʼязку',
        '# Свободно опирающаяся балка': '# Шарнірно оперта балка',
        '# ПЕРЕХОД К БЕЗРАЗМЕРНЫМ ПЕРЕМЕННЫМ': '# ПЕРЕХІД ДО БЕЗРОЗМІРНИХ ЗМІННИХ',
        '# Преобразование зависимой переменной': '# Перетворення залежної змінної',
        '# Преобразование пространственной координаты': '# Перетворення просторової координати',
        '# УРАВНЕНИЯ ПЕРВОГО ПОРЯДКА (МЕТОД ХАРАКТЕРИСТИК)': '# РІВНЯННЯ ПЕРШОГО ПОРЯДКУ (МЕТОД ХАРАКТЕРИСТИК)',
        '# Определение конформного отображения': '# Означення конформного відображення',
    }
    for source, replacement in heading_replacements.items():
        text = text.replace(source, replacement)

    text = _apply_stable_text_normalizations(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def _dedupe_standalone_image_paragraphs(chunk_text: str) -> str:
    parts = re.split(r"(\n\s*\n+)", chunk_text)
    deduped_parts: list[str] = []
    seen_refs: set[str] = set()

    for part in parts:
        if re.fullmatch(r"\n\s*\n+", part):
            if deduped_parts and not re.fullmatch(r"\n\s*\n+", deduped_parts[-1]):
                deduped_parts.append("\n\n")
            continue

        stripped = part.strip()
        image_match = _MARKDOWN_IMAGE_LINK_PATTERN.fullmatch(stripped)
        if image_match:
            image_ref = image_match.group(2).strip()
            if image_ref in seen_refs:
                continue
            seen_refs.add(image_ref)

        if stripped:
            deduped_parts.append(part)

    return _join_markdown_segments(deduped_parts)


def _filter_chunk_by_expected_page_window(
    chunk_text: str,
    start_page: int,
    end_page: int,
    *,
    tolerance: int = 8,
) -> str:
    """
    Drops obvious cross-contamination inside a page chunk.

    Marker OCR sometimes pastes earlier lecture fragments into late-page chunks.
    We only trust image-bearing segments whose `_page_XXX_` markers fall near the
    expected page window for the chunk; once an out-of-window image appears after
    in-window content, we suppress subsequent text until the next in-window image.
    """
    lower_bound = max(0, start_page - tolerance)
    upper_bound = end_page + tolerance
    parts = re.split(r"(\n\s*\n+)", chunk_text)

    filtered_parts: list[str] = []
    seen_in_window = False
    keep_mode = True

    for part in parts:
        if re.fullmatch(r"\n\s*\n+", part):
            if filtered_parts and not re.fullmatch(r"\n\s*\n+", filtered_parts[-1]):
                filtered_parts.append("\n\n")
            continue

        page_refs = [int(match.group("page")) for match in _PAGE_MARKER_PATTERN.finditer(part)]
        in_window = any(lower_bound <= page <= upper_bound for page in page_refs)
        has_out_of_window = bool(page_refs) and not in_window

        if in_window:
            seen_in_window = True
            keep_mode = True
            keep_part = True
        elif has_out_of_window:
            keep_part = False
            if seen_in_window:
                keep_mode = False
        else:
            keep_part = keep_mode or not seen_in_window

        if keep_part and part.strip():
            filtered_parts.append(part)

    return _join_markdown_segments(filtered_parts)


def export_chunked_pdfs(
    md_text: str,
    output_stem: str,
    output_dir: Path,
    images_dir: Path,
    pages_per_chunk: int = 50,
) -> list[Path]:
    chunk_dir = output_dir / f"{output_stem}_pdf_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_specs = _group_markdown_into_page_chunks(md_text, pages_per_chunk=pages_per_chunk)
    if not chunk_specs:
        raise ValueError("No Markdown chunks were produced for PDF export.")

    manifest_lines: list[str] = []
    generated_paths: list[Path] = []

    for index, (start_page, end_page, chunk_text) in enumerate(chunk_specs, start=1):
        chunk_stem = f"{output_stem}_p{start_page:03d}-{end_page:03d}"
        export_chunk_text = _filter_chunk_by_expected_page_window(
            chunk_text,
            start_page=start_page,
            end_page=end_page,
            tolerance=2,
        )
        export_chunk_text = _filter_chunk_by_local_page_monotonicity(
            export_chunk_text,
            max_backward_jump=10,
        )
        export_chunk_text = _drop_transform_table_contamination(
            export_chunk_text,
            start_page=start_page,
        )
        export_chunk_text = _dedupe_standalone_image_paragraphs(export_chunk_text)
        export_chunk_text = _normalize_chunk_export_style(export_chunk_text)
        export_chunk_text = _maybe_retranslate_chunk_text(export_chunk_text)
        export_chunk_text = _normalize_chunk_export_style(export_chunk_text)
        chunk_md_path = chunk_dir / f"{chunk_stem}.md"
        chunk_md_path.write_text(export_chunk_text, encoding="utf-8")
        log.info(
            "Chunk PDF %d/%d – pages %03d-%03d",
            index,
            len(chunk_specs),
            start_page,
            end_page,
        )
        try:
            generated_pdf_path = _build_pdf_only_from_markdown(
                md_text=export_chunk_text,
                output_stem=chunk_stem,
                output_dir=chunk_dir,
                images_dir=images_dir,
            )
            generated_paths.append(generated_pdf_path)
            manifest_lines.append(
                f"{index}\t{start_page:03d}-{end_page:03d}\tOK\t{chunk_md_path.name}\t{generated_pdf_path.name}"
            )
        except Exception as exc:
            log.error(
                "Chunk PDF %d/%d failed for pages %03d-%03d: %s",
                index,
                len(chunk_specs),
                start_page,
                end_page,
                exc,
            )
            manifest_lines.append(
                f"{index}\t{start_page:03d}-{end_page:03d}\tFAILED\t{chunk_md_path.name}\t{exc}"
            )

    manifest_path = chunk_dir / "chunk_manifest.tsv"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    log.info("Saved chunk manifest: %s", manifest_path)
    return generated_paths


def _prepare_markdown_for_pdf(md_text: str) -> str:
    def sanitize_bare_math_paragraphs(text: str) -> str:
        parts = re.split(r'(\n\s*\n+)', text)
        sanitized_parts: list[str] = []

        for part in parts:
            if not part or re.fullmatch(r'\n\s*\n+', part):
                sanitized_parts.append(part)
                continue

            stripped = part.strip()
            if not stripped:
                sanitized_parts.append(part)
                continue

            if stripped.startswith(("```", "~~~", "![](")):
                sanitized_parts.append(part)
                continue

            if "$" in part or r"\[" in part or r"\(" in part:
                sanitized_parts.append(part)
                continue

            non_empty_lines = [line for line in stripped.splitlines() if line.strip()]
            if not non_empty_lines:
                sanitized_parts.append(part)
                continue

            math_line_count = sum(_looks_like_math_line(line) for line in non_empty_lines)
            if _BARE_ENV_NAME_PATTERN.search(stripped):
                sanitized_parts.append(_split_mixed_pdf_block(stripped))
                continue

            if math_line_count == len(non_empty_lines):
                sanitized_parts.append(_render_pdf_math_or_code(stripped))
                continue

            if 0 < math_line_count < len(non_empty_lines):
                sanitized_parts.append(_split_mixed_pdf_block(stripped))
                continue

            sanitized_parts.append(part)

        return "".join(sanitized_parts)

    prepared = clean_markdown_formatting(md_text)
    prepared = _remove_pdf_only_sections(prepared)
    prepared = _normalize_display_math_fences(prepared)
    prepared = _normalize_image_links(prepared, IMAGES_DIR)
    prepared = prepared.replace(r'\$\$', '$$').replace(r'\$', '$').replace(r'\_', '_')
    prepared = prepared.replace(r'\rm ', r'\mathrm{ }').replace(r'\rm', r'\mathrm')

    def promote_inline_environment(match: re.Match[str]) -> str:
        return _render_pdf_math_or_code(match.group("content"))

    prepared = _INLINE_ENV_MATH_PATTERN.sub(promote_inline_environment, prepared)

    def sanitize_inline_display_math(match: re.Match[str]) -> str:
        return _render_pdf_math_or_code(match.group(1))

    # Do not rewrite multiline $$...$$ or \[...\] fences here. In OCR-heavy
    # chapters a stray fence earlier in the file can make a DOTALL regex pair
    # the wrong delimiters and corrupt an otherwise valid display block.
    # Existing fenced display math is preserved as-is; only same-line display
    # math gets normalized through the math/code sanitizer.
    prepared = re.sub(r"\$\$([^\n]+?)\$\$", sanitize_inline_display_math, prepared)
    prepared = re.sub(r"\\\[([^\n]+?)\\\]", sanitize_inline_display_math, prepared)
    prepared = sanitize_bare_math_paragraphs(prepared)
    prepared = _sanitize_inline_pdf_math(prepared)
    prepared = _wrap_remaining_tex_fragments(prepared)
    prepared = _repair_known_pdf_math_artifacts(prepared)
    prepared = re.sub(
        r'(?ms)^\s*\$\$\s*$\n(?:\s*\n)*^\s*\$\$\s*$\n?',
        '',
        prepared,
    )
    prepared = re.sub(r"\$\$\s*\.\.", "$$", prepared)
    prepared = re.sub(r"\n{3,}", "\n\n", prepared)
    return prepared


def _prepare_markdown_for_safe_pdf(md_text: str) -> str:
    safe_text = _prepare_markdown_for_pdf(md_text)

    def block_to_code(match: re.Match[str]) -> str:
        inner = _normalize_pdf_math_content(match.group(1))
        if not inner:
            return "\n\n"
        return _render_pdf_code_block(inner)

    safe_text = re.sub(r"\$\$(.*?)\$\$", block_to_code, safe_text, flags=re.DOTALL)
    safe_text = re.sub(r"\\\[(.*?)\\\]", block_to_code, safe_text, flags=re.DOTALL)
    safe_text = re.sub(r"\\\((.*?)\\\)", lambda m: f"`{m.group(1).strip()}`", safe_text, flags=re.DOTALL)
    safe_text = re.sub(
        r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
        lambda m: f"`{m.group(1).strip()}`",
        safe_text,
        flags=re.DOTALL,
    )
    safe_text = _neutralize_residual_safe_pdf_tex(safe_text)
    safe_text = re.sub(r"\n{3,}", "\n\n", safe_text)
    return safe_text


def _inject_graphics_path(tex_text: str, graphics_root_dir: Path) -> str:
    graphics_root = graphics_root_dir.absolute().as_posix().rstrip("/") + "/"
    graphics_line = (
        f"\\graphicspath{{{{{graphics_root}}}}}\n"
        "\\setkeys{Gin}{width=0.66\\linewidth,height=0.70\\textheight,keepaspectratio}\n"
    )

    if "\\graphicspath{" in tex_text:
        return re.sub(r'\\graphicspath\{.*?\}\n?', graphics_line, tex_text, count=1)

    marker = "\\usepackage{graphicx}\n"
    if marker in tex_text:
        return tex_text.replace(marker, marker + graphics_line, 1)

    return tex_text


def _inject_pdf_layout_tuning(tex_text: str) -> str:
    if "\\clubpenalty=10000" in tex_text:
        return tex_text

    tuning_block = (
        "\\usepackage{float}\n"
        "\\usepackage[section]{placeins}\n"
        "\\raggedbottom\n"
        "\\clubpenalty=10000\n"
        "\\widowpenalty=10000\n"
        "\\displaywidowpenalty=10000\n"
        "\\brokenpenalty=10000\n"
        "\\emergencystretch=2em\n"
        "\\allowdisplaybreaks[2]\n"
        "\\setlength{\\textfloatsep}{12pt plus 2pt minus 4pt}\n"
        "\\setlength{\\floatsep}{10pt plus 2pt minus 2pt}\n"
        "\\setlength{\\intextsep}{10pt plus 2pt minus 2pt}\n"
        "\\makeatletter\n"
        "\\def\\fps@figure{htbp}\n"
        "\\makeatother\n"
    )

    marker = "\\begin{document}\n"
    if marker in tex_text:
        return tex_text.replace(marker, tuning_block + marker, 1)

    return tuning_block + tex_text


def _inject_pdf_fonts(tex_text: str) -> str:
    if "\\setmainfont{" in tex_text:
        return tex_text

    marker = "\\usepackage{lmodern}\n"
    font_block = (
        "\\usepackage{lmodern}\n"
        "\\ifPDFTeX\\else\n"
        "\\setmainfont{DejaVu Serif}\n"
        "\\setsansfont{DejaVu Sans}\n"
        "\\setmonofont{DejaVu Sans Mono}\n"
        "\\setmathfont{STIX Two Math}\n"
        "\\fi\n"
    )

    if marker in tex_text:
        return tex_text.replace(marker, font_block, 1)

    return tex_text


def _extract_latex_error_summary(stdout: str, stderr: str) -> str:
    combined_output = "\n".join(part for part in (stdout, stderr) if part)
    error_lines: list[str] = []

    for line in combined_output.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("!")
            or re.match(r"^[^:]+:\d+:", stripped)
            or "Emergency stop" in stripped
        ):
            error_lines.append(stripped)

    if error_lines:
        return "\n".join(error_lines[-15:])

    tail_lines = combined_output.splitlines()[-20:]
    return "\n".join(tail_lines).strip()


def _build_pdf_via_tex(
    md_text: str,
    output_stem: str,
    output_dir: Path,
    res_path: str,
    graphics_root_dir: Optional[Path] = None,
    allow_partial_output: bool = False,
    input_format: str = "markdown+raw_tex+tex_math_dollars",
) -> Path:
    try:
        import pypandoc
    except ImportError as exc:
        raise RuntimeError("pypandoc is required to generate intermediate TeX.") from exc

    if not shutil.which("xelatex"):
        raise RuntimeError("XeLaTeX is not available in PATH.")

    build_dir = TEMP_PDF_BUILD_DIR / output_stem
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    tex_path = build_dir / f"{output_stem}.tex"
    pdf_path = build_dir / f"{output_stem}.pdf"

    tex_extra_args = [
        "--standalone",
        f"--resource-path={res_path}",
        "-V", "lang=uk",
        "-V", "geometry:margin=2.5cm",
    ]

    pypandoc.convert_text(
        md_text,
        "tex",
        format=input_format,
        outputfile=str(tex_path),
        extra_args=tex_extra_args,
    )

    tex_text = tex_path.read_text(encoding="utf-8")
    tex_text = _inject_pdf_fonts(tex_text)
    tex_text = _inject_graphics_path(tex_text, graphics_root_dir or output_dir)
    tex_text = _inject_pdf_layout_tuning(tex_text)
    tex_path.write_text(tex_text, encoding="utf-8")

    latex_cmd = [
        "xelatex",
        "-interaction=nonstopmode",
        "-file-line-error",
        tex_path.name,
    ]

    last_error_summary = ""
    had_recoverable_latex_errors = False

    for _ in range(2):
        result = subprocess.run(
            latex_cmd,
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            last_error_summary = _extract_latex_error_summary(result.stdout, result.stderr)
            if not allow_partial_output:
                raise RuntimeError(last_error_summary or "XeLaTeX failed without a readable error summary.")
            had_recoverable_latex_errors = True

    if not pdf_path.exists():
        raise RuntimeError(last_error_summary or "XeLaTeX completed without producing a PDF file.")

    if had_recoverable_latex_errors:
        log.warning("  XeLaTeX produced a PDF with recoverable errors: %s", last_error_summary)

    final_pdf_path = output_dir / f"{output_stem}.pdf"
    shutil.copy2(pdf_path, final_pdf_path)
    return final_pdf_path


def export_to_book_formats(
    md_text: str, 
    output_stem: str, 
    output_dir: Path,
    images_dir: Path
):
    try:
        import pypandoc
    except ImportError:
        log.warning("pypandoc not installed. Run 'pip install pypandoc'. Skipping EPUB/PDF export.")
        return

    epub_path = output_dir / f"{output_stem}.epub"
    pdf_path  = output_dir / f"{output_stem}.pdf"
    css_path  = BASE_DIR / "book_style.css"

    log.info("Stage 6 – Exporting to EPUB and PDF via pandoc ...")

    export_md_text = _remove_pdf_only_sections(md_text)

    res_path = _build_resource_path(output_dir, images_dir)
    
    epub_args = [
        "--mathml",
        f"--resource-path={res_path}",
    ]
    if css_path.exists():
        epub_args.append(f"--css={str(css_path)}")

    try:
        pypandoc.convert_text(
            export_md_text,
            'epub',
            format='markdown',
            outputfile=str(epub_path),
            extra_args=epub_args,
        )
        log.info("  Generated EPUB: %s", epub_path)
    except Exception as e:
        log.error("  EPUB generation failed: %s", e)

    try:
        _build_pdf_only_from_markdown(
            md_text=export_md_text,
            output_stem=output_stem,
            output_dir=output_dir,
            images_dir=images_dir,
        )
    except Exception as e:
        log.error(
            "  PDF generation failed. Ensure XeLaTeX (MiKTeX/TeX Live) is installed and in PATH. Details: %s",
            e,
        )

# ===========================================================================
# Orchestration
# ===========================================================================

def process_document(
    input_pdf_path:  Optional[str | Path] = None,
    input_md_path:   Optional[str | Path] = None,
    output_md_path:  Optional[str | Path] = None,
    api_key:         Optional[str] = None,
    endpoint:        Optional[str] = None,
    region:          Optional[str] = None,
    target_lang:     str = TARGET_LANG,
    rebuild_only:    bool = False,
) -> Path:
    api_key = api_key or AZURE_TRANSLATOR_KEY
    endpoint = endpoint or AZURE_TRANSLATOR_ENDPOINT
    region = region or AZURE_TRANSLATOR_REGION
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    if input_md_path:
        md_path = Path(input_md_path)
        log.info("Stage 1 – Loading pre-parsed Markdown: %s", md_path)
        md_text = md_path.read_text(encoding="utf-8")
        stem = md_path.stem
        
        source_images = md_path.parent / "images"
        if source_images.exists() and source_images.is_dir():
            if source_images.resolve() != IMAGES_DIR.resolve():
                shutil.copytree(source_images, IMAGES_DIR, dirs_exist_ok=True)
                log.info("  Copied images from source folder.")
            else:
                log.info("  Source images already point to the working images folder; skipping copy.")
    elif input_pdf_path:
        pdf_path = Path(input_pdf_path)
        stem = pdf_path.stem
        log.info("Stage 1 – Splitting PDF: %s", pdf_path)
        chunk_paths = split_pdf(pdf_path, chunk_dir=TEMP_CHUNKS_DIR, chunk_size=50)
        
        md_chunks = []
        for i, chunk_pdf in enumerate(chunk_paths):
            prefix = f"chunk{i+1:02d}_"
            log.info("Processing chunk %s", chunk_pdf.name)
            chunk_md = parse_pdf_to_md(chunk_pdf, images_dir=IMAGES_DIR, image_prefix=prefix)
            md_chunks.append(chunk_md)
            
        md_text = "\n\n".join(md_chunks)
        raw_path = OUTPUT_DIR / f"{stem}_raw.md"
        raw_path.write_text(md_text, encoding="utf-8")
        log.info("Сырой текст сохранен в %s. Если перевод прервется, вы сможете запустить скрипт, передав этот файл.", raw_path.name)
    else:
        raise ValueError("Provide either 'input_pdf_path' or 'input_md_path'.")

    original_md_text = md_text
    md_text = _repair_known_source_markdown_artifacts(md_text)

    if not rebuild_only:
        rescued_md_text = rescue_broken_latex(md_text)
        masked_text, elements_dict = mask_elements(rescued_md_text)

        translated_text = translate_text_azure(
            text=masked_text, 
            api_key=api_key, 
            endpoint=endpoint, 
            region=region, 
            target_lang=target_lang
        )

        final_md = unmask_elements(translated_text, elements_dict)
        final_md = _safe_second_pass_cleanup(final_md)
        final_md = retranslate_residual_russian_paragraphs(
            final_md,
            api_key=api_key,
            endpoint=endpoint,
            region=region,
            target_lang=target_lang,
        )
        final_md = _safe_second_pass_cleanup(final_md)
        log.info("  Stage 4b – Markdown formatting and second-pass cleanup complete.")
    else:
        final_md = _safe_second_pass_cleanup(md_text)
        final_md = retranslate_residual_russian_paragraphs(
            final_md,
            api_key=api_key,
            endpoint=endpoint,
            region=region,
            target_lang=target_lang,
        )
        final_md = _safe_second_pass_cleanup(final_md)
        log.info("  Rebuild mode: Translation skipped, second-pass cleanup applied.")

    final_md = _restore_unresolved_placeholders(final_md, original_md_text)
    final_md = _repair_known_pdf_math_artifacts(final_md)
    final_md = _normalize_image_links(final_md, IMAGES_DIR)
    out_path = OUTPUT_DIR / f"{stem}_uk.md"
    out_path.write_text(final_md, encoding="utf-8")

    export_to_book_formats(final_md, stem, OUTPUT_DIR, images_dir=IMAGES_DIR)

    log.info("=" * 60)
    log.info("Pipeline complete! Output: %s", out_path)
    log.info("=" * 60)
    return out_path

# ===========================================================================
# CLI entry-point
# ===========================================================================

if __name__ == "__main__":
    import glob
    
    print("\n" + "=" * 70)
    print(" 📚 Azure Book Translator (PDF Chunks & MD)")
    print("=" * 70)

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = list(INPUT_DIR.glob("*.pdf"))
    mds = list(INPUT_DIR.glob("*.md"))
    all_files = pdfs + mds

    input_file = None
    if len(all_files) == 1:
        auto_f = all_files[0]
        print(f"✔️  Найден один файл: {auto_f.name}")
        use_auto = input("👉 Использовать его? (Y/n): ").strip().lower()
        if use_auto != 'n':
            input_file = str(auto_f)
            
    if not input_file and len(all_files) > 0:
        print("\nДоступные файлы в 'input/':")
        for idx, f in enumerate(all_files, 1):
            print(f"  {idx}. {f.name}")
        print("  0. Указать другой файл (drag & drop)")
        
        choice = input("👉 Выберите файл (цифра):\n> ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(all_files):
            input_file = str(all_files[int(choice)-1])
            
    if not input_file:
        raw_path = input("\n👉 Перетащите .pdf или .md файл в консоль:\n> ").strip()
        input_file = raw_path.strip('\'"')
        
    if not input_file:
        print("❌ Файл не выбран.")
        sys.exit(1)

    input_path = Path(input_file)
    if not input_path.exists():
        print(f"❌ Ошибка. Файл не найден: {input_path}")
        sys.exit(1)

    print("\nРежимы:")
    print("  1. Перевод (Полный цикл: распознавание PDF/чтение MD -> Azure)")
    print("  2. Пересборка (Без перевода: только генерация PDF/EPUB из существующего MD)")
    mode = input("👉 Выберите режим (1 или 2):\n> ").strip()
    
    rebuild = (mode == '2')
    is_pdf = input_path.suffix.lower() == '.pdf'
    
    if not shutil.which("pandoc"):
        log.warning("ВНИМАНИЕ: Pandoc не найден. Конвертация в PDF/EPUB будет пропущена.")
    if not shutil.which("xelatex"):
        log.warning("ВНИМАНИЕ: XeLaTeX не найден. Конвертация в PDF будет невозмона.")

    try:
        process_document(
            input_pdf_path=input_path if is_pdf else None,
            input_md_path=input_path if not is_pdf else None,
            rebuild_only=rebuild,
        )
        print(f"\n✅ Готово! Файлы лежат в {OUTPUT_DIR}\n")
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        sys.exit(1)
