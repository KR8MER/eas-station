"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Regression tests for two VFD rendering bugs found while auditing why the
VFD screens looked so much plainer than the OLED ones:

1. Every text element on a custom VFD screen called
   NoritakeVFDController.draw_text() with its arguments in the wrong order
   -- (text, x, y) instead of the real (x, y, text) signature.

2. Both VFD render paths called vfd_controller.clear_display(), a method
   that does not exist on NoritakeVFDController (the real method is
   clear_screen()) -- an AttributeError on the very first VFD command of
   every render. This is the bigger of the two: custom VFD screens were
   failing completely, not just rendering with garbled text.

Both call sites (scripts/screen_manager.py's _display_vfd_screen() and
scripts/screen_manager_gated.py's push_vfd_pending_scene()) have since been
rewritten to render a whole frame through
scripts.vfd_controller.render_vfd_elements() + NoritakeVFDController.
render_frame() (one bitmap push instead of one GU-7000 command per
primitive -- see tests/test_vfd_render_elements.py for that engine's own
coverage, including a dedicated invert-text/invert-icon regression test for
bug #1's underlying "text drawn white-on-white" failure mode). Neither call
site invokes draw_text() or clear_screen() directly anymore, so the specific
buggy call shapes are now structurally impossible to reintroduce there --
what's pinned here is that the real API surface stays what these rewrites
depend on.
"""

from pathlib import Path

SCREEN_MANAGER = Path(__file__).resolve().parents[1] / "scripts" / "screen_manager.py"
SCREEN_MANAGER_GATED = Path(__file__).resolve().parents[1] / "scripts" / "screen_manager_gated.py"
VFD_CONTROLLER = Path(__file__).resolve().parents[1] / "scripts" / "vfd_controller.py"


def test_noritake_vfd_controller_has_no_clear_display_method():
    """Confirms the real method name -- if this ever fails, clear_screen()
    was renamed to clear_display() and render_frame() (which calls
    self.clear_screen() internally) should follow."""
    source = VFD_CONTROLLER.read_text(encoding="utf-8")
    assert "def clear_screen(self)" in source
    assert "def clear_display(self)" not in source


def test_noritake_vfd_controller_has_no_draw_text_arg_order_regression():
    """draw_text()'s signature must stay (x, y, text); render_vfd_elements()
    calls draw.text() (Pillow, not this method) so this only matters for
    direct callers like screen_manager_gated.py's simpler paths, if any
    reappear."""
    source = VFD_CONTROLLER.read_text(encoding="utf-8")
    assert "def draw_text(self, x: int, y: int, text: str)" in source


def test_display_vfd_screen_delegates_to_render_frame():
    """_display_vfd_screen() must render through the bitmap engine, not
    hand-roll GU-7000 commands (the code path the original bugs lived in)."""
    source = SCREEN_MANAGER.read_text(encoding="utf-8")
    start = source.index("def _display_vfd_screen")
    end = source.index("\n    def ", start + 1)
    method_source = source[start:end]

    assert "vfd_controller.render_frame(" in method_source
    assert "vfd_controller.draw_text(" not in method_source
    assert "vfd_controller.clear_screen(" not in method_source
    assert "vfd_controller.clear_display(" not in method_source


def test_push_vfd_pending_scene_delegates_to_render_frame():
    source = SCREEN_MANAGER_GATED.read_text(encoding="utf-8")
    start = source.index("def push_vfd_pending_scene")
    try:
        end = source.index("\ndef ", start + 1)
    except ValueError:
        end = len(source)  # last function in the file
    fn_source = source[start:end]

    assert "vfd_controller.render_frame(" in fn_source
    assert "vfd_controller.draw_text(" not in fn_source
    assert "vfd_controller.clear_screen(" not in fn_source
    assert "vfd_controller.clear_display(" not in fn_source
