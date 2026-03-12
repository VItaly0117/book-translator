import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the script directory to path
sys.path.append(str(Path(__file__).parent))

import book_translator

def test_svg_to_png_conversion():
    """Test the SVG to PNG conversion logic used in recreate_image_with_gemini."""
    temp_svg = Path("test_input.svg")
    test_png = Path("test_output.png")
    
    svg_content = """<svg width="100" height="100">
      <circle cx="50" cy="50" r="40" stroke="black" stroke-width="3" fill="red" />
    </svg>"""
    
    temp_svg.write_text(svg_content)
    
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        
        drawing = svg2rlg(str(temp_svg))
        renderPM.drawToFile(drawing, str(test_png), fmt="PNG")
        
        if test_png.exists():
            print("✅ SVG to PNG conversion successful!")
        else:
            print("❌ SVG to PNG conversion failed - output file missing.")
    except Exception as e:
        print(f"❌ SVG to PNG conversion failed: {e}")
    finally:
        if temp_svg.exists(): temp_svg.unlink()
        if test_png.exists(): test_png.unlink()

@patch('google.generativeai.GenerativeModel')
def test_recreate_image_with_mock_gemini(mock_model_class):
    """Test recreate_image_with_gemini with a mocked Gemini API."""
    mock_model = MagicMock()
    mock_model_class.return_value = mock_model
    
    mock_response = MagicMock()
    mock_response.text = """<svg width="100" height="100">
      <rect width="100" height="100" style="fill:blue;" />
    </svg>"""
    mock_model.generate_content.return_value = mock_response
    
    test_img = Path("test_image.png")
    # Create a dummy image
    from PIL import Image
    Image.new('RGB', (100, 100), color='red').save(test_img)
    
    # Mock GEMINI_API_KEY
    with patch('book_translator.GEMINI_API_KEY', 'fake_key'):
        try:
            book_translator.recreate_image_with_gemini(test_img)
            print("✅ recreate_image_with_gemini execution successful!")
        except Exception as e:
            print(f"❌ recreate_image_with_gemini failed: {e}")
        finally:
            if test_img.exists(): test_img.unlink()

if __name__ == "__main__":
    print("Starting verification tests...")
    test_svg_to_png_conversion()
    test_recreate_image_with_mock_gemini()
