from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import tempfile
import unittest
import zipfile


MODULE_PATH = pathlib.Path(__file__).parents[1] / "audit_release.py"
SPEC = importlib.util.spec_from_file_location("audit_release", MODULE_PATH)
assert SPEC and SPEC.loader
audit_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_release)


class AuditReleaseTests(unittest.TestCase):
    @staticmethod
    def _pe(machine: int) -> bytes:
        payload = bytearray(128)
        payload[:2] = b"MZ"
        struct.pack_into("<I", payload, 0x3C, 0x40)
        payload[0x40:0x44] = b"PE\0\0"
        struct.pack_into("<H", payload, 0x44, machine)
        return bytes(payload)

    @staticmethod
    def _elf(machine: int) -> bytes:
        payload = bytearray(64)
        payload[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", payload, 18, machine)
        return bytes(payload)

    @staticmethod
    def _macho(cpu_type: int) -> bytes:
        payload = bytearray(32)
        payload[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", payload, 4, cpu_type)
        return bytes(payload)

    def _sbom(self, root: pathlib.Path) -> pathlib.Path:
        path = root / "sbom.json"
        path.write_text(
            json.dumps(
                {"components": [{"name": "yatouv8", "licenses": [{"license": {}}]}]}
            ),
            encoding="utf-8",
        )
        return path

    def _wheel(
        self,
        root: pathlib.Path,
        platform: str,
        *,
        bundled_arch: str | None = None,
    ) -> pathlib.Path:
        wheel = root / f"yatouv8-0.1.2-cp310-cp310-{platform}.whl"
        if platform.startswith("win_"):
            native = self._pe(0xAA64 if platform == "win_arm64" else 0x8664)
            native_name = "yatouv8/_native.pyd"
        elif platform.startswith("macosx_"):
            native = self._macho(
                0x0100000C if platform.endswith("arm64") else 0x01000007
            )
            native_name = "yatouv8/_native.so"
        else:
            native = self._elf(183 if platform.endswith("aarch64") else 62)
            native_name = "yatouv8/_native.so"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(native_name, native)
            archive.writestr("yatouv8-0.1.2.dist-info/licenses/LICENSE", "license")
            archive.writestr("yatouv8-0.1.2.dist-info/licenses/NOTICE", "notice")
            archive.writestr(
                "yatouv8-0.1.2.dist-info/WHEEL",
                f"Wheel-Version: 1.0\nTag: cp310-cp310-{platform}\n",
            )
            if bundled_arch:
                machine = 0xAA64 if bundled_arch == "aarch64" else 0x8664
                archive.writestr("yatouv8.libs/zlib1.dll", self._pe(machine))
        return wheel

    def test_linux_does_not_require_windows_zlib_dll(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            report = audit_release.audit(
                self._wheel(root, "manylinux_2_28_x86_64"),
                self._sbom(root),
            )
            self.assertTrue(report["wheel"]["native_dependency_policy_ok"])

    def test_windows_does_not_require_unreferenced_zlib(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            report = audit_release.audit(
                self._wheel(root, "win_amd64"), self._sbom(root)
            )
            self.assertTrue(report["wheel"]["native_dependency_policy_ok"])

    def test_windows_arm64_rejects_bundled_x64_dll(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            report = audit_release.audit(
                self._wheel(root, "win_arm64", bundled_arch="x86_64"),
                self._sbom(root),
            )
            self.assertFalse(report["wheel"]["native_dependency_policy_ok"])
            self.assertFalse(report["accepted"])

    def test_macos_and_musllinux_are_release_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            sbom = self._sbom(root)
            for platform in ("macosx_11_0_arm64", "musllinux_1_2_aarch64"):
                report = audit_release.audit(
                    self._wheel(root, platform), sbom
                )
                self.assertTrue(report["wheel"]["platform_supported"])

    def test_unknown_native_platform_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            report = audit_release.audit(
                self._wheel(root, "linux_x86_64"), self._sbom(root)
            )
            self.assertFalse(report["wheel"]["platform_supported"])
            self.assertFalse(report["accepted"])


if __name__ == "__main__":
    unittest.main()
