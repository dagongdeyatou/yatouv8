"""Run the live Google VM flow in a fresh, hidden Chrome profile.

This is a negative control for the HTTP acceptance runner.  It intentionally
uses Chrome's own DOM, VM, cookie jar and navigation stack, and persists only
response hashes plus redacted cookie metadata.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
import time
from typing import Any


COLLECTOR_PATH = pathlib.Path(__file__).parents[1] / "chrome-collector" / "collector.py"
SPEC = importlib.util.spec_from_file_location("yatouv8_chrome_collector", COLLECTOR_PATH)
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


def page_state(client: Any, session_id: str) -> dict[str, Any]:
    """Read bounded terminal markers from the current top-level document."""

    result = client.call(
        "Runtime.evaluate",
        {
            "expression": """
(() => {
  const html = document.documentElement?.outerHTML || "";
  return {
    url: location.href,
    ready_state: document.readyState,
    length: new TextEncoder().encode(html).length,
    sha256_input: html,
    sorry: location.pathname.startsWith("/sorry/") ||
      document.body?.innerText.includes("异常流量") ||
      document.body?.innerText.includes("unusual traffic from your computer network"),
    result_dom: Boolean(document.querySelector("#search h3, #rso h3")) ||
      html.includes("SearchResultsPage"),
    webdriver: navigator.webdriver,
    user_agent: navigator.userAgent,
    platform: navigator.platform
  };
})()
""".strip(),
            "returnByValue": True,
            "awaitPromise": True,
        },
        session_id=session_id,
    )
    if "exceptionDetails" in result:
        raise RuntimeError(f"page-state probe failed: {result['exceptionDetails']}")
    state = dict(result.get("result", {}).get("value") or {})
    html = str(state.pop("sha256_input", ""))
    state["sha256"] = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return state


def document_responses(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return top-level/document response evidence in observed order."""

    records = []
    for message in events:
        if message.get("method") != "Network.responseReceived":
            continue
        params = message.get("params", {})
        if params.get("type") != "Document":
            continue
        response = params.get("response", {})
        records.append({
            "status": int(response.get("status", 0)),
            "url": str(response.get("url", "")),
            "protocol": str(response.get("protocol", "")),
            "from_disk_cache": bool(response.get("fromDiskCache", False)),
            "from_service_worker": bool(response.get("fromServiceWorker", False)),
        })
    return records


def redacted_sg_ss(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return SG_SS metadata without writing token values."""

    output = []
    for cookie in cookies:
        if cookie.get("name") != "SG_SS":
            continue
        value = str(cookie.get("value", ""))
        output.append({
            "domain": cookie.get("domain"),
            "path": cookie.get("path"),
            "secure": cookie.get("secure"),
            "value": "0" if value == "0" else f"<redacted:{len(value)}>",
            "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
        })
    return output


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    """Run one isolated Chrome control and return its evidence report."""

    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    transcript_path = output.with_suffix(".cdp.ndjson")
    stderr_path = output.with_suffix(".chrome.stderr.log")
    chrome = collector.ChromeProcess(arguments.chrome, "headless", stderr_path)
    if arguments.proxy:
        chrome.flags.insert(-1, f"--proxy-server={arguments.proxy}")
    chrome.flags.insert(-1, "--lang=zh-CN")
    client = None
    target_id = None
    cleanup_verified = False
    started_ms = time.time_ns() / 1_000_000
    final_state: dict[str, Any] = {}
    browser: dict[str, Any] = {}
    cookies: list[dict[str, Any]] = []
    try:
        websocket_url = chrome.start(arguments.timeout)
        with transcript_path.open("wb") as transcript:
            client = collector.CdpClient(
                websocket_url,
                collector.Transcript(transcript),
                arguments.timeout,
            )
            browser = client.call("Browser.getVersion")
            target_id = client.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session_id = client.call(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
            )["sessionId"]
            client.call("Runtime.enable", session_id=session_id)
            client.call("Page.enable", session_id=session_id)
            client.call("Network.enable", session_id=session_id)
            if not arguments.raw_headless_identity:
                product = str(browser.get("product", ""))
                match = re.search(r"Chrome/(\d+)", product)
                major = match.group(1) if match else "151"
                client.call(
                    "Network.setUserAgentOverride",
                    {
                        "userAgent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            f"Chrome/{major}.0.0.0 Safari/537.36"
                        ),
                        "acceptLanguage": "zh-CN,zh;q=0.9",
                        "platform": "Win32",
                        "userAgentMetadata": {
                            "brands": [
                                {"brand": "Not_A Brand", "version": "99"},
                                {"brand": "Chromium", "version": major},
                                {"brand": "Google Chrome", "version": major},
                            ],
                            "fullVersionList": [
                                {"brand": "Not_A Brand", "version": "99.0.0.0"},
                                {"brand": "Chromium", "version": f"{major}.0.0.0"},
                                {"brand": "Google Chrome", "version": f"{major}.0.0.0"},
                            ],
                            "fullVersion": f"{major}.0.0.0",
                            "platform": "Windows",
                            "platformVersion": "10.0.0",
                            "architecture": "x86",
                            "model": "",
                            "mobile": False,
                            "bitness": "64",
                            "wow64": False,
                        },
                    },
                    session_id=session_id,
                )
            client.call("Page.navigate", {"url": arguments.url}, session_id=session_id)

            deadline = time.monotonic() + arguments.timeout
            while time.monotonic() < deadline:
                try:
                    final_state = page_state(client, session_id)
                except RuntimeError:
                    time.sleep(0.1)
                    continue
                if final_state.get("sorry") or final_state.get("result_dom"):
                    break
                time.sleep(0.2)

            cookies = client.call("Network.getAllCookies", session_id=session_id).get(
                "cookies", []
            )
            with contextlib.suppress(Exception):
                client.call("Browser.close")
    finally:
        if client is not None:
            if target_id is not None:
                with contextlib.suppress(Exception):
                    client.call("Target.closeTarget", {"targetId": target_id})
            client.close()
        cleanup_verified = chrome.close()

    responses = document_responses(client.events if client is not None else [])
    report = {
        "schema": "yatouv8-google-vm-chrome-control/v1",
        "started_unix_ms": round(started_ms, 3),
        "finished_unix_ms": round(time.time_ns() / 1_000_000, 3),
        "target": arguments.url,
        "proxy": arguments.proxy,
        "raw_headless_identity": arguments.raw_headless_identity,
        "browser": browser,
        "final": final_state,
        "documents": responses,
        "sg_ss": redacted_sg_ss(cookies),
        "accepted": bool(final_state.get("result_dom") and not final_state.get("sorry")),
        "cleanup_verified": cleanup_verified,
    }
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    if transcript_path.exists():
        transcript_path.unlink()
    if stderr_path.exists() and not stderr_path.stat().st_size:
        stderr_path.unlink()
    return report


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    parser.add_argument(
        "--chrome",
        type=pathlib.Path,
        default=collector.DEFAULT_CHROME,
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--raw-headless-identity",
        action="store_true",
        help="Do not replace the HeadlessChrome UA/client hints with desktop Chrome values.",
    )
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args()


def main() -> int:
    report = run(parse_arguments())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
