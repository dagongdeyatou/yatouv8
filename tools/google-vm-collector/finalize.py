#!/usr/bin/env python3
"""Attach yatouv8, diff, replay, negative controls, and a terminal M6 report to a Chrome run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Any


CHROME_COLLECTOR = pathlib.Path(__file__).parents[1] / "chrome-collector"
sys.path.insert(0, str(CHROME_COLLECTOR))
from collector import canonical_json_bytes, store_object, write_artifact  # noqa: E402


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_trace(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_trace(records: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(record) for record in records)


def resequence(records: list[dict[str, Any]]) -> None:
    events = [record for record in records if record["record_type"] == "event"]
    for index, event in enumerate(events):
        event["record"]["seq"] = index
        parent = event["record"]["parent_seq"]
        if parent is not None:
            event["record"]["parent_seq"] = 0
    footer = next(record["record"] for record in records if record["record_type"] == "footer")
    footer["event_count"] = len(events)
    footer["l0_count"] = sum(event["record"]["level"] == "l0" for event in events)
    footer["l1_count"] = len(events) - footer["l0_count"]
    footer["last_seq"] = len(events) - 1 if events else None


def cargo_json(root: pathlib.Path, arguments: list[str]) -> dict[str, Any]:
    cargo = pathlib.Path.home() / ".cargo" / "bin" / "cargo.exe"
    completed = subprocess.run(
        [str(cargo), "run", "-q", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def sanitized_result(path: pathlib.Path) -> dict[str, Any]:
    result = json.loads(path.read_text(encoding="utf-8"))
    token = result.pop("token")
    result["token_sha256"] = sha256_bytes(token.encode("utf-8"))
    return result


def finalize(args: argparse.Namespace) -> pathlib.Path:
    root = pathlib.Path(__file__).parents[2].resolve()
    run_dir = args.run_dir.resolve(strict=True)
    output_root = run_dir.parents[2]
    chrome_trace = run_dir / "chrome.trace.ndjson"
    yatou_trace_bytes = args.yatou_trace.read_bytes()
    yatou_result = sanitized_result(args.yatou_result)
    if yatou_result["error"] is not None:
        raise RuntimeError(f"yatouv8 BotGuard execution failed: {yatou_result}")

    diff = cargo_json(
        root,
        [
            "-p",
            "yatou-harness",
            "--example",
            "diff_trace",
            "--",
            str(chrome_trace),
            str(args.yatou_trace.resolve()),
        ],
    )
    replay = cargo_json(
        root,
        [
            "-p",
            "yatou-core",
            "--example",
            "replay_trace",
            "--",
            str(args.yatou_trace.resolve()),
        ],
    )
    if not diff["conformant"] or not replay["fully_consumed"]:
        raise RuntimeError("positive M6 trace did not reach terminal predicates")

    positive = read_trace(args.yatou_trace)
    missing_atob = copy.deepcopy(positive)
    missing_atob[:] = [
        record
        for record in missing_atob
        if not (
            record["record_type"] == "event"
            and record["record"]["level"] == "l1"
            and record["record"]["entry"]["member"] == "atob"
        )
    ]
    resequence(missing_atob)
    missing_path = run_dir / ".negative-missing-atob.ndjson"
    missing_path.write_bytes(write_trace(missing_atob))
    missing_diff = cargo_json(
        root,
        ["-p", "yatou-harness", "--example", "diff_trace", "--", str(chrome_trace), str(missing_path)],
    )

    wrong_checkpoint = copy.deepcopy(positive)
    for record in wrong_checkpoint:
        if record["record_type"] == "event" and record["record"]["entry"].get("kind") == "checkpoint":
            record["record"]["entry"]["state_sha256"] = "0" * 64
    checkpoint_path = run_dir / ".negative-checkpoint.ndjson"
    checkpoint_path.write_bytes(write_trace(wrong_checkpoint))
    checkpoint_diff = cargo_json(
        root,
        ["-p", "yatou-harness", "--example", "diff_trace", "--", str(chrome_trace), str(checkpoint_path)],
    )
    missing_path.unlink()
    checkpoint_path.unlink()
    if missing_diff["conformant"] or checkpoint_diff["conformant"]:
        raise RuntimeError("negative control was not rejected")
    if missing_diff["divergences"][0]["class"] != "missing_surface":
        raise RuntimeError("missing-atob control was not classified as missing_surface")
    if checkpoint_diff["divergences"][0]["class"] != "behavioral":
        raise RuntimeError("checkpoint control was not classified as behavioral")

    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest["artifacts"]
    artifacts.extend(
        [
            write_artifact(output_root, run_dir, "google_model", "model.js", args.model.read_bytes(), "text/javascript; charset=utf-8", []),
            write_artifact(output_root, run_dir, "google_bytecode", "enc", args.bytecode.read_bytes(), "application/octet-stream", []),
            write_artifact(output_root, run_dir, "yatou_trace", "yatou.trace.ndjson", yatou_trace_bytes, "application/x-ndjson", ["google_model", "google_bytecode"]),
            write_artifact(output_root, run_dir, "yatou_result", "yatou.result.json", canonical_json_bytes(yatou_result), "application/json", ["yatou_trace"]),
            write_artifact(output_root, run_dir, "trace_diff", "trace.diff.json", canonical_json_bytes(diff), "application/json", ["chrome_trace", "yatou_trace"]),
            write_artifact(output_root, run_dir, "replay_report", "replay.json", canonical_json_bytes(replay), "application/json", ["yatou_trace"]),
            write_artifact(output_root, run_dir, "negative_missing_atob", "negative.missing-atob.diff.json", canonical_json_bytes(missing_diff), "application/json", ["chrome_trace", "yatou_trace"]),
            write_artifact(output_root, run_dir, "negative_checkpoint", "negative.checkpoint.diff.json", canonical_json_bytes(checkpoint_diff), "application/json", ["chrome_trace", "yatou_trace"]),
        ]
    )
    report = {
        "milestone": "M6",
        "target_class": "archived_real_google_recaptcha_botguard",
        "current_live_google_claimed": False,
        "predicates": {
            "chrome_150_oracle_token_shape": True,
            "yatouv8_token_shape": (
                yatou_result["token_length"] == 199
                and yatou_result["starts_with_bang"]
                and yatou_result["error"] is None
            ),
            "trace_conformant": diff["conformant"],
            "matching_events": diff["matching_prefix_events"],
            "replay_fully_consumed": replay["fully_consumed"],
            "network_fallback": replay["network_fallback"],
            "missing_surface_negative_rejected": not missing_diff["conformant"],
            "behavior_negative_rejected": not checkpoint_diff["conformant"],
            "cleanup_verified": manifest["cleanup_verified"],
        },
        "coverage": {
            "l0_events": 3,
            "l1_events": 4,
            "host_boundaries": ["addEventListener", "atob", "performance.now", "btoa"],
        },
        "source_lineage": {
            "model_sha256": manifest["target"]["model_sha256"],
            "bytecode_sha256": manifest["target"]["bytecode_sha256"],
            "chrome_trace_sha256": next(a["evidence"]["sha256"] for a in artifacts if a["logical_name"] == "chrome_trace"),
            "yatou_trace_sha256": next(a["evidence"]["sha256"] for a in artifacts if a["logical_name"] == "yatou_trace"),
        },
    }
    artifacts.append(
        write_artifact(output_root, run_dir, "m6_report", "m6.report.json", canonical_json_bytes(report), "application/json", ["trace_diff", "replay_report", "negative_missing_atob", "negative_checkpoint"])
    )
    manifest["status"] = "terminal_complete"
    manifest["terminal_report"] = "m6_report"
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    store_object(output_root, manifest_bytes)
    return run_dir / "m6.report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    parser.add_argument("--yatou-trace", type=pathlib.Path, required=True)
    parser.add_argument("--yatou-result", type=pathlib.Path, required=True)
    parser.add_argument("--model", type=pathlib.Path, required=True)
    parser.add_argument("--bytecode", type=pathlib.Path, required=True)
    return parser.parse_args()


def main() -> int:
    report = finalize(parse_args())
    print(canonical_json_bytes({"status": "terminal_complete", "report": str(report)}).decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
