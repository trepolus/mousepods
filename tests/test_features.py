# SPDX-License-Identifier: Apache-2.0
"""`mousepods on|off <feature>` and `mousepods status`: parsing, config updates and the status table."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import airpods_mouse_controller as m  # noqa: E402
import features as f  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_commands_are_recognised(self):
        cases = [
            (["on", "hands"], f.Toggle(True, ("hands",))),
            (["off", "dwell", "tilt"], f.Toggle(False, ("dwell", "tilt"))),
            (["status"], f.Status()),
            (["menu"], f.Menu()),
        ]
        for argv, want in cases:
            self.assertEqual(f.parse(argv), want, argv)

    def test_short_commands_go_to_the_running_controller(self):
        for word in ("pause", "resume", "toggle", "recenter", "quit"):
            self.assertEqual(f.parse([word]), f.Send(word), word)

    def test_other_arguments_are_left_to_the_normal_options(self):
        for argv in ([], ["--diag"], ["-h"], ["--send", "pause"]):
            self.assertIsNone(f.parse(argv), argv)

    def test_mistakes_say_what_is_valid(self):
        for argv in (["on"], ["off", "teleport"], ["on", "hands", "laser"]):
            result = f.parse(argv)
            self.assertIsInstance(result, f.Invalid, argv)
            self.assertIn("hands", result.message, argv)


class UpdateTests(unittest.TestCase):
    def test_each_feature_switches_its_own_setting(self):
        cases = [
            ("hands", {"hands": {"enabled": True}}),
            ("stem", {"stem": {"enabled": True}}),
            ("dwell", {"dwell_click": {"enabled": True}}),
            ("tilt", {"roll_click": {"enabled": True}}),
        ]
        for name, want in cases:
            self.assertEqual(f.config_updates(f.Toggle(True, (name,))), want, name)

    def test_several_features_at_once(self):
        self.assertEqual(f.config_updates(f.Toggle(False, ("dwell", "tilt"))),
                         {"dwell_click": {"enabled": False}, "roll_click": {"enabled": False}})

    def test_every_feature_points_at_a_real_setting(self):
        for name, feature in f.FEATURES.items():
            section, key = feature.path
            self.assertIn(key, m.DEFAULTS[section], name)


class StatusTests(unittest.TestCase):
    def test_status_lists_every_feature_and_the_mouse(self):
        cfg = m.load_config("/nonexistent.json")
        cfg["dwell_click"]["enabled"] = True
        cfg["mouse_paused"] = True
        lines = f.status_lines(cfg)
        self.assertEqual([line.split()[0] for line in lines], ["hands", "stem", "dwell", "tilt", "mouse", "mode"])
        self.assertIn("on", lines[2].split()[1])
        self.assertEqual(lines[4].split()[1], "paused")
        self.assertEqual(lines[0].split()[1], "off")


class MenuTests(unittest.TestCase):
    def cfg(self, **over):
        cfg = m.load_config("/nonexistent.json")
        cfg.update(over)
        return cfg

    def test_menu_lists_mouse_features_mode_and_recenter(self):
        rows = f.menu_rows(self.cfg(mouse_paused=False))
        self.assertEqual([r.key for r in rows], ["mouse", "hands", "stem", "dwell", "tilt", "mode", "recenter"])
        self.assertEqual(rows[0].state, "on")
        self.assertEqual(rows[5].state, "souris")

    def test_enter_does_the_right_thing_for_each_row(self):
        cfg = self.cfg(mouse_paused=False)
        cases = [
            ("mouse while running is paused live", "mouse", True, f.Send("toggle")),
            ("mouse while stopped is remembered", "mouse", False, f.ConfigUpdate({"mouse_paused": True})),
            ("feature flips its setting", "hands", True, f.ConfigUpdate({"hands": {"enabled": True}})),
            ("stem on turns off", "stem", True, f.ConfigUpdate({"stem": {"enabled": False}})),
            ("mode goes to pointer", "mode", True, f.ConfigUpdate({"mode": "pointeur"})),
            ("recenter while running", "recenter", True, f.Send("recenter")),
            ("recenter while stopped does nothing", "recenter", False, None),
        ]
        for name, key, running, want in cases:
            self.assertEqual(f.activate(key, cfg, running), want, name)

    def test_mode_from_pointer_or_glide_goes_back_to_mouse(self):
        for mode in ("pointeur", "glisse"):
            self.assertEqual(f.activate("mode", self.cfg(mode=mode), True), f.ConfigUpdate({"mode": "souris"}), mode)


if __name__ == "__main__":
    unittest.main()
