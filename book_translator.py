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
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from tqdm import tqdm

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

# DeepL max payload is 128 KB UTF-8.  We use 90 000 chars as a safe ceiling.
CHUNK_SIZE = 90_000

# ---------------------------------------------------------------------------
# Placeholder templates
# All must be purely [A-Za-z0-9] so DeepL treats them as opaque tokens.
# ---------------------------------------------------------------------------
_PH_MATH_BLOCK  = "MATHBLK{idx:04d}X"   # display / block math
_PH_MATH_INLINE = "MATHINL{idx:04d}X"   # inline math
_PH_IMAGE       = "IMGTOKEN{idx:04d}X"  # Markdown image links

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
# Stage 1 – PDF → Markdown
# ===========================================================================

def parse_pdf_to_md(
    pdf_path: str | Path,
    images_dir: Optional[Path] = None,
    parser: str = "auto",
    max_pages: Optional[int] = None,
) -> str:
    """
    Convert a PDF file to Markdown, preserving LaTeX formulas and images.

    Parser selection (``parser`` argument):
    * ``"auto"``       – tries pymupdf4llm first (fast), falls back to marker-pdf
    * ``"pymupdf4llm"``– lightweight, no PyTorch required, installs in seconds
    * ``"marker"``     – AI-powered (Surya), best quality, requires ~2 GB models

    Parameters
    ----------
    pdf_path : str | Path
        Source PDF to convert.
    images_dir : Path, optional
        Where to save extracted raster images. Defaults to ``images/``.
    parser : str
        Which PDF parser to use: ``"auto"``, ``"pymupdf4llm"``, or ``"marker"``.

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

    log.info("Stage 1 – Parsing PDF (%s): %s", parser, pdf_path)

    # ── pymupdf4llm path ────────────────────────────────────────────────────
    if parser in ("auto", "pymupdf4llm"):
        try:
            import pymupdf4llm  # type: ignore

            log.info("  Using pymupdf4llm parser …")
            pages = list(range(max_pages)) if max_pages else None
            md_text = pymupdf4llm.to_markdown(
                str(pdf_path),
                pages=pages,
                write_images=True,
                image_path=str(images_dir),
            )
            log.info("Stage 1 complete – %d characters extracted.", len(md_text))
            return md_text

        except ImportError:
            if parser == "pymupdf4llm":
                raise ImportError(
                    "pymupdf4llm is not installed.\n"
                    "  Run: pip install pymupdf4llm"
                )
            log.info("  pymupdf4llm not found, trying marker-pdf …")

    # ── marker-pdf path (supports both v0.x and v1.x APIs) ──────────────────
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
            cfg: dict = {"languages": ["English"]}
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
                langs=["English"],
                batch_multiplier=1,
            )
            for img_name, img_obj in images.items():
                dest = images_dir / img_name
                img_obj.save(str(dest))
                log.info("  Saved image: %s", dest)

        log.info("Stage 1 complete – %d characters extracted.", len(full_text))
        return full_text

    except ImportError:
        raise ImportError(
            "No PDF parser found!  Install one of:\n"
            "  pip install pymupdf4llm        ← recommended (fast, lightweight)\n"
            "  pip install marker-pdf         ← AI-powered but requires PyTorch\n\n"
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

    log.info(
        "Stage 2 – Masked %d block-math, %d inline-math, %d image(s).",
        block_idx, inline_idx, image_idx,
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
        split_pos = text.rfind("\n\n", start, end)
        if split_pos <= start:
            # … then single newline …
            split_pos = text.rfind("\n", start, end)
        if split_pos <= start:
            # … last resort: hard cut
            split_pos = end - 1

        chunks.append(text[start : split_pos + 1])
        start = split_pos + 1

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
    * Raises ``ValueError`` immediately if the API key is empty (no network
      call is made).

    Parameters
    ----------
    text : str
        Masked text produced by Stage 2 (must contain NO raw LaTeX or image
        Markdown – only opaque placeholders).
    api_key : str
        DeepL authentication key.
    target_lang : str
        ISO language code (default ``"UK"`` for Ukrainian).
    chunk_size : int
        Max characters per API request (default 90 000).
    retry_attempts : int
        Number of retry attempts per chunk before propagating the exception.
    retry_delay : float
        Base delay in seconds between retries (doubles on each attempt).

    Returns
    -------
    str
        Translated text with all placeholders intact.
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
    translated: list[str] = []

    for i, chunk in enumerate(tqdm(chunks, desc="Translating chunks"), start=1):
        log.info(
            "  Chunk %d/%d – %d chars …", i, len(chunks), len(chunk)
        )
        for attempt in range(1, retry_attempts + 1):
            try:
                result = translator.translate_text(
                    chunk,
                    source_lang="EN",
                    target_lang=target_lang,
                    preserve_formatting=True,
                )
                translated.append(result.text)
                break
            except deepl.DeepLException as exc:
                log.warning(
                    "  Chunk %d – attempt %d/%d failed: %s",
                    i, attempt, retry_attempts, exc,
                )
                if attempt == retry_attempts:
                    raise
                time.sleep(retry_delay * (2 ** (attempt - 1)))

    log.info("Stage 3 – Translation complete.")
    return "\n\n".join(translated)


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

        # Determine spacing based on placeholder type
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
# Stage 5 – Orchestration
# ===========================================================================

def process_document(
    input_pdf_path:  Optional[str | Path] = None,
    input_md_path:   Optional[str | Path] = None,
    output_md_path:  Optional[str | Path] = None,
    api_key:         Optional[str] = None,
    target_lang:     str = TARGET_LANG,
    parser:          str = "auto",
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
        md_text = parse_pdf_to_md(input_pdf_path, parser=parser, max_pages=max_pages)
        stem    = Path(input_pdf_path).stem

        raw_path = OUTPUT_DIR / f"{stem}_raw.md"
        raw_path.write_text(md_text, encoding="utf-8")
        log.info("  Raw Markdown cached: %s", raw_path)
    else:
        raise ValueError("Provide either 'input_pdf_path' or 'input_md_path'.")

    # ------------------------------------------------------------------
    # Stage 2 – Mask formulas + images
    # ------------------------------------------------------------------
    masked_text, elements_dict = mask_elements(md_text)

    masked_path = OUTPUT_DIR / f"{stem}_masked.md"
    masked_path.write_text(masked_text, encoding="utf-8")
    log.info("  Masked text cached: %s", masked_path)

    # ------------------------------------------------------------------
    # Stage 3 – Translate
    # ------------------------------------------------------------------
    translated_text = translate_text_deepl(masked_text, api_key, target_lang)

    trans_path = OUTPUT_DIR / f"{stem}_translated_masked.md"
    trans_path.write_text(translated_text, encoding="utf-8")
    log.info("  Translated (masked) cached: %s", trans_path)

    # ------------------------------------------------------------------
    # Stage 4 – Unmask
    # ------------------------------------------------------------------
    final_md = unmask_elements(translated_text, elements_dict)

    # ------------------------------------------------------------------
    # Stage 5 – Write final output
    # ------------------------------------------------------------------
    out_path = Path(output_md_path) if output_md_path else OUTPUT_DIR / f"{stem}_uk.md"
    out_path.write_text(final_md, encoding="utf-8")

    log.info("=" * 60)
    log.info("Pipeline complete!  Output: %s", out_path)
    log.info("=" * 60)
    return out_path


# ===========================================================================
# CLI entry-point
# ===========================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Translate a math/physics PDF textbook to Ukrainian, "
            "preserving all LaTeX formulas and embedded images."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", metavar="PATH",
                       help="Source PDF (will be parsed automatically).")
    group.add_argument("--md",  metavar="PATH",
                       help="Pre-parsed Markdown file (skips PDF parsing).")
    parser.add_argument("--output", metavar="PATH", default=None,
                        help="Output .md path (default: output/<stem>_uk.md).")
    parser.add_argument("--lang", metavar="LANG", default=TARGET_LANG,
                        help="DeepL target language code (default: UK).")
    parser.add_argument(
        "--parser", metavar="PARSER", default="auto",
        choices=["auto", "pymupdf4llm", "marker"],
        help=(
            "PDF parser to use (default: auto).\n"
            "  auto       – tries pymupdf4llm, falls back to marker\n"
            "  pymupdf4llm– fast, lightweight, works on text-based PDFs\n"
            "  marker     – AI-powered OCR, works on scanned/image-based PDFs"
        ),
    )
    parser.add_argument(
        "--max-pages", metavar="N", type=int, default=None,
        help="Process only the first N pages (useful for quick tests, e.g. --max-pages 20)."
    )
    args = parser.parse_args()

    try:
        result_path = process_document(
            input_pdf_path=args.pdf,
            input_md_path=args.md,
            output_md_path=args.output,
            target_lang=args.lang,
            parser=args.parser,
            max_pages=args.max_pages,
        )
        print(f"\n✅  Done!  Translated file → {result_path}")
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        sys.exit(1)
