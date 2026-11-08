# SPDX-License-Identifier: Apache-2.0
"""--ui opens the app in a browser: Chromium-style app window when available, else the system opener."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import airpods_mouse_controller as m  # noqa: E402


def opened_with(platform):
    with mock.patch.object(m.sys, "platform", platform), \
            mock.patch.object(m.shutil, "which", return_value=None), \
            mock.patch("urllib.request.urlopen", return_value=None), \
            mock.patch.object(m.subprocess, "Popen") as popen:
        m.open_ui(8737, "/nonexistent.json")
    return popen.call_args.args[0]


class OpenUiTests(unittest.TestCase):
    def test_macos_opens_the_default_browser(self):
        self.assertEqual(opened_with("darwin"), ["open", "http://127.0.0.1:8737/"])

    def test_linux_without_chromium_uses_xdg_open(self):
        self.assertEqual(opened_with("linux"), ["xdg-open", "http://127.0.0.1:8737/"])


if __name__ == "__main__":
    unittest.main()
