from __future__ import annotations

from pathlib import Path

import book_translator as bt


def skip_residual_retranslation(text: str, *args, **kwargs) -> str:
    return text


def main() -> None:
    pdfs = [
        Path.home() / "Downloads" / "split_middle_200_299_out" / "farlou_s_uravneniia_s_chastnymi_proizvodnymi_dlia_nauchnykh_p200-249.pdf",
        Path.home() / "Downloads" / "split_middle_200_299_out" / "farlou_s_uravneniia_s_chastnymi_proizvodnymi_dlia_nauchnykh_p250-299.pdf",
    ]

    bt.retranslate_residual_russian_paragraphs = skip_residual_retranslation

    for pdf_path in pdfs:
        if not pdf_path.exists():
            raise FileNotFoundError(f"Input PDF not found: {pdf_path}")

        bt.process_document(
            input_pdf_path=pdf_path,
            rebuild_only=True,
        )


if __name__ == "__main__":
    main()
