"""Execute current public reCAPTCHA loaders in isolated Chrome with stage two blocked."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
from typing import Any


def load_tools() -> Any:
    path = pathlib.Path(__file__).parents[1] / "chrome-collector" / "collector.py"
    spec = importlib.util.spec_from_file_location("yatou_chrome_collector_m9", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(manifest_path: pathlib.Path, output: pathlib.Path, chrome_path: pathlib.Path, timeout: float) -> None:
    tools = load_tools()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run = manifest_path.parent
    probes = [entry for entry in manifest["entries"] if entry["name"].endswith("-probe")]
    chrome = tools.ChromeProcess(chrome_path, "headless", output.with_suffix(".chrome.stderr.log"))
    client = None
    cleanup = False
    transcript_buffer = io.BytesIO()
    results = []
    try:
        websocket_url = chrome.start(timeout)
        client = tools.CdpClient(websocket_url, tools.Transcript(transcript_buffer), timeout)
        browser = client.call("Browser.getVersion")
        for probe in probes:
            target_id = client.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session_id = client.call(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )["sessionId"]
            client.call("Runtime.enable", session_id=session_id)
            client.call("Network.enable", session_id=session_id)
            client.call(
                "Network.setBlockedURLs",
                {
                    "urls": [
                        "https://www.gstatic.com/recaptcha/releases/*",
                        "https://www.gstatic.cn/recaptcha/releases/*",
                    ]
                },
                session_id=session_id,
            )
            source = (run / probe["filename"]).read_text(encoding="utf-8")
            result = tools.evaluate(client, session_id, source)
            results.append({"name": probe["name"], "result": result})
            client.call("Target.closeTarget", {"targetId": target_id})
        with contextlib.suppress(Exception):
            client.call("Browser.close")
    finally:
        if client is not None:
            client.close()
        cleanup = chrome.close()
    report = {
        "browser": browser,
        "results": results,
        "second_stage_network_blocked": True,
        "cleanup_verified": cleanup,
        "transcript_sha256": tools.sha256_bytes(transcript_buffer.getvalue()),
    }
    output.write_bytes(tools.canonical_json_bytes(report))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument(
        "--chrome",
        type=pathlib.Path,
        default=pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    collect(args.manifest, args.output, args.chrome, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
