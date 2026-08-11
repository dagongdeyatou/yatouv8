from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools" / "build" / "wheel_matrix.py"
SPEC = importlib.util.spec_from_file_location("wheel_matrix", MODULE_PATH)
assert SPEC and SPEC.loader
wheel_matrix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wheel_matrix)


class WheelMatrixTests(unittest.TestCase):
    @staticmethod
    def _pe(machine: int) -> bytes:
        payload = bytearray(128)
        payload[:2] = b"MZ"
        struct.pack_into("<I", payload, 0x3C, 0x40)
        payload[0x40:0x44] = b"PE\0\0"
        struct.pack_into("<H", payload, 0x44, machine)
        return bytes(payload)

    def test_canonical_matrix_is_complete(self) -> None:
        document = wheel_matrix.load_matrix()
        report = wheel_matrix.validate_matrix(document)
        self.assertEqual(report["target_count"], 8)
        self.assertEqual(report["python_count"], 5)
        self.assertEqual(report["wheel_count"], 40)
        self.assertTrue(report["accepted"])

    def test_github_matrices_cover_every_combination(self) -> None:
        matrices = wheel_matrix.github_matrices(wheel_matrix.load_matrix())
        self.assertEqual(len(matrices["windows_build"]), 10)
        self.assertEqual(len(matrices["windows_test"]), 10)
        self.assertEqual(len(matrices["macos_build"]), 2)
        self.assertEqual(len(matrices["linux_build"]), 4)
        self.assertEqual(len(matrices["linux_test"]), 20)
        self.assertTrue(
            all("@sha256:" in item["build_container"] for item in matrices["linux_build"])
        )

    def test_windows_builds_stay_on_visual_studio_2022(self) -> None:
        matrices = wheel_matrix.github_matrices(wheel_matrix.load_matrix())
        self.assertEqual(
            {item["build_runner"] for item in matrices["windows_build"]},
            {"windows-2022"},
        )
        x64_tests = [
            item
            for item in matrices["windows_test"]
            if item["id"] == "windows-x86_64"
        ]
        self.assertEqual({item["test_runner"] for item in x64_tests}, {"windows-2022"})

    def test_rejects_missing_target(self) -> None:
        document = json.loads(wheel_matrix.DEFAULT_MATRIX.read_text(encoding="utf-8"))
        document["targets"].pop()
        with self.assertRaisesRegex(wheel_matrix.MatrixError, "coverage mismatch"):
            wheel_matrix.validate_matrix(document)

    def test_verify_dist_uses_target_platform_and_python_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dist = pathlib.Path(temporary)
            wheel = dist / "yatouv8-0.1.0-cp310-cp310-win_arm64.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("yatouv8/_native.pyd", self._pe(0xAA64))
                archive.writestr("yatouv8-0.1.0.dist-info/licenses/LICENSE", "license")
                archive.writestr("yatouv8-0.1.0.dist-info/licenses/NOTICE", "notice")
                archive.writestr(
                    "yatouv8-0.1.0.dist-info/WHEEL",
                    "Wheel-Version: 1.0\nTag: cp310-cp310-win_arm64\n",
                )
            report = wheel_matrix.verify_dist(
                wheel_matrix.load_matrix(),
                target_id="windows-arm64",
                dist=dist,
                python_version="3.10",
            )
            self.assertTrue(report["accepted"])
            self.assertEqual(report["verified_count"], 1)


if __name__ == "__main__":
    unittest.main()
