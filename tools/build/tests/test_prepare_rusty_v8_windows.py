from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "build" / "prepare_rusty_v8_windows.py"
SPEC = importlib.util.spec_from_file_location("prepare_rusty_v8_windows", MODULE_PATH)
assert SPEC and SPEC.loader
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


class RustyV8WindowsAssetTests(unittest.TestCase):
    def test_manifest_locks_both_windows_targets(self) -> None:
        document = assets.load_manifest()
        self.assertEqual(document["version"], "150.4.0")
        self.assertEqual(
            set(document["targets"]),
            {"x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"},
        )

    def test_rejects_unlocked_asset_url(self) -> None:
        document = json.loads(assets.ASSET_MANIFEST.read_text(encoding="utf-8"))
        document["targets"]["x86_64-pc-windows-msvc"]["archive"]["url"] = (
            "https://example.invalid/latest/rusty_v8.lib.gz"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "assets.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(assets.AssetError, "not version locked"):
                assets.load_manifest(path)

    def test_cached_asset_must_match_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "asset"
            path.write_bytes(b"verified")
            digest = assets.file_sha256(path)
            self.assertEqual(assets.fetch("unused", path, digest), path)


if __name__ == "__main__":
    unittest.main()
