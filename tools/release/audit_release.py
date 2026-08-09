"""Audit wheel contents, hashes, licenses, and pinned release inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import zipfile
from typing import Any

MATRIX_PATH = pathlib.Path(__file__).resolve().parents[1] / "build" / "wheel_matrix.json"
BUILD_TOOLS = MATRIX_PATH.parent
if str(BUILD_TOOLS) not in sys.path:
    sys.path.insert(0, str(BUILD_TOOLS))

from verify_wheel import verify


def target_for_platform(platform: str) -> dict[str, Any] | None:
    """Return the matrix target embedded in a possibly compound wheel tag."""

    document = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    parts = set(platform.split("."))
    return next(
        (target for target in document["targets"] if target["platform_tag"] in parts),
        None,
    )


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(wheel: pathlib.Path, sbom: pathlib.Path) -> dict[str, Any]:
    document = json.loads(sbom.read_text(encoding="utf-8"))
    missing_licenses = [
        component["name"]
        for component in document["components"]
        if "licenses" not in component
    ]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    license_present = any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
    notice_present = any(name.endswith(".dist-info/licenses/NOTICE") for name in names)
    zlib_bundled = any(
        re.search(r"yatouv8\.libs/zlib[^/]*\.dll$", name, re.IGNORECASE)
        for name in names
    )
    wheel_platform = wheel.name.removesuffix(".whl").rsplit("-", 1)[-1]
    target = target_for_platform(wheel_platform)
    platform_supported = target is not None
    payload = verify(
        wheel,
        expected_platform=target["platform_tag"] if target else None,
        expected_arch=target["arch"] if target else None,
    )
    # Repaired wheels may or may not contain zlib depending on the CPython
    # distribution used to build them.  Absence is valid when _native has no
    # such dependency; every bundled native binary must instead match the
    # target architecture, which also prevents x64 DLLs leaking into ARM64.
    native_dependency_policy_ok = bool(payload["architecture_ok"])
    report = {
        "milestone": "m10",
        "wheel": {
            "filename": wheel.name,
            "sha256": sha256(wheel),
            "size_bytes": wheel.stat().st_size,
            "license_present": license_present,
            "notice_present": notice_present,
            "zlib_bundled": zlib_bundled,
            "native_dependency_policy_ok": native_dependency_policy_ok,
            "platform_tag": wheel_platform,
            "platform_supported": platform_supported,
            "native_architectures": payload["native_architectures"],
            "payload_accepted": payload["accepted"],
        },
        "sbom": {
            "filename": sbom.name,
            "sha256": sha256(sbom),
            "component_count": len(document["components"]),
            "missing_license_components": missing_licenses,
        },
        "lockfile_present": pathlib.Path("Cargo.lock").is_file(),
    }
    report["accepted"] = (
        license_present
        and notice_present
        and native_dependency_policy_ok
        and platform_supported
        and payload["accepted"]
        and not missing_licenses
        and report["lockfile_present"]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=pathlib.Path)
    parser.add_argument("--sbom", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    report = audit(args.wheel, args.sbom)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
