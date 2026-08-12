"""Validate and query yatouv8's canonical native wheel matrix."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

MODULE_DIR = pathlib.Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from verify_wheel import verify


DEFAULT_MATRIX = MODULE_DIR / "wheel_matrix.json"
EXPECTED_PYTHONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]
EXPECTED_TARGETS = {
    "windows-x86_64",
    "windows-arm64",
    "macos-x86_64",
    "macos-arm64",
    "manylinux-x86_64",
    "manylinux-aarch64",
    "musllinux-x86_64",
    "musllinux-aarch64",
}


class MatrixError(ValueError):
    """Raised when the checked-in wheel matrix violates its contract."""


def python_tag(version: str) -> str:
    """Convert ``3.10`` to the CPython wheel tag ``cp310``."""

    major, minor = version.split(".", 1)
    return f"cp{major}{minor}"


def load_matrix(path: pathlib.Path = DEFAULT_MATRIX) -> dict[str, Any]:
    """Load and validate a wheel matrix document."""

    document = json.loads(path.read_text(encoding="utf-8"))
    validate_matrix(document)
    return document


def validate_matrix(document: dict[str, Any]) -> dict[str, Any]:
    """Validate matrix invariants and return a machine-readable report."""

    if document.get("schema") != "yatouv8.wheel-matrix.v1":
        raise MatrixError("unsupported wheel matrix schema")
    if document.get("python_versions") != EXPECTED_PYTHONS:
        raise MatrixError("python_versions must be exactly CPython 3.10 through 3.14")

    targets = document.get("targets")
    if not isinstance(targets, list):
        raise MatrixError("targets must be a list")
    ids = [target.get("id") for target in targets]
    if len(ids) != len(set(ids)):
        raise MatrixError("target ids must be unique")
    if set(ids) != EXPECTED_TARGETS:
        missing = sorted(EXPECTED_TARGETS.difference(ids))
        extra = sorted(set(ids).difference(EXPECTED_TARGETS))
        raise MatrixError(f"target coverage mismatch: missing={missing}, extra={extra}")

    required = {
        "id",
        "family",
        "os",
        "libc",
        "arch",
        "rust_target",
        "platform_tag",
        "compatibility",
        "build_mode",
        "build_runner",
        "test_runner",
        "python_architecture",
        "artifact_name",
    }
    rust_targets: set[str] = set()
    platform_tags: set[str] = set()
    artifact_names: set[str] = set()
    for target in targets:
        missing_fields = sorted(required.difference(target))
        if missing_fields:
            raise MatrixError(f"{target.get('id', '<unknown>')} missing {missing_fields}")
        if target["rust_target"] in rust_targets:
            raise MatrixError(f"duplicate rust target: {target['rust_target']}")
        if target["platform_tag"] in platform_tags:
            raise MatrixError(f"duplicate platform tag: {target['platform_tag']}")
        if target["artifact_name"] in artifact_names:
            raise MatrixError(f"duplicate artifact name: {target['artifact_name']}")
        rust_targets.add(target["rust_target"])
        platform_tags.add(target["platform_tag"])
        artifact_names.add(target["artifact_name"])
        if target["family"] == "linux":
            for field in ("maturin_manylinux", "build_container", "test_container"):
                if not target.get(field):
                    raise MatrixError(f"{target['id']} missing Linux field {field}")
            for field in ("build_container", "test_container"):
                if "@sha256:" not in target[field]:
                    raise MatrixError(f"{target['id']} {field} must be digest pinned")

    return {
        "schema": "yatouv8.wheel-matrix-validation.v1",
        "target_count": len(targets),
        "python_count": len(EXPECTED_PYTHONS),
        "wheel_count": len(targets) * len(EXPECTED_PYTHONS),
        "accepted": True,
    }


def target_by_id(document: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Return one target or raise a useful error."""

    for target in document["targets"]:
        if target["id"] == target_id:
            return target
    raise MatrixError(f"unknown wheel target: {target_id}")


def _base_entry(target: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in target.items() if key != "family"}


def github_matrices(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Expand the canonical matrix into GitHub Actions job matrices."""

    windows_build: list[dict[str, Any]] = []
    windows_test: list[dict[str, Any]] = []
    macos_build: list[dict[str, Any]] = []
    linux_build: list[dict[str, Any]] = []
    linux_test: list[dict[str, Any]] = []
    versions = document["python_versions"]

    for target in document["targets"]:
        base = _base_entry(target)
        if target["family"] == "windows":
            windows_build.append({**base, "python_versions": " ".join(versions)})
            for version in versions:
                entry = {
                    **base,
                    "python_version": version,
                    "python_tag": python_tag(version),
                }
                windows_test.append(entry)
        elif target["family"] == "macos":
            macos_build.append({**base, "python_versions": " ".join(versions)})
        elif target["family"] == "linux":
            linux_build.append({**base, "python_versions": " ".join(versions)})
            for version in versions:
                linux_test.append(
                    {
                        **base,
                        "python_version": version,
                        "python_tag": python_tag(version),
                    }
                )

    return {
        "windows_build": windows_build,
        "windows_test": windows_test,
        "macos_build": macos_build,
        "linux_build": linux_build,
        "linux_test": linux_test,
    }


def verify_dist(
    document: dict[str, Any],
    *,
    target_id: str,
    dist: pathlib.Path,
    python_version: str | None = None,
) -> dict[str, Any]:
    """Verify that dist contains exactly the expected wheel subset."""

    target = target_by_id(document, target_id)
    versions = [python_version] if python_version else document["python_versions"]
    unknown_versions = sorted(set(versions).difference(document["python_versions"]))
    if unknown_versions:
        raise MatrixError(f"unsupported Python versions: {unknown_versions}")
    wheels = sorted(dist.glob(f"{document['package']}-{document['version']}-*.whl"))
    reports: list[dict[str, Any]] = []
    matched: set[pathlib.Path] = set()

    for version in versions:
        tag = python_tag(version)
        candidates = [
            wheel
            for wheel in wheels
            if f"-{tag}-{tag}-" in wheel.name
            and target["platform_tag"] in wheel.name.removesuffix(".whl").split("-")[-1].split(".")
        ]
        if len(candidates) != 1:
            raise MatrixError(
                f"expected one {target_id} {tag} wheel in {dist}, found {len(candidates)}"
            )
        report = verify(
            candidates[0],
            expected_python=tag,
            expected_platform=target["platform_tag"],
            expected_arch=target["arch"],
        )
        if not report["accepted"]:
            raise MatrixError(f"wheel verification failed: {candidates[0].name}")
        matched.add(candidates[0])
        reports.append(report)

    relevant = {
        wheel
        for wheel in wheels
        if target["platform_tag"] in wheel.name.removesuffix(".whl").split("-")[-1].split(".")
    }
    unexpected = sorted(wheel.name for wheel in relevant.difference(matched))
    if unexpected and python_version is None:
        raise MatrixError(f"unexpected {target_id} wheels: {unexpected}")

    return {
        "schema": "yatouv8.wheel-matrix-dist-verification.v1",
        "target": target_id,
        "platform_tag": target["platform_tag"],
        "expected_count": len(versions),
        "verified_count": len(reports),
        "wheels": reports,
        "accepted": True,
    }


def _print_json(value: Any, *, compact: bool = False) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=pathlib.Path, default=DEFAULT_MATRIX)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")

    target_parser = commands.add_parser("target")
    target_parser.add_argument("--target", required=True)

    field_parser = commands.add_parser("field")
    field_parser.add_argument("--target", required=True)
    field_parser.add_argument("--name", required=True)

    commands.add_parser("github-output")

    dist_parser = commands.add_parser("verify-dist")
    dist_parser.add_argument("--target", required=True)
    dist_parser.add_argument("--dist", required=True, type=pathlib.Path)
    dist_parser.add_argument("--python-version")

    args = parser.parse_args(argv)
    try:
        document = load_matrix(args.matrix)
        if args.command == "validate":
            _print_json(validate_matrix(document))
        elif args.command == "target":
            _print_json(target_by_id(document, args.target))
        elif args.command == "field":
            target = target_by_id(document, args.target)
            if args.name not in target:
                raise MatrixError(f"{args.target} has no field {args.name}")
            value = target[args.name]
            print(value if isinstance(value, str) else json.dumps(value))
        elif args.command == "github-output":
            for name, entries in github_matrices(document).items():
                print(f"{name}={json.dumps({'include': entries}, separators=(',', ':'))}")
        elif args.command == "verify-dist":
            _print_json(
                verify_dist(
                    document,
                    target_id=args.target,
                    dist=args.dist,
                    python_version=args.python_version,
                )
            )
        return 0
    except (OSError, json.JSONDecodeError, MatrixError, ValueError) as error:
        print(f"wheel-matrix: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
