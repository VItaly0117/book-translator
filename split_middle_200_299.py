#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from split_pdf_ranges import export_page_ranges


DEFAULT_RANGES: list[tuple[int, int]] = [(200, 249), (250, 299)]
DEFAULT_INPUT_PDF = (
    Path.home()
    / "Downloads"
    / "farlou_s_uravneniia_s_chastnymi_proizvodnymi_dlia_nauchnykh.pdf"
)
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "split_middle_200_299_out"


def main() -> int:
    if len(sys.argv) == 1:
        input_pdf = DEFAULT_INPUT_PDF
        output_dir = DEFAULT_OUTPUT_DIR
    elif len(sys.argv) in (2, 3):
        input_pdf = Path(sys.argv[1]).expanduser().resolve()
        output_dir = (
            Path(sys.argv[2]).expanduser().resolve()
            if len(sys.argv) == 3
            else Path.cwd() / "split_middle_out"
        )
    else:
        script_name = Path(sys.argv[0]).name
        print(
            f"Usage: python3 {script_name} [input_pdf] [output_dir]",
            file=sys.stderr,
        )
        return 2

    if not input_pdf.exists():
        print(f"Input PDF not found: {input_pdf}", file=sys.stderr)
        return 1

    outputs = export_page_ranges(input_pdf, output_dir, DEFAULT_RANGES)
    for path in outputs:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
