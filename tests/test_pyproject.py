# SPDX-License-Identifier: Apache-2.0
"""pyproject.toml lists every top-level module, so `uv run --project <repo> mousepods` can import them."""
import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(sys.version_info < (3, 11), "tomllib needs Python 3.11")
class PyprojectTests(unittest.TestCase):
    def test_every_top_level_module_is_packaged(self):
        import tomllib
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            listed = set(tomllib.load(f)["tool"]["setuptools"]["py-modules"])
        on_disk = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "*.py"))}
        self.assertEqual(on_disk - listed, set(), "add these to py-modules in pyproject.toml")

    def test_every_top_level_package_is_packaged(self):
        import tomllib
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            listed = set(tomllib.load(f)["tool"]["setuptools"]["packages"])
        on_disk = {os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(ROOT, "*", "__init__.py"))}
        self.assertEqual(on_disk - listed, set(), "add these to packages in pyproject.toml")


if __name__ == "__main__":
    unittest.main()
