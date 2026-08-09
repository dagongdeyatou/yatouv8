from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest
import zipfile


MODULE_PATH = pathlib.Path(__file__).parents[1] / "verify_wheel.py"
SPEC = importlib.util.spec_from_file_location("verify_wheel", MODULE_PATH)
assert SPEC and SPEC.loader
verify_wheel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_wheel)


class VerifyWheelTests(unittest.TestCase):
    def _wheel(self, root: pathlib.Path, platform: str) -> pathlib.Path:
        wheel = root / f"yatouv8-0.1.0-cp310-cp310-{platform}.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("yatouv8/_native.so", b"native")
            archive.writestr("yatouv8-0.1.0.dist-info/licenses/LICENSE", "license")
            archive.writestr("yatouv8-0.1.0.dist-info/licenses/NOTICE", "notice")
            archive.writestr(
                "yatouv8-0.1.0.dist-info/WHEEL",
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
            )
            self.assertTrue(report["accepted"])

    def test_rejects_wrong_python_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = self._wheel(
                pathlib.Path(temporary), "manylinux_2_28_x86_64"
            )
            report = verify_wheel.verify(wheel, expected_python="cp311")
            self.assertFalse(report["accepted"])


if __name__ == "__main__":
    unittest.main()
