"""Hydrate pinned files omitted from the crates.io v8 source package.

The v8 crate source build needs an ICU data blob and Chromium's vendored Rust
tree.  This helper is intentionally platform-neutral so Windows, manylinux,
and macOS builders consume exactly the same inputs and checksums.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from typing import Any, BinaryIO

V8_VERSION = "150.4.0"
ICU_URL = (
    "https://chromium.googlesource.com/chromium/deps/icu/+/"
    "ee5f27adc28bd3f15b2c293f726d14d2e336cbd5/common/icudtl.dat?format=TEXT"
)
ICU_SHA256 = "1cf67874b5a87a8363a86fb3f81e3cbbed54d389062dab8fb52308d5cf8c8612"
CHROMIUM_RUST_URL = (
    "https://chromium.googlesource.com/chromium/src/third_party/rust/+archive/"
    "26e8ff47f18a8d28d6187a04b6a16cb7332356f8.tar.gz"
)
CHROMIUM_RUST_TREE_SHA256 = (
    "b9aa1ddbf440b8e5234e029a2ad223f461c1b4fca12c9e168b5e4f5f7ee322ee"
)
CHROMIUM_RUST_ARCHIVE = "chromium-third-party-rust-26e8ff47.tar.gz"
CHROMIUM_RUST_PROBE = pathlib.PurePosixPath(
    "chromium_crates_io/vendor/icu_calendar_data-v2/build.rs"
)


class PreparationError(RuntimeError):
    """Raised when a pinned V8 source input cannot be verified."""


def sha256_file(path: pathlib.Path) -> str:
    """Return the lowercase SHA-256 digest of *path*."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def default_cache_dir() -> pathlib.Path:
    """Resolve a per-user download cache without platform-specific packages."""

    configured = os.environ.get("YATOU_DOWNLOAD_CACHE")
    if configured:
        return pathlib.Path(configured).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return pathlib.Path(os.environ["LOCALAPPDATA"]) / "yatouv8" / "downloads"
    root = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache"))
    return root / "yatouv8" / "downloads"


def _download(
    url: str,
    destination: pathlib.Path,
    expected_tree_sha256: str,
) -> pathlib.Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            actual = archive_tree_sha256(destination)
            if actual == expected_tree_sha256:
                return destination
        except PreparationError:
            pass
        destination.unlink()

    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "yatouv8-build/0.1"})
        with urllib.request.urlopen(request, timeout=900) as response, temporary.open("wb") as sink:
            shutil.copyfileobj(response, sink, length=1024 * 1024)
        actual = archive_tree_sha256(temporary)
        if actual != expected_tree_sha256:
            raise PreparationError(
                f"download tree checksum mismatch for {url}: "
                f"expected {expected_tree_sha256}, got {actual}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "yatouv8-build/0.1"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def locate_v8_root(cargo_home: pathlib.Path, version: str = V8_VERSION) -> pathlib.Path:
    """Locate one exact v8 crate directory in Cargo's registry cache."""

    registry = cargo_home / "registry" / "src"
    candidates = sorted(registry.glob(f"*/v8-{version}"))
    candidates = [candidate for candidate in candidates if candidate.is_dir()]
    if not candidates:
        raise PreparationError(f"v8 {version} source was not found under {registry}")
    return candidates[0].resolve()


def hydrate_icu(v8_root: pathlib.Path, url: str = ICU_URL) -> pathlib.Path:
    """Download, decode, and verify the pinned ICU data file."""

    destination = v8_root / "third_party" / "icu" / "common" / "icudtl.dat"
    if destination.is_file():
        actual = sha256_file(destination)
        if actual == ICU_SHA256:
            return destination
        raise PreparationError(
            f"existing ICU data checksum mismatch: expected {ICU_SHA256}, got {actual}"
        )

    try:
        encoded = b"".join(_read_url(url).split())
        payload = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise PreparationError(f"failed to decode ICU data from {url}: {error}") from error
    actual = hashlib.sha256(payload).hexdigest()
    if actual != ICU_SHA256:
        raise PreparationError(
            f"ICU data checksum mismatch: expected {ICU_SHA256}, got {actual}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    names: set[str] = set()
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise PreparationError(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk():
            raise PreparationError(f"archive links are not permitted: {member.name}")
        if not (member.isdir() or member.isfile()):
            raise PreparationError(f"unsupported archive entry: {member.name}")
        if member.name in names:
            raise PreparationError(f"duplicate archive entry: {member.name}")
        names.add(member.name)
        members.append(member)
    return members


def archive_tree_sha256(archive_path: pathlib.Path) -> str:
    """Hash extracted file paths, sizes, and contents independent of gzip bytes."""

    records: list[tuple[str, int, bytes]] = []
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in _safe_members(archive):
                if not member.isfile():
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise PreparationError(f"failed to read archive entry: {member.name}")
                digest = hashlib.sha256()
                with source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                records.append((member.name, member.size, digest.digest()))
    except tarfile.TarError as error:
        raise PreparationError(f"invalid tar archive {archive_path}: {error}") from error

    tree = hashlib.sha256()
    for name, size, digest in sorted(records):
        encoded_name = name.encode("utf-8")
        tree.update(len(encoded_name).to_bytes(8, "big"))
        tree.update(encoded_name)
        tree.update(size.to_bytes(8, "big"))
        tree.update(digest)
    return tree.hexdigest()


def _extract_verified_archive(archive_path: pathlib.Path, destination: pathlib.Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _safe_members(archive)
        for member in members:
            target = destination.joinpath(*pathlib.PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source: BinaryIO | None = archive.extractfile(member)
            if source is None:
                raise PreparationError(f"failed to read archive entry: {member.name}")
            with source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)


def hydrate_chromium_rust(v8_root: pathlib.Path, cache_dir: pathlib.Path) -> pathlib.Path:
    """Overlay Chromium's pinned vendored Rust source tree into the v8 crate."""

    target = v8_root / "third_party" / "rust"
    probe = target.joinpath(*CHROMIUM_RUST_PROBE.parts)
    if probe.is_file():
        return target

    archive_path = _download(
        CHROMIUM_RUST_URL,
        cache_dir / CHROMIUM_RUST_ARCHIVE,
        CHROMIUM_RUST_TREE_SHA256,
    )
    with tempfile.TemporaryDirectory(prefix="yatouv8-rust-vendor-") as temporary:
        extracted = pathlib.Path(temporary)
        _extract_verified_archive(archive_path, extracted)
        extracted_probe = extracted.joinpath(*CHROMIUM_RUST_PROBE.parts)
        if not extracted_probe.is_file():
            raise PreparationError(
                f"Chromium Rust archive is missing {CHROMIUM_RUST_PROBE.as_posix()}"
            )
        shutil.copytree(extracted, target, dirs_exist_ok=True)
    if not probe.is_file():
        raise PreparationError("failed to hydrate Chromium Rust vendor sources")
    return target


def prepare(
    *,
    cargo: str,
    cargo_home: pathlib.Path,
    cache_dir: pathlib.Path,
    v8_root: pathlib.Path | None,
    skip_cargo_fetch: bool,
) -> dict[str, Any]:
    """Prepare all pinned source inputs and return a machine-readable manifest."""

    if not skip_cargo_fetch:
        subprocess.run([cargo, "fetch", "--locked"], check=True)
    root = v8_root.resolve() if v8_root else locate_v8_root(cargo_home)
    icu = hydrate_icu(root)
    chromium_rust = hydrate_chromium_rust(root, cache_dir)
    return {
        "schema": "yatouv8.v8-source-preparation.v1",
        "v8_version": V8_VERSION,
        "v8_root": str(root),
        "icu_data": {"path": str(icu), "sha256": sha256_file(icu)},
        "chromium_rust": {
            "path": str(chromium_rust),
            "tree_sha256": CHROMIUM_RUST_TREE_SHA256,
            "probe": str(chromium_rust.joinpath(*CHROMIUM_RUST_PROBE.parts)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--cargo-home",
        type=pathlib.Path,
        default=pathlib.Path(os.environ.get("CARGO_HOME", pathlib.Path.home() / ".cargo")),
    )
    parser.add_argument("--cache-dir", type=pathlib.Path, default=default_cache_dir())
    parser.add_argument("--v8-root", type=pathlib.Path)
    parser.add_argument("--skip-cargo-fetch", action="store_true")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    try:
        manifest = prepare(
            cargo=args.cargo,
            cargo_home=args.cargo_home.expanduser(),
            cache_dir=args.cache_dir.expanduser(),
            v8_root=args.v8_root,
            skip_cargo_fetch=args.skip_cargo_fetch,
        )
    except (OSError, subprocess.CalledProcessError, PreparationError) as error:
        print(f"prepare-v8-source: {error}", file=sys.stderr)
        return 1
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
