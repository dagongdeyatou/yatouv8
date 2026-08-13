"""Verify a release tag and the exact 40-wheel PyPI upload set."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD_TOOLS = ROOT / "tools" / "build"
if str(BUILD_TOOLS) not in sys.path:
    sys.path.insert(0, str(BUILD_TOOLS))

import wheel_matrix


class ReleaseSetError(ValueError):
    """Raised when a tag or distribution set violates the release contract."""


def project_version() -> str:
    """Return the canonical version after checking every version declaration."""

    matrix = wheel_matrix.load_matrix()
    expected = str(matrix["version"])
    declarations = {
        "pyproject.toml": re.search(
            r'(?m)^version\s*=\s*"([^"]+)"',
            (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        ),
        "Cargo.toml": re.search(
            r'(?m)^version\s*=\s*"([^"]+)"',
            (ROOT / "Cargo.toml").read_text(encoding="utf-8"),
        ),
    }
    versions = {
        name: match.group(1) if match else None
        for name, match in declarations.items()
    }
    versions["wheel_matrix.json"] = expected
    if set(versions.values()) != {expected}:
        raise ReleaseSetError(f"version declarations disagree: {versions}")
    return expected


def verify_tag(tag: str) -> dict[str, Any]:
    """Require a stable ``vX.Y.Z`` tag matching the project version exactly."""

    version = project_version()
    expected = f"v{version}"
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ReleaseSetError(f"release tag must be vX.Y.Z, got {tag!r}")
    if tag != expected:
        raise ReleaseSetError(f"release tag {tag!r} must equal {expected!r}")
    return {
        "schema": "yatouv8.release-tag-verification.v1",
        "tag": tag,
        "version": version,
        "accepted": True,
    }


def verify_dist(dist: pathlib.Path) -> dict[str, Any]:
    """Require exactly one valid wheel for each target and CPython ABI."""

    matrix = wheel_matrix.load_matrix()
    wheels = sorted(dist.glob("*.whl"))
    expected_count = len(matrix["targets"]) * len(matrix["python_versions"])
    if len(wheels) != expected_count:
        raise ReleaseSetError(
            f"expected exactly {expected_count} wheels, found {len(wheels)}"
        )
    expected_prefix = f"{matrix['package']}-{matrix['version']}-"
    unexpected = [wheel.name for wheel in wheels if not wheel.name.startswith(expected_prefix)]
    if unexpected:
        raise ReleaseSetError(f"unexpected release filenames: {unexpected}")

    seen: set[pathlib.Path] = set()
    reports: list[dict[str, Any]] = []
    for target in matrix["targets"]:
        report = wheel_matrix.verify_dist(
            matrix,
            target_id=target["id"],
            dist=dist,
        )
        reports.append(report)
        for item in report["wheels"]:
            seen.add(dist / item["wheel"])
    if seen != set(wheels):
        unknown = sorted(path.name for path in set(wheels).difference(seen))
        duplicate_or_missing = sorted(path.name for path in seen.difference(wheels))
        raise ReleaseSetError(
            "wheel coverage mismatch: "
            f"unknown={unknown}, missing={duplicate_or_missing}"
        )

    return {
        "schema": "yatouv8.release-set-verification.v1",
        "package": matrix["package"],
        "version": project_version(),
        "target_count": len(matrix["targets"]),
        "python_count": len(matrix["python_versions"]),
        "wheel_count": len(wheels),
        "targets": reports,
        "accepted": True,
    }


def _write_report(report: dict[str, Any], output: pathlib.Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    tag_parser = commands.add_parser("verify-tag")
    tag_parser.add_argument("--tag", required=True)
    dist_parser = commands.add_parser("verify-dist")
    dist_parser.add_argument("--dist", type=pathlib.Path, required=True)
    dist_parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        report = (
            verify_tag(args.tag)
            if args.command == "verify-tag"
            else verify_dist(args.dist)
        )
        _write_report(report, getattr(args, "output", None))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"release-set: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
