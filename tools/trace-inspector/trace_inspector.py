#!/usr/bin/env python3
"""Inspect M3 L0 replay and L1 API-ledger NDJSON traces."""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any


class TraceInspectionError(ValueError):
    """Raised when physical NDJSON stream invariants fail."""


def read_records(path: pathlib.Path) -> list[dict[str, Any]]:
    """Decode non-empty NDJSON records."""
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise TraceInspectionError(f"invalid JSON at line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise TraceInspectionError(f"record at line {line_number} is not an object")
        records.append(value)
    return records


def inspect_trace(path: pathlib.Path) -> dict[str, Any]:
    """Validate physical ordering and return a human-oriented trace summary."""
    records = read_records(path)
    if len(records) < 2 or records[0].get("record_type") != "header":
        raise TraceInspectionError("trace must start with one header")
    if records[-1].get("record_type") != "footer":
        raise TraceInspectionError("trace must end with one footer")
    if any(record.get("record_type") != "event" for record in records[1:-1]):
        raise TraceInspectionError("only event records may appear between header and footer")

    header = records[0]["record"]
    footer = records[-1]["record"]
    events = [record["record"] for record in records[1:-1]]
    l0_kinds: collections.Counter[str] = collections.Counter()
    l1_operations: collections.Counter[str] = collections.Counter()
    ledger = []
    previous_time = 0
    for expected, event in enumerate(events):
        if event.get("seq") != expected:
            raise TraceInspectionError(
                f"expected sequence {expected}, found {event.get('seq')}"
            )
        logical_time = event.get("logical_time_ns")
        if not isinstance(logical_time, int) or logical_time < previous_time:
            raise TraceInspectionError(f"logical time regressed at sequence {expected}")
        previous_time = logical_time
        parent = event.get("parent_seq")
        if parent is not None and (not isinstance(parent, int) or parent >= expected):
            raise TraceInspectionError(f"invalid parent at sequence {expected}")
        entry = event.get("entry", {})
        if event.get("level") == "l0":
            l0_kinds[entry.get("kind", "<missing>")] += 1
        elif event.get("level") == "l1":
            operation = entry.get("operation", "<missing>")
            l1_operations[operation] += 1
            member = entry.get("member")
            ledger.append(
                {
                    "seq": expected,
                    "operation": operation,
                    "api": entry.get("target", "<missing>")
                    + (f".{member}" if member else ""),
                    "arguments": entry.get("arguments", []),
                    "outcome": entry.get("outcome"),
                    "call_site": entry.get("call_site"),
                }
            )
        else:
            raise TraceInspectionError(f"invalid trace level at sequence {expected}")

    if (
        footer.get("event_count") != len(events)
        or footer.get("l0_count") != sum(l0_kinds.values())
        or footer.get("l1_count") != sum(l1_operations.values())
        or footer.get("last_seq") != (len(events) - 1 if events else None)
        or footer.get("complete") is not True
    ):
        raise TraceInspectionError("footer counts do not match events")

    return {
        "status": "valid_physical_stream",
        "trace_id": header.get("trace_id"),
        "baseline_id": header.get("baseline_id"),
        "source": header.get("source"),
        "event_count": len(events),
        "l0_count": sum(l0_kinds.values()),
        "l1_count": sum(l1_operations.values()),
        "l0_kinds": dict(sorted(l0_kinds.items())),
        "l1_operations": dict(sorted(l1_operations.items())),
        "api_ledger": ledger,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=pathlib.Path)
    parser.add_argument(
        "--ledger",
        action="store_true",
        help="print each L1 browser API operation after the JSON summary",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    summary = inspect_trace(arguments.trace)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if arguments.ledger:
        for event in summary["api_ledger"]:
            print(
                f"L1 seq={event['seq']} {event['operation'].upper()} "
                f"{event['api']} @ {event['call_site']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
