from __future__ import annotations

import importlib.util
import pathlib
import struct
import tempfile
import unittest
import zipfile


MODULE_PATH = pathlib.Path(__file__).parents[1] / "verify_release_set.py"
SPEC = importlib.util.spec_from_file_location("verify_release_set", MODULE_PATH)
assert SPEC and SPEC.loader
release_set = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_set)


class VerifyReleaseSetTests(unittest.TestCase):
    @staticmethod
    def _native(operating_system: str, arch: str) -> tuple[str, bytes]:
        if operating_system == "windows":
            payload = bytearray(128)
            payload[:2] = b"MZ"
            struct.pack_into("<I", payload, 0x3C, 0x40)
            payload[0x40:0x44] = b"PE\0\0"
            struct.pack_into("<H", payload, 0x44, 0xAA64 if arch == "aarch64" else 0x8664)
            return "yatouv8/_native.pyd", bytes(payload)
        if operating_system == "macos":
            payload = bytearray(32)
            payload[:4] = b"\xcf\xfa\xed\xfe"
            struct.pack_into(
                "<I", payload, 4, 0x0100000C if arch == "aarch64" else 0x01000007
            )
            return "yatouv8/_native.so", bytes(payload)
        payload = bytearray(64)
        payload[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", payload, 18, 183 if arch == "aarch64" else 62)
        return "yatouv8/_native.so", bytes(payload)

    def _complete_dist(self, root: pathlib.Path) -> None:
        matrix = release_set.wheel_matrix.load_matrix()
        for target in matrix["targets"]:
            native_name, native = self._native(target["os"], target["arch"])
            for version in matrix["python_versions"]:
                tag = release_set.wheel_matrix.python_tag(version)
                filename = (
                    f"yatouv8-0.1.1-{tag}-{tag}-{target['platform_tag']}.whl"
                )
                with zipfile.ZipFile(root / filename, "w") as archive:
                    archive.writestr(native_name, native)
                    archive.writestr(
                        "yatouv8-0.1.1.dist-info/licenses/LICENSE", "license"
                    )
                    archive.writestr(
                        "yatouv8-0.1.1.dist-info/licenses/NOTICE", "notice"
                    )
                    archive.writestr(
                        "yatouv8-0.1.1.dist-info/WHEEL",
                        f"Wheel-Version: 1.0\nTag: {tag}-{tag}-{target['platform_tag']}\n",
                    )

    def test_tag_must_match_all_version_declarations(self) -> None:
        report = release_set.verify_tag("v0.1.1")
        self.assertTrue(report["accepted"])
        with self.assertRaisesRegex(release_set.ReleaseSetError, "must equal"):
            release_set.verify_tag("v0.1.0")

    def test_complete_release_contains_exactly_40_wheels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            self._complete_dist(root)
            report = release_set.verify_dist(root)
            self.assertTrue(report["accepted"])
            self.assertEqual(report["wheel_count"], 40)

    def test_release_rejects_an_extra_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            self._complete_dist(root)
            (root / "other-0.1.1-py3-none-any.whl").write_bytes(b"not a wheel")
            with self.assertRaisesRegex(release_set.ReleaseSetError, "exactly 40"):
                release_set.verify_dist(root)


if __name__ == "__main__":
    unittest.main()
