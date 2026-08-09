"""Verify wheel tags and mandatory yatouv8 release payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct
import zipfile
from typing import Any


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binary_architectures(payload: bytes) -> set[str]:
    """Return architectures declared by a PE, ELF, or Mach-O header."""

    if len(payload) >= 64 and payload[:2] == b"MZ":
        pe_offset = struct.unpack_from("<I", payload, 0x3C)[0]
        if (
            pe_offset + 6 <= len(payload)
            and payload[pe_offset : pe_offset + 4] == b"PE\0\0"
        ):
            machine = struct.unpack_from("<H", payload, pe_offset + 4)[0]
            value = {
                0x014C: "x86",
                0x8664: "x86_64",
                0xAA64: "aarch64",
            }.get(machine)
            return {value} if value else set()

    if len(payload) >= 20 and payload[:4] == b"\x7fELF":
        endian = {1: "<", 2: ">"}.get(payload[5])
        if endian:
            machine = struct.unpack_from(f"{endian}H", payload, 18)[0]
            value = {3: "x86", 62: "x86_64", 183: "aarch64"}.get(machine)
            return {value} if value else set()

    if len(payload) >= 8 and payload[:4] in (
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
    ):
        endian = "<" if payload[:4] == b"\xcf\xfa\xed\xfe" else ">"
        cpu_type = struct.unpack_from(f"{endian}I", payload, 4)[0]
        value = {0x01000007: "x86_64", 0x0100000C: "aarch64"}.get(cpu_type)
        return {value} if value else set()

    if len(payload) >= 8 and payload[:4] in (
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    ):
        endian = ">" if payload[:4] == b"\xca\xfe\xba\xbe" else "<"
        count = struct.unpack_from(f"{endian}I", payload, 4)[0]
        if count > 32 or len(payload) < 8 + count * 20:
            return set()
        result: set[str] = set()
        for index in range(count):
            cpu_type = struct.unpack_from(f"{endian}I", payload, 8 + index * 20)[0]
            value = {0x01000007: "x86_64", 0x0100000C: "aarch64"}.get(cpu_type)
            if value:
                result.add(value)
        return result

    return set()


def verify(
    wheel: pathlib.Path,
    *,
    expected_python: str | None = None,
    expected_platform: str | None = None,
    expected_arch: str | None = None,
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

        native_binaries = [
            name
            for name in names
            if (
                name.startswith("yatouv8/_native")
                or name.startswith("yatouv8.libs/")
            )
            and name.lower().endswith((".so", ".pyd", ".dll", ".dylib"))
        ]
        native_architectures = {
            name: sorted(binary_architectures(archive.read(name)))
            for name in native_binaries
        }

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
    architecture_ok = expected_arch is None or (
        bool(native_architectures)
        and all(
            architectures == [expected_arch]
            for architectures in native_architectures.values()
        )
    )
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
        "native_architectures": native_architectures,
        "architecture_ok": architecture_ok,
        "license_present": license_present,
        "notice_present": notice_present,
        "metadata_tag_present": metadata_ok,
        "accepted": bool(
            native_modules
            and license_present
            and notice_present
            and python_ok
            and platform_ok
            and architecture_ok
            and metadata_ok
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=pathlib.Path)
    parser.add_argument("--expected-python")
    parser.add_argument("--expected-platform")
    parser.add_argument("--expected-arch")
    args = parser.parse_args()
    try:
        report = verify(
            args.wheel,
            expected_python=args.expected_python,
            expected_platform=args.expected_platform,
            expected_arch=args.expected_arch,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"accepted": False, "error": str(error)}, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
