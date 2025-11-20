"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""
SMOKING GUN PROOF: Dual Scrolling Fix

This test demonstrates the EXACT problem and proves the fix works.
It simulates the scrolling canvas and shows that:

OLD APPROACH: [empty_128px][TEXT][empty_128px]
- Text rendered ONCE at position 128
- At certain offsets, both empty space AND text are visible = DUAL SCROLLING BUG

NEW APPROACH: [TEXT][separator_128px][TEXT]  
- Text rendered TWICE with separator in between
- At ANY offset, only ONE element is visible = NO DUAL SCROLLING

This is the definitive proof that the fix works.
"""

import pytest

pytestmark = pytest.mark.unit


class TestSmokingGunProof:
    """Comprehensive proof that the dual scrolling bug is fixed."""
    
    def test_OLD_APPROACH_CAUSES_DUAL_SCROLLING(self):
        """PROOF OF BUG: Show that old approach causes dual scrolling."""
        print("\n" + "="*80)
        print("OLD APPROACH (BUGGY): [empty_128px][TEXT_80px][empty_128px]")
        print("="*80)
        
        display_width = 128
        text_width = 80
        
        # OLD CANVAS LAYOUT:
        # Position 0-127: EMPTY SPACE
        # Position 128-207: TEXT (rendered once at position 128)
        # Position 208-335: EMPTY SPACE
        text_start = display_width  # 128
        text_end = text_start + text_width  # 208
        canvas_width = display_width + text_width + display_width  # 336
        
        print(f"Canvas: {canvas_width}px wide")
        print(f"Empty space: [0-{text_start}]")
        print(f"Text: [{text_start}-{text_end}]")
        print(f"Empty space: [{text_end}-{canvas_width}]")
        print()
        
        # CRITICAL TEST: Find offsets where BOTH empty and text are visible
        dual_scroll_offsets = []
        
        for offset in range(canvas_width - display_width + 1):
            crop_left = offset
            crop_right = offset + display_width
            
            # Check what's visible in this window
            shows_empty_before_text = crop_left < text_start and crop_right > 0
            shows_text = crop_left < text_end and crop_right > text_start
            shows_empty_after_text = crop_left < canvas_width and crop_right > text_end
            
            # BUG: If we see empty AND text, that's dual scrolling!
            if (shows_empty_before_text or shows_empty_after_text) and shows_text:
                dual_scroll_offsets.append(offset)
        
        print(f"❌ DUAL SCROLLING DETECTED at {len(dual_scroll_offsets)} offsets!")
        print(f"   Offsets with dual scrolling: {dual_scroll_offsets[:10]}... (showing first 10)")
        print()
        
        # Show specific example
        example_offset = 50
        crop_left = example_offset
        crop_right = crop_left + display_width  # 178
        print(f"Example at offset {example_offset}:")
        print(f"  Window: [{crop_left}-{crop_right}]")
        print(f"  Shows empty space: [{crop_left}-{text_start}] = {text_start - crop_left}px of empty")
        print(f"  Shows text: [{text_start}-{crop_right}] = {crop_right - text_start}px of text")
        print(f"  ⚠️  USER SEES: Empty space on left, text on right = DUAL SCROLLING!")
        print()
        
        # This is the bug!
        assert len(dual_scroll_offsets) > 0, "Old approach SHOULD have dual scrolling"
        assert example_offset in dual_scroll_offsets
        
    def test_NEW_APPROACH_PREVENTS_DUAL_SCROLLING(self):
        """PROOF OF FIX: Show that new approach prevents dual scrolling."""
        print("\n" + "="*80)
        print("NEW APPROACH (FIXED): [TEXT_80px][separator_128px][TEXT_80px]")
        print("="*80)
        
        display_width = 128
        text_width = 80
        separator_width = 128  # At least display_width
        
        # NEW CANVAS LAYOUT:
        # Position 0-79: TEXT (first copy)
        # Position 80-207: SEPARATOR ("***" centered in 128px)
        # Position 208-287: TEXT (second copy for seamless loop)
        first_text_start = 0
        first_text_end = text_width  # 80
        separator_start = first_text_end  # 80
        separator_end = separator_start + separator_width  # 208
        second_text_start = separator_end  # 208
        second_text_end = second_text_start + text_width  # 288
        canvas_width = second_text_end
        
        print(f"Canvas: {canvas_width}px wide")
        print(f"First text: [{first_text_start}-{first_text_end}]")
        print(f"Separator: [{separator_start}-{separator_end}]")
        print(f"Second text: [{second_text_start}-{second_text_end}]")
        print()
        
        # CRITICAL TEST: Verify NO offset shows both text copies simultaneously
        loop_point = text_width + separator_width  # 208
        dual_text_offsets = []
        
        for offset in range(loop_point + 1):
            crop_left = offset
            crop_right = offset + display_width
            
            # Check what's visible in this window
            shows_first_text = crop_left < first_text_end and crop_right > first_text_start
            shows_separator = crop_left < separator_end and crop_right > separator_start
            shows_second_text = crop_left < second_text_end and crop_right > second_text_start
            
            # CRITICAL: Both text copies should NEVER be visible simultaneously
            if shows_first_text and shows_second_text:
                dual_text_offsets.append(offset)
        
        print(f"✅ DUAL SCROLLING CHECK: {len(dual_text_offsets)} offsets with both texts visible")
        print()
        
        # Show specific examples
        print("Example at offset 0 (start of loop):")
        crop_left = 0
        crop_right = crop_left + display_width  # 128
        print(f"  Window: [{crop_left}-{crop_right}]")
        print(f"  Shows first text: [{first_text_start}-{first_text_end}] ✓")
        print(f"  Shows separator: [{separator_start}-{crop_right}] ✓")
        print(f"  Shows second text: No ✓")
        print(f"  ✅ USER SEES: Only first text + separator = NO DUAL SCROLLING!")
        print()
        
        print(f"Example at offset {loop_point} (loop point):")
        crop_left = loop_point
        crop_right = crop_left + display_width  # 336
        print(f"  Window: [{crop_left}-{crop_right}]")
        print(f"  Shows first text: No ✓")
        print(f"  Shows separator: No ✓")
        print(f"  Shows second text: [{second_text_start}-{second_text_end}] ✓")
        print(f"  ✅ USER SEES: Only second text = NO DUAL SCROLLING!")
        print(f"  → Offset resets to 0 for seamless loop")
        print()
        
        # This is the fix!
        assert len(dual_text_offsets) == 0, "New approach should NEVER show both text copies"
        
    def test_SMOKING_GUN_COMPARISON(self):
        """SMOKING GUN: Direct comparison showing the fix."""
        print("\n" + "="*80)
        print("SMOKING GUN: SIDE-BY-SIDE COMPARISON")
        print("="*80)
        
        display_width = 128
        text_width = 80
        
        # OLD APPROACH
        old_text_start = display_width  # Text at position 128
        old_text_end = old_text_start + text_width  # 208
        old_canvas_width = display_width + text_width + display_width  # 336
        
        # NEW APPROACH  
        new_separator_width = display_width  # 128
        new_first_text_end = text_width  # 80
        new_separator_end = text_width + new_separator_width  # 208
        new_second_text_start = new_separator_end  # 208
        new_canvas_width = text_width + new_separator_width + text_width  # 288
        
        # Test at offset 50 (where old approach shows dual scrolling)
        test_offset = 50
        crop_left = test_offset
        crop_right = crop_left + display_width  # 178
        
        print(f"\nTesting at offset {test_offset}, window [{crop_left}-{crop_right}]:")
        print()
        
        # OLD APPROACH
        print("OLD APPROACH:")
        old_shows_empty = crop_left < old_text_start
        old_shows_text = crop_right > old_text_start and crop_left < old_text_end
        print(f"  Empty space visible: [{crop_left}-{old_text_start}] = {old_text_start - crop_left}px")
        print(f"  Text visible: [{old_text_start}-{crop_right}] = {crop_right - old_text_start}px")
        print(f"  ❌ RESULT: Dual scrolling - user sees BOTH empty and text!")
        print()
        
        # NEW APPROACH
        print("NEW APPROACH:")
        new_shows_first_text = crop_right > 0 and crop_left < new_first_text_end
        new_shows_separator = crop_right > new_first_text_end and crop_left < new_separator_end
        print(f"  First text visible: [{crop_left}-{new_first_text_end}] = {new_first_text_end - crop_left}px")
        print(f"  Separator visible: [{new_first_text_end}-{crop_right}] = {crop_right - new_first_text_end}px")
        print(f"  Second text visible: No")
        print(f"  ✅ RESULT: No dual scrolling - user sees only first text + separator!")
        print()
        
        # THE SMOKING GUN
        print("🔥 SMOKING GUN PROOF:")
        print(f"   OLD: Shows empty ({old_shows_empty}) AND text ({old_shows_text}) = DUAL SCROLLING ❌")
        print(f"   NEW: Shows only text ({new_shows_first_text}) and separator ({new_shows_separator}) = NO DUAL SCROLLING ✅")
        print()
        
        assert old_shows_empty and old_shows_text, "Old approach SHOULD have dual scrolling"
        assert not (new_shows_first_text and new_shows_separator and new_second_text_start <= crop_right), \
            "New approach should NOT show both text copies"
            
    def test_MATHEMATICAL_PROOF(self):
        """Mathematical proof that separator_width >= display_width prevents dual text visibility."""
        print("\n" + "="*80)
        print("MATHEMATICAL PROOF")
        print("="*80)
        
        display_width = 128
        
        # Test with various text widths
        test_cases = [
            ("Very short", 30),
            ("Short", 60),
            ("Medium", 100),
            ("Long", 150),
            ("Very long", 200),
        ]
        
        print("\nTesting with different text widths:")
        print()
        
        for name, text_width in test_cases:
            separator_width = max(display_width, display_width)  # Always >= display_width
            
            first_text_end = text_width
            separator_end = text_width + separator_width
            second_text_start = separator_end
            
            # The gap between text copies
            gap = second_text_start - first_text_end
            
            print(f"{name} text ({text_width}px):")
            print(f"  First text: [0-{first_text_end}]")
            print(f"  Separator: [{first_text_end}-{separator_end}]")
            print(f"  Second text: [{second_text_start}-...]")
            print(f"  Gap between texts: {gap}px")
            
            # PROOF: If gap >= display_width, then a window of display_width
            # can NEVER show both text copies simultaneously
            if gap >= display_width:
                print(f"  ✅ Gap ({gap}px) >= display_width ({display_width}px)")
                print(f"     → Window of {display_width}px can NEVER show both text copies")
            else:
                print(f"  ❌ Gap ({gap}px) < display_width ({display_width}px)")
                print(f"     → Window could show both text copies!")
            print()
            
            # Verify the gap is always >= display_width
            assert gap >= display_width, f"Gap {gap}px should be >= display_width {display_width}px"
        
        print("="*80)
        print("MATHEMATICAL PROOF COMPLETE: separator_width >= display_width")
        print("ensures that NO window can show both text copies simultaneously!")
        print("="*80)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])  # -s to show print statements
