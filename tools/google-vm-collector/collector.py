#!/usr/bin/env python3
"""Capture a normative and instrumented Chrome trace for the archived Google BotGuard VM."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import pathlib
import secrets
import sys
from typing import Any


CHROME_COLLECTOR = pathlib.Path(__file__).parents[1] / "chrome-collector"
sys.path.insert(0, str(CHROME_COLLECTOR))
from collector import (  # noqa: E402
    CdpClient,
    ChromeProcess,
    DEFAULT_CHROME,
    Transcript,
    canonical_json_bytes,
    evaluate,
    sha256_file,
    store_object,
    utc_now,
    write_artifact,
)


BASELINE_ID = "win11-chrome150.0.7871.188-headful-m2-v2"
MODEL_SHA256 = "eb283e820750810020f120000c99008dcf8930d9ce9d8b881a01ff88157bb9ff"
BYTECODE_SHA256 = "f2f5fee92d9717e207fc88d4c9893370df86d23e78c47252fbf0f30422f086f0"
SHAPE_SHA256 = "3aa5c21179d18c00217ac31433aae57bc2cb7eacab7ae70df3a72d7f8b927cd0"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_id() -> str:
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def attach_blank(client: CdpClient) -> tuple[str, str]:
    target_id = client.call("Target.createTarget", {"url": "about:blank"})["targetId"]
    session_id = client.call(
        "Target.attachToTarget", {"targetId": target_id, "flatten": True}
    )["sessionId"]
    client.call("Runtime.enable", session_id=session_id)
    return target_id, session_id


def invocation_expression(model: str, encoded: str, instrumented: bool) -> str:
    setup = ""
    calls = "[]"
    if instrumented:
        setup = r"""
const __calls = [];
const __addEventListener = window.addEventListener;
window.addEventListener = function addEventListener(...args) {
  const result = Reflect.apply(__addEventListener, this, args);
  __calls.push({target:"EventTarget.prototype",member:"addEventListener",arguments:[{kind:"string",preview:"string"}],outcome:{kind:"undefined",preview:"undefined"}});
  return result;
};
const __atob = window.atob;
window.atob = function atob(input) {
  const result = Reflect.apply(__atob, this, arguments);
  __calls.push({target:"globalThis",member:"atob",arguments:[{kind:"string",preview:`chars:${String(input).length}`}],outcome:{kind:"string",preview:`bytes:${result.length}`}});
  return result;
};
const __btoa = window.btoa;
window.btoa = function btoa(input) {
  const result = Reflect.apply(__btoa, this, arguments);
  __calls.push({target:"globalThis",member:"btoa",arguments:[{kind:"string",preview:`bytes:${String(input).length}`}],outcome:{kind:"string",preview:`chars:${result.length}`}});
  return result;
};
const __now = performance.now;
performance.now = function now() {
  const result = Reflect.apply(__now, this, arguments);
  __calls.push({target:"Performance.prototype",member:"now",arguments:[],outcome:{kind:"number",preview:"number"}});
  return result;
};
"""
        calls = "__calls"
    return f"""(() => {{
{setup}
{model}
const instance = new botguard.bg({json.dumps(encoded)});
const token = instance.invoke();
return {{
  token,
  token_type: typeof token,
  token_length: typeof token === "string" ? token.length : -1,
  starts_with_bang: typeof token === "string" && token.startsWith("!"),
  error: instance.o ?? null,
  webdriver: navigator.webdriver,
  calls: {calls}
}};
}})()"""


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    token = result.pop("token")
    result["token_sha256"] = sha256_bytes(token.encode("utf-8"))
    return result


def value_summary(value: dict[str, str]) -> dict[str, Any]:
    return {"kind": value["kind"], "preview": value["preview"], "sha256": None}


def trace_ndjson(calls: list[dict[str, Any]]) -> bytes:
    records: list[dict[str, Any]] = [
        {
            "record_type": "header",
            "record": {
                "schema_version": 1,
                "trace_id": "google-botguard-archived-m6-chrome",
                "baseline_id": BASELINE_ID,
                "source": "chrome",
                "created_at": "2026-08-07T00:00:00Z",
                "producer": "yatouv8-google-vm-collector/0.1.0",
            },
        },
        {
            "record_type": "event",
            "record": {
                "seq": 0,
                "logical_time_ns": 0,
                "parent_seq": None,
                "level": "l0",
                "entry": {
                    "kind": "eval_start",
                    "eval_id": "botguard.invoke",
                    "source_sha256": MODEL_SHA256,
                },
            },
        },
    ]
    for index, call in enumerate(calls, start=1):
        records.append(
            {
                "record_type": "event",
                "record": {
                    "seq": index,
                    "logical_time_ns": index,
                    "parent_seq": 0,
                    "level": "l1",
                    "entry": {
                        "operation": "call",
                        "target": call["target"],
                        "member": call["member"],
                        "arguments": [value_summary(item) for item in call["arguments"]],
                        "outcome": {
                            "kind": "return",
                            "value": value_summary(call["outcome"]),
                        },
                        "call_site": None,
                    },
                },
            }
        )
    checkpoint_seq = len(calls) + 1
    records.extend(
        [
            {
                "record_type": "event",
                "record": {
                    "seq": checkpoint_seq,
                    "logical_time_ns": checkpoint_seq,
                    "parent_seq": 0,
                    "level": "l0",
                    "entry": {
                        "kind": "checkpoint",
                        "name": "botguard.result.shape",
                        "state_sha256": SHAPE_SHA256,
                    },
                },
            },
            {
                "record_type": "event",
                "record": {
                    "seq": checkpoint_seq + 1,
                    "logical_time_ns": checkpoint_seq + 1,
                    "parent_seq": 0,
                    "level": "l0",
                    "entry": {
                        "kind": "eval_end",
                        "eval_id": "botguard.invoke",
                        "outcome": "return",
                    },
                },
            },
            {
                "record_type": "footer",
                "record": {
                    "event_count": checkpoint_seq + 2,
                    "l0_count": 3,
                    "l1_count": len(calls),
                    "last_seq": checkpoint_seq + 1,
                    "complete": True,
                },
            },
        ]
    )
    return b"".join(canonical_json_bytes(record) for record in records)


def collect(args: argparse.Namespace) -> pathlib.Path:
    model_bytes = args.model.read_bytes()
    bytecode = args.bytecode.read_bytes()
    if sha256_bytes(model_bytes) != MODEL_SHA256:
        raise ValueError("model.js SHA-256 does not match the pinned Google artifact")
    if sha256_bytes(bytecode) != BYTECODE_SHA256:
        raise ValueError("enc SHA-256 does not match the pinned Google artifact")
    model = model_bytes.decode("utf-8")
    import base64

    encoded = base64.b64encode(bytecode).decode("ascii")
    identifier = run_id()
    output_root = args.output_root.resolve()
    temp = output_root / ".tmp"
    temp.mkdir(parents=True, exist_ok=True)
    transcript_path = temp / f"{identifier}.google-vm.cdp.ndjson"
    stderr_path = temp / f"{identifier}.google-vm.chrome.stderr.log"
    chrome = ChromeProcess(args.chrome, "headful", stderr_path)
    client: CdpClient | None = None
    targets: list[str] = []
    cleanup_verified = False
    started_at = utc_now()
    try:
        websocket_url = chrome.start(args.timeout)
        with transcript_path.open("wb") as stream:
            client = CdpClient(websocket_url, Transcript(stream), args.timeout)
            browser = client.call("Browser.getVersion")
            target, session = attach_blank(client)
            targets.append(target)
            oracle = evaluate(client, session, invocation_expression(model, encoded, False))
            client.call("Target.closeTarget", {"targetId": target})
            targets.remove(target)
            target, session = attach_blank(client)
            targets.append(target)
            diagnostic = evaluate(client, session, invocation_expression(model, encoded, True))
            client.call("Target.closeTarget", {"targetId": target})
            targets.remove(target)
            with contextlib.suppress(Exception):
                client.call("Browser.close")
    finally:
        if client is not None:
            for target in targets:
                with contextlib.suppress(Exception):
                    client.call("Target.closeTarget", {"targetId": target})
            client.close()
        cleanup_verified = chrome.close()

    oracle = public_result(oracle)
    diagnostic = public_result(diagnostic)
    for name, result in (("oracle", oracle), ("diagnostic", diagnostic)):
        if result["token_length"] != 199 or not result["starts_with_bang"] or result["error"]:
            raise RuntimeError(f"{name} BotGuard predicate failed: {result}")
        if result["webdriver"] is not False:
            raise RuntimeError(f"{name} was contaminated by webdriver=true")
    if [call["member"] for call in diagnostic["calls"]] != [
        "addEventListener",
        "atob",
        "now",
        "btoa",
    ]:
        raise RuntimeError(f"unexpected diagnostic call order: {diagnostic['calls']}")
    trace = trace_ndjson(diagnostic["calls"])
    run_dir = output_root / "reports" / "m6" / identifier
    run_dir.mkdir(parents=True, exist_ok=False)
    artifacts = [
        write_artifact(output_root, run_dir, "raw_cdp", "raw.cdp.ndjson", transcript_path.read_bytes(), "application/x-ndjson", []),
        write_artifact(output_root, run_dir, "chrome_oracle", "oracle.json", canonical_json_bytes(oracle), "application/json", ["raw_cdp"]),
        write_artifact(output_root, run_dir, "instrumented_diagnostic", "diagnostic.json", canonical_json_bytes(diagnostic), "application/json", ["raw_cdp"]),
        write_artifact(output_root, run_dir, "chrome_trace", "chrome.trace.ndjson", trace, "application/x-ndjson", ["instrumented_diagnostic", "chrome_oracle"]),
    ]
    if stderr_path.exists() and stderr_path.stat().st_size:
        artifacts.append(write_artifact(output_root, run_dir, "chrome_stderr", "chrome.stderr.log", stderr_path.read_bytes(), "text/plain; charset=utf-8", []))
    manifest = {
        "schema_version": 1,
        "baseline_id": BASELINE_ID,
        "run_id": identifier,
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": "complete",
        "cleanup_verified": cleanup_verified,
        "target": {
            "kind": "archived_real_google_recaptcha_botguard",
            "model_sha256": MODEL_SHA256,
            "bytecode_sha256": BYTECODE_SHA256,
            "source_url": "https://github.com/neuroradiology/InsideReCaptcha",
        },
        "browser": browser,
        "chrome_executable_sha256": sha256_file(chrome.executable),
        "artifacts": artifacts,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    (run_dir / "manifest.json").write_bytes(manifest_bytes)
    store_object(output_root, manifest_bytes)
    transcript_path.unlink(missing_ok=True)
    stderr_path.unlink(missing_ok=True)
    if not cleanup_verified:
        raise RuntimeError("Chrome cleanup could not be verified")
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=pathlib.Path, default=DEFAULT_CHROME)
    parser.add_argument("--model", type=pathlib.Path, required=True)
    parser.add_argument("--bytecode", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, default=pathlib.Path(".yatou/evidence"))
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    run_dir = collect(parse_args())
    print(canonical_json_bytes({"status": "complete", "run_dir": str(run_dir)}).decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
