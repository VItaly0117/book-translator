import sys
import os
from pathlib import Path
from unittest.mock import MagicMock
sys.modules['pypdf'] = MagicMock()
sys.modules['requests'] = MagicMock()

import pytest
import book_translator
from book_translator import (
    _filter_chunk_by_local_page_monotonicity,
    _needs_residual_translation,
    _normalize_chunk_export_style,
    _build_pdf_via_tex,
    _join_markdown_segments,
    _maybe_retranslate_chunk_text,
    _prepare_markdown_for_safe_pdf,
    _group_markdown_into_page_chunks,
    _remove_pdf_only_sections,
    _repair_known_pdf_math_artifacts,
    _split_markdown_into_page_chunks,
    _chunk_text,
    export_to_book_formats,
    mask_elements,
    retranslate_residual_russian_paragraphs,
    rescue_broken_latex,
    translate_text_azure,
    unmask_elements,
)

class TestBookTranslator:

    @staticmethod
    def _mock_sqlite(mocker, fetchone_result=None):
        mock_cursor = mocker.Mock()
        mock_cursor.fetchone.return_value = fetchone_result

        mock_conn = mocker.Mock()
        mock_conn.cursor.return_value = mock_cursor

        mock_connect = mocker.patch('book_translator.sqlite3.connect')
        mock_connect.return_value.__enter__.return_value = mock_conn

        return mock_cursor, mock_conn, mock_connect

    def test_mask_and_unmask_elements(self):
        """
        Тест маскирования и демаскирования.
        Проверяет работу mask_elements и unmask_elements на строке 
        с блочной формулой $$x^2$$ и инлайн формулой $y$.
        """
        original_text = "Блочная формула:\n\n$$x^2$$\n\nи инлайн формула $y$."
        
        # 1. Маскируем текст
        masked_text, elements_dict = mask_elements(original_text)
        
        # Убеждаемся, что оригинальные формулы заменены на плейсхолдеры
        assert "$$x^2$$" not in masked_text
        assert "$y$" not in masked_text
        assert len(elements_dict) == 2
        
        # Все плейсхолдеры должны содержать MATHBLK или MATHINL
        block_ph = next((k for k in elements_dict.keys() if "MATHBLK" in k), None)
        inline_ph = next((k for k in elements_dict.keys() if "MATHINL" in k), None)
        assert block_ph is not None
        assert inline_ph is not None
        
        # 2. Демаскируем (восстанавливаем) текст
        final_text = unmask_elements(masked_text, elements_dict)
        
        # Убеждаемся, что формулы вернулись в исходное состояние
        assert "$$x^2$$" in final_text
        assert "$y$" in final_text

    def test_chunk_text(self):
        """
        Тест чанкования.
        Проверяет корректное разбиение длинного текста по символу двойного переноса строки.
        """
        # Создаем текст из трех абзацев, разделенных двойным переносом
        p1 = "First paragraph."
        p2 = "Second paragraph, which we want to split right here."
        p3 = "Third paragraph."
        
        text = f"{p1}\n\n{p2}\n\n{p3}"
        
        # Заставляем чанкер резать после первого или второго параграфа, установив малый chunk_size
        chunk_size = len(p1) + len(p2) + 5
        
        chunks = _chunk_text(text, chunk_size=chunk_size)
        
        assert len(chunks) == 2
        # Первый чанк должен заканчиваться двойным переносом перед третьим абзацем
        assert p1 in chunks[0]
        assert p2 in chunks[0]
        assert p3 in chunks[1]

    def test_translate_text_azure(self, mocker):
        self._mock_sqlite(mocker, fetchone_result=None)

        # 3. Мокаем requests.post
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = [{'translations': [{'text': 'Тестовый перевод'}]}]
        mock_response.raise_for_status = mocker.Mock()
        mocker.patch('book_translator.requests.post', return_value=mock_response)
        mocker.patch('book_translator.time.sleep')

        # 4. Вызов функции
        result = translate_text_azure(
            text="Test text",
            api_key="fake_key",
            endpoint="https://api.fake.com/",
            region="fake_region",
            target_lang="uk"
        )

        assert "Тестовый перевод" in result

    def test_rescue_broken_latex_wraps_bare_environments(self):
        original_text = (
            r"\begin{aligned}a&=b\end{aligned}" "\n\n"
            r"\begin{split}x&=y\end{split}" "\n\n"
            r"\begin{cases}1,&x>0\\0,&x\le 0\end{cases}" "\n\n"
            r"\begin{array}{ll}u&=v\end{array}"
        )

        rescued_text = rescue_broken_latex(original_text)

        assert "$$\n\\begin{aligned}a&=b\\end{aligned}\n$$" in rescued_text
        assert "$$\n\\begin{split}x&=y\\end{split}\n$$" in rescued_text
        assert "$$\n\\begin{cases}1,&x>0\\\\0,&x\\le 0\\end{cases}\n$$" in rescued_text
        assert "$$\n\\begin{array}{ll}u&=v\\end{array}\n$$" in rescued_text

    def test_rescue_broken_latex_fixes_common_environment_typos(self):
        original_text = (
            r"\begin{case}a\\b\end{case}" "\n\n"
            r"\begin{align}x&=1\end{align}"
        )

        rescued_text = rescue_broken_latex(original_text)

        assert r"\begin{case}" not in rescued_text
        assert r"\end{case}" not in rescued_text
        assert r"\begin{align}" not in rescued_text
        assert r"\end{align}" not in rescued_text
        assert r"\begin{cases}" in rescued_text
        assert r"\end{cases}" in rescued_text
        assert r"\begin{aligned}" in rescued_text
        assert r"\end{aligned}" in rescued_text

    def test_rescue_broken_latex_preserves_existing_wrapped_math(self):
        original_text = "До\n\n$$\n\\begin{aligned}a&=b\n\\end{aligned}\n$$\n\nПосле"

        rescued_text = rescue_broken_latex(original_text)

        assert rescued_text == original_text

    def test_export_to_book_formats_keeps_relative_image_paths(self, mocker, tmp_path):
        output_dir = tmp_path / "Output_Final"
        images_dir = output_dir / "images"
        output_dir.mkdir()
        images_dir.mkdir()

        fake_pypandoc = MagicMock()
        mocker.patch.dict(sys.modules, {"pypandoc": fake_pypandoc})
        build_pdf_mock = mocker.patch(
            "book_translator._build_pdf_via_tex",
            return_value=output_dir / "book.pdf",
        )

        md_text = "Text\n\n![](images/pic.png)\n"
        expected_res_path = os.pathsep.join(
            [".", output_dir.absolute().as_posix(), images_dir.absolute().as_posix()]
        )

        export_to_book_formats(md_text, "book", output_dir, images_dir)

        assert fake_pypandoc.convert_text.call_count == 1
        epub_call = fake_pypandoc.convert_text.call_args
        assert f"--resource-path={expected_res_path}" in epub_call.kwargs["extra_args"]
        assert "images/pic.png" in epub_call.args[0]
        build_pdf_mock.assert_called_once()
        assert build_pdf_mock.call_args.kwargs["res_path"] == expected_res_path
        assert "images/pic.png" in build_pdf_mock.call_args.kwargs["md_text"]

    def test_remove_pdf_only_sections_keeps_mixed_formula_tables_but_trims_tail_sections(self):
        markdown = (
            "# Основний текст\n\n"
            "![](images/_page_10_pic.jpeg)\n\n"
            "# ТАБЛИЦІ ІНТЕГРАЛЬНИХ ПЕРЕТВОРЕНЬ\n\n"
            "Це ще не хвостовий додаток.\n\n"
            "# Наступний розділ\n\n"
            "Корисний навчальний текст.\n\n"
            "![](images/_page_360_pic.jpeg)\n\n"
            "# ТАБЛИЦІ ІНТЕГРАЛЬНИХ ПЕРЕТВОРЕНЬ\n\n"
            "ТАБЛИЦЯ F. Перетворення Лапласа\n\n"
            "| a | b |\n\n"
            "# **КРОССВОРД**\n\n"
            "Сетка\n\n"
            "# Джерела ()\n\n"
            "Корисний список\n"
        )

        cleaned = _remove_pdf_only_sections(markdown)

        assert cleaned.count("# ТАБЛИЦІ ІНТЕГРАЛЬНИХ ПЕРЕТВОРЕНЬ") == 2
        assert "Це ще не хвостовий додаток." in cleaned
        assert "# Наступний розділ" in cleaned
        assert "Корисний навчальний текст." in cleaned
        assert "# **КРОССВОРД**" not in cleaned
        assert "# Джерела ()" not in cleaned
        assert "Корисний список" not in cleaned

    def test_prepare_markdown_for_safe_pdf_neutralizes_residual_tex_lines(self):
        markdown = (
            "Текст перед блоком.\n\n"
            "\\Дельта u + u^2 = 0\n\n"
            "1. Умова\n"
            "    \\qquad u_{\\theta}(r, \\theta) = r \\cos \\theta,\n\n"
            "тривиальное решение X\\left(x\\right)\n"
        )

        safe_text = _prepare_markdown_for_safe_pdf(markdown)

        assert "`\\Дельта u + u^2 = 0`" in safe_text
        assert "~~~\n\\qquad u_{\\theta}(r, \\theta) = r \\cos \\theta,\n~~~" in safe_text
        assert "`тривиальное решение 'X\\left(x\\right)'`" in safe_text

    def test_split_markdown_into_page_chunks_uses_page_markers_and_headings(self):
        markdown = (
            "# Part 1\n\n"
            "Intro\n\n"
            "![](images/_page_10_pic.jpeg)\n\n"
            "More text\n\n"
            "# Part 2\n\n"
            "![](images/_page_55_pic.jpeg)\n\n"
            "Middle\n\n"
            "# Part 3\n\n"
            "![](images/_page_102_pic.jpeg)\n\n"
            "Tail\n"
        )

        chunks = _split_markdown_into_page_chunks(markdown, pages_per_chunk=50)

        assert [(start, end) for start, end, _ in chunks] == [
            (0, 49),
            (50, 99),
            (100, 102),
        ]
        assert chunks[0][2].startswith("# Part 1")
        assert chunks[1][2].startswith("# Part 2")
        assert chunks[2][2].startswith("# Part 3")

    def test_group_markdown_into_page_chunks_uses_actual_page_buckets_when_order_regresses(self):
        markdown = (
            "# Part 1\n\n"
            "![](images/_page_10_pic.jpeg)\n\n"
            "Intro text.\n\n"
            "# Part 2\n\n"
            "![](images/_page_55_pic.jpeg)\n\n"
            "Second section.\n\n"
            "# Late contamination\n\n"
            "![](images/_page_315_pic.jpeg)\n\n"
            "Late text.\n\n"
            "# Backfilled middle section\n\n"
            "![](images/_page_147_pic.jpeg)\n\n"
            "Backfilled text.\n\n"
            "![](images/_page_170_pic.jpeg)\n\n"
            "Real middle text.\n\n"
            "![](images/_page_205_pic.jpeg)\n\n"
            "Inherited paragraph after 205.\n\n"
            "![](images/_page_273_pic.jpeg)\n\n"
            "Section 250.\n\n"
            "![](images/_page_301_pic.jpeg)\n\n"
            "Section 300.\n\n"
            "![](images/_page_350_pic.jpeg)\n\n"
            "Tail.\n"
        )

        chunks = _group_markdown_into_page_chunks(markdown, pages_per_chunk=50)
        chunk_map = {(start, end): text for start, end, text in chunks}

        assert list(chunk_map.keys()) == [
            (0, 49),
            (50, 99),
            (100, 149),
            (150, 199),
            (200, 249),
            (250, 299),
            (300, 349),
            (350, 350),
        ]
        assert "images/_page_147_pic.jpeg" in chunk_map[(100, 149)]
        assert "images/_page_315_pic.jpeg" not in chunk_map[(150, 199)]
        assert "images/_page_170_pic.jpeg" in chunk_map[(150, 199)]
        assert "Inherited paragraph after 205." in chunk_map[(200, 249)]
        assert "images/_page_273_pic.jpeg" in chunk_map[(250, 299)]
        assert "images/_page_315_pic.jpeg" in chunk_map[(300, 349)]

    def test_group_markdown_into_page_chunks_drops_formula_handbook_sections(self):
        markdown = (
            "![](images/_page_150_pic.jpeg)\n\n"
            "Main section intro.\n\n"
            "# ТАБЛИЦЯ B. Перетворення Лапласа\n\n"
            "Table row 1.\n\n"
            "Table row 2.\n\n"
            "# Наступний розділ\n\n"
            "![](images/_page_170_pic.jpeg)\n\n"
            "Real chapter text.\n"
        )

        chunks = _group_markdown_into_page_chunks(markdown, pages_per_chunk=50)
        chunk_map = {(start, end): text for start, end, text in chunks}

        assert "Main section intro." in chunk_map[(150, 170)]
        assert "# ТАБЛИЦЯ B. Перетворення Лапласа" not in chunk_map[(150, 170)]
        assert "Table row 1." not in chunk_map[(150, 170)]
        assert "Table row 2." not in chunk_map[(150, 170)]
        assert "# Наступний розділ" in chunk_map[(150, 170)]
        assert "chapter text." in chunk_map[(150, 170)]

    def test_join_markdown_segments_preserves_block_boundaries(self):
        joined = _join_markdown_segments(
            [
                "First paragraph.",
                "![](images/pic.png)",
                "# Heading",
                "Tail text.",
            ]
        )

        assert joined == (
            "First paragraph.\n\n"
            "![](images/pic.png)\n\n"
            "# Heading\n\n"
            "Tail text.\n"
        )

    def test_maybe_retranslate_chunk_text_uses_residual_translation_when_candidates_exist(self, mocker):
        mocker.patch(
            "book_translator.retranslate_residual_russian_paragraphs",
            return_value="translated chunk",
        )

        result = _maybe_retranslate_chunk_text("# РЯДЫ И ПРЕОБРАЗОВАНИЯ ФУРЬЕ")

        assert result == "translated chunk"

    def test_translate_text_azure_waits_retry_after_plus_five_on_429(self, mocker):
        self._mock_sqlite(mocker, fetchone_result=None)

        response_429 = mocker.Mock()
        response_429.status_code = 429
        response_429.headers = {"Retry-After": "12"}

        response_200 = mocker.Mock()
        response_200.status_code = 200
        response_200.headers = {}
        response_200.json.return_value = [{'translations': [{'text': 'Перевод после ретрая'}]}]
        response_200.raise_for_status = mocker.Mock()

        mocker.patch('book_translator.requests.post', side_effect=[response_429, response_200])
        sleep_mock = mocker.patch('book_translator.time.sleep')

        result = translate_text_azure(
            text="Test text",
            api_key="fake_key",
            endpoint="https://api.fake.com/",
            region="fake_region",
            target_lang="uk"
        )

        assert "Перевод после ретрая" in result
        sleep_mock.assert_any_call(17)
        sleep_mock.assert_any_call(3.0)

    def test_translate_text_azure_sleeps_after_success_and_uses_single_worker(self, mocker):
        self._mock_sqlite(mocker, fetchone_result=None)

        response_200 = mocker.Mock()
        response_200.status_code = 200
        response_200.headers = {}
        response_200.json.return_value = [{'translations': [{'text': 'Тестовый перевод'}]}]
        response_200.raise_for_status = mocker.Mock()

        mocker.patch('book_translator.requests.post', return_value=response_200)
        sleep_mock = mocker.patch('book_translator.time.sleep')

        captured = {}

        class DummyExecutor:
            def __init__(self, max_workers):
                captured["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def map(self, func, iterable):
                return map(func, iterable)

        mocker.patch('book_translator.concurrent.futures.ThreadPoolExecutor', DummyExecutor)

        result = translate_text_azure(
            text="Test text",
            api_key="fake_key",
            endpoint="https://api.fake.com/",
            region="fake_region",
            target_lang="uk"
        )

        assert "Тестовый перевод" in result
        assert captured["max_workers"] == 1
        sleep_mock.assert_any_call(3.0)

    def test_needs_residual_translation_detects_short_russian_heading_and_caption(self):
        assert _needs_residual_translation("# РЯДЫ И ПРЕОБРАЗОВАНИЯ ФУРЬЕ")
        assert _needs_residual_translation("РИС. 16.1. Поперечные колебания струны.")
        assert not _needs_residual_translation("# РЯДИ І ПЕРЕТВОРЕННЯ ФУР'Є")

    def test_filter_chunk_by_local_page_monotonicity_drops_backward_jump_and_trailing_unmarked_text(self):
        chunk_text = (
            "# Розділ\n\n"
            "![](images/_page_170_pic.jpeg)\n\n"
            "Коректний текст сторінки 170.\n\n"
            "![](images/_page_118_pic.jpeg)\n\n"
            "Чужий текст зі старішої сторінки.\n\n"
            "Успадкований абзац після чужого маркера.\n\n"
            "![](images/_page_177_pic.jpeg)\n\n"
            "Повернення до коректного фрагмента.\n"
        )

        filtered = _filter_chunk_by_local_page_monotonicity(
            chunk_text,
            max_backward_jump=10,
        )

        assert "images/_page_170_pic.jpeg" in filtered
        assert "Коректний текст сторінки 170." in filtered
        assert "images/_page_118_pic.jpeg" not in filtered
        assert "Чужий текст зі старішої сторінки." not in filtered
        assert "Успадкований абзац після чужого маркера." not in filtered
        assert "images/_page_177_pic.jpeg" in filtered
        assert "Повернення до коректного фрагмента." in filtered

    def test_normalize_chunk_export_style_splits_meta_line_and_normalizes_headings(self):
        chunk_text = (
            "# УРАВНЕНИЯ ПЕРВОГО ПОРЯДКА (МЕТОД ХАРАКТЕРИСТИК) "
            "МЕТА ЛЕКЦІЇ: Пояснити метод.\n\n"
            "#TASKS:\n\n"
            "Лекция 27\n\n"
            "FIG. 21.1. Підпис рисунка.\n"
        )

        normalized = _normalize_chunk_export_style(chunk_text)

        assert "# РІВНЯННЯ ПЕРШОГО ПОРЯДКУ (МЕТОД ХАРАКТЕРИСТИК)\n\nМЕТА ЛЕКЦІЇ: Пояснити метод." in normalized
        assert "# ЗАВДАННЯ" in normalized
        assert "## Лекція 27" in normalized
        assert "Рис. 21.1. Підпис рисунка." in normalized

    def test_retranslate_residual_russian_paragraphs_batches_short_segments(self, mocker):
        source_text = (
            "# РЯДЫ И ПРЕОБРАЗОВАНИЯ ФУРЬЕ\n\n"
            "РИС. 16.1. Поперечные колебания струны.\n\n"
            "# РЯДИ І ПЕРЕТВОРЕННЯ ФУР'Є\n"
        )

        translate_mock = mocker.patch(
            "book_translator.translate_text_azure",
            return_value=(
                "SEGMENTTOKEN0000XYZ\n# РЯДИ І ПЕРЕТВОРЕННЯ ФУР'Є\n\n"
                "SEGMENTTOKEN0001XYZ\nРис. 16.1. Поперечні коливання струни.\n"
            ),
        )

        result = retranslate_residual_russian_paragraphs(
            source_text,
            api_key="real_key",
            endpoint="https://api.fake.com/",
            region="real_region",
            target_lang="uk",
        )

        assert "# РЯДИ І ПЕРЕТВОРЕННЯ ФУР'Є" in result
        assert "Рис. 16.1. Поперечні коливання струни." in result
        assert translate_mock.call_count == 1

    def test_build_pdf_via_tex_accepts_partial_output_when_allowed(self, mocker, tmp_path):
        fake_pypandoc = MagicMock()
        mocker.patch.dict(sys.modules, {"pypandoc": fake_pypandoc})
        mocker.patch("book_translator.shutil.which", return_value="/usr/bin/xelatex")

        def fake_convert_text(_text, _to, format, outputfile, extra_args):
            Path(outputfile).write_text(
                "\\usepackage{graphicx}\n\\usepackage{lmodern}\n\\begin{document}\nTest\n\\end{document}\n",
                encoding="utf-8",
            )

        fake_pypandoc.convert_text.side_effect = fake_convert_text

        def fake_run(_cmd, cwd, **_kwargs):
            pdf_path = Path(cwd) / "demo.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%mock\n")
            return mocker.Mock(returncode=1, stdout="", stderr="recoverable latex warning")

        mocker.patch("book_translator.subprocess.run", side_effect=fake_run)

        output_pdf = _build_pdf_via_tex(
            md_text="Test",
            output_stem="demo",
            output_dir=tmp_path,
            res_path=".",
            allow_partial_output=True,
        )

        assert output_pdf.exists()
        assert output_pdf.name == "demo.pdf"

    def test_safe_second_pass_cleanup_reverts_when_math_placeholders_leak(self, mocker):
        mocker.patch(
            "book_translator.second_pass_cleanup",
            return_value="Text before\n\nMATHBLK0001X\n\nText after",
        )
        cleanup_mock = mocker.patch(
            "book_translator.clean_markdown_formatting",
            return_value="fallback cleanup",
        )

        result = book_translator._safe_second_pass_cleanup("original text")

        assert result == "fallback cleanup"
        cleanup_mock.assert_called_once_with("original text")

    def test_repair_known_pdf_math_artifacts_rewrites_green_function_block(self):
        broken_text = (
            "1. Начальной температуры $q(x)$,\n\n"
            "    2. Функции  G(x, t) = \\frac{1}{2$\\alpha$ \\sqrt{$\\pi$ t}} "
            "e^{-(x-\\xi)^2/4c^2t} , которая называется функцией Грина или функцией источника.\n\n"
            "Теперь формуле (12.9) можно дать следующую интерпретацию.\n\n"
            "# ЗАМЕЧАНИЕ"
        )

        repaired_text = _repair_known_pdf_math_artifacts(broken_text)

        assert "функцією Гріна" in repaired_text
        assert "\\frac{1}{2\\alpha \\sqrt{\\pi t}}" in repaired_text
        assert "# ЗАМЕЧАНИЕ" in repaired_text
        assert "Начальной температуры" not in repaired_text

    def test_repair_known_pdf_math_artifacts_rewrites_canonical_tasks_section(self):
        broken_text = (
            "# ЗАВДАННЯ\n\n"
            "- 1. Які з цих параболічних і еліптичних рівнянь записуються у канонічній формі:\n\n"
            "    - a) u_t = u_{xx} hu ,\n"
            "         - 6) u_{xy} + u_{xx} + 3u = \\sin x ,\n"
            "         - \\mathbf{B}) \\ \\hat{u_{xx}} + 2\\hat{u_{yy}} = 0, - \\mathbf{r}) \\ u_{xx} = \\sin^2 x ?\n\n"
            "- 2. Перетворимо параболічне рівняння.\n\n"
            "# МЕТОД МОНТЕ-КАРЛО (ВСТУП)"
        )

        repaired_text = _repair_known_pdf_math_artifacts(broken_text)

        assert "записані у канонічній формі" in repaired_text
        assert ") $u_t = u_{xx} + hu$," in repaired_text
        assert ") $u_{xx} + 2u_{yy} = 0$," in repaired_text
        assert "# МЕТОД МОНТЕ-КАРЛО (ВСТУП)" in repaired_text

    def test_repair_known_pdf_math_artifacts_rewrites_variational_intro_section(self):
        broken_text = (
            "# КАЛЬКУЛЮС ВАРІАЦІЙ (РІВНЯННЯ ЕЙЛЕРА–ЛАГРАНЖА)\n\n"
            "МЕТА ЛЕКЦІЇ: Ввести поняття функціоналу.\n\n"
            "$$.\n\n"
            "що є функцією функції y.\n\n"
            "Бернуллі показав, що час сходження записується у формі\n\n"
            "$$\n\n"
            "Нахождение минимума функционала  $J[y] = \\int_{0}^{1} [y^2 + y'^2] dx$ ."
        )

        repaired_text = _repair_known_pdf_math_artifacts(broken_text)

        assert "J[y] = \\int_a^b F(x, y, y')\\,dx" in repaired_text
        assert "Рівняння (44.2) називається рівнянням Ейлера-Лагранжа" in repaired_text
        assert "Нахождение минимума функционала" in repaired_text
        assert "що є функцією функції y" not in repaired_text

    def test_repair_known_pdf_math_artifacts_does_not_replace_from_first_tasks_heading(self):
        broken_text = (
            "# ЗАДАЧИ\n\n"
            "Ранний список задач, который нельзя стирать.\n\n"
            + ("текст\n" * 600)
            + "# Лекція 47\n\n"
            "Початок наступної лекції.\n"
        )

        repaired_text = _repair_known_pdf_math_artifacts(broken_text)

        assert "Ранний список задач, который нельзя стирать." in repaired_text
        assert repaired_text.count("# ЗАДАЧИ") == 1
        assert "# Лекція 47" in repaired_text
