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
import sys
import time
import datetime
import sqlite3
import hashlib
import concurrent.futures
import shutil
import uuid
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
    
    md_text = md_text.replace(r"\rm ", r"\mathrm{ }").replace(r"\rm", r"\mathrm")
    
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
    import uuid
    hidden_math = {}
    
    def hide_math(match):
        uid = f"HIDE{uuid.uuid4().hex}X"
        hidden_math[uid] = match.group(0)
        return uid

    temp_text = md_text
    
    # 1. Прячем уже обернутую математику
    for pattern, flags in _BLOCK_MATH_PATTERNS:
        temp_text = re.sub(pattern, hide_math, temp_text, flags=flags)
    for pattern, flags in _INLINE_MATH_PATTERNS:
        temp_text = re.sub(pattern, hide_math, temp_text, flags=flags)

    # 2. Паттерн А: Математические окружения
    envs = r"(cases|matrix|pmatrix|bmatrix|vmatrix|Vmatrix|array|align|eqnarray|equation)"
    pattern_a = r"(\\begin\{(" + envs + r")\}.*?\\end\{\2\})"
    temp_text = re.sub(pattern_a, r"\n\n$$\n\1\n$$\n\n", temp_text, flags=re.DOTALL)
    
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

def mask_elements(md_text: str) -> tuple[str, dict[str, str]]:
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
    if not api_key or not region:
        raise ValueError(
            "AZURE_TRANSLATOR_KEY or AZURE_TRANSLATOR_REGION is not set. "
            "Copy .env.template → .env and fill in your keys."
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

    def _translate_chunk(args_tuple) -> str:
        i, chunk = args_tuple
        chunk_md5 = hashlib.md5(chunk.encode('utf-8')).hexdigest()
        
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
                request_headers = headers.copy()
                request_headers['X-ClientTraceId'] = str(uuid.uuid4())
                body = [{'text': chunk}]

                response = requests.post(constructed_url, params=params, headers=request_headers, json=body, timeout=30)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 15))
                    log.warning("  [429] Rate limit hit! Waiting %d seconds...", retry_after)
                    time.sleep(retry_after + 1)
                    continue

                response.raise_for_status()
                res_data = response.json()
                res_text = res_data[0]['translations'][0]['text']
                
                with sqlite3.connect(db_path, timeout=10) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO translation_cache (md5, translated_text) VALUES (?, ?)", 
                        (chunk_md5, res_text)
                    )
                time.sleep(1.5)
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

    images_abs_dir = images_dir.absolute().as_posix()
    
    # 1) Replacing 'images/' or './images/' strings inside ']()'
    md_text = re.sub(r'\]\((?:images/|\./images/)', f']({images_abs_dir}/', md_text)
    
    # 2) Replacing pure filenames just inside ']()' - marker pdf formats this
    md_text = re.sub(r'\]\((?!http|/|[A-Za-z]:)(.*?)\)', f']({images_abs_dir}/\1)', md_text)

    resource_dirs = [
        ".",
        output_dir.absolute().as_posix(),
        images_dir.absolute().as_posix()
    ]
    res_path = os.pathsep.join(resource_dirs)
    
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

    pdf_args = [
        "--pdf-engine=xelatex",
        f"--resource-path={res_path}",
        "-V", "graphics=true",
        "-V", "maxwidth=\textwidth",
        "-V", "maxheight=0.8\textheight",
        "-V", "mainfont=Times New Roman",
        "-V", "monofont=Courier New",
        "-V", "sansfont=Arial",
        "-V", "pagestyle=plain",
        "-V", "lang=uk",
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
        log.error("  PDF generation failed. Ensure XeLaTeX (MiKTeX/TeX Live) is installed and in PATH. Details: %s", e)

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
            shutil.copytree(source_images, IMAGES_DIR, dirs_exist_ok=True)
            log.info("  Copied images from source folder.")
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

    if not rebuild_only:
        rescued_md_text = rescue_broken_latex(md_text)
        masked_text, elements_dict = mask_elements(rescued_md_text)

        translated_text = translate_text_azure(
            text=masked_text, 
            api_key=AZURE_TRANSLATOR_KEY, 
            endpoint=AZURE_TRANSLATOR_ENDPOINT, 
            region=AZURE_TRANSLATOR_REGION, 
            target_lang=TARGET_LANG
        )

        final_md = unmask_elements(translated_text, elements_dict)
        final_md = clean_markdown_formatting(final_md)
        log.info("  Stage 4b – Markdown formatting cleaned.")
    else:
        final_md = md_text
        log.info("  Rebuild mode: Skipping translation stages.")

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
