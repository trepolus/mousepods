# SPDX-License-Identifier: Apache-2.0
"""macOS pointer: cursor maths (pure) and MacPointer driven through a fake CoreGraphics backend."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import macos_pointer as mp  # noqa: E402

LAPTOP = (0, 0, 1512, 982)            # main display, global points
MONITOR = (1512, -98, 1920, 1080)     # external display to the right, top edge higher


class NearestOnDisplaysTests(unittest.TestCase):
    def test_point_in_a_gap_goes_to_the_closest_display(self):
        cases = [
            ("on the laptop stays", (10, 10), (10, 10)),
            ("above the laptop, left of the monitor top", (1400, -50), (1400, 0)),
            ("below the laptop", (700, 1050), (700, 981)),
            ("below the gap, laptop edge is a little closer", (1505, 1050), (1505, 981)),
        ]
        for name, point, want in cases:
            self.assertEqual(mp.nearest_on_displays(point, [LAPTOP, MONITOR]), want, name)


class KeepOnDisplaysTests(unittest.TestCase):
    def test_cursor_stays_on_a_real_display(self):
        cases = [
            ("inside the laptop", (100, 100), (90, 90), (100, 100)),
            ("across to the monitor", (1600, 50), (1500, 50), (1600, 50)),
            ("past the left edge", (-40, 300), (10, 300), (0, 300)),
            ("below the laptop", (700, 2000), (700, 900), (700, 981)),
            ("above the monitor", (2000, -500), (2000, 0), (2000, -98)),
            ("gap under the laptop next to the taller monitor", (1400, 990), (1400, 970), (1400, 981)),
            ("off the far right of the monitor", (4000, 200), (3400, 200), (3431, 200)),
        ]
        for name, target, current, want in cases:
            self.assertEqual(mp.keep_on_displays(target, current, [LAPTOP, MONITOR]), want, name)

    def test_cursor_lost_between_displays_returns_to_the_first(self):
        self.assertEqual(mp.keep_on_displays((5000, 5000), (5000, 4000), [LAPTOP, MONITOR]), (1511, 981))


class CursorMathTests(unittest.TestCase):
    def test_small_moves_add_up_to_whole_pixels(self):
        math = mp.CursorMath()
        steps = [math.relative((100, 100), 0.4, -0.3, [LAPTOP]) for _ in range(3)]
        self.assertEqual(steps, [None, None, mp.RelativeMove((101, 100), (1, 0))])
        self.assertEqual(math.relative((101, 100), 0.0, -0.2, [LAPTOP]), mp.RelativeMove((101, 99), (0, -1)))

    def test_delta_is_the_intended_move_even_at_the_screen_edge(self):
        # Games under pointer lock keep turning although the hidden cursor cannot go further.
        move = mp.CursorMath().relative((1511, 500), 30, 0, [LAPTOP])
        self.assertEqual(move, mp.RelativeMove((1511, 500), (30, 0)))

    def test_absolute_spans_all_displays_as_one_canvas(self):
        # Canvas = bounding box of laptop + monitor: x 0..3431, y -98..981.
        cases = [
            ("top left of the canvas is above the laptop, nearest is its top left", 0.0, 0.0, (0, 0)),
            ("bottom right of the canvas is below the monitor, nearest is its bottom", 1.0, 1.0, (3431, 981)),
            ("left third lands on the laptop", 0.2, 0.5, (686, 442)),
            ("right half lands on the monitor", 0.75, 0.2, (2573, 118)),
            ("top right corner of the monitor", 1.0, 0.0, (3431, -98)),
            ("beyond the edge is clamped", 1.4, -0.2, (3431, -98)),
        ]
        for name, fx, fy, want in cases:
            self.assertEqual(mp.CursorMath().absolute(fx, fy, [LAPTOP, MONITOR]), want, name)

    def test_absolute_on_a_single_display_uses_its_pixels(self):
        self.assertEqual(mp.CursorMath().absolute(0.5, 0.5, [LAPTOP]), (756, 490))
        self.assertEqual(mp.CursorMath().absolute(1.0, 1.0, [LAPTOP]), (1511, 981))

    def test_absolute_skips_repeats(self):
        math = mp.CursorMath()
        self.assertEqual(math.absolute(0.5, 0.5, [LAPTOP]), (756, 490))
        self.assertIsNone(math.absolute(0.5, 0.5, [LAPTOP]))

    def test_scroll_sends_whole_lines_only(self):
        s = mp.ScrollMath()
        self.assertEqual([s.lines(v) for v in (0.6, 0.6, -2.5, 0.3)], [0, 1, -2, 0])


class CursorHistoryTests(unittest.TestCase):
    def test_position_at_an_earlier_time(self):
        h = mp.CursorHistory(keep_s=1.0)
        for t, point in ((10.0, (100, 100)), (10.2, (110, 100)), (10.4, (130, 105)), (10.6, (160, 120))):
            h.record(t, point)
        cases = [
            ("exactly a recorded time", 10.2, (110, 100)),
            ("between records takes the earlier one", 10.5, (130, 105)),
            ("before the oldest record takes the oldest", 9.0, (100, 100)),
            ("after the newest takes the newest", 11.0, (160, 120)),
        ]
        for name, t, want in cases:
            self.assertEqual(h.at(t), want, name)

    def test_old_positions_are_forgotten(self):
        h = mp.CursorHistory(keep_s=1.0)
        h.record(0.0, (1, 1))
        h.record(5.0, (2, 2))
        self.assertEqual(h.at(0.0), (2, 2))

    def test_empty_history_knows_nothing(self):
        self.assertIsNone(mp.CursorHistory().at(1.0))


class FakeCoreGraphics:
    def __init__(self, trusted=True, cursor=(100, 100)):
        self.calls = []
        self._trusted = trusted
        self.position = cursor

    def trusted(self):
        return self._trusted

    def cursor(self):
        return self.position

    screens = [LAPTOP, MONITOR]

    def displays(self):
        return list(self.screens)

    deltas = None

    def move(self, point, delta=(0, 0)):
        self.calls.append(("move", point))
        self.deltas = (self.deltas or []) + [delta]
        self.position = point

    def button(self, button, down, point):
        self.calls.append(("button", button, down, point))

    def drag(self, point, button, delta=(0, 0)):
        self.calls.append(("drag", button, point))
        self.deltas = (self.deltas or []) + [delta]
        self.position = point

    def scroll(self, lines):
        self.calls.append(("scroll", lines))


class MacPointerTests(unittest.TestCase):
    def test_relative_moves_start_from_the_real_cursor(self):
        cg = FakeCoreGraphics(cursor=(300, 200))
        p = mp.MacPointer(backend=cg, sleep=lambda s: None)
        p.move_rel(5.5, -2)
        p.move_rel(0.6, 0)
        self.assertEqual(cg.calls, [("move", (305, 198)), ("move", (306, 198))])

    def test_rewound_click_lands_where_the_cursor_was_before_the_jolt(self):
        cg = FakeCoreGraphics(cursor=(300, 200))
        now = [0.0]
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: now[0])
        for t, dx in ((0.1, 10), (0.2, 10), (0.6, 40), (0.7, 40)):    # aim, then the press jolts the head
            now[0] = t
            p.move_rel(dx, 0)
        now[0] = 0.8
        p.click("left", rewind_s=0.5)
        self.assertEqual(cg.calls[-3:], [("move", (320, 200)), ("button", "left", True, (320, 200)),
                                         ("button", "left", False, (320, 200))])

    def test_click_without_rewind_stays_put(self):
        cg = FakeCoreGraphics(cursor=(300, 200))
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: 1.0)
        p.move_rel(10, 0)
        p.click("left")
        self.assertEqual(cg.calls[-2:], [("button", "left", True, (310, 200)), ("button", "left", False, (310, 200))])

    def test_moves_while_a_button_is_held_are_drags(self):
        cg = FakeCoreGraphics(cursor=(100, 100))
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: 1.0)
        p.press("left")
        p.move_rel(5, 0)
        p.release("left")
        p.move_rel(5, 0)
        self.assertEqual(cg.calls, [("button", "left", True, (100, 100)), ("drag", "left", (105, 100)),
                                    ("button", "left", False, (105, 100)), ("move", (110, 100))])

    def test_press_twice_and_release_unpressed_are_ignored(self):
        cg = FakeCoreGraphics(cursor=(1, 1))
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: 1.0)
        p.release("left")
        p.press("left")
        p.press("left")
        self.assertEqual(cg.calls, [("button", "left", True, (1, 1))])

    def test_release_all_lets_go_of_every_held_button(self):
        cg = FakeCoreGraphics(cursor=(1, 1))
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: 1.0)
        p.press("left")
        p.release_all()
        p.release_all()
        self.assertEqual(cg.calls, [("button", "left", True, (1, 1)), ("button", "left", False, (1, 1))])

    def test_every_move_carries_its_delta_for_pointer_lock(self):
        cg = FakeCoreGraphics(cursor=(300, 200))
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: 1.0)
        p.move_rel(5, -3)
        cg.position = (300, 200)             # pointer lock: the hidden cursor stays where it is
        p.move_rel(4, 0)
        p.press("left")
        p.move_rel(0, 2)
        self.assertEqual(cg.deltas, [(5, -3), (4, 0), (0, 2)])

    def test_pointer_mode_delta_is_the_jump(self):
        cg = FakeCoreGraphics(cursor=(100, 100))
        mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: 1.0).move_abs(0.0, 0.0)
        self.assertEqual(cg.deltas, [(-100, -100)])

    def test_click_presses_and_releases_where_the_cursor_is(self):
        cg = FakeCoreGraphics(cursor=(42, 24))
        mp.MacPointer(backend=cg, sleep=lambda s: None).click("right")
        self.assertEqual(cg.calls, [("button", "right", True, (42, 24)), ("button", "right", False, (42, 24))])

    def test_pointer_mode_spans_both_displays(self):
        cg = FakeCoreGraphics()
        mp.MacPointer(backend=cg, sleep=lambda s: None).move_abs(1.0, 0.0)
        self.assertEqual(cg.calls, [("move", (3431, -98))])

    def test_plugged_in_monitor_is_used_within_a_second(self):
        cg = FakeCoreGraphics()
        cg.screens = [LAPTOP]
        now = [0.0]
        p = mp.MacPointer(backend=cg, sleep=lambda s: None, clock=lambda: now[0])
        p.move_abs(1.0, 0.0)
        cg.screens = [LAPTOP, MONITOR]
        now[0] = 0.5
        p.move_abs(0.99, 0.0)
        now[0] = 1.1
        p.move_abs(1.0, 0.0)
        self.assertEqual(cg.calls, [("move", (1511, 0)), ("move", (1496, 0)), ("move", (3431, -98))])

    def test_missing_accessibility_permission_is_reported(self):
        with self.assertLogs("macos_pointer", level="WARNING") as logs:
            mp.MacPointer(backend=FakeCoreGraphics(trusted=False), sleep=lambda s: None)
        self.assertIn("Accessibility", logs.output[0])


class ControllerClickTests(unittest.TestCase):
    def controller(self):
        import airpods_mouse_controller as m

        class RecordingPointer:
            def __init__(self):
                self.clicks = []

            def click(self, button="left", **kwargs):
                self.clicks.append((button, kwargs))

            def __getattr__(self, name):
                return lambda *a, **k: None

        cfg = m.load_config("/nonexistent.json")
        cfg.update(notifications=False, mouse_paused=False)
        ptr = RecordingPointer()
        return m.Controller(cfg, ptr), ptr

    def test_stem_click_passes_the_rewind_to_the_pointer(self):
        ctl, ptr = self.controller()
        ctl.click("left", rewind_s=0.5)
        self.assertEqual(ptr.clicks, [("left", {"rewind_s": 0.5})])

    def test_command_click_does_not_rewind(self):
        ctl, ptr = self.controller()
        ctl.command("right_click")
        self.assertEqual(ptr.clicks, [("right", {})])

    def test_no_click_while_paused(self):
        ctl, ptr = self.controller()
        ctl.set_paused(True)
        ctl.click("left", rewind_s=0.5)
        self.assertEqual(ptr.clicks, [])


@unittest.skipUnless(sys.platform == "darwin", "CoreGraphics only exists on macOS")
class CoreGraphicsBindingTests(unittest.TestCase):
    def test_bindings_load_and_read_the_screen(self):
        cg = mp.CoreGraphics()
        displays = cg.displays()
        self.assertTrue(displays)
        self.assertTrue(all(w > 0 and h > 0 for _, _, w, h in displays))
        self.assertIsInstance(cg.trusted(), bool)
        self.assertEqual(len(cg.cursor()), 2)


if __name__ == "__main__":
    unittest.main()
