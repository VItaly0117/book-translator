import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import os
import sys

# Add the script directory to path
sys.path.append(str(Path(__file__).parent))

import book_translator

class TestGeminiImageRecreation(unittest.TestCase):
    
    @patch('book_translator.svg2rlg')
    @patch('book_translator.Path')
    def test_recreate_image_with_gemini_success(self, mock_path, mock_svg2rlg):
        # Setup
        mock_genai = MagicMock()
        mock_client_instance = MagicMock()
        mock_genai.Client.return_value = mock_client_instance
        
        mock_response = MagicMock()
        mock_response.text = "<svg>...</svg>"
        mock_client_instance.models.generate_content.return_value = mock_response
        
        # Configure Path mock
        mock_path_instance = MagicMock()
        mock_path_instance.name = "test_image.png"
        mock_path.return_value = mock_path_instance
        
        test_path = MagicMock(spec=Path)
        test_path.name = "test_image.png"
        
        mock_image = MagicMock()
        mock_renderPM = MagicMock()
        
        # Action
        with patch('book_translator.GEMINI_API_KEY', 'fake_key'), \
             patch('book_translator._AI_IMAGES_AVAILABLE', True), \
             patch('book_translator.genai', mock_genai), \
             patch('book_translator.Image', mock_image), \
             patch('book_translator.renderPM', mock_renderPM):
            book_translator.recreate_image_with_gemini(test_path)
        
        # Assertions
        mock_image.open.assert_called_once_with(test_path)
        mock_genai.Client.assert_called_once_with(api_key='fake_key')
        mock_client_instance.models.generate_content.assert_called_once()
        mock_svg2rlg.assert_called_once_with("temp_gemini.svg")
        mock_renderPM.drawToFile.assert_called_once()
        # Verify unlink was called on some path instance (likely the temp file)
        mock_path_instance.unlink.assert_called()

    @patch('book_translator._AI_IMAGES_AVAILABLE', False)
    def test_recreate_image_missing_libraries_raises_error(self):
        test_path = Path("test_image.png")
        with self.assertRaises(ImportError):
            book_translator.recreate_image_with_gemini(test_path)

    @patch('book_translator._AI_IMAGES_AVAILABLE', True)
    @patch('book_translator.GEMINI_API_KEY', '')
    def test_recreate_image_missing_api_key_raises_error(self):
        test_path = Path("test_image.png")
        with self.assertRaises(ValueError):
            book_translator.recreate_image_with_gemini(test_path)

    @patch('book_translator.svg2rlg')
    @patch('book_translator.Path')
    def test_recreate_image_cleans_markdown_tags(self, mock_path, mock_svg2rlg):
        # Setup
        mock_genai = MagicMock()
        mock_client_instance = MagicMock()
        mock_genai.Client.return_value = mock_client_instance
        
        mock_response = MagicMock()
        mock_response.text = "```svg\n<svg>Cleaned</svg>\n```"
        mock_client_instance.models.generate_content.return_value = mock_response
        
        mock_path_instance = MagicMock()
        mock_path_instance.name = "test_image.png"
        mock_path.return_value = mock_path_instance
        
        test_path = MagicMock(spec=Path)
        test_path.name = "test_image.png"
        
        mock_image = MagicMock()
        mock_renderPM = MagicMock()
        
        # Action
        with patch('book_translator.GEMINI_API_KEY', 'fake_key'), \
             patch('book_translator._AI_IMAGES_AVAILABLE', True), \
             patch('book_translator.genai', mock_genai), \
             patch('book_translator.Image', mock_image), \
             patch('book_translator.renderPM', mock_renderPM):
            book_translator.recreate_image_with_gemini(test_path)
        
        # Verify the content written to temp file was cleaned
        mock_path_instance.write_text.assert_called()
        written_svg = mock_path_instance.write_text.call_args[0][0]
        self.assertEqual(written_svg, "<svg>Cleaned</svg>")

if __name__ == '__main__':
    unittest.main()
