#!/usr/bin/env python3
"""
make_pdf.py
===========
Standalone script to generate PDF/EPUB from an existing translated Markdown file.
Useful when PDF generation failed during the main pipeline.

Usage:
    python3 make_pdf.py path/to/book_uk.md
    python3 make_pdf.py path/to/book_uk.md --output-dir ./output
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from book_translator import (
    export_to_book_formats,
    clean_markdown_formatting,
    BASE_DIR,
)


def main():
    parser = argparse.ArgumentParser(
        description="Generate PDF/EPUB from a translated Markdown file."
    )
    parser.add_argument(
        "md_path",
        help="Path to the translated Markdown file (.md)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: same as input file)"
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip markdown cleaning (use if already cleaned)"
    )
    args = parser.parse_args()

    md_path = Path(args.md_path)
    if not md_path.exists():
        print(f"❌ Error: File not found: {md_path}")
        sys.exit(1)

    if not md_path.suffix.lower() == ".md":
        print(f"❌ Error: File must be a .md file")
        sys.exit(1)

    # Determine output directory
    output_dir = Path(args.output_dir) if args.output_dir else md_path.parent
    
    # Determine images directory
    images_dir = output_dir / "images"
    if not images_dir.exists():
        # Try parent directory
        images_dir = md_path.parent / "images"
    if not images_dir.exists():
        images_dir = None
        print("⚠️  Warning: No images directory found. Images may not be included.")

    # Read markdown
    print(f"📖 Reading: {md_path}")
    md_text = md_path.read_text(encoding="utf-8")

    # Clean if requested
    if not args.no_clean:
        print("🧹 Cleaning markdown formatting...")
        md_text = clean_markdown_formatting(md_text)

    # Get stem for output files
    stem = md_path.stem

    # Export
    print(f"📄 Generating EPUB and PDF...")
    export_to_book_formats(md_text, stem, output_dir, images_dir=images_dir)

    print(f"\n✅ Done! Files saved to: {output_dir}")
    print(f"   - {stem}.epub")
    print(f"   - {stem}.pdf")


if __name__ == "__main__":
    main()
