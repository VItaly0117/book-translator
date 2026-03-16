import pytest
from book_translator import mask_elements, unmask_elements, _chunk_text, translate_text_azure

class TestBookTranslator:

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
        """
        Mock-тест для Azure: Напиши тест для translate_text_azure.
        Используй mocker.patch('requests.post').
        Замокай sqlite3.connect, чтобы тест не создавал реальную базу данных на диске.
        """
        # Мокаем sqlite3.connect (база кеширования)
        mock_sqlite = mocker.patch('sqlite3.connect')
        
        # Мокаем requests.post (вызов Azure API)
        mock_post = mocker.patch('requests.post')
        
        # Создаем фейковый успешный JSON ответ от перевода
        mock_response = mocker.Mock()
        mock_response.json.return_value = [{'translations': [{'text': 'Тестовый перевод'}]}]
        mock_response.raise_for_status = mocker.Mock()
        mock_post.return_value = mock_response
        
        # Вызываем функцию перевода с фейковыми данными
        result = translate_text_azure(
            text="Test text", 
            api_key="fake_key", 
            endpoint="https://api.fake.com/", 
            region="fake_region", 
            target_lang="uk",
            chunk_size=5000
        )
        
        # Проверяем, что запрос действительно улетел:
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        
        # Проверим, что запрос отправился на нужный URL
        assert args[0] == "https://api.fake.com/translate"
        assert kwargs["params"]["to"] == "uk"
        assert kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "fake_key"
        assert kwargs["headers"]["Ocp-Apim-Subscription-Region"] == "fake_region"
        
        # Проверяем сам результат
        assert result == "Тестовый перевод"
        
        # Убеждаемя, что мы вызывали мокнутую БД:
        mock_sqlite.assert_called()
