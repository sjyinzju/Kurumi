import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kurumi.paths import load_paths


class PathsTest(unittest.TestCase):
    def test_reject_external_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "paths.toml"
            config.write_text(
                f"quant_project = '{root / 'quant'}'\ndata_root = '{root / 'data'}'\n"
                f"output_dir = '{root / 'data' / 'reports'}'\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_paths(config)

    def test_explicit_workspace_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "paths.toml"
            config.write_text(
                f"quant_project = '{root / 'quant'}'\ndata_root = '{root / 'data'}'\n"
                f"output_dir = '{root / 'out'}'\n", encoding="utf-8"
            )
            self.assertEqual(load_paths(config)["output_dir"], root / "out")
