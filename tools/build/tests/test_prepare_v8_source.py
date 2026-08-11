from __future__ import annotations

import gzip
import importlib.util
import io
import os
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
    @staticmethod
    def _write_archive(path: pathlib.Path, *, gzip_mtime: int) -> None:
        with path.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=gzip_mtime) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    payload = b"stable source contents"
                    member = tarfile.TarInfo("vendor/example/build.rs")
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))

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

    def test_rejects_duplicate_archive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            archive_path = root / "duplicate.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for payload in (b"first", b"second"):
                    member = tarfile.TarInfo("vendor/example/build.rs")
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
            with self.assertRaisesRegex(
                prepare_v8_source.PreparationError, "duplicate archive entry"
            ):
                prepare_v8_source.archive_tree_sha256(archive_path)

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

    def test_tree_hash_ignores_gzip_container_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            self._write_archive(first, gzip_mtime=1)
            self._write_archive(second, gzip_mtime=2)

            self.assertNotEqual(
                prepare_v8_source.sha256_file(first),
                prepare_v8_source.sha256_file(second),
            )
            self.assertEqual(
                prepare_v8_source.archive_tree_sha256(first),
                prepare_v8_source.archive_tree_sha256(second),
            )

    def test_patch_run_bindgen_preserves_inherited_library_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            runner = root.joinpath(*prepare_v8_source.RUN_BINDGEN_PATH.parts)
            runner.parent.mkdir(parents=True)
            runner.write_text(
                "import os\n"
                "import subprocess\n"
                "env = {}\n"
                "args = type('Args', (), {\n"
                "    'ld_library_path': '/chromium/clang',\n"
                "    'libclang_path': '/chromium/libclang',\n"
                "    'bindgen_exe': '/chromium/bindgen',\n"
                "    'rustfmt_exe': '/chromium/rustfmt',\n"
                "})()\n"
                "genargs = []\n"
                "fmtargs = []\n"
                "env[\"LD_LIBRARY_PATH\"] = args.ld_library_path\n"
                "env[\"LIBCLANG_PATH\"] = args.libclang_path\n"
                "subprocess.check_call([args.bindgen_exe, *genargs], env=env)\n"
                "subprocess.check_call([args.rustfmt_exe, *fmtargs])\n",
                encoding="utf-8",
            )

            original_check_call = prepare_v8_source.subprocess.check_call
            calls: list[tuple[list[str], dict[str, object]]] = []
            prepare_v8_source.subprocess.check_call = (
                lambda command, **kwargs: calls.append((command, kwargs))
            )
            previous = {
                name: os.environ.get(name)
                for name in (
                    "LD_LIBRARY_PATH",
                    "YATOU_BINDGEN_EXE",
                    "YATOU_RUSTFMT_EXE",
                    "YATOU_LIBCLANG_PATH",
                    "BINDGEN_EXTRA_CLANG_ARGS",
                    "BINDGEN_EXTRA_CLANG_ARGS_aarch64_unknown_linux_gnu",
                )
            }
            try:
                prepare_v8_source.patch_run_bindgen_library_path(root)
                first = runner.read_text(encoding="utf-8")
                prepare_v8_source.patch_run_bindgen_library_path(root)
                second = runner.read_text(encoding="utf-8")

                self.assertEqual(first, second)
                self.assertIn('os.environ.get("LD_LIBRARY_PATH")', first)
                self.assertIn('os.environ.get("YATOU_BINDGEN_EXE"', first)
                self.assertIn('os.environ.get("YATOU_RUSTFMT_EXE"', first)
                namespace: dict[str, object] = {}
                os.environ["LD_LIBRARY_PATH"] = "/host/lib"
                os.environ["YATOU_BINDGEN_EXE"] = "/host/bindgen"
                os.environ["YATOU_RUSTFMT_EXE"] = "/host/rustfmt"
                os.environ["YATOU_LIBCLANG_PATH"] = "/host/libclang"
                os.environ["BINDGEN_EXTRA_CLANG_ARGS"] = "--target=global"
                os.environ[
                    "BINDGEN_EXTRA_CLANG_ARGS_aarch64_unknown_linux_gnu"
                ] = "--target=aarch64-unknown-linux-gnu"
                exec(first, namespace)
            finally:
                prepare_v8_source.subprocess.check_call = original_check_call
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
            self.assertEqual(
                namespace["env"]["LD_LIBRARY_PATH"],
                os.pathsep.join(("/chromium/clang", "/host/lib")),
            )
            self.assertEqual(namespace["env"]["LIBCLANG_PATH"], "/host/libclang")
            self.assertNotIn("BINDGEN_EXTRA_CLANG_ARGS", namespace["env"])
            self.assertNotIn(
                "BINDGEN_EXTRA_CLANG_ARGS_aarch64_unknown_linux_gnu",
                namespace["env"],
            )
            self.assertEqual(calls[0][0], ["/host/bindgen"])
            self.assertEqual(calls[1][0], ["/host/rustfmt"])

    def test_patch_run_bindgen_rejects_unknown_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            runner = root.joinpath(*prepare_v8_source.RUN_BINDGEN_PATH.parts)
            runner.parent.mkdir(parents=True)
            runner.write_text("# changed upstream\n", encoding="utf-8")
            with self.assertRaisesRegex(
                prepare_v8_source.PreparationError, "no longer matches"
            ):
                prepare_v8_source.patch_run_bindgen_library_path(root)


if __name__ == "__main__":
    unittest.main()
