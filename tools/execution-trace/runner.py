"""Run JavaScript with opt-in Inspector coverage and rank dynamic blockers."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

import yatouv8


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--source", type=pathlib.Path, required=True)
    result.add_argument("--output", type=pathlib.Path, required=True)
    result.add_argument("--url", default="https://fixture.invalid/")
    result.add_argument("--symbol", action="append", dest="symbols")
    result.add_argument("--get-trace", action="store_true")
    result.add_argument("--max-scripts", type=int, default=256)
    result.add_argument("--max-source-bytes", type=int, default=1_048_576)
    return result


def main() -> int:
    arguments = parser().parse_args()
    source = arguments.source.read_text(encoding="utf-8")
    config = yatouv8.RuntimeConfig(
        url=arguments.url,
        get_trace=yatouv8.GetTraceConfig(
            enabled=arguments.get_trace,
            max_events=100_000,
        ),
        execution_trace=yatouv8.ExecutionTraceConfig(
            enabled=True,
            capture_source=True,
            max_scripts=arguments.max_scripts,
            max_source_bytes=arguments.max_source_bytes,
        ),
    )
    eval_result: Any = None
    eval_error: dict[str, str] | None = None
    with yatouv8.Runtime(config) as runtime:
        try:
            eval_result = runtime.eval(source)
        except yatouv8.JSException as error:
            eval_error = {"name": error.name, "message": error.message}
        capture = runtime.execution_trace
        get_trace = runtime.trace if arguments.get_trace else None
        get_trace_stats = runtime.get_trace_stats
    symbols = arguments.symbols or ["knitsail", "td", "sgs"]
    analysis = yatouv8.analyze_execution_trace(capture, symbols)
    artifact = {
        "schema": "yatouv8-execution-diagnostic/v1",
        "source": {
            "path": str(arguments.source.resolve()),
            "length_bytes": len(source.encode("utf-8")),
        },
        "eval_result": eval_result,
        "eval_error": eval_error,
        "execution_trace": capture,
        "analysis": analysis,
        "get_trace": get_trace,
        "get_trace_stats": get_trace_stats,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=repr),
        encoding="utf-8",
    )
    temporary.replace(arguments.output)
    print(json.dumps({
        "output": str(arguments.output.resolve()),
        "eval_error": eval_error,
        "coverage": capture.get("summary"),
        "blockers": analysis.get("summary"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
