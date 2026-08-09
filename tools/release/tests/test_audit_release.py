from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile


MODULE_PATH = pathlib.Path(__file__).parents[1] / "audit_release.py"
SPEC = importlib.util.spec_from_file_location("audit_release", MODULE_PATH)
assert SPEC and SPEC.loader
audit_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_release)


class AuditReleaseTests(unittest.TestCase):
    def _sbom(self, root: pathlib.Path) -> pathlib.Path:
        path = root / "sbom.json"
        path.write_text(
            json.dumps(
                {"components": [{"name": "yatouv8", "licenses": [{"license": {}}]}]}
            ),
            encoding="utf-8",
        )
        return path

    def _wheel(self, root: pathlib.Path, platform: str, *, zlib: bool) -> pathlib.Path:
        wheel = root / f"yatouv8-0.1.0-cp310-cp310-{platform}.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("yatouv8-0.1.0.dist-info/licenses/LICENSE", "license")
            archive.writestr("yatouv8-0.1.0.dist-info/licenses/NOTICE", "notice")
            if zlib:
                archive.writestr("yatouv8.libs/zlib1.dll", b"zlib")
        return wheel

    def test_linux_does_not_require_windows_zlib_dll(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            report = audit_release.audit(
                self._wheel(root, "manylinux_2_28_x86_64", zlib=False),
                self._sbom(root),
            )
            self.assertTrue(report["wheel"]["native_dependency_policy_ok"])

    def test_windows_still_requires_bundled_zlib(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            report = audit_release.audit(
                self._wheel(root, "win_amd64", zlib=False), self._sbom(root)
            )
            self.assertFalse(report["wheel"]["native_dependency_policy_ok"])


if __name__ == "__main__":
    unittest.main()
