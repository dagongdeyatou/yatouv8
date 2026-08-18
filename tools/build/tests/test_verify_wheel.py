from __future__ import annotations

import importlib.util
import pathlib
import struct
import tempfile
import unittest
import zipfile


MODULE_PATH = pathlib.Path(__file__).parents[1] / "verify_wheel.py"
SPEC = importlib.util.spec_from_file_location("verify_wheel", MODULE_PATH)
assert SPEC and SPEC.loader
verify_wheel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_wheel)


class VerifyWheelTests(unittest.TestCase):
    @staticmethod
    def _elf(machine: int) -> bytes:
        payload = bytearray(64)
        payload[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", payload, 18, machine)
        return bytes(payload)

    def _wheel(
        self,
        root: pathlib.Path,
        platform: str,
        *,
        native: bytes | None = None,
    ) -> pathlib.Path:
        wheel = root / f"yatouv8-0.1.2-cp310-cp310-{platform}.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "yatouv8/_native.so",
                native if native is not None else self._elf(62),
            )
            archive.writestr("yatouv8-0.1.2.dist-info/licenses/LICENSE", "license")
            archive.writestr("yatouv8-0.1.2.dist-info/licenses/NOTICE", "notice")
            archive.writestr(
                "yatouv8-0.1.2.dist-info/WHEEL",
                f"Wheel-Version: 1.0\nTag: cp310-cp310-{platform}\n",
            )
        return wheel

    def test_accepts_matching_manylinux_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = self._wheel(
                pathlib.Path(temporary), "manylinux_2_28_x86_64"
            )
            report = verify_wheel.verify(
                wheel,
                expected_python="cp310",
                expected_platform="manylinux_2_28_x86_64",
                expected_arch="x86_64",
            )
            self.assertTrue(report["accepted"])
            self.assertEqual(
                report["native_architectures"]["yatouv8/_native.so"],
                ["x86_64"],
            )

    def test_rejects_wrong_python_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = self._wheel(
                pathlib.Path(temporary), "manylinux_2_28_x86_64"
            )
            report = verify_wheel.verify(wheel, expected_python="cp311")
            self.assertFalse(report["accepted"])

    def test_rejects_wrong_native_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = self._wheel(
                pathlib.Path(temporary),
                "manylinux_2_28_aarch64",
                native=self._elf(62),
            )
            report = verify_wheel.verify(
                wheel,
                expected_platform="manylinux_2_28_aarch64",
                expected_arch="aarch64",
            )
            self.assertFalse(report["accepted"])
            self.assertFalse(report["architecture_ok"])

    def test_rejects_mixed_architecture_bundled_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            wheel = self._wheel(root, "manylinux_2_28_x86_64")
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("yatouv8.libs/helper.so", self._elf(183))
            report = verify_wheel.verify(wheel, expected_arch="x86_64")
            self.assertFalse(report["accepted"])
            self.assertEqual(
                report["native_architectures"]["yatouv8.libs/helper.so"],
                ["aarch64"],
            )


if __name__ == "__main__":
    unittest.main()
