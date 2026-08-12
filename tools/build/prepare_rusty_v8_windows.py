"""Download and verify locked rusty_v8 assets for Windows wheel builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request


ASSET_MANIFEST = pathlib.Path(__file__).with_name("rusty_v8_windows_assets.json")
CHUNK_SIZE = 1024 * 1024


class AssetError(ValueError):
    """Raised when the locked Windows asset contract is violated."""


def file_sha256(path: pathlib.Path) -> str:
    """Return the lower-case SHA-256 of *path*."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: pathlib.Path = ASSET_MANIFEST) -> dict[str, object]:
    """Load and validate the checked-in asset manifest."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "yatouv8.rusty-v8-windows-assets.v1":
        raise AssetError("unsupported Windows rusty_v8 asset schema")
    if document.get("version") != "150.4.0":
        raise AssetError("Windows rusty_v8 assets must be pinned to 150.4.0")
    targets = document.get("targets")
    expected = {"x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"}
    if not isinstance(targets, dict) or set(targets) != expected:
        raise AssetError("Windows rusty_v8 target coverage mismatch")
    for target, record in targets.items():
        if not isinstance(record, dict):
            raise AssetError(f"invalid target record: {target}")
        for kind in ("archive", "binding"):
            asset = record.get(kind)
            if not isinstance(asset, dict):
                raise AssetError(f"{target} missing {kind}")
            url = asset.get("url")
            digest = asset.get("sha256")
            expected_prefix = "https://github.com/denoland/rusty_v8/releases/download/v150.4.0/"
            if not isinstance(url, str) or not url.startswith(expected_prefix):
                raise AssetError(f"{target} {kind} URL is not version locked")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise AssetError(f"{target} {kind} SHA-256 is invalid")
    return document


def fetch(url: str, destination: pathlib.Path, expected_sha256: str) -> pathlib.Path:
    """Fetch one asset atomically and reject any digest mismatch."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and file_sha256(destination) == expected_sha256:
        return destination
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=900) as response, temporary.open("wb") as stream:
            while chunk := response.read(CHUNK_SIZE):
                stream.write(chunk)
        actual = file_sha256(temporary)
        if actual != expected_sha256:
            raise AssetError(
                f"asset checksum mismatch: expected {expected_sha256}, got {actual}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def prepare(target: str, cache: pathlib.Path) -> dict[str, object]:
    """Prepare the two assets for *target* and return an environment contract."""

    document = load_manifest()
    targets = document["targets"]
    if target not in targets:
        raise AssetError(f"unsupported Windows target: {target}")
    version = str(document["version"])
    target_record = targets[target]
    target_root = cache / version / target
    resolved: dict[str, dict[str, str]] = {}
    for kind in ("archive", "binding"):
        record = target_record[kind]
        url = str(record["url"])
        digest = str(record["sha256"])
        destination = target_root / pathlib.PurePosixPath(url).name
        fetch(url, destination, digest)
        resolved[kind] = {
            "path": str(destination.resolve()),
            "url": url,
            "sha256": digest,
        }
    return {
        "schema": "yatouv8.rusty-v8-windows-preparation.v1",
        "version": version,
        "target": target,
        "archive": resolved["archive"],
        "binding": resolved["binding"],
    }


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--cache", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        report = prepare(args.target, args.cache)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    except (AssetError, OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
