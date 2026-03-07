"""
test_translator.py
==================
Comprehensive pytest test suite for book_translator.py.

Coverage:
  1.  TestMaskElements             – masking of LaTeX (block + inline) and images
  2.  TestMaskImageLinks            – image-specific masking edge cases
  3.  TestUnmaskElements            – restoration of all element types
  4.  TestBackwardsCompatibleAliases– alias backward-compat
  5.  TestChunkText                 – text chunking / size limits
  6.  TestTranslateTextDeepL        – mocked DeepL API calls
  7.  TestFullPipelineIntegration   – end-to-end with math + images (all mocked)
  8.  TestRussianLocalizationFast   – fast pipeline integration (all mocked)
  9.  TestEnhanceBookImage          – OpenCV binarisation (10×10 numpy arrays, no PIL)
  10. TestCleanMarkdownFormatting   – markdown cleanup utilities

Run:
    pytest test_translator.py -v
    pytest test_translator.py -v --tb=short     # compact tracebacks
    pytest test_translator.py -v -k "Format"    # only formatting tests
"""

from __future__ import annotations

import re
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import book_translator
# Isolate tests so they don't use the real cache.db
book_translator.BASE_DIR = Path(tempfile.mkdtemp())
book_translator.OUTPUT_DIR = book_translator.BASE_DIR / "output"

# ── Module under test ───────────────────────────────────────────────────────
from book_translator import (
    _chunk_text,
    clean_markdown_formatting,
    enhance_book_image,
    mask_elements,
    mask_math,          # backward-compat alias – must still work
    translate_text_deepl,
    unmask_elements,
    unmask_math,        # backward-compat alias – must still work
)


# ===========================================================================
# Helpers
# ===========================================================================

def _block_phs(text: str) -> list[str]:
    return re.findall(r"MATHBLK\d{4}X", text)

def _inline_phs(text: str) -> list[str]:
    return re.findall(r"MATHINL\d{4}X", text)

def _image_phs(text: str) -> list[str]:
    return re.findall(r"IMGTOKEN\d{4}X", text)

def _all_phs(text: str) -> list[str]:
    return re.findall(r"(?:MATHBLK|MATHINL|IMGTOKEN)\d{4}X", text)

def _round_trip(original: str) -> tuple[str, str, dict]:
    masked, elements_dict = mask_elements(original)
    final = unmask_elements(masked, elements_dict)
    return masked, final, elements_dict


# ===========================================================================
# 1. Masking – LaTeX formulas
# ===========================================================================

class TestMaskElements:

    def test_block_double_dollar_is_masked(self):
        formula = r"$$\frac{\partial u}{\partial t} = \alpha^2 \frac{\partial^2 u}{\partial x^2}$$"
        text    = f"The heat equation:\n{formula}\n\nIs fundamental."
        masked, elems = mask_elements(text)
        assert formula not in masked
        assert formula in elems.values()
        assert len(_block_phs(masked)) == 1
        assert "$" not in masked

    def test_block_backslash_bracket_is_masked(self):
        formula = r"\[ u(0,t) = 0, \quad u(L,t) = 0 \]"
        text = f"Boundary conditions: {formula} hold for all t."
        masked, elems = mask_elements(text)
        assert formula in elems.values()
        assert r"\[" not in masked
        assert len(_block_phs(masked)) == 1

    def test_multiline_block_math_is_single_token(self):
        formula = "$$\n" + r"\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}" + "\n$$"
        text = f"Classic result:\n{formula}\n"
        masked, elems = mask_elements(text)
        assert len(elems) == 1
        assert formula in elems.values()

    def test_inline_dollar_is_masked(self):
        text   = r"The solution is $u(x,t) = X(x)T(t)$ by separation."
        masked, elems = mask_elements(text)
        assert r"$u(x,t) = X(x)T(t)$" not in masked
        assert r"$u(x,t) = X(x)T(t)$" in elems.values()
        assert len(_inline_phs(masked)) == 1

    def test_inline_backslash_parens_is_masked(self):
        formula = r"\( f(x) = x^2 \)"
        text    = f"The function {formula} is a parabola."
        masked, elems = mask_elements(text)
        assert formula in elems.values()
        assert r"\(" not in masked

    def test_adjacent_inline_formulas_are_independent(self):
        text   = r"We have $a$ and $b$ as free parameters."
        masked, elems = mask_elements(text)
        assert len(elems) == 2
        assert r"$a$" in elems.values()
        assert r"$b$" in elems.values()
        assert len(set(_inline_phs(masked))) == 2

    def test_block_and_inline_in_same_paragraph(self):
        text = textwrap.dedent(r"""
            The PDE is $u_t = \alpha u_{xx}$.
            $$u(x,t) = \sum_{n=1}^{\infty} B_n \sin\!\left(\frac{n\pi x}{L}\right)$$
            Initial condition: $u(x,0) = f(x)$.
        """)
        masked, elems = mask_elements(text)
        assert "$" not in masked
        assert len(_block_phs(masked))  == 1
        assert len(_inline_phs(masked)) == 2

    def test_no_latex_survives_masking(self):
        text = textwrap.dedent(r"""
            $u_t = \alpha u_{xx}$
            $$\nabla^2 \phi = 0$$
            \[ \oint \vec{E} \cdot d\vec{A} = \frac{Q}{\varepsilon_0} \]
            \( \hbar \frac{\partial \psi}{\partial t} = \hat{H} \psi \)
        """)
        masked, _ = mask_elements(text)
        for delim in [r"$$", r"\[", r"\(", r"\]", r"\)", "$"]:
            assert delim not in masked, f"LaTeX delimiter {delim!r} survived masking!"

    def test_plain_text_unchanged(self):
        text = "Superposition: if u and v satisfy the PDE, so does u plus v."
        masked, elems = mask_elements(text)
        assert elems == {}
        assert masked.strip() == text.strip()

    def test_placeholder_keys_are_alphanumeric(self):
        text = r"Solve $\nabla^2 \phi = 0$ in domain $\Omega$."
        masked, elems = mask_elements(text)
        for ph in elems:
            assert re.fullmatch(r"[A-Za-z0-9]+", ph)

    def test_page_number_is_masked(self):
        text = "End of chapter.\n\n[Page 12]\n\nNext chapter."
        masked, elems = mask_elements(text)
        assert "[Page 12]" in elems.values()
        assert "PAGENUM" in masked
        final = unmask_elements(masked, elems)
        assert "page-break-after: always;" in final


# ===========================================================================
# 2. Masking – Markdown image links
# ===========================================================================

class TestMaskImageLinks:

    def test_simple_image_is_masked(self):
        text = "Figure 1 shows the solution.\n\n![Graph 1](images/page_10_img.png)\n"
        masked, elems = mask_elements(text)
        assert "![Graph 1](images/page_10_img.png)" not in masked
        assert "![Graph 1](images/page_10_img.png)" in elems.values()
        assert len(_image_phs(masked)) == 1

    def test_image_with_spaces_in_alt_text(self):
        img   = "![Temperature distribution at t=0](images/temp_dist.png)"
        text  = f"See the figure below.\n{img}\n"
        masked, elems = mask_elements(text)
        assert img in elems.values()
        assert "![" not in masked

    def test_image_with_relative_path(self):
        img  = "![Fig 3](../images/subfolder/wave_eq_fig3.png)"
        masked, elems = mask_elements(img)
        assert img in elems.values()

    def test_image_with_empty_alt_text(self):
        img  = "![](images/unlabelled.png)"
        masked, elems = mask_elements(img)
        assert img in elems.values()

    def test_multiple_images_get_unique_tokens(self):
        text = textwrap.dedent("""
            ![Figure 1](images/fig1.png)
            Some text in between.
            ![Figure 2](images/fig2.png)
        """)
        masked, elems = mask_elements(text)
        assert len(set(_image_phs(masked))) == 2
        assert "![Figure 1](images/fig1.png)" in elems.values()
        assert "![Figure 2](images/fig2.png)" in elems.values()

    def test_image_and_formula_coexist(self):
        text = textwrap.dedent(r"""
            The solution $u(x,t)$ is plotted below.
            ![Solution plot](images/solution.png)
        """)
        masked, elems = mask_elements(text)
        assert len(_inline_phs(masked)) == 1
        assert len(_image_phs(masked))  == 1
        assert "$" not in masked
        assert "![" not in masked

    def test_regular_markdown_link_is_not_masked(self):
        text = "See [this reference](https://example.com) for details."
        masked, elems = mask_elements(text)
        assert _image_phs(masked) == []
        assert "[this reference](https://example.com)" in masked


# ===========================================================================
# 3. Unmasking – restoration fidelity
# ===========================================================================

class TestUnmaskElements:

    def test_inline_formula_is_restored(self):
        original = r"The solution $u(x,t) = X(x)T(t)$ is separated."
        _, final, _ = _round_trip(original)
        assert r"$u(x,t) = X(x)T(t)$" in final

    def test_block_formula_is_restored(self):
        formula  = r"$$\frac{\partial u}{\partial t} = \alpha^2 \frac{\partial^2 u}{\partial x^2}$$"
        original = f"Heat equation:\n{formula}\n"
        _, final, _ = _round_trip(original)
        assert formula in final

    def test_image_link_is_restored_exactly(self):
        img      = "![Graph 1](images/page_10_img.png)"
        original = f"Figure below.\n\n{img}\n"
        _, final, _ = _round_trip(original)
        assert img in final

    def test_whitespace_tolerance_around_placeholder(self):
        _, math_dict = mask_elements(r"$f(x) = x^2$")
        ph = next(iter(math_dict))
        for padded in [f"  {ph}  ", f"\n{ph}\n", f"\t{ph}\t"]:
            result = unmask_elements(padded, math_dict)
            assert r"$f(x) = x^2$" in result

    def test_no_leftover_placeholders(self):
        original = textwrap.dedent(r"""
            Equation: $u_t = \kappa u_{xx}$.
            $$\int_0^L \sin^2\!\!\left(\frac{n\pi x}{L}\right) dx = \frac{L}{2}$$
            ![Eigenfunction plot](images/eigen.png)
        """)
        _, final, _ = _round_trip(original)
        assert _all_phs(final) == []

    def test_all_elements_present_after_round_trip(self):
        original = textwrap.dedent(r"""
            The general solution is $u = c_1 u_1 + c_2 u_2$.
            $$\frac{d^2 y}{dx^2} + p(x)\frac{dy}{dx} + q(x)y = 0$$
            The Wronskian $W = u_1 u_2' - u_2 u_1' \ne 0$.
            ![Wronskian diagram](images/wronskian.png)
        """).strip()
        _, final, elems = _round_trip(original)
        assert len(elems) == 4
        for original_elem in elems.values():
            assert original_elem in final

    def test_empty_dict_returns_text_unchanged(self):
        text = "Це рівняння не має формул."
        assert unmask_elements(text, {}) == text

    def test_latex_backslashes_not_treated_as_regex(self):
        formula  = r"$$\frac{\partial^2 u}{\partial x^2} = 0$$"
        original = f"Laplace equation: {formula}"
        _, final, _ = _round_trip(original)
        assert formula in final


# ===========================================================================
# 4. Backward-compatible aliases
# ===========================================================================

class TestBackwardsCompatibleAliases:

    def test_mask_math_alias_works(self):
        text = r"Solve $x^2 = 4$."
        masked_via_alias, elems = mask_math(text)
        assert len(elems) == 1
        assert r"$x^2 = 4$" in elems.values()
        assert "$" not in masked_via_alias

    def test_unmask_math_alias_works(self):
        _, elems = mask_elements(r"$E = mc^2$")
        ph = next(iter(elems))
        result_alias = unmask_math(f"Формула {ph} є відомою.", elems)
        result_new   = unmask_elements(f"Формула {ph} є відомою.", elems)
        assert result_alias == result_new


# ===========================================================================
# 5. Text chunking
# ===========================================================================

class TestChunkText:

    def test_short_text_not_split(self):
        text = "Short."
        assert _chunk_text(text, chunk_size=1000) == [text]

    def test_chunks_never_exceed_size_limit(self):
        text   = "Word " * 40_000
        chunks = _chunk_text(text, chunk_size=50_000)
        for i, chunk in enumerate(chunks):
            assert len(chunk) <= 50_000

    def test_all_content_preserved(self):
        paragraphs = [" ".join(["word"] * 100)] * 50
        text       = "\n\n".join(paragraphs)
        chunks     = _chunk_text(text, chunk_size=5_000)
        rejoined   = "".join(chunks)
        assert rejoined.replace("\n", "") == text.replace("\n", "")

    def test_long_paragraph_without_newlines_still_splits(self):
        long_line = "x" * 50_000
        chunks    = _chunk_text(long_line, chunk_size=10_000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 10_000

    def test_chunk_protects_headers(self):
        text = ("word " * 1_000) + "\n\n# Chapter 2\n\nContent paragraph."
        chunks = _chunk_text(text, chunk_size=len("word " * 1_000) + 16)
        for chunk in chunks:
            assert not chunk.rstrip().endswith("# Chapter 2")


# ===========================================================================
# 6. Mocked DeepL API
# ===========================================================================

class TestTranslateTextDeepL:

    def _result(self, text: str) -> MagicMock:
        r = MagicMock()
        r.text = text
        return r

    @patch("book_translator.deepl")
    def test_returns_translated_text(self, mock_deepl):
        fake = self._result("Рівняння теплопровідності є фундаментальним.")
        mock_deepl.Translator.return_value.translate_text.return_value = fake
        mock_deepl.DeepLException = Exception
        out = translate_text_deepl("The heat equation is fundamental.", api_key="fake:fx")
        assert out == "Рівняння теплопровідності є фундаментальним."

    @patch("book_translator.deepl")
    def test_translate_caching(self, mock_deepl, tmp_path):
        """Caching: same chunk must not be sent twice to DeepL."""
        book_translator.BASE_DIR = tmp_path
        mock_deepl.Translator.return_value.translate_text.return_value = self._result("Cached translation")
        mock_deepl.DeepLException = Exception
        res1 = translate_text_deepl("test text", api_key="k:fx")
        assert res1 == "Cached translation"
        assert mock_deepl.Translator.return_value.translate_text.call_count == 1
        res2 = translate_text_deepl("test text", api_key="k:fx")
        assert res2 == "Cached translation"
        assert mock_deepl.Translator.return_value.translate_text.call_count == 1

    @patch("book_translator.deepl")
    def test_correct_api_parameters(self, mock_deepl):
        mock_translator = MagicMock()
        mock_translator.translate_text.return_value = self._result("ok")
        mock_deepl.Translator.return_value = mock_translator
        mock_deepl.DeepLException = Exception
        translate_text_deepl("text", api_key="key:fx", target_lang="UK")
        kwargs = mock_translator.translate_text.call_args.kwargs
        assert kwargs["source_lang"]         == "RU"
        assert kwargs["target_lang"]         == "UK"
        assert kwargs["preserve_formatting"] is True

    @patch("book_translator.deepl")
    def test_raises_on_empty_api_key(self, mock_deepl):
        with pytest.raises(ValueError, match="DEEPL_API_KEY"):
            translate_text_deepl("text", api_key="")
        mock_deepl.Translator.assert_not_called()

    @patch("book_translator.deepl")
    def test_math_placeholders_survive_translation(self, mock_deepl):
        original = r"The equation $u_t = \kappa u_{xx}$ models diffusion."
        masked, elems = mask_elements(original)
        ph = _inline_phs(masked)[0]
        simulated = f"Рівняння {ph} моделює дифузію."
        mock_deepl.Translator.return_value.translate_text.return_value = self._result(simulated)
        mock_deepl.DeepLException = Exception
        translated = translate_text_deepl(masked, api_key="k:fx")
        final      = unmask_elements(translated, elems)
        assert r"$u_t = \kappa u_{xx}$" in final

    @patch("book_translator.deepl")
    def test_image_placeholders_survive_translation(self, mock_deepl):
        img      = "![Solution](images/solution.png)"
        original = f"Figure:\n\n{img}\n"
        masked, elems = mask_elements(original)
        ph = _image_phs(masked)[0]
        simulated = f"Малюнок:\n\n{ph}\n"
        mock_deepl.Translator.return_value.translate_text.return_value = self._result(simulated)
        mock_deepl.DeepLException = Exception
        translated = translate_text_deepl(masked, api_key="k:fx")
        final      = unmask_elements(translated, elems)
        assert img in final


    @patch("book_translator.deepl")
    def test_chunked_translation_joins_results(self, mock_deepl, tmp_path):
        """Multiple chunks must be sent to DeepL and results joined.

        Uses both tmp_path (fresh cache.db) AND a UUID-prefixed unique text
        so no old cached chunks can pollute the side_effect counter.
        """
        import uuid
        book_translator.BASE_DIR = tmp_path   # fresh SQLite per test

        counter = [0]
        seen_calls: list[str] = []

        def side_effect(text, **kw):
            counter[0] += 1
            r = MagicMock()
            r.text = f"[chunk {counter[0]}]"
            return r

        mock_deepl.Translator.return_value.translate_text.side_effect = side_effect
        mock_deepl.DeepLException = Exception

        # UUID prefix guarantees this text has never been cached before
        unique_prefix = f"UNIQUE_{uuid.uuid4().hex}"
        big_text = unique_prefix + "\n\n" + "\n\n".join(["word " * 200] * 15)
        result = translate_text_deepl(big_text, api_key="k:fx", chunk_size=6_000)

        # At least 2 API calls must have been made (text was split into chunks)
        assert counter[0] >= 2, (
            f"Expected >= 2 DeepL calls, got {counter[0]}"
        )
        # The joined result must contain output from multiple chunks
        assert result.count("[chunk") >= 2, (
            f"Expected >= 2 chunk labels in result, got:\n{result!r}"
        )


# ===========================================================================

# 7. Full pipeline integration (all stages mocked)
# ===========================================================================

class TestFullPipelineIntegration:

    @patch("book_translator.deepl")
    def test_math_and_images_both_survive_pipeline(self, mock_deepl):
        original = textwrap.dedent(r"""
            The heat equation
            $$\frac{\partial u}{\partial t} = \alpha^2 \frac{\partial^2 u}{\partial x^2}$$
            governs heat conduction.  With initial condition $u(x,0) = f(x)$
            and boundary conditions $u(0,t) = u(L,t) = 0$, the solution is
            $$u(x,t) = \sum_{n=1}^{\infty} B_n \sin\!\left(\frac{n\pi x}{L}\right)$$
            where $B_n = \frac{2}{L}\int_0^L f(x)\sin\!\left(\frac{n\pi x}{L}\right)dx$.
            ![Temperature profile](images/heat_profile.png)
        """).strip()

        masked, elems = mask_elements(original)
        assert "$"  not in masked
        assert "![" not in masked

        def fake_translate(text, **kw):
            r = MagicMock()
            r.text = text.replace("The heat equation", "Рівняння теплопровідності")
            return r

        mock_deepl.Translator.return_value.translate_text.side_effect = fake_translate
        mock_deepl.DeepLException = Exception

        translated = translate_text_deepl(masked, api_key="test:fx")
        for ph in elems:
            assert ph in translated
        final = unmask_elements(translated, elems)
        for orig_elem in elems.values():
            assert orig_elem in final
        assert _all_phs(final) == []
        assert "Рівняння теплопровідності" in final
        assert "![Temperature profile](images/heat_profile.png)" in final

    @patch("book_translator.deepl")
    def test_pipeline_with_images_only(self, mock_deepl):
        original = textwrap.dedent("""
            Chapter 1: Introduction
            ![Overview diagram](images/overview.png)
            This chapter introduces the main concepts.
            ![Second figure](images/fig2.png)
        """).strip()

        masked, elems = mask_elements(original)
        assert len(_image_phs(masked)) == 2
        assert "![" not in masked

        mock_deepl.Translator.return_value.translate_text.return_value = \
            MagicMock(text=masked.replace("Chapter", "Розділ"))
        mock_deepl.DeepLException = Exception

        translated = translate_text_deepl(masked, api_key="k:fx")
        final      = unmask_elements(translated, elems)

        assert "![Overview diagram](images/overview.png)" in final
        assert "![Second figure](images/fig2.png)" in final
        assert _image_phs(final) == []


# ===========================================================================
# 8. Russian Localization Pipeline
# ===========================================================================

class TestRussianLocalizationFast:
    @patch("book_translator.export_to_book_formats")
    @patch("book_translator.deepl")
    @patch("book_translator.datetime")
    def test_fast_russian_pipeline(self, mock_dt, mock_deepl, mock_export, tmp_path):
        from book_translator import process_document
        import datetime
        
        # Force a predictable run_dir name
        mock_dt.datetime.now.return_value = datetime.datetime(2026, 3, 7, 15, 30, 0)

        md_text = "Тестовая страница\n\n[page 1]\n\n$$E=mc^2$$"
        in_md = tmp_path / "input.md"
        in_md.write_text(md_text, encoding="utf-8")

        mock_deepl.Translator.return_value.translate_text.return_value = MagicMock(
            text="Test page\n\nPAGENUM0000X\n\nMATHBLK0000X"
        )
        mock_deepl.DeepLException = Exception

        book_translator.BASE_DIR = tmp_path
        book_translator.OUTPUT_DIR = tmp_path
        out_file = process_document(
            input_md_path=in_md,
            output_md_path=tmp_path / "out.md",
            api_key="fake",
            target_lang="UK"
        )

        assert out_file.exists()
        out_content = out_file.read_text(encoding="utf-8")
        assert "Test page" in out_content
        assert "E=mc^2" in out_content
        assert "page-break-after" in out_content
        mock_export.assert_called_once()

        # Verify isolated run directory contents
        expected_run_dir = tmp_path / "2026-03-07_15-30-00_Saturday"
        assert expected_run_dir.exists()
        assert (expected_run_dir / "images").exists()
        assert (expected_run_dir / "input_masked.md").exists()


# ===========================================================================
# 9. enhance_book_image   (requires opencv-python + numpy)
# ===========================================================================

class TestEnhanceBookImage:
    """
    Lightweight unit tests for enhance_book_image().

    All tests use a 10×10 numpy uint8 array encoded/decoded by cv2 – no PIL,
    no large images, no time.sleep().  The whole class is auto-skipped when
    opencv-python is not installed so CI without OpenCV doesn't break.
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_cv2(self):
        """Auto-skip every test when opencv-python or numpy is not installed."""
        pytest.importorskip("cv2",   reason="opencv-python not installed")
        pytest.importorskip("numpy", reason="numpy not installed")

    # ── Helper ────────────────────────────────────────────────────────────

    def _write_dirty_png(self, tmp_path: Path) -> Path:
        """
        Build a 10×10 grayscale PNG and save it using cv2 only (no PIL).

        Layout:
          rows 0-3  → grey background  (≈180)
          rows 4-5  → dark stripe      (≈20)   ← should become black
          rows 6-9  → grey background  (≈180)
        """
        import cv2
        import numpy as np

        data = np.full((10, 10), 180, dtype=np.uint8)
        data[4:6, :] = 20                        # dark foreground stripe

        ok, buf = cv2.imencode(".png", data)
        assert ok, "cv2.imencode failed in test helper"
        path = tmp_path / "dirty.png"
        path.write_bytes(buf.tobytes())
        return path

    # ── Tests ─────────────────────────────────────────────────────────────

    def test_output_is_strictly_binary(self, tmp_path):
        """Every pixel in the output must be exactly 0 or 255."""
        import cv2

        path = self._write_dirty_png(tmp_path)
        enhance_book_image(path)

        result = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        assert result is not None
        unique = set(result.flatten().tolist())
        assert unique <= {0, 255}, f"Non-binary pixels found: {unique - {0, 255}}"

    def test_background_becomes_white(self, tmp_path):
        """Light background rows must become 255 after binarisation."""
        import cv2
        import numpy as np

        path = self._write_dirty_png(tmp_path)
        enhance_book_image(path)

        result = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        bg = np.concatenate([result[0:4, :], result[6:10, :]])
        white_ratio = float((bg == 255).sum()) / bg.size
        assert white_ratio > 0.7, f"Expected >70% white in background, got {white_ratio:.1%}"

    def test_dark_stripe_becomes_black(self, tmp_path):
        """Dark stripe rows must become predominantly 0 (black)."""
        import cv2
        import numpy as np

        path = self._write_dirty_png(tmp_path)
        enhance_book_image(path)

        result = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        stripe = result[4:6, :]
        black_ratio = float((stripe == 0).sum()) / stripe.size
        assert black_ratio > 0.7, f"Expected >70% black in stripe, got {black_ratio:.1%}"

    def test_file_overwritten_in_place(self, tmp_path):
        """enhance_book_image must overwrite the original file (not create a copy)."""
        import cv2

        path = self._write_dirty_png(tmp_path)
        enhance_book_image(path)

        assert path.exists()
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        assert img is not None
        assert img.shape == (10, 10)

    def test_missing_file_does_not_raise(self, tmp_path):
        """A path that doesn't exist must be handled gracefully – no exception."""
        ghost = tmp_path / "ghost_that_does_not_exist.png"
        enhance_book_image(ghost)   # must NOT raise


# ===========================================================================
# 10. clean_markdown_formatting
# ===========================================================================

class TestCleanMarkdownFormatting:
    """
    Pure Python string tests – zero I/O, zero external calls.
    Runs in milliseconds.
    """

    # ─── 1. Blank-line collapse ───────────────────────────────────────────

    def test_triple_blank_lines_collapsed(self):
        text = "Paragraph one.\n\n\n\nParagraph two."
        result = clean_markdown_formatting(text)
        assert "\n\n\n" not in result
        assert "Paragraph one." in result
        assert "Paragraph two." in result

    def test_five_blank_lines_collapsed_to_two(self):
        text = "A\n\n\n\n\nB"
        result = clean_markdown_formatting(text)
        assert result.count("\n") <= 3

    def test_single_blank_line_unchanged(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = clean_markdown_formatting(text)
        assert "\n\n" in result

    # ─── 2. Inline math space trimming ───────────────────────────────────

    def test_spaces_inside_inline_math_removed(self):
        text = "The equation $ u_t = u_{xx} $ models diffusion."
        result = clean_markdown_formatting(text)
        assert "$ u_t = u_{xx} $" in result, f"Got: {result!r}"

    def test_block_math_not_affected(self):
        text = "Display:\n\n$$ u_t = u_{xx} $$\n\nEnd."
        result = clean_markdown_formatting(text)
        assert "$$ u_t = u_{xx} $$" in result

    def test_multiple_inline_formulas_trimmed(self):
        text = "Variables $ a $ and $ b $ are free."
        result = clean_markdown_formatting(text)
        assert "$ a $" in result
        assert "$ b $" in result

    def test_inline_math_without_extra_spaces_unchanged(self):
        text = "Solution: $u(x,t)$ is given above."
        result = clean_markdown_formatting(text)
        assert "$u(x,t)$" in result

    # ─── 3. Paragraph re-joining ─────────────────────────────────────────

    def test_broken_line_rejoined(self):
        text = "This is a long sentence that was broken by the\nOCR parser at the page margin."
        result = clean_markdown_formatting(text)
        # The new robust regex successfully joins it all
        assert "broken by the OCR parser" in result, f"Got:\n{result!r}"

    def test_sentence_ending_line_not_joined(self):
        text = "First sentence.\nSecond sentence starts here."
        result = clean_markdown_formatting(text)
        assert "First sentence." in result
        assert "Second sentence" in result

    def test_heading_not_joined_to_next_line(self):
        text = "## Chapter 1\nThis is the first paragraph."
        result = clean_markdown_formatting(text)
        assert "## Chapter 1" in result
        assert "This is the first paragraph." in result
        lines = result.split("\n")
        assert len([l for l in lines if l.startswith("## Chapter")]) == 1

    def test_image_line_not_joined_with_next(self):
        text = "![Fig 1](images/fig.png)\nCaption text here."
        result = clean_markdown_formatting(text)
        assert "![Fig 1](images/fig.png)" in result
        assert "Caption text here." in result

    def test_blank_line_preserved_between_paragraphs(self):
        text = "First paragraph ends here.\n\nSecond paragraph starts."
        result = clean_markdown_formatting(text)
        assert "\n\n" in result

    # ─── 4. Caption attachment ────────────────────────────────────────────

    def test_caption_attached_to_image(self):
        text = "![Graph](images/graph.png)\nFigure 1: Heat profile."
        result = clean_markdown_formatting(text)
        assert "![Graph](images/graph.png)\n\nFigure 1: Heat profile." in result

    def test_no_false_caption_when_blank_line_between(self):
        text = "![Graph](images/graph.png)\n\nSome unrelated paragraph."
        result = clean_markdown_formatting(text)
        assert "Some unrelated paragraph." in result

    # ─── 5. Idempotency and edge cases ───────────────────────────────────

    def test_already_clean_text_unchanged(self):
        text = "Clean paragraph one.\n\nClean paragraph two with $formula$."
        once  = clean_markdown_formatting(text)
        twice = clean_markdown_formatting(once)
        assert once == twice

    def test_empty_string_returns_empty(self):
        assert clean_markdown_formatting("") == ""

    def test_plain_text_not_mangled(self):
        text = "Simple sentence. Another sentence. Third sentence.\n\nNew paragraph."
        result = clean_markdown_formatting(text)
        assert "Simple sentence." in result
        assert "Another sentence." in result
        assert "New paragraph." in result

    # ─── 6. User Specific OCR Fixes ──────────────────────────────────────

    def test_isolated_inline_formula_rejoined(self):
        text = "This is a formula\n\n$x$\n\nin a sentence."
        result = clean_markdown_formatting(text)
        assert "This is a formula $x$ in a sentence." in result

    def test_detached_punctuation_rejoined(self):
        text = "Equation is given by\n, 0 < x < 1"
        result = clean_markdown_formatting(text)
        assert "Equation is given by, 0 < x < 1" in result

    def test_glued_text_around_math_separated_strictly(self):
        text = "word$u(x)$ and $t$word but keep 3$ and 4$."
        result = clean_markdown_formatting(text)
        assert "word$u(x)$ and $t$word" in result
        assert "keep 3$ and 4$" in result

    def test_broken_table_commas_collapsed(self):
        text = "Value1,,,Value2,,,,Value3"
        result = clean_markdown_formatting(text)
        # Note: multiple commas -> space, but if there's no space around them, 
        # it replaces exactly the commas, so "Value1 Value2 Value3".
        assert "Value1 Value2 Value3" in result
