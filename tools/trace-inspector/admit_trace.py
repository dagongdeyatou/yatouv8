#!/usr/bin/env python3
"""Admit a validated M3 trace with lineage to a headful Chrome snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from typing import Any

from trace_inspector import inspect_trace


def canonical_json_bytes(value: Any) -> bytes:
    """Encode deterministic UTF-8 JSON."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def store_object(evidence_root: pathlib.Path, data: bytes) -> tuple[str, str]:
    """Store immutable bytes and return digest plus POSIX relative path."""
    digest = hashlib.sha256(data).hexdigest()
    relative = pathlib.PurePosixPath("objects", "sha256", digest[:2], digest)
    destination = evidence_root.joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError(f"content-address collision: {destination}")
    if not destination.exists():
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    return digest, relative.as_posix()


def admit(
    trace_path: pathlib.Path,
    snapshot_path: pathlib.Path,
    evidence_root: pathlib.Path,
) -> dict[str, Any]:
    """Validate inputs, preserve content addresses, and write an M3 lineage manifest."""
    trace_path = trace_path.resolve(strict=True)
    snapshot_path = snapshot_path.resolve(strict=True)
    evidence_root = evidence_root.resolve()
    summary = inspect_trace(trace_path)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("capture_mode") != "headful":
        raise ValueError("M3 trace must reference a headful Chrome baseline")
    if snapshot.get("environment", {}).get("navigator", {}).get("webdriver") is not False:
        raise ValueError("headful baseline exposes navigator.webdriver")
    if snapshot.get("baseline_id") != summary.get("baseline_id"):
        raise ValueError("trace and Chrome snapshot baseline_id mismatch")

    trace_bytes = trace_path.read_bytes()
    snapshot_bytes = snapshot_path.read_bytes()
    summary_bytes = canonical_json_bytes(summary)
    trace_digest, trace_relative = store_object(evidence_root, trace_bytes)
    snapshot_digest, snapshot_relative = store_object(evidence_root, snapshot_bytes)
    summary_digest, summary_relative = store_object(evidence_root, summary_bytes)
    manifest = {
        "schema_version": 1,
        "milestone": "m3_trace_spine",
        "status": "complete",
        "scope": "deterministic infrastructure fixture; not a real Google VM success claim",
        "baseline_id": summary["baseline_id"],
        "trace_id": summary["trace_id"],
        "guarantees": {
            "rust_semantic_validation": True,
            "independent_physical_validation": True,
            "strict_l0_consumption": True,
            "network_fallback": False,
            "l1_operations": [
                "get",
                "set",
                "call",
                "construct",
                "own_keys",
                "get_own_property_descriptor",
                "get_prototype_of",
                "has",
                "define_property",
            ],
        },
        "artifacts": [
            {
                "logical_name": "chrome_headful_snapshot",
                "relative_path": snapshot_relative,
                "size_bytes": len(snapshot_bytes),
                "evidence": {"sha256": snapshot_digest, "media_type": "application/json"},
                "parents": [],
            },
            {
                "logical_name": "m3_trace_ndjson",
                "relative_path": trace_relative,
                "size_bytes": len(trace_bytes),
                "evidence": {
                    "sha256": trace_digest,
                    "media_type": "application/x-ndjson",
                },
                "parents": ["chrome_headful_snapshot"],
            },
            {
                "logical_name": "trace_inspection",
                "relative_path": summary_relative,
                "size_bytes": len(summary_bytes),
                "evidence": {"sha256": summary_digest, "media_type": "application/json"},
                "parents": ["m3_trace_ndjson"],
            },
        ],
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_digest, manifest_relative = store_object(evidence_root, manifest_bytes)
    readable_dir = evidence_root / "traces" / "m3"
    readable_dir.mkdir(parents=True, exist_ok=True)
    (readable_dir / "trace-inspection.json").write_bytes(summary_bytes)
    (readable_dir / "manifest.json").write_bytes(manifest_bytes)
    return {
        "status": "admitted",
        "trace_sha256": trace_digest,
        "manifest_sha256": manifest_digest,
        "manifest_object": manifest_relative,
        "manifest": str(readable_dir / "manifest.json"),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=pathlib.Path)
    parser.add_argument("--snapshot", type=pathlib.Path, required=True)
    parser.add_argument("--evidence-root", type=pathlib.Path, default=pathlib.Path(".yatou/evidence"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    print(
        json.dumps(
            admit(arguments.trace, arguments.snapshot, arguments.evidence_root),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
