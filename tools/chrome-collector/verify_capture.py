#!/usr/bin/env python3
"""Independently verify one admitted Chrome evidence run."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any


SCHEMA_VERSION = 1
READABLE_COPIES = {
    "raw_cdp": "raw.cdp.ndjson",
    "chrome_snapshot": "snapshot.json",
    "chrome_stderr": "chrome.stderr.log",
}


class VerificationError(ValueError):
    """Raised when a capture violates an evidence invariant."""


def sha256_file(path: pathlib.Path) -> str:
    """Return the lowercase SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"expected JSON object: {path}")
    return value


def infer_evidence_root(run_dir: pathlib.Path) -> pathlib.Path:
    """Infer the evidence root from baselines/<id>/runs/<run>."""
    if run_dir.parent.name != "runs" or run_dir.parent.parent.parent.name != "baselines":
        raise VerificationError(f"unexpected run directory layout: {run_dir}")
    return run_dir.parent.parent.parent.parent


def verify_lineage(artifacts: list[dict[str, Any]]) -> None:
    """Verify unique names, existing parent edges, and an acyclic graph."""
    names = [artifact["logical_name"] for artifact in artifacts]
    if len(names) != len(set(names)):
        raise VerificationError("duplicate artifact logical_name")
    graph = {artifact["logical_name"]: artifact.get("parents", []) for artifact in artifacts}
    for name, parents in graph.items():
        if name in parents:
            raise VerificationError(f"self-referential lineage edge: {name}")
        missing = [parent for parent in parents if parent not in graph]
        if missing:
            raise VerificationError(f"missing lineage parent for {name}: {missing}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise VerificationError(f"lineage cycle contains: {name}")
        if name in visited:
            return
        visiting.add(name)
        for parent in graph[name]:
            visit(parent)
        visiting.remove(name)
        visited.add(name)

    for name in names:
        visit(name)


def verify_capture(run_dir: pathlib.Path) -> dict[str, Any]:
    """Verify schema links, content addresses, lineage, and pollution proof."""
    run_dir = run_dir.resolve()
    evidence_root = infer_evidence_root(run_dir)
    manifest = load_json(run_dir / "manifest.json")
    snapshot = load_json(run_dir / "snapshot.json")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError("unsupported manifest schema_version")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError("unsupported snapshot schema_version")
    for field in ("baseline_id", "run_id"):
        if manifest.get(field) != snapshot.get(field):
            raise VerificationError(f"manifest/snapshot {field} mismatch")
    if manifest.get("status") != "complete" or manifest.get("cleanup_verified") is not True:
        raise VerificationError("run is not complete with verified cleanup")

    pollution = snapshot.get("pollution", {})
    if not (
        pollution.get("unchanged") is True
        and pollution.get("before_global_keys_sha256")
        == pollution.get("after_global_keys_sha256")
        and pollution.get("added") == []
        and pollution.get("removed") == []
    ):
        raise VerificationError("collector pollution proof failed")

    surfaces = snapshot.get("surfaces")
    if not isinstance(surfaces, list):
        raise VerificationError("snapshot surfaces must be an array")
    for surface in surfaces:
        descriptor_keys = [descriptor["key"] for descriptor in surface["descriptors"]]
        if descriptor_keys != surface["own_keys"]:
            raise VerificationError(f"descriptor order mismatch: {surface['path']}")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise VerificationError("manifest has no artifacts")
    verify_lineage(artifacts)

    checks: list[dict[str, Any]] = []
    for artifact in artifacts:
        digest = artifact["evidence"]["sha256"]
        relative = pathlib.PurePosixPath(artifact["relative_path"])
        expected = pathlib.PurePosixPath("objects", "sha256", digest[:2], digest)
        if relative != expected or relative.is_absolute() or ".." in relative.parts:
            raise VerificationError(f"invalid content-addressed path: {relative}")
        object_path = evidence_root.joinpath(*relative.parts).resolve()
        if not object_path.is_relative_to(evidence_root.resolve()) or not object_path.is_file():
            raise VerificationError(f"missing evidence object: {object_path}")
        if object_path.stat().st_size != artifact["size_bytes"]:
            raise VerificationError(f"size mismatch: {artifact['logical_name']}")
        if sha256_file(object_path) != digest:
            raise VerificationError(f"digest mismatch: {artifact['logical_name']}")

        readable_name = READABLE_COPIES.get(artifact["logical_name"])
        if readable_name and sha256_file(run_dir / readable_name) != digest:
            raise VerificationError(f"readable copy mismatch: {artifact['logical_name']}")
        checks.append(
            {
                "logical_name": artifact["logical_name"],
                "sha256": digest,
                "size_bytes": artifact["size_bytes"],
            }
        )

    return {
        "status": "verified",
        "baseline_id": snapshot["baseline_id"],
        "run_id": snapshot["run_id"],
        "browser_product": snapshot["browser"]["product"],
        "capture_mode": snapshot["capture_mode"],
        "surfaces": len(surfaces),
        "available_surfaces": sum(surface["available"] for surface in surfaces),
        "cleanup_verified": True,
        "artifacts": checks,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=pathlib.Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    print(json.dumps(verify_capture(arguments.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
