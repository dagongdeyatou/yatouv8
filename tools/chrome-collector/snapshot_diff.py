#!/usr/bin/env python3
"""Compare stable Chrome snapshot fields while reporting clock distributions separately."""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
from typing import Any


def load_snapshot(path: pathlib.Path) -> dict[str, Any]:
    """Load a snapshot JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"snapshot is not an object: {path}")
    return value


def normalize(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Remove run identity and raw timing values from a comparison copy."""
    result = copy.deepcopy(snapshot)
    result.pop("run_id", None)
    result.pop("captured_at", None)
    environment = result.get("environment", {})
    environment.pop("clock_sample", None)
    profile = environment.get("clock_profile")
    if isinstance(profile, dict):
        profile.pop("samples", None)
        profile.pop("summary", None)
    return result


def differences(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    """Return deterministic JSON-pointer-like differences."""
    if type(left) is not type(right):
        return [{"path": path or "/", "left": left, "right": right}]
    if isinstance(left, dict):
        found: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{key}"
            if key not in left or key not in right:
                found.append({"path": child, "left": left.get(key), "right": right.get(key)})
            else:
                found.extend(differences(left[key], right[key], child))
        return found
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path or "/", "left_length": len(left), "right_length": len(right)}]
        found = []
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            found.extend(differences(left_item, right_item, f"{path}/{index}"))
        return found
    return [] if left == right else [{"path": path or "/", "left": left, "right": right}]


def clock_summary(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Return the retained browser-derived clock summary."""
    profile = snapshot.get("environment", {}).get("clock_profile")
    if not isinstance(profile, dict):
        return None
    return {
        "tight_loop_samples": profile["tight_loop_samples"],
        "delayed_samples": profile["delayed_samples"],
        **profile["summary"],
    }


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Build a stable-field and timing-distribution comparison report."""
    stable_differences = differences(normalize(left), normalize(right))
    return {
        "schema_version": 1,
        "left": {"baseline_id": left.get("baseline_id"), "run_id": left.get("run_id")},
        "right": {"baseline_id": right.get("baseline_id"), "run_id": right.get("run_id")},
        "stable_equal": not stable_differences,
        "stable_difference_count": len(stable_differences),
        "stable_differences": stable_differences,
        "clock_profiles": {"left": clock_summary(left), "right": clock_summary(right)},
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=pathlib.Path)
    parser.add_argument("right", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    report = compare(load_snapshot(arguments.left), load_snapshot(arguments.right))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["stable_equal"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
