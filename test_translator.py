import sys
import os
from unittest.mock import MagicMock
sys.modules['pypdf'] = MagicMock()
sys.modules['requests'] = MagicMock()

import pytest
import book_translator
from book_translator import (
    _chunk_text,
    export_to_book_formats,
    mask_elements,
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

        md_text = "Text\n\n![](images/pic.png)\n"
        expected_res_path = os.pathsep.join([".", output_dir.absolute().as_posix()])

        export_to_book_formats(md_text, "book", output_dir, images_dir)

        assert fake_pypandoc.convert_text.call_count == 2
        for call in fake_pypandoc.convert_text.call_args_list:
            assert call.args[0] == md_text
            assert f"--resource-path={expected_res_path}" in call.kwargs["extra_args"]

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
