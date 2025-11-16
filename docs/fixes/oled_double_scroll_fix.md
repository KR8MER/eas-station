# OLED Double Scrolling Fix Documentation

## Problem Description

The OLED display was showing a "double scrolling" effect where text appeared to be duplicated and scrolling in two places simultaneously.

## Root Cause

The `prepare_scroll_content()` method in `app_core/oled.py` creates a padded buffer for seamless scrolling with this structure:

```
[text][separator][text]
```

For smooth scrolling, the text is rendered twice - once at the beginning and once after the separator. As the display window scrolls through this buffer, it creates a seamless looping effect.

However, when the text was **shorter than the display width (128px)**, the display window could show parts of BOTH text copies simultaneously, creating the double-text visual glitch.

### Example (BUGGY behavior):

```
Display width: 128px
Text width: 80px
Separator width: 50px

Buffer: [Text(80px)][Sep(50px)][Text(80px)] = 210px total

At offset=0:
Display window: [0-128]
Shows: First text (0-80) + Separator (80-130)
       └─ First text visible ✓
                               └─ Part of separator visible
                                  
At offset=50:  
Display window: [50-178]
Shows: End of first text (50-80) + Separator (80-130) + Start of second text (130-178)
                └─ First text visible ✓
                                       └─ Second text visible ✓
                                          ❌ BOTH TEXTS VISIBLE! DOUBLE SCROLLING BUG!
```

## Solution

Ensure the padding (separator + extra space) is **at least equal to the display width (128px)**. This guarantees that both text copies can never appear in the same 128px window.

### Implementation:

```python
# OLD CODE (buggy):
separator_width = int(temp_draw.textlength(separator, font=separator_font))  # e.g., 50px
# Buffer: [text][sep(50px)][text]

# NEW CODE (fixed):
separator_width = int(temp_draw.textlength(separator, font=separator_font))  # e.g., 50px
min_separator_and_padding = max(separator_width, self.width)  # e.g., max(50, 128) = 128px
# Buffer: [text][padding(128px with centered separator)][text]
```

### Example (FIXED behavior):

```
Display width: 128px
Text width: 80px
Min padding: 128px (max of separator width and display width)

Buffer: [Text(80px)][Padding(128px)][Text(80px)] = 288px total

At offset=0:
Display window: [0-128]
Shows: First text (0-80) + Padding (80-128)
       └─ Only first text visible ✓

At offset=80:
Display window: [80-208]  
Shows: End of padding (80-208)
       └─ No text visible, just padding/separator

At offset=208:
Display window: [208-336]
Shows: Start of second text (208-288) + empty space
       └─ Only second text visible ✓

Loop resets to offset=0, creating seamless scrolling without overlap!
```

## Verification

Created comprehensive tests in `tests/test_oled_double_scroll_fix.py` that verify:

1. ✅ Padding is at least display_width to prevent double text visibility
2. ✅ Seamless loop works correctly with various text widths
3. ✅ At no offset can both text copies be visible simultaneously

## Result

- **Before fix**: Text could appear duplicated when scrolling (double scrolling glitch)
- **After fix**: Only ONE text copy is visible at any given time (smooth, seamless scrolling)

## Files Modified

1. `app_core/oled.py` - Fixed `prepare_scroll_content()` method
   - Line 317: Calculate `min_separator_and_padding = max(separator_width, self.width)`
   - Line 335: Center separator within the padding area
   - Line 340: Use `min_separator_and_padding` for second text offset
   - Line 347: Return `min_separator_and_padding` as `separator_width` for loop calculations

2. `tests/test_oled_double_scroll_fix.py` - New comprehensive tests

## Impact

- Fixes visual glitch on OLED displays
- Maintains seamless scrolling behavior  
- No performance impact (pre-rendering approach unchanged)
- Works correctly for all text widths (short and long)
