"""Admit M9 only when current public loader behavior matches Chrome exactly."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def result_from_yatou(path: pathlib.Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    result = report["result"]
    if not result["ok"] or result["json"] is None:
        raise RuntimeError(f"yatouv8 loader failed: {result}")
    return json.loads(result["json"])


def finalize(
    manifest_path: pathlib.Path,
    chrome_path: pathlib.Path,
    yatou_paths: list[pathlib.Path],
    output: pathlib.Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chrome = json.loads(chrome_path.read_text(encoding="utf-8"))
    chrome_results = {entry["name"]: entry["result"] for entry in chrome["results"]}
    probes = [entry for entry in manifest["entries"] if entry["name"].endswith("-probe")]
    if len(probes) != len(yatou_paths):
        raise RuntimeError("yatouv8 result count does not match corpus probes")
    comparisons = []
    for probe, path in zip(sorted(probes, key=lambda entry: entry["ordinal"]), yatou_paths, strict=True):
        yatou_result = result_from_yatou(path)
        chrome_result = chrome_results[probe["name"]]
        comparisons.append(
            {
                "name": probe["name"],
                "conformant": yatou_result == chrome_result,
                "chrome_sha256": hashlib.sha256(canonical(chrome_result)).hexdigest(),
                "yatou_sha256": hashlib.sha256(canonical(yatou_result)).hexdigest(),
                "chrome": chrome_result,
                "yatouv8": yatou_result,
            }
        )

    mutated = json.loads(json.dumps(comparisons[0]["yatouv8"]))
    mutated["inserted"]["src"] += ".negative-control"
    negative_control_rejected = mutated != comparisons[0]["chrome"]
    report = {
        "milestone": "m9",
        "run_id": manifest["run_id"],
        "release": manifest["release"],
        "current_public_loader_claimed": True,
        "current_live_challenge_claimed": False,
        "mirror_release_match": manifest["mirror_release_match"],
        "archived_artifacts_present": manifest["archived_artifacts_present"],
        "chrome_cleanup_verified": chrome["cleanup_verified"],
        "second_stage_network_blocked": chrome["second_stage_network_blocked"],
        "all_loaders_conformant": all(item["conformant"] for item in comparisons),
        "negative_control_rejected": negative_control_rejected,
        "comparisons": comparisons,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--chrome", required=True, type=pathlib.Path)
    parser.add_argument("--yatou", required=True, type=pathlib.Path, action="append")
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    report = finalize(args.manifest, args.chrome, args.yatou, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    accepted = (
        report["all_loaders_conformant"]
        and report["negative_control_rejected"]
        and report["chrome_cleanup_verified"]
        and report["mirror_release_match"]
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
