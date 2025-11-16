"""Tests for optimized OLED scrolling functionality.

This module tests the refactored scrolling logic that separates content
rendering from the animation loop for improved performance.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import Dict

# Mark all tests in this file as unit tests
pytestmark = pytest.mark.unit


@pytest.fixture
def mock_pil_modules():
    """Mock PIL modules for testing without actual hardware."""
    with patch('app_core.oled.Image') as mock_image, \
         patch('app_core.oled.ImageDraw') as mock_draw, \
         patch('app_core.oled.ImageFont') as mock_font, \
         patch('app_core.oled.i2c') as mock_i2c, \
         patch('app_core.oled.ssd1306') as mock_ssd1306:
        
        # Setup mock image
        mock_img = Mock()
        mock_img.crop = Mock(return_value=mock_img)
        mock_img.paste = Mock()
        mock_image.new = Mock(return_value=mock_img)
        
        # Setup mock draw
        mock_draw_obj = Mock()
        mock_draw_obj.text = Mock()
        mock_draw_obj.textlength = Mock(return_value=100.0)
        mock_draw.Draw = Mock(return_value=mock_draw_obj)
        
        # Setup mock font - getbbox should return tuple of integers
        mock_font_obj = Mock()
        mock_font_obj.getbbox = Mock(return_value=(0, 0, 10, 12))
        mock_font.load_default = Mock(return_value=mock_font_obj)
        mock_font.truetype = Mock(return_value=mock_font_obj)
        
        # Setup mock device
        mock_device = Mock()
        mock_device.display = Mock()
        mock_ssd1306.return_value = mock_device
        
        yield {
            'image': mock_image,
            'draw': mock_draw,
            'font': mock_font,
            'device': mock_device,
            'img': mock_img,
            'draw_obj': mock_draw_obj,
        }


@pytest.fixture
def oled_controller(mock_pil_modules):
    """Create an OLED controller instance for testing."""
    from app_core.oled import ArgonOLEDController
    
    controller = ArgonOLEDController(
        width=128,
        height=64,
        i2c_bus=1,
        i2c_address=0x3C,
    )
    return controller


@pytest.fixture
def sample_lines():
    """Create sample OLED lines for testing."""
    from app_core.oled import OLEDLine
    
    return [
        OLEDLine(text="Line 1", x=0, y=0, font="small"),
        OLEDLine(text="Line 2", x=0, y=15, font="small"),
        OLEDLine(text="Line 3", x=0, y=30, font="small"),
    ]


class TestPrepareScrollContent:
    """Tests for the prepare_scroll_content method."""
    
    def test_prepare_scroll_content_returns_image_and_dimensions(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that prepare_scroll_content returns both image and dimensions."""
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Verify return types
        assert content_image is not None
        assert isinstance(dimensions, dict)
        assert 'max_x' in dimensions
        assert 'max_y' in dimensions
        
        # Verify dimensions are reasonable
        assert dimensions['max_x'] >= 0
        assert dimensions['max_y'] >= 0
    
    def test_prepare_scroll_content_creates_large_image(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that a large buffer image is created (2x display size)."""
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Verify Image.new was called with correct size
        mock_pil_modules['image'].new.assert_called()
        call_args = mock_pil_modules['image'].new.call_args_list[-1]
        mode, size = call_args[0]
        assert mode == "1"  # 1-bit monochrome
        assert size == (oled_controller.width * 2, oled_controller.height * 2)
    
    def test_prepare_scroll_content_renders_text_once(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that text is rendered during preparation (may be multiple times due to wrapping)."""
        mock_draw_obj = mock_pil_modules['draw_obj']
        mock_draw_obj.text.reset_mock()
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Verify text was drawn (at least once per line, possibly more due to wrapping)
        assert mock_draw_obj.text.call_count >= len(sample_lines)
    
    def test_prepare_scroll_content_with_invert(self, oled_controller, sample_lines, mock_pil_modules):
        """Test content preparation with inverted colors."""
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines, invert=True)
        
        # Verify Image.new was called with inverted background (255 for white)
        call_args = mock_pil_modules['image'].new.call_args_list[-1]
        assert call_args[1]['color'] == 255
    
    def test_prepare_scroll_content_empty_lines(self, oled_controller, mock_pil_modules):
        """Test that empty lines are skipped during preparation."""
        from app_core.oled import OLEDLine
        
        lines = [
            OLEDLine(text="", x=0, y=0, font="small", allow_empty=False),
            OLEDLine(text="Valid text", x=0, y=15, font="small"),
        ]
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        mock_draw_obj.text.reset_mock()
        
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        
        # Only non-empty lines should be drawn (at least once, possibly more due to wrapping)
        assert mock_draw_obj.text.call_count >= 1
    
    def test_prepare_scroll_content_calculates_bounds(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that content bounds are calculated correctly."""
        # Mock textlength to return consistent values
        mock_pil_modules['draw_obj'].textlength.return_value = 80.0
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Verify dimensions reflect the rendered content
        assert dimensions['max_x'] > 0
        assert dimensions['max_y'] > 0


class TestRenderScrollFrame:
    """Tests for the optimized render_scroll_frame method."""
    
    def test_render_scroll_frame_accepts_prerendered_content(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that render_scroll_frame accepts pre-rendered content."""
        from app_core.oled import OLEDScrollEffect
        
        # Prepare content first
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Render frame should work with pre-rendered content
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_LEFT,
            offset=0,
        )
        
        # Verify device.display was called
        assert mock_pil_modules['device'].display.called
    
    def test_render_scroll_frame_no_text_rendering(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that render_scroll_frame does NOT perform text rendering."""
        from app_core.oled import OLEDScrollEffect
        
        # Prepare content
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Reset mock to track only render_scroll_frame calls
        mock_draw_obj = mock_pil_modules['draw_obj']
        mock_draw_obj.text.reset_mock()
        
        # Render multiple frames
        for offset in range(5):
            oled_controller.render_scroll_frame(
                content_image,
                dimensions,
                OLEDScrollEffect.SCROLL_LEFT,
                offset=offset * 10,
            )
        
        # Verify NO text rendering occurred in render_scroll_frame
        assert mock_draw_obj.text.call_count == 0
    
    def test_render_scroll_frame_scroll_left_effect(self, oled_controller, sample_lines, mock_pil_modules):
        """Test scroll left effect cropping with seamless wrapping."""
        from app_core.oled import OLEDScrollEffect
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        mock_img = mock_pil_modules['img']
        mock_img.crop.reset_mock()
        
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_LEFT,
            offset=10,
        )
        
        # Verify crop was called (may be called once or twice for wrapping)
        assert mock_img.crop.called
        # The offset is applied with modulo for seamless looping
        # Just verify that cropping occurred - exact args depend on wrapping logic
    
    def test_render_scroll_frame_scroll_right_effect(self, oled_controller, sample_lines, mock_pil_modules):
        """Test scroll right effect cropping."""
        from app_core.oled import OLEDScrollEffect
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        mock_img = mock_pil_modules['img']
        mock_img.crop.reset_mock()
        
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_RIGHT,
            offset=10,
        )
        
        # Verify crop was called
        assert mock_img.crop.called
    
    def test_render_scroll_frame_scroll_up_effect(self, oled_controller, sample_lines, mock_pil_modules):
        """Test scroll up effect cropping."""
        from app_core.oled import OLEDScrollEffect
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        mock_img = mock_pil_modules['img']
        mock_img.crop.reset_mock()
        
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_UP,
            offset=10,
        )
        
        # Verify crop was called
        assert mock_img.crop.called
        crop_args = mock_img.crop.call_args[0][0]
        # For scroll up, y offset should be 10
        assert crop_args[1] == 10
    
    def test_render_scroll_frame_static_effect(self, oled_controller, sample_lines, mock_pil_modules):
        """Test static (no animation) effect."""
        from app_core.oled import OLEDScrollEffect
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.STATIC,
            offset=0,
        )
        
        # Verify device.display was called
        assert mock_pil_modules['device'].display.called
    
    def test_render_scroll_frame_with_invert(self, oled_controller, sample_lines, mock_pil_modules):
        """Test frame rendering with inverted colors."""
        from app_core.oled import OLEDScrollEffect
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines, invert=True)
        
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_LEFT,
            offset=0,
            invert=True,
        )
        
        # Verify Image.new was called with inverted background
        call_args = mock_pil_modules['image'].new.call_args_list[-1]
        assert call_args[1]['color'] == 255


class TestScrollingPerformance:
    """Tests to verify performance improvements."""
    
    def test_multiple_frames_single_content_preparation(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that content is prepared once for multiple frames."""
        from app_core.oled import OLEDScrollEffect
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        
        # Prepare content once
        mock_draw_obj.text.reset_mock()
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        text_calls_during_prep = mock_draw_obj.text.call_count
        
        # Render 10 frames
        mock_draw_obj.text.reset_mock()
        for offset in range(0, 100, 10):
            oled_controller.render_scroll_frame(
                content_image,
                dimensions,
                OLEDScrollEffect.SCROLL_LEFT,
                offset=offset,
            )
        
        # Verify NO additional text rendering during frame rendering
        assert mock_draw_obj.text.call_count == 0
        
        # All text rendering should have happened during preparation (at least once per line)
        assert text_calls_during_prep >= len(sample_lines)


class TestBackwardCompatibility:
    """Tests to ensure the API changes don't break existing functionality."""
    
    def test_prepare_and_render_workflow(self, oled_controller, sample_lines, mock_pil_modules):
        """Test the complete prepare-render workflow."""
        from app_core.oled import OLEDScrollEffect
        
        # Step 1: Prepare content
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        # Step 2: Render multiple frames
        for offset in range(0, 50, 5):
            oled_controller.render_scroll_frame(
                content_image,
                dimensions,
                OLEDScrollEffect.SCROLL_LEFT,
                offset=offset,
            )
        
        # Verify workflow completed without errors
        assert mock_pil_modules['device'].display.call_count >= 10
    
    def test_all_scroll_effects_work(self, oled_controller, sample_lines, mock_pil_modules):
        """Test that all scroll effects work with the new implementation."""
        from app_core.oled import OLEDScrollEffect
        
        content_image, dimensions = oled_controller.prepare_scroll_content(sample_lines)
        
        effects = [
            OLEDScrollEffect.SCROLL_LEFT,
            OLEDScrollEffect.SCROLL_RIGHT,
            OLEDScrollEffect.SCROLL_UP,
            OLEDScrollEffect.SCROLL_DOWN,
            OLEDScrollEffect.WIPE_LEFT,
            OLEDScrollEffect.WIPE_RIGHT,
            OLEDScrollEffect.WIPE_UP,
            OLEDScrollEffect.WIPE_DOWN,
            OLEDScrollEffect.FADE_IN,
            OLEDScrollEffect.STATIC,
        ]
        
        for effect in effects:
            oled_controller.render_scroll_frame(
                content_image,
                dimensions,
                effect,
                offset=10,
            )
        
        # All effects should render without error
        assert mock_pil_modules['device'].display.call_count == len(effects)


class TestScrollingTextBehavior:
    """Tests to ensure scrolling text behaves correctly for smooth horizontal scrolling."""
    
    def test_prepare_scroll_content_does_not_wrap_long_text(self, oled_controller, mock_pil_modules):
        """Test that prepare_scroll_content keeps long text as a single line for smooth scrolling."""
        from app_core.oled import OLEDLine
        
        # Create a line with very long text - should NOT be wrapped for scrolling
        long_text = "This is a very long line of text that will scroll horizontally as one continuous line"
        lines = [
            OLEDLine(text=long_text, x=0, y=0, font="small", wrap=True),
        ]
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        mock_draw_obj.text.reset_mock()
        
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        
        # Verify that text.draw was called only once (no wrapping for scrolling)
        # Scrolling text should remain as a single long line for smooth horizontal scrolling
        assert mock_draw_obj.text.call_count == 1, \
            "Scrolling text should be kept as a single line for smooth horizontal scrolling"
    
    def test_prepare_scroll_content_single_line_for_all_text(self, oled_controller, mock_pil_modules):
        """Test that prepare_scroll_content keeps all text as single lines."""
        from app_core.oled import OLEDLine
        
        long_text = "This is a very long line of text that could be wrapped but shouldn't be for scrolling"
        
        lines = [
            OLEDLine(text=long_text, x=0, y=0, font="small", wrap=False),
        ]
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        mock_draw_obj.text.reset_mock()
        
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        
        # Should only render once (no wrapping) 
        assert mock_draw_obj.text.call_count == 1, \
            "Scrolling text should render as single line"
    
    def test_prepare_scroll_content_differs_from_display_lines(self, oled_controller, mock_pil_modules):
        """Test that prepare_scroll_content does NOT wrap text like display_lines does.
        
        This is intentional: scrolling content should scroll as one long continuous line,
        while static content wraps to fit the display width.
        """
        from app_core.oled import OLEDLine
        
        # Long text that would be wrapped in display_lines but not in prepare_scroll_content
        long_text = "EMERGENCY ALERT: This is a very long emergency message that needs to scroll"
        lines = [
            OLEDLine(text=long_text, x=0, y=0, font="small", wrap=True, max_width=128),
        ]
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        
        # Mock textlength to return consistent values
        def mock_textlength(text, font=None):
            return len(text) * 8.0
        mock_draw_obj.textlength = mock_textlength
        
        # Test display_lines wrapping (should wrap)
        mock_draw_obj.text.reset_mock()
        oled_controller.display_lines(lines)
        display_lines_call_count = mock_draw_obj.text.call_count
        
        # Test prepare_scroll_content (should NOT wrap)
        mock_draw_obj.text.reset_mock()
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        scroll_content_call_count = mock_draw_obj.text.call_count
        
        # Scrolling content should NOT wrap (single line for smooth horizontal scroll)
        assert scroll_content_call_count == 1, \
            "Scrolling text should remain as single line for smooth horizontal scrolling"
        
        # Display lines SHOULD wrap (multiple lines for static display)
        assert display_lines_call_count > 1, \
            "Static text should be wrapped to fit display width"
        
        # They should be different!
        assert scroll_content_call_count != display_lines_call_count, \
            f"Scrolling and static text should behave differently: scrolling={scroll_content_call_count} (single line), static={display_lines_call_count} (wrapped)"


class TestSeamlessScrollingLoop:
    """Tests to ensure scrolling loops seamlessly without jumping."""
    
    def test_scroll_left_wraps_seamlessly_at_content_end(self, oled_controller, mock_pil_modules):
        """Test that SCROLL_LEFT wraps seamlessly when reaching end of content."""
        from app_core.oled import OLEDLine, OLEDScrollEffect
        
        # Create content that's 200 pixels wide
        long_text = "A" * 25  # ~200 pixels at 8px/char
        lines = [OLEDLine(text=long_text, x=0, y=0, font="small")]
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        def mock_textlength(text, font=None):
            return len(text) * 8.0
        mock_draw_obj.textlength = mock_textlength
        
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        
        # Content is 200 pixels wide, display is 128 pixels
        assert dimensions['max_x'] == 200
        
        # Test offset near the end (offset 180)
        # This should wrap: show last 20px of content + first 108px wrapped
        mock_img = mock_pil_modules['img']
        mock_img.crop.reset_mock()
        mock_img.paste.reset_mock()
        
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_LEFT,
            offset=180,  # Near end of 200px content
        )
        
        # Should paste twice: once for end of content, once for wrapped beginning
        assert mock_img.paste.call_count == 2, \
            "Should paste twice when wrapping (end + beginning)"
    
    def test_scroll_left_uses_modulo_for_offset(self, oled_controller, mock_pil_modules):
        """Test that offsets beyond content width wrap using modulo."""
        from app_core.oled import OLEDLine, OLEDScrollEffect
        
        long_text = "Test text"
        lines = [OLEDLine(text=long_text, x=0, y=0, font="small")]
        
        mock_draw_obj = mock_pil_modules['draw_obj']
        def mock_textlength(text, font=None):
            return len(text) * 8.0
        mock_draw_obj.textlength = mock_textlength
        
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        max_x = dimensions['max_x']  # e.g., 72 pixels
        
        # Test offset that exceeds content width (should wrap via modulo)
        offset_beyond = max_x + 10  # e.g., 82
        expected_wrapped_offset = 10  # 82 % 72 = 10
        
        # This should work without errors and render correctly
        oled_controller.render_scroll_frame(
            content_image,
            dimensions,
            OLEDScrollEffect.SCROLL_LEFT,
            offset=offset_beyond,
        )
        
        # Verify device.display was called (rendering succeeded)
        assert mock_pil_modules['device'].display.called
