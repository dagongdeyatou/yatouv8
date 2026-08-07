"""Compare the exact bounded M8 Chrome and yatouv8 results."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def finalize(
    chrome_path: pathlib.Path,
    yatou_path: pathlib.Path,
    output: pathlib.Path,
    milestone: str = "m8",
) -> dict[str, Any]:
    chrome = json.loads(chrome_path.read_text(encoding="utf-8"))
    yatou = json.loads(yatou_path.read_text(encoding="utf-8"))
    yatou_result = json.loads(yatou["result"]["json"])
    chrome_result = chrome["result"]
    report = {
        "milestone": milestone,
        "conformant": chrome_result == yatou_result,
        "chrome_result_sha256": hashlib.sha256(canonical(chrome_result)).hexdigest(),
        "yatou_result_sha256": hashlib.sha256(canonical(yatou_result)).hexdigest(),
        "chrome_cleanup_verified": chrome["cleanup_verified"],
        "trace_complete": yatou["trace"]["footer"]["complete"],
        "trace_events": yatou["trace"]["footer"]["event_count"],
        "network_fallback": yatou["environment"]["networkFallback"],
        "chrome": chrome_result,
        "yatouv8": yatou_result,
    }
    if not report["conformant"]:
        report["differences"] = {
            key: {"chrome": chrome_result.get(key), "yatouv8": yatou_result.get(key)}
            for key in sorted(chrome_result.keys() | yatou_result.keys())
            if chrome_result.get(key) != yatou_result.get(key)
        }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", required=True, type=pathlib.Path)
    parser.add_argument("--yatou", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--milestone", default="m8")
    arguments = parser.parse_args()
    report = finalize(
        arguments.chrome,
        arguments.yatou,
        arguments.output,
        arguments.milestone,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["conformant"] and report["chrome_cleanup_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
