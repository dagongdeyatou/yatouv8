"""Run the td-initialization candidate probe against Chrome, iv8_rs and yatouv8."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("probe.js")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_yatou(source: str) -> Any:
    import yatouv8

    config = yatouv8.RuntimeConfig(url="https://www.google.com/search?q=yatouv8")
    with yatouv8.Runtime(config) as runtime:
        return runtime.eval(source)


def run_iv8(source: str) -> Any:
    import iv8_rs

    context = iv8_rs.JSContext()
    try:
        return context.eval(source)
    finally:
        context.close()


def run_chrome(source: str, chrome: Path, work: Path, timeout: float) -> Any:
    collector = load_module(
        "yatou_semantic_chrome_collector",
        ROOT / "tools" / "host-conformance" / "collector.py",
    )
    probe = work / "probe.js"
    result = work / "chrome.json"
    work.mkdir(parents=True, exist_ok=True)
    probe.write_text(source, encoding="utf-8")
    collector.collect(chrome, result, timeout, probe)
    report = json.loads(result.read_text(encoding="utf-8"))
    if not report.get("cleanup_verified"):
        raise RuntimeError("Chrome probe cleanup was not verified")
    return report["result"]


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value}
    result: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(flatten(child, path))
        else:
            result[path] = child
    return result


def compare(oracle: Any, candidate: Any) -> list[dict[str, Any]]:
    left = flatten(oracle)
    right = flatten(candidate)
    differences = []
    for path in sorted(set(left) | set(right)):
        if canonical(left.get(path)) != canonical(right.get(path)):
            differences.append({"path": path, "chrome": left.get(path), "candidate": right.get(path)})
    return differences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("all", "chrome", "iv8", "yatou"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--chrome",
        type=Path,
        default=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    source = PROBE.read_text(encoding="utf-8")
    backends = ("chrome", "iv8", "yatou") if args.backend == "all" else (args.backend,)
    results: dict[str, Any] = {}
    for backend in backends:
        if backend == "chrome":
            results[backend] = run_chrome(source, args.chrome, args.output.parent / "chrome-work", args.timeout)
        elif backend == "iv8":
            results[backend] = run_iv8(source)
        else:
            results[backend] = run_yatou(source)
    report: dict[str, Any] = {"schema": "yatouv8-semantic-conformance/v1", "results": results}
    if "chrome" in results:
        for backend in ("iv8", "yatou"):
            if backend in results:
                report[f"chrome_vs_{backend}"] = compare(results["chrome"], results[backend])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
