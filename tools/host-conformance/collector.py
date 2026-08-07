"""Collect the bounded M8 DOM/CSSOM/Event Chrome oracle result."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
from typing import Any


def load_chrome_collector() -> Any:
    """Load the existing raw-CDP implementation without duplicating process code."""

    path = pathlib.Path(__file__).parents[1] / "chrome-collector" / "collector.py"
    spec = importlib.util.spec_from_file_location("yatou_chrome_collector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(chrome_path: pathlib.Path, output: pathlib.Path, timeout: float) -> None:
    """Run one isolated Chrome target and persist its by-value oracle result."""

    chrome_tools = load_chrome_collector()
    probe = pathlib.Path(__file__).with_name("probe.js").read_text(encoding="utf-8")
    stderr = output.with_suffix(".chrome.stderr.log")
    chrome = chrome_tools.ChromeProcess(chrome_path, "headless", stderr)
    client = None
    target_id = None
    cleanup_verified = False
    transcript_buffer = io.BytesIO()
    try:
        websocket_url = chrome.start(timeout)
        transcript = chrome_tools.Transcript(transcript_buffer)
        client = chrome_tools.CdpClient(websocket_url, transcript, timeout)
        browser = client.call("Browser.getVersion")
        target_id = client.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session_id = client.call(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )["sessionId"]
        client.call("Runtime.enable", session_id=session_id)
        result = chrome_tools.evaluate(client, session_id, probe)
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

    report = {
        "browser": browser,
        "result": result,
        "cleanup_verified": cleanup_verified,
        "transcript_sha256": chrome_tools.sha256_bytes(transcript_buffer.getvalue()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(chrome_tools.canonical_json_bytes(report))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chrome",
        type=pathlib.Path,
        default=pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    )
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    arguments = parser.parse_args()
    collect(arguments.chrome, arguments.output, arguments.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
