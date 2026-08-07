"""Audit wheel contents, hashes, licenses, and pinned release inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import zipfile
from typing import Any


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
    zlib_bundled = any(re.search(r"yatouv8\.libs/zlib[^/]*\.dll$", name, re.IGNORECASE) for name in names)
    report = {
        "milestone": "m10",
        "wheel": {
            "filename": wheel.name,
            "sha256": sha256(wheel),
            "size_bytes": wheel.stat().st_size,
            "license_present": license_present,
            "notice_present": notice_present,
            "zlib_bundled": zlib_bundled,
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
        and zlib_bundled
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
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
