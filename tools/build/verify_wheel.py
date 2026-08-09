"""Verify wheel tags and mandatory yatouv8 release payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import zipfile
from typing import Any


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(
    wheel: pathlib.Path,
    *,
    expected_python: str | None = None,
    expected_platform: str | None = None,
) -> dict[str, Any]:
    if wheel.suffix != ".whl":
        raise ValueError(f"not a wheel filename: {wheel.name}")
    try:
        _, python_tag, abi_tag, platform_tag_with_suffix = wheel.name.rsplit("-", 3)
    except ValueError as error:
        raise ValueError(f"invalid wheel filename: {wheel.name}") from error
    platform_tag = platform_tag_with_suffix.removesuffix(".whl")

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        wheel_metadata_names = [
            name for name in names if name.endswith(".dist-info/WHEEL")
        ]
        wheel_metadata = (
            archive.read(wheel_metadata_names[0]).decode("utf-8")
            if len(wheel_metadata_names) == 1
            else ""
        )

    native_modules = [
        name
        for name in names
        if name.startswith("yatouv8/_native")
        and name.endswith((".so", ".pyd", ".dylib"))
    ]
    license_present = any(
        name.endswith(".dist-info/licenses/LICENSE") for name in names
    )
    notice_present = any(name.endswith(".dist-info/licenses/NOTICE") for name in names)
    python_ok = expected_python is None or (
        python_tag == expected_python and abi_tag.startswith(expected_python)
    )
    platform_ok = expected_platform is None or expected_platform in platform_tag.split(".")
    metadata_tag = f"Tag: {python_tag}-{abi_tag}-{platform_tag}"
    metadata_ok = metadata_tag in wheel_metadata

    report: dict[str, Any] = {
        "schema": "yatouv8.wheel-verification.v1",
        "wheel": wheel.name,
        "sha256": sha256(wheel),
        "size_bytes": wheel.stat().st_size,
        "python_tag": python_tag,
        "abi_tag": abi_tag,
        "platform_tag": platform_tag,
        "native_modules": native_modules,
        "license_present": license_present,
        "notice_present": notice_present,
        "metadata_tag_present": metadata_ok,
        "accepted": bool(
            native_modules
            and license_present
            and notice_present
            and python_ok
            and platform_ok
            and metadata_ok
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=pathlib.Path)
    parser.add_argument("--expected-python")
    parser.add_argument("--expected-platform")
    args = parser.parse_args()
    try:
        report = verify(
            args.wheel,
            expected_python=args.expected_python,
            expected_platform=args.expected_platform,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"accepted": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
