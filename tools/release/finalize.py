"""Create the content-addressed M10 terminal acceptance report."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import shutil
from typing import Any


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def store(root: pathlib.Path, source: pathlib.Path) -> dict[str, Any]:
    digest = sha256(source)
    relative = pathlib.Path("objects") / "sha256" / digest[:2] / digest
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(destination) != digest:
            raise RuntimeError(f"content-address collision: {destination}")
    else:
        temporary = destination.with_suffix(".tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    return {
        "logical_name": source.name,
        "source_path": str(source.resolve()),
        "object_path": relative.as_posix(),
        "sha256": digest,
        "size_bytes": source.stat().st_size,
    }


def finalize(args: argparse.Namespace) -> pathlib.Path:
    m6, m8, m9 = load(args.m6), load(args.m8), load(args.m9)
    performance, audit = load(args.performance), load(args.audit)
    m6_predicates = m6["predicates"]
    predicates = {
        "m6_archived_botguard_conformant": (
            m6_predicates["trace_conformant"]
            and m6_predicates["matching_events"] == 7
            and m6_predicates["replay_fully_consumed"]
            and not m6_predicates["network_fallback"]
        ),
        "m7_python_sdk_wheel_verified": audit["accepted"],
        "m8_host_conformant": (
            m8["conformant"]
            and m8["chrome_cleanup_verified"]
            and m8["trace_complete"]
            and not m8["network_fallback"]
        ),
        "m9_current_public_loaders_conformant": (
            m9["all_loaders_conformant"]
            and m9["mirror_release_match"]
            and m9["negative_control_rejected"]
            and m9["chrome_cleanup_verified"]
        ),
        "m10_quality_gate": performance["accepted"],
        "m10_release_audit": audit["accepted"],
        "current_live_challenge_claimed": False,
    }
    if not all(value for key, value in predicates.items() if key != "current_live_challenge_claimed"):
        raise RuntimeError(f"M10 predicates failed: {predicates}")

    root = args.output_root.resolve()
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + secrets.token_hex(4)
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    sources = [args.m6, args.m8, args.m9, args.performance, args.wheel, args.sbom, args.audit]
    artifacts = []
    for source in sources:
        artifact = store(root, source)
        destination = run / source.name
        shutil.copyfile(source, destination)
        artifacts.append(artifact)

    report = {
        "schema_version": 1,
        "milestone": "M10",
        "status": "terminal_complete",
        "version": "0.1.1",
        "run_id": run_id,
        "completed_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "predicates": predicates,
        "coverage": {
            "milestones": ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"],
            "m8_trace_events": m8["trace_events"],
            "m9_release": m9["release"],
            "performance_trace_events": performance["trace_events"],
            "sbom_components": audit["sbom"]["component_count"],
        },
        "limitations": {
            "current_live_google_challenge": "not claimed",
            "current_public_loader": "verified on google.com and recaptcha.net",
            "current_gstatic_second_stage": "acquired and content-addressed; challenge execution is outside M10 claim",
            "layout_engine": "not implemented by MVP design",
        },
        "cleanup_verified": True,
        "artifacts": artifacts,
    }
    report_path = run / "m10.report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    report_hash = sha256(report_path)
    (run / "m10.report.sha256").write_text(f"{report_hash}  m10.report.json\n", encoding="ascii")
    store(root, report_path)
    print(report_path)
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m6", required=True, type=pathlib.Path)
    parser.add_argument("--m8", required=True, type=pathlib.Path)
    parser.add_argument("--m9", required=True, type=pathlib.Path)
    parser.add_argument("--performance", required=True, type=pathlib.Path)
    parser.add_argument("--wheel", required=True, type=pathlib.Path)
    parser.add_argument("--sbom", required=True, type=pathlib.Path)
    parser.add_argument("--audit", required=True, type=pathlib.Path)
    parser.add_argument("--output-root", type=pathlib.Path, default=pathlib.Path(".yatou/evidence/reports/m10"))
    finalize(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
