from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "build" / "python_windows_arm64_assets.py"
SPEC = importlib.util.spec_from_file_location("python_windows_arm64_assets", MODULE_PATH)
assert SPEC and SPEC.loader
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


class PythonWindowsArm64AssetTests(unittest.TestCase):
    def test_manifest_locks_native_cpython_310_arm64_and_pip(self) -> None:
        document = assets.load_manifest()
        self.assertEqual(document["runtime"]["version"], "3.10.2")
        self.assertEqual(document["runtime"]["architecture"], "arm64")
        self.assertEqual(document["pip"]["version"], "26.2.1")

    def test_rejects_non_arm64_runtime(self) -> None:
        document = json.loads(assets.ASSET_MANIFEST.read_text(encoding="utf-8"))
        document["runtime"]["architecture"] = "x86_64"
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "assets.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(assets.AssetError, "native Windows ARM64"):
                assets.load_manifest(path)

    def test_rejects_unlocked_runtime_url(self) -> None:
        document = json.loads(assets.ASSET_MANIFEST.read_text(encoding="utf-8"))
        document["runtime"]["url"] = "https://example.invalid/python.zip"
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "assets.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(assets.AssetError, "locked python.org"):
                assets.load_manifest(path)


if __name__ == "__main__":
    unittest.main()
