"""Collect content-addressed Chrome surface evidence through raw CDP."""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, BinaryIO

import websocket


COLLECTOR_NAME = "yatouv8-chrome-collector"
COLLECTOR_VERSION = "0.1.0"
SCHEMA_VERSION = 1
DEFAULT_CHROME = pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
GLOBAL_KEYS_EXPRESSION = """
(() => Reflect.ownKeys(globalThis).map((key) => typeof key === "symbol"
  ? {kind: "symbol", display: String(key), description: key.description ?? null,
     registry_key: Symbol.keyFor(key) ?? null}
  : {kind: "string", display: key, description: null, registry_key: null}))()
""".strip()
BASELINE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp with millisecond precision."""

    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically without changing array order."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    """Hash a file without reading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_baseline_id(value: str) -> str:
    """Validate a baseline identifier against the Rust schema contract."""

    if not value or not BASELINE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"invalid baseline id: {value}")
    return value


def sanitize_flags(flags: list[str]) -> list[str]:
    """Remove ephemeral profile paths while preserving behavior-changing flags."""

    result: list[str] = []
    for flag in flags:
        if flag.startswith("--user-data-dir="):
            result.append("--user-data-dir=<ephemeral>")
        elif flag.startswith("--remote-debugging-port="):
            result.append("--remote-debugging-port=<ephemeral-nonzero>")
        else:
            result.append(flag)
    return result


def reserve_loopback_port() -> int:
    """Ask Windows for an unused nonzero loopback TCP port."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def property_key_labels(keys: list[dict[str, Any]]) -> list[str]:
    """Create stable labels suitable for pollution comparisons."""

    labels: list[str] = []
    for key in keys:
        if key["kind"] == "string":
            labels.append(f"string:{key['display']}")
        else:
            labels.append(
                "symbol:"
                + json.dumps(
                    [key.get("display"), key.get("description"), key.get("registry_key")],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
    return labels


def pollution_delta(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    """Return added and removed labels while respecting duplicate symbols."""

    before_counts = collections.Counter(before)
    after_counts = collections.Counter(after)
    added = list((after_counts - before_counts).elements())
    removed = list((before_counts - after_counts).elements())
    return added, removed


class Transcript:
    """Append-only NDJSON transcript for CDP messages."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._sequence = 0

    def write(self, direction: str, message: dict[str, Any]) -> None:
        """Write one timestamped transcript record."""

        self._sequence += 1
        record = {
            "sequence": self._sequence,
            "at": utc_now(),
            "direction": direction,
            "message": message,
        }
        self._stream.write(canonical_json_bytes(record))
        self._stream.flush()


class CdpClient:
    """Minimal synchronous raw-CDP client with flattened target sessions."""

    def __init__(self, websocket_url: str, transcript: Transcript, timeout: float) -> None:
        self._socket = websocket.create_connection(
            websocket_url,
            timeout=timeout,
            suppress_origin=True,
            http_proxy_host=None,
            http_proxy_port=None,
        )
        self._transcript = transcript
        self._next_id = 0
        self.events: list[dict[str, Any]] = []

    def close(self) -> None:
        """Close the websocket."""

        with contextlib.suppress(Exception):
            self._socket.close()

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one command and wait for its matching response."""

        self._next_id += 1
        command: dict[str, Any] = {"id": self._next_id, "method": method}
        if params is not None:
            command["params"] = params
        if session_id is not None:
            command["sessionId"] = session_id
        self._transcript.write("send", command)
        self._socket.send(json.dumps(command, ensure_ascii=False, separators=(",", ":")))

        while True:
            payload = self._socket.recv()
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            message = json.loads(payload)
            self._transcript.write("receive", message)
            if message.get("id") != command["id"]:
                self.events.append(message)
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})


class ChromeProcess:
    """Chrome process and its isolated temporary profile."""

    def __init__(self, executable: pathlib.Path, mode: str, stderr_path: pathlib.Path) -> None:
        self.executable = executable.resolve(strict=True)
        self.mode = mode
        self.stderr_path = stderr_path
        self.profile_dir = pathlib.Path(tempfile.mkdtemp(prefix="yatouv8-chrome-profile-"))
        self.process: subprocess.Popen[bytes] | None = None
        self.remote_debugging_port = reserve_loopback_port()
        self.flags = [
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self.remote_debugging_port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--metrics-recording-only",
            "--password-store=basic",
            "--window-size=1280,720",
        ]
        if mode == "headless":
            self.flags.append("--headless=new")
        else:
            # Keep the real compositor/headful execution path without covering the user's desktop.
            self.flags.append("--window-position=-32000,-32000")
        self.flags.append("about:blank")

    def start(self, timeout: float) -> str:
        """Launch Chrome and return its browser websocket URL."""

        stderr_stream = self.stderr_path.open("wb")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if self.mode == "headless" else 0
        try:
            self.process = subprocess.Popen(
                [str(self.executable), *self.flags],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_stream,
                creationflags=creation_flags,
            )
        finally:
            stderr_stream.close()

        deadline = time.monotonic() + timeout
        version_url = f"http://127.0.0.1:{self.remote_debugging_port}/json/version"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Chrome exited before CDP was ready: {self.process.returncode}")
            try:
                with opener.open(version_url, timeout=0.25) as response:
                    version = json.load(response)
                websocket_url = version.get("webSocketDebuggerUrl")
                if websocket_url:
                    return str(websocket_url)
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.05)
        raise TimeoutError(f"Chrome did not expose {version_url} within {timeout} seconds")

    def close(self) -> bool:
        """Terminate Chrome and verify removal of the isolated profile."""

        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5)

        for _ in range(20):
            try:
                shutil.rmtree(self.profile_dir)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.1)
        return (process is None or process.poll() is not None) and not self.profile_dir.exists()


def evaluate(client: CdpClient, session_id: str, expression: str) -> Any:
    """Evaluate an expression by value in the dedicated object group."""

    result = client.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "objectGroup": "yatouv8-m2-probe",
            "includeCommandLineAPI": False,
            "silent": False,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": False,
        },
        session_id=session_id,
    )
    if "exceptionDetails" in result:
        raise RuntimeError(f"probe evaluation failed: {result['exceptionDetails']}")
    remote_object = result.get("result", {})
    if "value" not in remote_object:
        raise RuntimeError(f"probe returned no by-value result: {remote_object}")
    return remote_object["value"]


def chrome_product_version(product: str) -> str:
    """Extract the four-part version from a CDP product string."""

    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", product)
    if not match:
        raise ValueError(f"could not parse Chrome product version: {product}")
    return match.group(1)


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    """Apply the admission invariants before writing evidence."""

    pollution = snapshot["pollution"]
    if not pollution["unchanged"] or pollution["added"] or pollution["removed"]:
        raise RuntimeError(f"collector polluted globalThis: {pollution}")
    if pollution["before_global_keys_sha256"] != pollution["after_global_keys_sha256"]:
        raise RuntimeError("pollution hashes disagree despite an unchanged key sequence")
    for surface in snapshot["surfaces"]:
        own_keys = surface["own_keys"]
        descriptor_keys = [descriptor["key"] for descriptor in surface["descriptors"]]
        if own_keys != descriptor_keys:
            raise RuntimeError(f"descriptor order mismatch for {surface['path']}")
    clock_profile = snapshot["environment"].get("clock_profile")
    if clock_profile is not None:
        expected = clock_profile["tight_loop_samples"] + clock_profile["delayed_samples"]
        actual = len(clock_profile["samples"])
        if actual != expected or clock_profile["summary"]["sample_count"] != actual:
            raise RuntimeError("clock profile sample count mismatch")


def store_object(output_root: pathlib.Path, data: bytes) -> tuple[str, pathlib.Path]:
    """Store bytes under their SHA-256 content address."""

    digest = sha256_bytes(data)
    relative = pathlib.Path("objects") / "sha256" / digest[:2] / digest
    destination = output_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise RuntimeError(f"content-address collision at {destination}")
    else:
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    return digest, relative


def write_artifact(
    output_root: pathlib.Path,
    run_dir: pathlib.Path,
    logical_name: str,
    filename: str,
    data: bytes,
    media_type: str,
    parents: list[str],
) -> dict[str, Any]:
    """Write a readable run copy and an immutable content-addressed copy."""

    run_path = run_dir / filename
    run_path.write_bytes(data)
    digest, relative = store_object(output_root, data)
    return {
        "logical_name": logical_name,
        "relative_path": relative.as_posix(),
        "size_bytes": len(data),
        "evidence": {"sha256": digest, "media_type": media_type},
        "parents": parents,
    }


def collect(arguments: argparse.Namespace) -> pathlib.Path:
    """Run one collector session and return the snapshot path."""

    started_at = utc_now()
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + secrets.token_hex(4)
    output_root = arguments.output_root.resolve()
    temporary_root = output_root / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    transcript_path = temporary_root / f"{run_id}.cdp.ndjson"
    stderr_path = temporary_root / f"{run_id}.chrome.stderr.log"
    probe_path = pathlib.Path(__file__).with_name("probe.js")
    probe_source = probe_path.read_text(encoding="utf-8")
    probe_sha256 = sha256_bytes(probe_source.encode("utf-8"))
    chrome = ChromeProcess(arguments.chrome, arguments.mode, stderr_path)
    cleanup_verified = False
    client: CdpClient | None = None
    target_id: str | None = None

    try:
        websocket_url = chrome.start(arguments.timeout)
        with transcript_path.open("wb") as transcript_stream:
            transcript = Transcript(transcript_stream)
            client = CdpClient(websocket_url, transcript, arguments.timeout)
            browser = client.call("Browser.getVersion")
            target_id = client.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session_id = client.call(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )["sessionId"]
            client.call("Runtime.enable", session_id=session_id)

            before_keys = evaluate(client, session_id, GLOBAL_KEYS_EXPRESSION)
            probe_result = evaluate(client, session_id, probe_source)
            after_keys = evaluate(client, session_id, GLOBAL_KEYS_EXPRESSION)
            client.call(
                "Runtime.releaseObjectGroup",
                {"objectGroup": "yatouv8-m2-probe"},
                session_id=session_id,
            )
            client.call("Target.closeTarget", {"targetId": target_id})
            target_id = None
            with contextlib.suppress(Exception):
                client.call("Browser.close")
    finally:
        if client is not None:
            if target_id is not None:
                with contextlib.suppress(Exception):
                    client.call("Target.closeTarget", {"targetId": target_id})
            client.close()
        cleanup_verified = chrome.close()

    product_version = chrome_product_version(browser["product"])
    baseline_id = validate_baseline_id(
        arguments.baseline_id
        or f"win11-chrome{product_version}-{arguments.mode}-m2-v1"
    )
    before_labels = property_key_labels(before_keys)
    after_labels = property_key_labels(after_keys)
    added, removed = pollution_delta(before_labels, after_labels)
    before_hash = sha256_bytes(canonical_json_bytes(before_keys))
    after_hash = sha256_bytes(canonical_json_bytes(after_keys))
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "run_id": run_id,
        "captured_at": utc_now(),
        "capture_mode": arguments.mode,
        "browser": {
            "protocol_version": browser["protocolVersion"],
            "product": browser["product"],
            "revision": browser["revision"],
            "user_agent": browser["userAgent"],
            "js_version": browser["jsVersion"],
        },
        "host": {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "chrome_executable": str(chrome.executable),
            "chrome_executable_sha256": sha256_file(chrome.executable),
        },
        "collector": {
            "name": COLLECTOR_NAME,
            "version": COLLECTOR_VERSION,
            "probe_sha256": probe_sha256,
            "command_line_flags": sanitize_flags(chrome.flags),
        },
        "environment": probe_result["environment"],
        "pollution": {
            "before_global_keys_sha256": before_hash,
            "after_global_keys_sha256": after_hash,
            "unchanged": before_keys == after_keys,
            "added": added,
            "removed": removed,
        },
        "surfaces": probe_result["surfaces"],
    }
    validate_snapshot(snapshot)

    run_dir = output_root / "baselines" / baseline_id / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    transcript_bytes = transcript_path.read_bytes()
    snapshot_bytes = canonical_json_bytes(snapshot)
    artifacts = [
        write_artifact(
            output_root,
            run_dir,
            "raw_cdp",
            "raw.cdp.ndjson",
            transcript_bytes,
            "application/x-ndjson",
            [],
        ),
        write_artifact(
            output_root,
            run_dir,
            "chrome_snapshot",
            "snapshot.json",
            snapshot_bytes,
            "application/json",
            ["raw_cdp"],
        ),
    ]
    stderr_bytes = stderr_path.read_bytes() if stderr_path.exists() else b""
    if stderr_bytes:
        artifacts.append(
            write_artifact(
                output_root,
                run_dir,
                "chrome_stderr",
                "chrome.stderr.log",
                stderr_bytes,
                "text/plain; charset=utf-8",
                [],
            )
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "status": "complete",
        "cleanup_verified": cleanup_verified,
        "artifacts": artifacts,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    (run_dir / "manifest.json").write_bytes(manifest_bytes)
    store_object(output_root, manifest_bytes)

    transcript_path.unlink(missing_ok=True)
    stderr_path.unlink(missing_ok=True)
    if not cleanup_verified:
        raise RuntimeError("Chrome process or temporary profile cleanup could not be verified")
    return run_dir / "snapshot.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=pathlib.Path, default=DEFAULT_CHROME)
    parser.add_argument("--output-root", type=pathlib.Path, default=pathlib.Path(".yatou/evidence"))
    parser.add_argument("--baseline-id")
    parser.add_argument("--mode", choices=("headless", "headful"), default="headless")
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    snapshot = collect(arguments)
    print(canonical_json_bytes({"status": "complete", "snapshot": str(snapshot)}).decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
