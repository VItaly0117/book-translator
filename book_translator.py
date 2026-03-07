"""
book_translator.py
==================
Automated pipeline to translate a mathematical physics textbook from English
to Ukrainian using the DeepL API, while preserving ALL LaTeX formulas AND
Markdown image links with 100 % fidelity.

Pipeline stages:
    1. parse_pdf_to_md()      – convert PDF → Markdown (with images & LaTeX)
    2. mask_elements()        – replace LaTeX + image links with opaque tokens
    3. translate_text_deepl() – translate token-only text via DeepL API
    4. unmask_elements()      – restore originals from the token dictionary
    5. process_document()     – orchestrate all stages end-to-end

What gets protected (masked):
    ┌─────────────────────────────────┬───────────────────────────┐
    │ Element                         │ Placeholder format        │
    ├─────────────────────────────────┼───────────────────────────┤
    │ Block math   $$...$$            │ MATHBLK0001X              │
    │ Block math   \\[...\\]           │ MATHBLK0002X              │
    │ Inline math  $...$              │ MATHINL0001X              │
    │ Inline math  \\(...\\)          │ MATHINL0002X              │
    │ Markdown image  ![alt](src)     │ IMGTOKEN0001X             │
    └─────────────────────────────────┴───────────────────────────┘

All placeholders are purely alphanumeric so DeepL treats them as
untranslatable code tokens.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
import datetime
import sqlite3
import hashlib
import concurrent.futures
import csv
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Optional: OpenCV for image enhancement
# ---------------------------------------------------------------------------
try:
    import cv2          # type: ignore
    import numpy as np  # type: ignore
    _CV2_AVAILABLE = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore
    np = None   # type: ignore
    _CV2_AVAILABLE = False

# ---------------------------------------------------------------------------
# Try to import deepl at module level so tests can patch it easily.
# We keep a module-level reference; the actual ImportError is raised only
# when translate_text_deepl() is actually called.
# ---------------------------------------------------------------------------
try:
    import deepl  # type: ignore
except ImportError:  # pragma: no cover
    deepl = None  # type: ignore

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

DEEPL_API_KEY: str = os.getenv("DEEPL_API_KEY", "")
TARGET_LANG: str   = os.getenv("TARGET_LANG", "UK")

BASE_DIR   = Path(__file__).parent
INPUT_DIR  = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
IMAGES_DIR = BASE_DIR / "images"

# DeepL max payload is 128 KB UTF-8.  We use 10 000 chars as a safe ceiling.
CHUNK_SIZE = 10_000

# ---------------------------------------------------------------------------
# Placeholder templates
# All must be purely [A-Za-z0-9] so DeepL treats them as opaque tokens.
# ---------------------------------------------------------------------------
_PH_MATH_BLOCK  = "MATHBLK{idx:04d}X"   # display / block math
_PH_MATH_INLINE = "MATHINL{idx:04d}X"   # inline math
_PH_IMAGE       = "IMGTOKEN{idx:04d}X"  # Markdown image links
_PH_PAGENUM     = "PAGENUM{idx:04d}X"   # Page numbers

# ---------------------------------------------------------------------------
# Regex patterns (applied in ORDER – most specific first to avoid overlap)
# ---------------------------------------------------------------------------
# Group 1: block-level math patterns
_BLOCK_MATH_PATTERNS: list[tuple[str, int]] = [
    (r"\$\$.*?\$\$",    re.DOTALL),   # $$...$$
    (r"\\\[.*?\\\]",    re.DOTALL),   # \[...\]
]

# Group 2: inline math patterns
_INLINE_MATH_PATTERNS: list[tuple[str, int]] = [
    (r"(?<!\$)\$(?!\$).+?(?<!\$)\$(?!\$)", re.DOTALL),  # $...$
    (r"\\\(.*?\\\)",                        re.DOTALL),  # \(...\)
]

# Group 3: Markdown image links  ![alt text](path/to/image.png)
# Captures the entire ![...](...)  construct including any whitespace inside.
_IMAGE_PATTERN = (r"!\[[^\]]*\]\([^)]+\)", 0)   # flags=0 (single-line OK)


# ===========================================================================
# Image Enhancement (OpenCV)
# ===========================================================================

def enhance_book_image(image_path: str | Path) -> None:
    """
    Enhance a scanned book image in-place using classic computer-vision
    algorithms.  The result is a strictly binary (pure black / pure white)
    image saved back to the same path.

    Algorithm
    ---------
    1. Convert to grayscale.
    2. Apply a 3×3 median blur to remove salt-and-pepper noise.
    3. Binarise with Otsu's global threshold – background becomes pure white
       (255) and all foreground pixels (lines / text) become pure black (0).
    4. Overwrite the original file with the cleaned image.

    If OpenCV (``cv2``) is not installed the function logs a warning and
    returns immediately without modifying the file.

    Parameters
    ----------
    image_path : str | Path
        Path to the image file (PNG / JPEG / TIFF …).
    """
    if not _CV2_AVAILABLE:
        log.warning("enhance_book_image: cv2 not installed – skipping image enhancement.")
        return

    image_path = str(image_path)
    img = cv2.imread(image_path)
    if img is None:
        log.warning("enhance_book_image: cannot read image %s – skipping.", image_path)
        return

    # 1. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 2. Median blur – removes isolated noise pixels without smearing edges
    blurred = cv2.medianBlur(gray, 3)

    # 3. Otsu binarisation (global, works well for old scanned pages)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    # 4. Save back to the same path
    cv2.imwrite(image_path, binary)
    log.debug("enhance_book_image: processed %s", image_path)
# ===========================================================================
# Markdown Formatting Cleanup
# ===========================================================================

def clean_markdown_formatting(md_text: str) -> str:
    """Очищает грязный Markdown, сгенерированный marker-pdf."""
    
    # 0. ФИКС РАЗОРВАННЫХ ПРЕДЛОЖЕНИЙ (когда картинка влезает посреди слова)
    # Пример: "мідна і \n\n ![img] \n\n сталь-" -> "мідна і сталь- \n\n ![img]"
    md_text = re.sub(
        r'([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\-]+)\s*\n+(!\[.*?\]\(.*?\))\s*\n+([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ])', 
        r'\1 \3\n\n\2\n\n', 
        md_text
    )

    # 1. Удаляем обратные кавычки вокруг формул (спасает от серых фонов)
    # Заменяем `\s*\$(.*?)\$\s*` на $\1$ (для инлайн формул) и `\s*\$\$(.*?)\$\$\s*` на $$\1$$ (для блочных)
    md_text = re.sub(r'`\s*\$\$(.*?)\$\$\s*`', r'$$\1$$', md_text, flags=re.DOTALL)
    md_text = re.sub(r'`\s*\$(.*?)\$\s*`', r'$\1$', md_text)
    
    # 1.5 Добавляем пробел между кириллицей и математикой ($) 
    md_text = re.sub(r'([а-яА-ЯёЁіІїЇєЄґҐ])\$', r'\1 $', md_text)
    md_text = re.sub(r'\$([а-яА-ЯёЁіІїЇєЄґҐ])', r'$ \1', md_text)
    
    # 2. Исправляем специфичный баг склеивания переменных OCR-ом
    md_text = re.sub(r'\bxit\b', '$x$ і $t$', md_text)
    md_text = re.sub(r'r,\s*\\theta\s*it\b', '$r$, $\\theta$ і $t$', md_text)
    md_text = md_text.replace('$x~i~t$', '$x$ і $t$')
    md_text = md_text.replace('$r,\\theta i~t$', '$r$, $\\theta$ і $t$')
    
    # 3. Втягиваем одиночные инлайн-формулы и союзы из отдельных абзацев обратно в строку
    md_text = re.sub(r'\n+\s*(\$[^$\n]+\$)\s*\n+', r' \1 ', md_text)
    md_text = re.sub(r'\n+\s*(i|і|та|або|а)\s*\n+', r' \1 ', md_text)
    
    # 4. Притягиваем оторванную пунктуацию (запятые, точки) обратно к формулам и тексту
    md_text = re.sub(r'\s*\n+\s*([\,\.\;\:\)])', r'\1', md_text)
    
    # Схлопываем одинокаие переносы строк внутри предложений (чтобы абзацы не разрывались)
    # Оставляем только \n\n для реальных абзацев
    md_text = re.sub(r'([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\-]+)\n([a-zA-Zа-яА-ЯёЁіІїЇєЄґҐ\-])', r'\1 \2', md_text)
    
    # 5. Уничтожаем мусор из разрушенных таблиц (3+ запятых подряд меняем на пробел)
    md_text = re.sub(r',{3,}', ' ', md_text)
    md_text = re.sub(r'^[ \t\,]+$', '', md_text, flags=re.MULTILINE)
    
    # 6. Фикс отступов у блочных формул: pandoc делает серый фон, если перед $$ есть пробелы
    md_text = re.sub(r'^[ \t]+(\$\$)', r'\1', md_text, flags=re.MULTILINE)
    
    # 7. Защищаем картинки (добавляем пустые строки, чтобы текст не прилипал)
    md_text = re.sub(r'\s*(!\[.*?\]\(.*?\))\s*', r'\n\n\1\n\n', md_text)
    
    # 8. Схлопываем гигантские пробелы (3+ переноса строки) в стандартные абзацы
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    
    # 9. Заменяем устаревшие теги LaTeX для Pandoc
    md_text = md_text.replace(r"\rm ", r"\mathrm{ }").replace(r"\rm", r"\mathrm")
    
    return md_text


# ===========================================================================
# Stage 1 – PDF → Markdown
# ===========================================================================

def parse_pdf_to_md(
    pdf_path: str | Path,
    images_dir: Optional[Path] = None,
    max_pages: Optional[int] = None,
) -> str:
    """
    Convert a PDF file to Markdown, preserving LaTeX formulas and images.

    Uses `marker-pdf` (AI-powered, best quality) for parsing.

    Parameters
    ----------
    pdf_path : str | Path
        Source PDF to convert.
    images_dir : Path, optional
        Where to save extracted raster images. Defaults to ``images/``.
    max_pages : int, optional
        Process only first N pages (for testing).

    Returns
    -------
    str
        Full Markdown text with formulas and image references intact.
    """
    pdf_path   = Path(pdf_path)
    images_dir = images_dir or IMAGES_DIR
    images_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    log.info("Stage 1 – Parsing PDF (marker): %s", pdf_path)

    try:
        log.info("  Using marker-pdf parser (loading models, this may take a while) …")
        if max_pages:
            log.info("  ⚙️  max-pages limit: %d", max_pages)

        # ── Try new API first: marker-pdf >= 1.0 ────────────────────────────
        try:
            from marker.converters.pdf import PdfConverter      # type: ignore
            from marker.models import create_model_dict         # type: ignore
            from marker.config.parser import ConfigParser       # type: ignore

            log.info("  Detected marker-pdf v1.x API")
            cfg: dict = {"languages": ["Russian"]}
            if max_pages:
                cfg["max_pages"] = max_pages

            config_parser = ConfigParser(cfg)
            converter = PdfConverter(
                config=config_parser.generate_config_dict(),
                artifact_dict=create_model_dict(),
                llm_service=None,
            )
            rendered = converter(str(pdf_path))
            full_text = rendered.markdown

            for img_name, img_obj in rendered.images.items():
                dest = images_dir / img_name
                img_obj.save(str(dest))
                log.info("  Saved image: %s", dest)
                enhance_book_image(dest)

        # ── Fall back to old API: marker-pdf < 1.0 ──────────────────────────
        except ImportError:
            from marker.convert import convert_single_pdf  # type: ignore
            from marker.models import load_all_models       # type: ignore

            log.info("  Detected marker-pdf v0.x API")
            models = load_all_models()
            full_text, images, _meta = convert_single_pdf(
                str(pdf_path),
                models,
                max_pages=max_pages,
                langs=["Russian"],
                batch_multiplier=1,
            )
            for img_name, img_obj in images.items():
                dest = images_dir / img_name
                img_obj.save(str(dest))
                log.info("  Saved image: %s", dest)
                enhance_book_image(dest)

        log.info("Stage 1 complete – %d characters extracted.", len(full_text))
        return full_text

    except ImportError:
        raise ImportError(
            "marker-pdf is not installed.\n"
            "  Run: pip install marker-pdf\n\n"
            "Or convert the PDF manually and use:\n"
            "  python3 book_translator.py --md input/your_book.md"
        )


# ===========================================================================
# Stage 2 – Masking (formulas + images)
# ===========================================================================

def mask_elements(md_text: str) -> tuple[str, dict[str, str]]:
    """
    Replace all LaTeX formulas AND Markdown image links with opaque
    alphanumeric placeholders that DeepL will not touch.

    Processing order (important – applied sequentially):
        1. Block math  ($$...$$  and  \\[...\\])
        2. Inline math ($...$  and  \\(...\\))
        3. Image links (![alt](src))

    This order prevents inline patterns from partially matching block math.

    Parameters
    ----------
    md_text : str
        Raw Markdown (from Stage 1 or a pre-converted file).

    Returns
    -------
    masked_text : str
        Text with all protected elements replaced by tokens.
    elements_dict : dict[str, str]
        Maps every placeholder → its original string for exact restoration.
    """
    elements_dict: dict[str, str] = {}
    block_idx  = 0
    inline_idx = 0
    image_idx  = 0
    page_idx   = 0

    result = md_text

    # --- 1. Block math ---
    def _replace_block(match: re.Match) -> str:
        nonlocal block_idx
        ph = _PH_MATH_BLOCK.format(idx=block_idx)
        elements_dict[ph] = match.group(0)
        block_idx += 1
        # Surround with newlines so the placeholder stands on its own line
        return f"\n\n{ph}\n\n"

    for pattern, flags in _BLOCK_MATH_PATTERNS:
        result = re.sub(pattern, _replace_block, result, flags=flags)

    # --- 2. Inline math ---
    def _replace_inline(match: re.Match) -> str:
        nonlocal inline_idx
        ph = _PH_MATH_INLINE.format(idx=inline_idx)
        elements_dict[ph] = match.group(0)
        inline_idx += 1
        return f" {ph} "

    for pattern, flags in _INLINE_MATH_PATTERNS:
        result = re.sub(pattern, _replace_inline, result, flags=flags)

    # --- 3. Image links ---
    def _replace_image(match: re.Match) -> str:
        nonlocal image_idx
        ph = _PH_IMAGE.format(idx=image_idx)
        elements_dict[ph] = match.group(0)
        image_idx += 1
        # Keep on its own line so pandoc does not merge it into prose
        return f"\n\n{ph}\n\n"

    img_pattern, img_flags = _IMAGE_PATTERN
    result = re.sub(img_pattern, _replace_image, result, flags=img_flags)

    # --- 4. Page numbers ---
    def _replace_page(match: re.Match) -> str:
        nonlocal page_idx
        ph = _PH_PAGENUM.format(idx=page_idx)
        elements_dict[ph] = match.group(0).strip()
        page_idx += 1
        return f"\n\n{ph}\n\n"

    result = re.sub(r"(?im)^\s*(?:\[page\s*\d+\]|\d+)\s*$", _replace_page, result)

    log.info(
        "Stage 2 – Masked %d block-math, %d inline-math, %d image(s), %d page(s).",
        block_idx, inline_idx, image_idx, page_idx,
    )
    return result, elements_dict


# ---------------------------------------------------------------------------
# Backward-compatible alias (keeps old tests / scripts working)
# ---------------------------------------------------------------------------
def mask_math(md_text: str) -> tuple[str, dict[str, str]]:
    """Alias for mask_elements() – deprecated, use mask_elements() instead."""
    return mask_elements(md_text)


# ===========================================================================
# Stage 3 – DeepL Translation
# ===========================================================================

def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """
    Split *text* into chunks of at most *chunk_size* characters.

    Always tries to break at a paragraph boundary (double newline) to keep
    sentences intact.  Falls back to single newline, then hard-splits as a
    last resort.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break

        # Prefer paragraph break …
        split_pos = text.rfind("\n\n", int(start), int(end))
        if split_pos <= start:
            # … then single newline …
            split_pos = text.rfind("\n", int(start), int(end))
        if split_pos <= start:
            # … last resort: hard cut
            split_pos = int(end) - 1

        # Prevent splitting a chunk such that it ends with a markdown header without its content
        while split_pos > start:
            chunk_so_far = text[start : split_pos + 1].rstrip()
            last_newline = int(chunk_so_far.rfind("\n"))
            last_line = chunk_so_far[last_newline + 1:] if last_newline != -1 else chunk_so_far
            if re.match(r"^#+\s", last_line):
                # The chunk ends with a header. Move split_pos back to before this header.
                prev_split = int(text.rfind("\n", start, start + last_newline) if last_newline != -1 else -1)
                if prev_split <= start:
                    break  # Can't go further back, accept it
                split_pos = prev_split
            else:
                break

        chunks.append(text[int(start) : int(split_pos) + 1])
        start = int(split_pos) + 1

    log.info("  Splitting into %d chunk(s) for translation.", len(chunks))
    return chunks


def translate_text_deepl(
    text: str,
    api_key: str,
    target_lang: str = TARGET_LANG,
    chunk_size: int  = CHUNK_SIZE,
    retry_attempts: int   = 3,
    retry_delay:    float = 5.0,
) -> str:
    """
    Translate *text* from English to *target_lang* using the DeepL API.

    Key behaviours:
    * Auto-chunks text to stay under DeepL's 128 KB per-request limit.
    * Uses ``preserve_formatting=True`` to avoid whitespace mangling around
      placeholders.
    * Retries with exponential back-off on transient API errors.
    * Uses `sqlite3` for local caching to survive disconnects and save progress.
    * Translates chunks in parallel using ThreadPoolExecutor.
    """
    if deepl is None:
        raise ImportError("DeepL package missing. Run: pip install deepl")

    if not api_key:
        raise ValueError(
            "DEEPL_API_KEY is not set. "
            "Copy .env.template → .env and fill in your key."
        )

    translator = deepl.Translator(api_key)
    chunks     = _chunk_text(text, chunk_size)

    # ── 1. Glossary Support ──
    glossary_id = None
    glossary_path = BASE_DIR / "glossary.csv"
    if glossary_path.exists():
        try:
            entries = {}
            with open(glossary_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        entries[row[0].strip()] = row[1].strip()
            if entries:
                glossary = translator.create_glossary(
                    "Project Glossary", source_lang="RU", target_lang=target_lang, entries=entries
                )
                glossary_id = glossary.glossary_id
                log.info("  Loaded glossary from glossary.csv with %d entries.", len(entries))
        except Exception as e:
            log.warning("  Failed to load glossary.csv: %s", e)

    # ── 2. DB Cache Setup ──
    db_path = BASE_DIR / "cache.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS translation_cache (md5 TEXT PRIMARY KEY, translated_text TEXT)"
        )

    # ── 3. Parallel Translation Function ──
    def _translate_chunk(args_tuple) -> str:
        i, chunk = args_tuple
        chunk_md5 = hashlib.md5(chunk.encode('utf-8')).hexdigest()
        
        # Check cache
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT translated_text FROM translation_cache WHERE md5 = ?", (chunk_md5,))
            row = cursor.fetchone()
            if row:
                log.info("  Chunk %d/%d – Loaded from cache", i, len(chunks))
                return row[0]

        log.info("  Chunk %d/%d – Transmitting %d chars …", i, len(chunks), len(chunk))
        for attempt in range(1, retry_attempts + 1):
            try:
                # Need to use **kwargs because glossary is only accepted if not None
                kwargs = {
                    "source_lang": "RU",
                    "target_lang": target_lang,
                    "preserve_formatting": True
                }
                if glossary_id:
                    kwargs["glossary"] = glossary_id
                    
                result = translator.translate_text(chunk, **kwargs)
                res_text = result.text
                
                # Save to cache
                with sqlite3.connect(db_path, timeout=10) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO translation_cache (md5, translated_text) VALUES (?, ?)", 
                        (chunk_md5, res_text)
                    )
                return res_text
                
            except deepl.DeepLException as exc:
                log.warning("  Chunk %d – attempt %d/%d failed: %s", i, attempt, retry_attempts, exc)
                if attempt == retry_attempts:
                    raise
                time.sleep(retry_delay * (2 ** (attempt - 1)))
        return ""

    # ── 4. Execution ──
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(_translate_chunk, enumerate(chunks, start=1))
        translated = list(results)

    log.info("Stage 3 – Translation complete.")
    return "\n\n".join(translated)
    return text


# ===========================================================================
# Stage 4 – Unmasking
# ===========================================================================

def unmask_elements(
    translated_text: str,
    elements_dict: dict[str, str],
) -> str:
    """
    Restore every original element (LaTeX formula or image link) from
    *elements_dict* into *translated_text*, replacing its placeholder.

    Spacing rules after restoration:
    * Block math / images → surrounded by blank lines (``\\n\\n``).
    * Inline math         → surrounded by single spaces.

    DeepL sometimes changes whitespace around placeholders; this function
    uses a flexible ``\\s*TOKEN\\s*`` pattern to handle all variations.

    Parameters
    ----------
    translated_text : str
        DeepL output with placeholders still present (Stage 3 output).
    elements_dict : dict[str, str]
        Mapping  placeholder → original string, from Stage 2.

    Returns
    -------
    str
        Final Markdown with all LaTeX formulas and image links restored.
    """
    result = translated_text

    for placeholder, original in elements_dict.items():
        escaped = re.escape(placeholder)
        pattern = rf"\s*{escaped}\s*"

        # Determine spacing and restoration strategy based on placeholder type
        if placeholder.startswith("PAGENUM"):
            # Turn page numbers into clean page break dividers for EPUB/PDF
            replacement = '\n\n<div style="page-break-after: always;"></div>\n\n'
        else:
            is_block = (
                placeholder.startswith("MATHBLK")
                or placeholder.startswith("IMGTOKEN")
            )
            replacement = f"\n\n{original}\n\n" if is_block else f" {original} "

        # Use a lambda to prevent re.sub from interpreting backslashes in
        # the replacement string (critical for LaTeX with \frac, \sin, etc.)
        result = re.sub(pattern, lambda _m, r=replacement: r, result)

    # Normalise excess blank lines introduced by block restorations
    result = re.sub(r"\n{3,}", "\n\n", result)

    log.info(
        "Stage 4 – Unmasking complete. %d element(s) restored.",
        len(elements_dict),
    )
    return result


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------
def unmask_math(
    translated_text: str,
    math_dict: dict[str, str],
) -> str:
    """Alias for unmask_elements() – deprecated, use unmask_elements()."""
    return unmask_elements(translated_text, math_dict)


# ===========================================================================
# Stage 5 – Exporting via Pandoc
# ===========================================================================

def export_to_book_formats(
    md_text: str, 
    output_stem: str, 
    output_dir: Path,
    images_dir: Optional[Path] = None
):
    """
    Convert the final Markdown text into professionally styled EPUB and PDF
    books using Pandoc.
    """
    try:
        import pypandoc
    except ImportError:
        log.warning("pypandoc not installed. Run 'pip install pypandoc'. Skipping EPUB/PDF export.")
        return

    epub_path = output_dir / f"{output_stem}.epub"
    pdf_path  = output_dir / f"{output_stem}.pdf"
    css_path  = BASE_DIR / "book_style.css"

    log.info("Stage 6 – Exporting to EPUB and PDF via pandoc ...")

    # ВАЖНО ДЛЯ WINDOWS: принудительно заменяем относительные пути картинок на строгие абсолютные пути
    # Это гарантирует, что Pandoc стопроцентно найдет каждый файл
    images_abs_dir = (images_dir or IMAGES_DIR).absolute().as_posix()
    md_text = re.sub(r'\]\((?:images/|\./images/)', f']({images_abs_dir}/', md_text)
    
    import os
    res_path = f".{os.pathsep}{output_dir.absolute()}{os.pathsep}{(images_dir or IMAGES_DIR).absolute()}"
    
    # ------------------------------------------------------------------
    # EPUB – with MathML for formula rendering
    # ------------------------------------------------------------------
    epub_args = [
        "--mathml",
        f"--resource-path={res_path}",
    ]
    if css_path.exists():
        epub_args.append(f"--css={str(css_path)}")

    try:
        pypandoc.convert_text(
            md_text,
            'epub',
            format='markdown',
            outputfile=str(epub_path),
            extra_args=epub_args,
        )
        log.info("  Generated EPUB: %s", epub_path)
    except Exception as e:
        log.error("  EPUB generation failed: %s", e)

    # ------------------------------------------------------------------
    # PDF – XeLaTeX with full Cyrillic / Unicode font support
    # ------------------------------------------------------------------
    # XeLaTeX is required for Cyrillic (Ukrainian / Russian) text.
    # Without an explicit Cyrillic-capable font the text is silently
    # dropped by pdflatex, leaving only punctuation and formulas.
    pdf_args = [
        "--pdf-engine=xelatex",
        f"--resource-path={res_path}",
        # Main serif font – DejaVu Serif ships with most TeX distributions
        # and covers the full Cyrillic Unicode block.
        "-V", "mainfont=DejaVu Serif",
        # Monospace font for code blocks
        "-V", "monofont=DejaVu Sans Mono",
        # Sans-serif for headers
        "-V", "sansfont=DejaVu Sans",
        # Page numbering at the bottom-centre of every page
        "-V", "pagestyle=plain",
        # Required packages for Cyrillic + geometry
        "-V", "lang=uk",
        # fontenc / inputenc are handled automatically by XeLaTeX
        # geometry: standard book margins
        "-V", "geometry:margin=2.5cm",
    ]

    try:
        pypandoc.convert_text(
            md_text,
            'pdf',
            format='markdown+raw_tex',
            outputfile=str(pdf_path),
            extra_args=pdf_args,
        )
        log.info("  Generated PDF: %s", pdf_path)
    except Exception as e:
        log.error("  Ошибка генерации PDF. Убедитесь, что MiKTeX (XeLaTeX) установлен и добавлен в системный PATH Windows. Детали: %s", e)


# ===========================================================================
# Orchestration
# ===========================================================================

def process_document(
    input_pdf_path:  Optional[str | Path] = None,
    input_md_path:   Optional[str | Path] = None,
    output_md_path:  Optional[str | Path] = None,
    api_key:         Optional[str] = None,
    target_lang:     str = TARGET_LANG,
    max_pages:       Optional[int] = None,
) -> Path:
    """
    Run the complete translation pipeline end-to-end.

    Provide EITHER *input_pdf_path* (PDF will be parsed automatically via
    marker-pdf) OR *input_md_path* (uses a pre-converted Markdown, skipping
    Stage 1).

    Intermediate files saved to ``output/`` for debugging:
        ``<stem>_raw.md``                – raw marker-pdf output
        ``<stem>_masked.md``             – after formula/image masking
        ``<stem>_translated_masked.md``  – DeepL output (before unmasking)
        ``<stem>_uk.md``                 – **final translated file**

    Parameters
    ----------
    input_pdf_path : str | Path, optional
        Source PDF file.
    input_md_path : str | Path, optional
        Pre-parsed Markdown file (skips Stage 1).
    output_md_path : str | Path, optional
        Explicit output path.  Defaults to ``output/<stem>_uk.md``.
    api_key : str, optional
        DeepL API key.  Falls back to the ``DEEPL_API_KEY`` env var.
    target_lang : str
        DeepL target language (default: ``"UK"``).

    Returns
    -------
    Path
        Path to the written output Markdown file.
    """
    api_key = api_key or DEEPL_API_KEY
    
    run_name = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%A")
    run_dir = OUTPUT_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    
    images_dir = run_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Stage 1 – Obtain Markdown source
    # ------------------------------------------------------------------
    if input_md_path:
        md_path = Path(input_md_path)
        if not md_path.exists():
            raise FileNotFoundError(f"Markdown input not found: {md_path}")
        log.info("Stage 1 – Loading pre-parsed Markdown: %s", md_path)
        md_text = md_path.read_text(encoding="utf-8")
        stem    = md_path.stem
    elif input_pdf_path:
        md_text = parse_pdf_to_md(input_pdf_path, images_dir=images_dir, max_pages=max_pages)
        stem    = Path(input_pdf_path).stem

        raw_path = run_dir / f"{stem}_raw.md"
        raw_path.write_text(md_text, encoding="utf-8")
        log.info("  Raw Markdown cached: %s", raw_path)
    else:
        raise ValueError("Provide either 'input_pdf_path' or 'input_md_path'.")

    # ------------------------------------------------------------------
    # Stage 2 – Mask formulas + images
    # ------------------------------------------------------------------
    masked_text, elements_dict = mask_elements(md_text)

    masked_path = run_dir / f"{stem}_masked.md"
    masked_path.write_text(masked_text, encoding="utf-8")
    log.info("  Masked text cached: %s", masked_path)

    # ------------------------------------------------------------------
    # Stage 3 – Translate
    # ------------------------------------------------------------------
    translated_text = translate_text_deepl(masked_text, api_key, target_lang)

    trans_path = run_dir / f"{stem}_translated_masked.md"
    trans_path.write_text(translated_text, encoding="utf-8")
    log.info("  Translated (masked) cached: %s", trans_path)

    # ------------------------------------------------------------------
    # Stage 4 – Unmask
    # ------------------------------------------------------------------
    final_md = unmask_elements(translated_text, elements_dict)

    # ------------------------------------------------------------------
    # Stage 4b – Clean markdown formatting
    # ------------------------------------------------------------------
    final_md = clean_markdown_formatting(final_md)
    log.info("  Stage 4b – Markdown formatting cleaned.")

    # ------------------------------------------------------------------
    # Stage 5 – Write final output
    # ------------------------------------------------------------------
    out_path = Path(output_md_path) if output_md_path else run_dir / f"{stem}_uk.md"
    out_path.write_text(final_md, encoding="utf-8")

    # ------------------------------------------------------------------
    # Stage 6 – Export (EPUB/PDF)
    # ------------------------------------------------------------------
    export_to_book_formats(final_md, stem, run_dir, images_dir=images_dir)

    log.info("=" * 60)
    log.info("Pipeline complete!  Output: %s", out_path)
    log.info("=" * 60)
    return out_path


# ===========================================================================
# CLI entry-point
# ===========================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Translate a math/physics PDF textbook to Ukrainian, "
            "preserving all LaTeX formulas and embedded images."
        )
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--pdf", metavar="PATH",
                       help="Source PDF (will be parsed automatically).")
    group.add_argument("--md",  metavar="PATH",
                       help="Pre-parsed Markdown file (skips PDF parsing).")
    parser.add_argument("--output", metavar="PATH", default=None,
                        help="Output .md path (default: output/<stem>_uk.md).")
    parser.add_argument("--lang", metavar="LANG", default=TARGET_LANG,
                        help="DeepL target language code (default: UK).")
    parser.add_argument(
        "--max-pages", metavar="N", type=int, default=None,
        help="Process only the first N pages (useful for quick tests, e.g. --max-pages 20)."
    )
    args = parser.parse_args()

    # Интерактивное меню для удобного запуска пользователем без аргументов
    if not args.pdf and not args.md:
        print("\n" + "=" * 70)
        print(" 📚 Интерактивный переводчик научных книг (PDF/MD)")
        print("=" * 70)
        print("\nДобро пожаловать! Скрипт проведет вас через процесс перевода.")
        print("Вы можете использовать два формата:")
        print("  1. Файл .pdf (Будет применено ИИ-распознавание, извлечение формул)")
        print("  2. Файл .md  (Пропуск распознавания, сразу перевод готового текста)\n")
        
        file_path = input("👉 1. Введите путь к PDF или MD файлу (например, input/book.pdf):\n> ").strip()
        if not file_path:
            print("❌ Ошибка: необходимо указать путь к файлу.")
            sys.exit(1)
            
        if file_path.lower().endswith('.pdf'):
            args.pdf = file_path
            print("✔️  Выбран PDF-файл. Будет запущен полный цикл с распознаванием.")
        elif file_path.lower().endswith('.md'):
            args.md = file_path
            print("✔️  Выбран MD-файл. Этап PDF-парсинга будет пропущен.")
        else:
            print("❌ Ошибка: неподдерживаемый формат. Пожалуйста, укажите файл .pdf или .md")
            sys.exit(1)
            
        print("\nТестовый режим: Вы можете перевести только первые N страниц книги.")
        max_pgs = input("👉 2. Сколько страниц перевести? (Оставьте пустым, чтобы перевести ВСЮ книгу):\n> ").strip()
        if max_pgs.isdigit():
            args.max_pages = int(max_pgs)
            
        print("\n🚀 Начинаю процесс...\n" + "=" * 60 + "\n")
        
    # --- Предварительные проверки (Pre-flight checks) ---
    if not shutil.which("pandoc"):
        log.warning(
            "ВНИМАНИЕ: Pandoc не найден в системном PATH. "
            "Конвертация в EPUB и PDF (Финальный этап) будет пропущена. "
            "Вам будет доступен только Markdown-исходник."
        )
    if not shutil.which("xelatex"):
        log.warning(
            "ВНИМАНИЕ: XeLaTeX не найден в системном PATH. "
            "Конвертация в PDF будет невозможна. Убедитесь, что установлен MiKTeX "
            "(или TeX Live) и его папка bin добавлена в Переменные Среды Windows."
        )

    try:
        result_path = process_document(
            input_pdf_path=args.pdf,
            input_md_path=args.md,
            output_md_path=args.output,
            target_lang=args.lang,
            max_pages=args.max_pages,
        )
        print(f"\n✅  Done!  Translated file → {result_path}")
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        sys.exit(1)
