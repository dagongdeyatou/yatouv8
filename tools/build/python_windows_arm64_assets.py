"""Validate the locked CPython runtime used by Windows ARM64 wheel tests."""

from __future__ import annotations

import json
import pathlib


ASSET_MANIFEST = pathlib.Path(__file__).with_name("python_windows_arm64_assets.json")


class AssetError(ValueError):
    """Raised when the Windows ARM64 test-runtime contract is invalid."""


def _validate_sha256(value: object, *, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AssetError(f"{label} SHA-256 is invalid")


def load_manifest(path: pathlib.Path = ASSET_MANIFEST) -> dict[str, object]:
    """Load and validate the pinned native CPython 3.10 ARM64 test runtime."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "yatouv8.python-windows-arm64-assets.v1":
        raise AssetError("unsupported Windows ARM64 Python asset schema")

    runtime = document.get("runtime")
    pip = document.get("pip")
    if not isinstance(runtime, dict) or not isinstance(pip, dict):
        raise AssetError("runtime and pip records are required")
    if runtime.get("version") != "3.10.2" or runtime.get("python_version") != "3.10":
        raise AssetError("the fallback runtime must remain CPython 3.10.2 / ABI 3.10")
    if runtime.get("architecture") != "arm64":
        raise AssetError("the fallback runtime must be native Windows ARM64")
    expected_runtime_url = (
        "https://www.python.org/ftp/python/3.10.2/"
        "python-3.10.2-embed-arm64.zip"
    )
    if runtime.get("url") != expected_runtime_url:
        raise AssetError("the fallback runtime URL must be the locked python.org asset")
    if pip.get("version") != "26.2.1":
        raise AssetError("the embedded runtime bootstrap must use pinned pip 26.2.1")
    pip_url = pip.get("url")
    if not isinstance(pip_url, str) or not pip_url.startswith(
        "https://files.pythonhosted.org/"
    ) or not pip_url.endswith("/pip-26.2.1-py3-none-any.whl"):
        raise AssetError("the pip URL must be the locked PyPI wheel asset")
    _validate_sha256(runtime.get("sha256"), label="runtime")
    _validate_sha256(pip.get("sha256"), label="pip")
    return document
