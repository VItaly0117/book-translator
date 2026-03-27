from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from pypdf import PdfReader, PdfWriter

import book_translator as bt


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CHUNK_DIR = ROOT_DIR / "Output_Final" / "farlou_rebuild_chunked_v6_pdf_chunks"
DEFAULT_IMAGES_DIR = ROOT_DIR / "Output_Final" / "images"
DEFAULT_OUTPUT_ROOT = ROOT_DIR / "Output_Final"


def _compile_chunk(md_path: Path, chunk_dir: Path, images_dir: Path) -> Path:
    md_text = md_path.read_text(encoding="utf-8")
    prepared = bt._prepare_markdown_for_pdf(bt._remove_pdf_only_sections(md_text))
    res_path = bt._build_resource_path(chunk_dir, images_dir)
    try:
        return bt._build_pdf_via_tex(
            md_text=prepared,
            output_stem=md_path.stem,
            output_dir=chunk_dir,
            res_path=res_path,
            graphics_root_dir=images_dir.parent,
            allow_partial_output=False,
        )
    except RuntimeError:
        # Some canonical chunks still contain localized OCR/TeX damage.
        # For manual review passes, a recoverable PDF is more useful than
        # failing the whole merged build after XeLaTeX already emitted output.
        return bt._build_pdf_via_tex(
            md_text=prepared,
            output_stem=md_path.stem,
            output_dir=chunk_dir,
            res_path=res_path,
            graphics_root_dir=images_dir.parent,
            allow_partial_output=True,
        )


def _merge_pdfs(pdf_paths: list[Path], output_path: Path) -> None:
    writer = PdfWriter()
    for pdf_path in pdf_paths:
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            writer.add_page(page)

    with output_path.open("wb") as handle:
        writer.write(handle)


def rebuild_manual_review(
    chunk_dir: Path,
    images_dir: Path,
    output_dir: Path,
    chunk_names: list[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    built_pdfs: list[Path] = []
    for chunk_name in chunk_names:
        md_path = chunk_dir / chunk_name
        if not md_path.exists():
            raise FileNotFoundError(f"Chunk not found: {md_path}")

        built_pdf = _compile_chunk(md_path, chunk_dir, images_dir)
        shutil.copy2(md_path, output_dir / md_path.name)
        shutil.copy2(built_pdf, output_dir / built_pdf.name)
        built_pdfs.append(output_dir / built_pdf.name)

    merged_name = f"{output_dir.name}_{chunk_names[0].split('_p')[-1].split('.')[0]}_{chunk_names[-1].split('_p')[-1].split('.')[0]}_merged.pdf"
    merged_path = output_dir / merged_name
    _merge_pdfs(built_pdfs, merged_path)
    return merged_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild a canonical manual-review PDF from selected canonical markdown chunks.",
    )
    parser.add_argument(
        "--pass-name",
        default="manual_help_pass_02",
        help="Output directory name created under Output_Final.",
    )
    parser.add_argument(
        "--chunk-dir",
        type=Path,
        default=DEFAULT_CHUNK_DIR,
        help="Directory containing canonical markdown chunks.",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help="Directory containing extracted images referenced by markdown.",
    )
    parser.add_argument(
        "chunk_names",
        nargs="+",
        help="Canonical markdown chunk filenames to compile and merge.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = DEFAULT_OUTPUT_ROOT / args.pass_name
    merged_pdf = rebuild_manual_review(
        chunk_dir=args.chunk_dir,
        images_dir=args.images_dir,
        output_dir=output_dir,
        chunk_names=args.chunk_names,
    )
    print(merged_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
