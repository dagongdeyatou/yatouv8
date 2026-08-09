from __future__ import annotations

import importlib.util
import io
import pathlib
import tarfile
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "prepare_v8_source.py"
SPEC = importlib.util.spec_from_file_location("prepare_v8_source", MODULE_PATH)
assert SPEC and SPEC.loader
prepare_v8_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_v8_source)


class PrepareV8SourceTests(unittest.TestCase):
    def test_locates_exact_v8_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cargo_home = pathlib.Path(temporary)
            expected = cargo_home / "registry" / "src" / "index" / "v8-150.4.0"
            expected.mkdir(parents=True)
            (expected.parent / "v8-149.0.0").mkdir()
            self.assertEqual(
                prepare_v8_source.locate_v8_root(cargo_home), expected.resolve()
            )

    def test_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            archive_path = root / "unsafe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                payload = b"escape"
                member = tarfile.TarInfo("../escape.txt")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            with self.assertRaisesRegex(
                prepare_v8_source.PreparationError, "unsafe archive path"
            ):
                prepare_v8_source._extract_verified_archive(
                    archive_path, root / "output"
                )
            self.assertFalse((root / "escape.txt").exists())

    def test_extracts_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            archive_path = root / "safe.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                payload = b"ok"
                member = tarfile.TarInfo("vendor/example/build.rs")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            output = root / "output"
            prepare_v8_source._extract_verified_archive(archive_path, output)
            self.assertEqual((output / "vendor/example/build.rs").read_bytes(), b"ok")


if __name__ == "__main__":
    unittest.main()
