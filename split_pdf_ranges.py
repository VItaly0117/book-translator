#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def parse_range_token(token: str) -> tuple[int, int]:
    token = token.strip()
    if not token:
        raise ValueError("Empty range token.")

    if "-" in token:
        start_str, end_str = token.split("-", 1)
        start = int(start_str)
        end = int(end_str)
    else:
        start = end = int(token)

    if start < 1:
        raise ValueError(f"Page ranges are 1-based, got {token!r}.")
    if end < start:
        raise ValueError(f"Invalid range {token!r}: end must be >= start.")

    return start, end


def export_page_ranges(input_pdf: Path, output_dir: Path, ranges: list[tuple[int, int]]) -> list[Path]:
    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)

    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = []
    for start, end in ranges:
        if end > total_pages:
            raise ValueError(
                f"Range {start}-{end} exceeds the input PDF length ({total_pages} pages)."
            )

        writer = PdfWriter()
        for page_index in range(start - 1, end):
            writer.add_page(reader.pages[page_index])

        out_path = output_dir / f"{input_pdf.stem}_p{start:03d}-{end:03d}.pdf"
        with out_path.open("wb") as handle:
            writer.write(handle)

        outputs.append(out_path)

    return outputs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split a PDF into explicit page-range PDFs.",
    )
    parser.add_argument(
        "input_pdf",
        type=Path,
        help="Source PDF to split.",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory where the split PDFs will be written.",
    )
    parser.add_argument(
        "ranges",
        nargs="+",
        help="Page ranges in 1-based inclusive form, e.g. 200-249 250-299 312.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    input_pdf: Path = args.input_pdf
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    ranges = [parse_range_token(token) for token in args.ranges]
    outputs = export_page_ranges(input_pdf, args.output_dir, ranges)

    for path in outputs:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
