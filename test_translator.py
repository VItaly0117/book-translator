"""
test_translator.py
==================
Comprehensive pytest test suite for book_translator.py.

Coverage:
  1.  TestMaskElements        – masking of LaTeX (block + inline) and images
  2.  TestUnmaskElements      – restoration of all element types
  3.  TestMaskImageLinks      – image-specific masking edge cases
  4.  TestRoundTrip           – combined mask → unmask fidelity
  5.  TestChunkText           – text chunking / size limits
  6.  TestTranslateTextDeepL  – mocked DeepL API calls
  7.  TestFullPipelineIntegration – end-to-end with math + images (all mocked)

Run:
    pytest test_translator.py -v
    pytest test_translator.py -v --tb=short     # compact tracebacks
    pytest test_translator.py -v -k "image"     # only image-related tests
"""

from __future__ import annotations

import re
import textwrap
from unittest.mock import MagicMock, patch

import pytest

# ── Module under test ───────────────────────────────────────────────────────
from book_translator import (
    _chunk_text,
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
    """Return all MATHBLK placeholders found in *text*."""
    return re.findall(r"MATHBLK\d{4}X", text)


def _inline_phs(text: str) -> list[str]:
    """Return all MATHINL placeholders found in *text*."""
    return re.findall(r"MATHINL\d{4}X", text)


def _image_phs(text: str) -> list[str]:
    """Return all IMGTOKEN placeholders found in *text*."""
    return re.findall(r"IMGTOKEN\d{4}X", text)


def _all_phs(text: str) -> list[str]:
    """Return every placeholder (any type) found in *text*."""
    return re.findall(r"(?:MATHBLK|MATHINL|IMGTOKEN)\d{4}X", text)


def _round_trip(original: str) -> tuple[str, str, dict]:
    """
    mask_elements → identity 'translation' → unmask_elements.
    Simulates a no-op DeepL call to verify round-trip fidelity.
    """
    masked, elements_dict = mask_elements(original)
    final = unmask_elements(masked, elements_dict)
    return masked, final, elements_dict


# ===========================================================================
# 1. Masking – LaTeX formulas
# ===========================================================================

class TestMaskElements:

    # ── block math ──────────────────────────────────────────────────────────

    def test_block_double_dollar_is_masked(self):
        """$$...$$ must be captured as a single MATHBLK token."""
        formula = r"$$\frac{\partial u}{\partial t} = \alpha^2 \frac{\partial^2 u}{\partial x^2}$$"
        text    = f"The heat equation:\n{formula}\n\nIs fundamental."
        masked, elems = mask_elements(text)

        assert formula not in masked,          "Raw block math survived masking."
        assert formula in elems.values(),      "Block formula not saved in dict."
        assert len(_block_phs(masked)) == 1,   "Expected exactly 1 MATHBLK token."
        assert "$" not in masked,              "Stray $ found in masked text."

    def test_block_backslash_bracket_is_masked(self):
        r"""\\[...\\] display math must be captured as MATHBLK."""
        formula = r"\[ u(0,t) = 0, \quad u(L,t) = 0 \]"
        text = f"Boundary conditions: {formula} hold for all t."
        masked, elems = mask_elements(text)

        assert formula in elems.values()
        assert r"\[" not in masked
        assert len(_block_phs(masked)) == 1

    def test_multiline_block_math_is_single_token(self):
        """A $$...$$ spanning multiple lines must become ONE token."""
        formula = (
            "$$\n"
            r"\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}"
            "\n$$"
        )
        text = f"Classic result:\n{formula}\n"
        masked, elems = mask_elements(text)

        assert len(elems) == 1, f"Expected 1 element, got {len(elems)}: {elems}"
        assert formula in elems.values()

    # ── inline math ─────────────────────────────────────────────────────────

    def test_inline_dollar_is_masked(self):
        """$u(x,t) = X(x)T(t)$ must be replaced by MATHINL token."""
        text   = r"The solution is $u(x,t) = X(x)T(t)$ by separation."
        masked, elems = mask_elements(text)

        assert r"$u(x,t) = X(x)T(t)$" not in masked
        assert r"$u(x,t) = X(x)T(t)$" in elems.values()
        assert len(_inline_phs(masked)) == 1

    def test_inline_backslash_parens_is_masked(self):
        r"""\\(...\\) inline math must become MATHINL token."""
        formula = r"\( f(x) = x^2 \)"
        text    = f"The function {formula} is a parabola."
        masked, elems = mask_elements(text)

        assert formula in elems.values()
        assert r"\(" not in masked

    def test_adjacent_inline_formulas_are_independent(self):
        """Each inline formula gets its own unique token."""
        text   = r"We have $a$ and $b$ as free parameters."
        masked, elems = mask_elements(text)

        assert len(elems) == 2
        assert r"$a$" in elems.values()
        assert r"$b$" in elems.values()
        assert len(set(_inline_phs(masked))) == 2

    # ── mixed block + inline ─────────────────────────────────────────────────

    def test_block_and_inline_in_same_paragraph(self):
        """Block and inline math in the same text both get masked correctly."""
        text = textwrap.dedent(r"""
            The PDE is $u_t = \alpha u_{xx}$.

            $$u(x,t) = \sum_{n=1}^{\infty} B_n \sin\!\left(\frac{n\pi x}{L}\right)$$

            Initial condition: $u(x,0) = f(x)$.
        """)
        masked, elems = mask_elements(text)

        assert "$" not in masked,   "Stray $ in masked output."
        assert r"\[" not in masked, r"Stray \[ in masked output."
        # 1 block, 2 inline
        assert len(_block_phs(masked))  == 1
        assert len(_inline_phs(masked)) == 2

    def test_no_latex_survives_masking(self):
        """After masking, ZERO LaTeX delimiters must remain."""
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
        """Pure prose with no math/images must pass through untouched."""
        text = "Superposition: if u and v satisfy the PDE, so does u plus v."
        masked, elems = mask_elements(text)

        assert elems == {}
        assert masked.strip() == text.strip()

    def test_placeholder_keys_are_alphanumeric(self):
        """All placeholder strings must match [A-Za-z0-9]+ (DeepL safety)."""
        text = r"Solve $\nabla^2 \phi = 0$ in domain $\Omega$."
        masked, elems = mask_elements(text)

        for ph in elems:
            assert re.fullmatch(r"[A-Za-z0-9]+", ph), (
                f"Placeholder {ph!r} contains non-alphanumeric chars!"
            )


# ===========================================================================
# 2. Masking – Markdown image links
# ===========================================================================

class TestMaskImageLinks:

    def test_simple_image_is_masked(self):
        """![alt](images/pic.png) must become an IMGTOKEN placeholder."""
        text = "Figure 1 shows the solution.\n\n![Graph 1](images/page_10_img.png)\n"
        masked, elems = mask_elements(text)

        assert "![Graph 1](images/page_10_img.png)" not in masked
        assert "![Graph 1](images/page_10_img.png)" in elems.values()
        assert len(_image_phs(masked)) == 1

    def test_image_with_spaces_in_alt_text(self):
        """Alt text containing spaces must not break the image regex."""
        img   = "![Temperature distribution at t=0](images/temp_dist.png)"
        text  = f"See the figure below.\n{img}\n"
        masked, elems = mask_elements(text)

        assert img in elems.values()
        assert "![" not in masked

    def test_image_with_relative_path(self):
        """Images referenced with relative subdirectory paths are captured."""
        img  = "![Fig 3](../images/subfolder/wave_eq_fig3.png)"
        masked, elems = mask_elements(img)

        assert img in elems.values()

    def test_image_with_empty_alt_text(self):
        """An image with empty alt text ![](path) is still masked."""
        img  = "![](images/unlabelled.png)"
        masked, elems = mask_elements(img)

        assert img in elems.values()

    def test_multiple_images_get_unique_tokens(self):
        """Each image reference gets a distinct IMGTOKEN."""
        text = textwrap.dedent("""
            ![Figure 1](images/fig1.png)

            Some text in between.

            ![Figure 2](images/fig2.png)
        """)
        masked, elems = mask_elements(text)

        img_tokens = _image_phs(masked)
        assert len(set(img_tokens)) == 2, (
            f"Expected 2 unique image tokens, got {img_tokens}"
        )
        assert "![Figure 1](images/fig1.png)" in elems.values()
        assert "![Figure 2](images/fig2.png)" in elems.values()

    def test_image_and_formula_coexist(self):
        """A paragraph with both a formula and an image masks both correctly."""
        text = textwrap.dedent(r"""
            The solution $u(x,t)$ is plotted below.

            ![Solution plot](images/solution.png)
        """)
        masked, elems = mask_elements(text)

        assert len(_inline_phs(masked)) == 1,  "Expected 1 inline math token."
        assert len(_image_phs(masked))  == 1,  "Expected 1 image token."
        assert "$" not in masked
        assert "![" not in masked

    def test_regular_markdown_link_is_not_masked(self):
        """A plain hyperlink [text](url) must NOT be treated as an image."""
        text = "See [this reference](https://example.com) for details."
        masked, elems = mask_elements(text)

        # No image tokens – the link has no leading !
        assert _image_phs(masked) == [], "Hyperlink was incorrectly masked as image!"
        assert "[this reference](https://example.com)" in masked


# ===========================================================================
# 3. Unmasking – restoration fidelity
# ===========================================================================

class TestUnmaskElements:

    def test_inline_formula_is_restored(self):
        """Inline formula survives mask → unmask unchanged."""
        original = r"The solution $u(x,t) = X(x)T(t)$ is separated."
        _, final, _ = _round_trip(original)

        assert r"$u(x,t) = X(x)T(t)$" in final, f"Final: {final!r}"

    def test_block_formula_is_restored(self):
        """Block formula survives mask → unmask unchanged."""
        formula  = r"$$\frac{\partial u}{\partial t} = \alpha^2 \frac{\partial^2 u}{\partial x^2}$$"
        original = f"Heat equation:\n{formula}\n"
        _, final, _ = _round_trip(original)

        assert formula in final, f"Final: {final!r}"

    def test_image_link_is_restored_exactly(self):
        """Markdown image link survives mask → unmask byte-for-byte."""
        img      = "![Graph 1](images/page_10_img.png)"
        original = f"Figure below.\n\n{img}\n"
        _, final, _ = _round_trip(original)

        assert img in final, f"Final: {final!r}"

    def test_whitespace_tolerance_around_placeholder(self):
        """
        DeepL may add/remove surrounding spaces.  unmask_elements() must
        handle leading/trailing whitespace around ANY token type.
        """
        _, math_dict = mask_elements(r"$f(x) = x^2$")
        ph = next(iter(math_dict))

        for padded in [f"  {ph}  ", f"\n{ph}\n", f"\t{ph}\t"]:
            result = unmask_elements(padded, math_dict)
            assert r"$f(x) = x^2$" in result, (
                f"Formula not restored from {padded!r}. Result: {result!r}"
            )

    def test_no_leftover_placeholders(self):
        """After unmasking, zero tokens of any kind must remain."""
        original = textwrap.dedent(r"""
            Equation: $u_t = \kappa u_{xx}$.

            $$\int_0^L \sin^2\!\!\left(\frac{n\pi x}{L}\right) dx = \frac{L}{2}$$

            ![Eigenfunction plot](images/eigen.png)
        """)
        _, final, _ = _round_trip(original)

        leftover = _all_phs(final)
        assert leftover == [], f"Leftover tokens: {leftover}\nFinal:\n{final}"

    def test_all_elements_present_after_round_trip(self):
        """Every original formula and image must appear in the final output."""
        original = textwrap.dedent(r"""
            The general solution is $u = c_1 u_1 + c_2 u_2$.

            $$\frac{d^2 y}{dx^2} + p(x)\frac{dy}{dx} + q(x)y = 0$$

            The Wronskian $W = u_1 u_2' - u_2 u_1' \ne 0$.

            ![Wronskian diagram](images/wronskian.png)
        """).strip()

        _, final, elems = _round_trip(original)

        assert len(elems) == 4, f"Expected 4 elements, got {len(elems)}: {elems}"
        for original_elem in elems.values():
            assert original_elem in final, (
                f"Element missing from final output: {original_elem!r}\n"
                f"Final:\n{final}"
            )

    def test_empty_dict_returns_text_unchanged(self):
        """unmask_elements with {} must be a no-op."""
        text = "Це рівняння не має формул."
        assert unmask_elements(text, {}) == text

    def test_latex_backslashes_not_treated_as_regex(self):
        r"""
        Formulas containing \frac, \partial, etc. have backslashes that
        must NOT be treated as regex metacharacters during substitution.
        """
        formula  = r"$$\frac{\partial^2 u}{\partial x^2} = 0$$"
        original = f"Laplace equation: {formula}"
        _, final, _ = _round_trip(original)

        # Exact LaTeX string must be present character-for-character
        assert formula in final, (
            f"Backslash corruption detected.\nFinal: {final!r}"
        )


# ===========================================================================
# 4. Backward-compatible aliases
# ===========================================================================

class TestBackwardsCompatibleAliases:

    def test_mask_math_alias_works(self):
        """mask_math() must delegate to mask_elements() correctly."""
        text = r"Solve $x^2 = 4$."
        masked_via_alias, elems = mask_math(text)
        masked_via_new,   _     = mask_elements(text)

        # Both should produce the same structure (placeholder names may differ
        # only in index if called independently, but element count must match)
        assert len(elems) == 1
        assert r"$x^2 = 4$" in elems.values()
        assert "$" not in masked_via_alias

    def test_unmask_math_alias_works(self):
        """unmask_math() must delegate to unmask_elements() correctly."""
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
        text   = "Word " * 40_000      # ~200 000 chars
        chunks = _chunk_text(text, chunk_size=50_000)
        for i, chunk in enumerate(chunks):
            assert len(chunk) <= 50_000, (
                f"Chunk {i} is {len(chunk)} chars > 50 000 limit."
            )

    def test_all_content_preserved(self):
        paragraphs = [" ".join(["word"] * 100)] * 50
        text       = "\n\n".join(paragraphs)
        chunks     = _chunk_text(text, chunk_size=5_000)
        rejoined   = "".join(chunks)
        assert rejoined.replace("\n", "") == text.replace("\n", ""), (
            "Content was lost or corrupted during chunking."
        )

    def test_long_paragraph_without_newlines_still_splits(self):
        long_line = "x" * 50_000   # no whitespace at all
        chunks    = _chunk_text(long_line, chunk_size=10_000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 10_000


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

        out = translate_text_deepl(
            "The heat equation is fundamental.",
            api_key="fake:fx",
        )
        assert out == "Рівняння теплопровідності є фундаментальним."

    @patch("book_translator.deepl")
    def test_correct_api_parameters(self, mock_deepl):
        """Must call DeepL with source_lang=EN, target_lang=UK, preserve_formatting=True."""
        mock_translator = MagicMock()
        mock_translator.translate_text.return_value = self._result("ok")
        mock_deepl.Translator.return_value = mock_translator
        mock_deepl.DeepLException = Exception

        translate_text_deepl("text", api_key="key:fx", target_lang="UK")

        kwargs = mock_translator.translate_text.call_args.kwargs
        assert kwargs["source_lang"]         == "EN"
        assert kwargs["target_lang"]         == "UK"
        assert kwargs["preserve_formatting"] is True

    @patch("book_translator.deepl")
    def test_raises_on_empty_api_key(self, mock_deepl):
        with pytest.raises(ValueError, match="DEEPL_API_KEY"):
            translate_text_deepl("text", api_key="")
        mock_deepl.Translator.assert_not_called()

    @patch("book_translator.deepl")
    def test_math_placeholders_survive_translation(self, mock_deepl):
        """After mock translate + unmask, the original formula must be intact."""
        original = r"The equation $u_t = \kappa u_{xx}$ models diffusion."
        masked, elems = mask_elements(original)
        ph = _inline_phs(masked)[0]

        simulated = f"Рівняння {ph} моделює дифузію."
        mock_deepl.Translator.return_value.translate_text.return_value = \
            self._result(simulated)
        mock_deepl.DeepLException = Exception

        translated = translate_text_deepl(masked, api_key="k:fx")
        final      = unmask_elements(translated, elems)

        assert r"$u_t = \kappa u_{xx}$" in final, f"FINAL: {final!r}"

    @patch("book_translator.deepl")
    def test_image_placeholders_survive_translation(self, mock_deepl):
        """After mock translate + unmask, the original image link must be intact."""
        img      = "![Solution](images/solution.png)"
        original = f"Figure:\n\n{img}\n"
        masked, elems = mask_elements(original)
        ph = _image_phs(masked)[0]

        simulated = f"Малюнок:\n\n{ph}\n"
        mock_deepl.Translator.return_value.translate_text.return_value = \
            self._result(simulated)
        mock_deepl.DeepLException = Exception

        translated = translate_text_deepl(masked, api_key="k:fx")
        final      = unmask_elements(translated, elems)

        assert img in final, f"Image link lost! FINAL: {final!r}"

    @patch("book_translator.deepl")
    def test_chunked_translation_joins_results(self, mock_deepl):
        """Multiple chunks must be joined and all returned."""
        counter = [0]

        def side_effect(text, **kw):
            counter[0] += 1
            r = MagicMock()
            r.text = f"[chunk {counter[0]}]"
            return r

        mock_deepl.Translator.return_value.translate_text.side_effect = side_effect
        mock_deepl.DeepLException = Exception

        big_text = "\n\n".join(["word " * 200] * 15)   # ~17 000 chars
        result = translate_text_deepl(big_text, api_key="k:fx", chunk_size=6_000)

        assert counter[0] >= 2
        assert "[chunk 1]" in result
        assert "[chunk 2]" in result


# ===========================================================================
# 7. Full pipeline integration (all stages mocked)
# ===========================================================================

class TestFullPipelineIntegration:

    @patch("book_translator.deepl")
    def test_math_and_images_both_survive_pipeline(self, mock_deepl):
        """
        Core integration test:  mask → translate (mock) → unmask.

        The final output must:
          (a) contain every original LaTeX formula verbatim
          (b) contain every original Markdown image link verbatim
          (c) contain NO leftover placeholder tokens
          (d) contain Ukrainian prose (from the mock translation)
        """
        original = textwrap.dedent(r"""
            The heat equation

            $$\frac{\partial u}{\partial t} = \alpha^2 \frac{\partial^2 u}{\partial x^2}$$

            governs heat conduction.  With initial condition $u(x,0) = f(x)$
            and boundary conditions $u(0,t) = u(L,t) = 0$, the solution is

            $$u(x,t) = \sum_{n=1}^{\infty} B_n \sin\!\left(\frac{n\pi x}{L}\right)$$

            where $B_n = \frac{2}{L}\int_0^L f(x)\sin\!\left(\frac{n\pi x}{L}\right)dx$.

            ![Temperature profile](images/heat_profile.png)
        """).strip()

        # ── Stage 2: mask ────────────────────────────────────────────────────
        masked, elems = mask_elements(original)

        assert "$"  not in masked, "Raw $ survived masking."
        assert "![" not in masked, "Raw image link survived masking."

        # ── Stage 3: mock DeepL – translate prose, keep tokens ──────────────
        def fake_translate(text, **kw):
            translated = (
                text
                .replace("The heat equation", "Рівняння теплопровідності")
                .replace("governs heat conduction.", "описує теплопровідність.")
                .replace("With initial condition", "З початковою умовою")
                .replace("and boundary conditions", "та граничними умовами")
                .replace("the solution is", "розв'язок є")
                .replace("where", "де")
            )
            r = MagicMock()
            r.text = translated
            return r

        mock_deepl.Translator.return_value.translate_text.side_effect = fake_translate
        mock_deepl.DeepLException = Exception

        translated = translate_text_deepl(masked, api_key="test:fx")

        # Tokens must be untouched by the mock translator
        for ph in elems:
            assert ph in translated, f"Token {ph!r} was mangled by fake translator!"

        # ── Stage 4: unmask ──────────────────────────────────────────────────
        final = unmask_elements(translated, elems)

        # (a) all formulas present
        for orig_elem in elems.values():
            assert orig_elem in final, (
                f"Element missing from final:\n  {orig_elem!r}\nFinal:\n{final}"
            )

        # (b) no tokens remain
        leftover = _all_phs(final)
        assert leftover == [], f"Leftover tokens: {leftover}"

        # (c) Ukrainian text present
        assert "Рівняння теплопровідності" in final

        # (d) image link present
        assert "![Temperature profile](images/heat_profile.png)" in final

    @patch("book_translator.deepl")
    def test_pipeline_with_images_only(self, mock_deepl):
        """A document with images but no formulas must process correctly."""
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
            MagicMock(text=masked.replace("Chapter", "Розділ")
                                 .replace("This chapter introduces the main concepts.",
                                          "У цьому розділі представлено основні концепції."))
        mock_deepl.DeepLException = Exception

        translated = translate_text_deepl(masked, api_key="k:fx")
        final      = unmask_elements(translated, elems)

        assert "![Overview diagram](images/overview.png)" in final
        assert "![Second figure](images/fig2.png)"        in final
        assert _image_phs(final) == [], "Image tokens not removed from final output."
