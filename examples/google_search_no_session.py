"""Google SG_SS flow using module-level curl_cffi requests and yatouv8.

No ``Session`` object is created.  The script explicitly carries the complete
cookie jar across requests, lets yatouv8 execute the inline challenge, and
uses the navigation URL and headers returned in ``ChallengeBundle``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlsplit

import yatouv8
from curl_cffi import requests


def merge_cookies(jar: requests.Cookies, response: Any) -> None:
    """Merge cookies from every redirect and the final response."""

    for item in [*list(getattr(response, "history", []) or []), response]:
        response_cookies = getattr(item, "cookies", None)
        if response_cookies is not None:
            jar.update(response_cookies)


def response_summary(response: Any) -> dict[str, Any]:
    """Classify a Google response without storing its complete body."""

    body = str(getattr(response, "text", "") or "")
    url = str(getattr(response, "url", "") or "")
    path = urlsplit(url).path
    sorry = path.startswith("/sorry/") or "unusual traffic" in body.lower()
    h3_count = len(re.findall(r"<h3\b", body, re.IGNORECASE))
    result_dom = "SearchResultsPage" in body or (
        h3_count > 0
        and bool(re.search(r'id=["\'](?:search|rso)["\']', body, re.IGNORECASE))
    )
    return {
        "status": int(getattr(response, "status_code", 0) or 0),
        "url": url,
        "body_bytes": len(body.encode()),
        "sorry": sorry,
        "result_dom": result_dom,
        "h3_count": h3_count,
    }


def run_once(
    *,
    target: str,
    proxy: str,
    impersonate: str,
    timeout: float,
    output: Path,
) -> dict[str, Any]:
    """Run one fresh no-Session challenge attempt."""

    parsed = urlsplit(target)
    home_url = f"{parsed.scheme}://{parsed.netloc}/"
    proxies = {"http": proxy, "https": proxy} if proxy else None
    jar = requests.Cookies()

    home = requests.get(
        home_url,
        cookies=jar,
        proxies=proxies,
        impersonate=impersonate,
        headers=yatouv8.browser_headers(),
        timeout=timeout,
        allow_redirects=True,
    )
    merge_cookies(jar, home)

    request_start_ms = time.time_ns() / 1_000_000
    first = requests.get(
        target,
        cookies=jar,
        proxies=proxies,
        impersonate=impersonate,
        headers=yatouv8.browser_headers(referer=str(home.url)),
        timeout=timeout,
        allow_redirects=True,
    )
    merge_cookies(jar, first)

    bundle = yatouv8.solve_with_yatouv8(
        first,
        jar,
        navigation_start_ms=request_start_ms,
    )

    # This applies the complete exported cookie set, not only SG_SS.
    bundle.apply_cookies(jar)

    second = requests.get(
        cookies=jar,
        proxies=proxies,
        impersonate=impersonate,
        timeout=timeout,
        allow_redirects=True,
        **bundle.request_kwargs(),
    )
    merge_cookies(jar, second)

    second_state = response_summary(second)
    accepted = bool(
        second_state["status"] == 200
        and not second_state["sorry"]
        and second_state["result_dom"]
    )
    if accepted:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(str(second.text), encoding="utf-8")

    return {
        "accepted": accepted,
        "home": response_summary(home),
        "first": response_summary(first),
        "second": second_state,
        "challenge": {
            "inline_script_count": bundle.inline_script_count,
            "executed_script_count": bundle.executed_script_count,
            "navigation_has_sei": "sei=" in bundle.navigation_url,
            "sg_ss_prefix": bundle.sg_ss[:1],
            "sg_ss_length": len(bundle.sg_ss),
            "sg_ss_sha256": hashlib.sha256(bundle.sg_ss.encode()).hexdigest(),
        },
        "cookie_names": sorted({cookie.name for cookie in jar.jar}),
        "output": str(output.resolve()) if accepted else None,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="https://www.google.com/search?q=亚非",
        help="Google search URL that returns the inline challenge",
    )
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    # chrome136 is supported by the user's curl_cffi 0.13 installation.
    parser.add_argument("--impersonate", default="chrome136")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("google_result.html"))
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.attempts < 1 or arguments.attempts > 10:
        raise SystemExit("--attempts must be in 1..=10")

    attempts = []
    for number in range(1, arguments.attempts + 1):
        try:
            result = run_once(
                target=arguments.url,
                proxy=arguments.proxy,
                impersonate=arguments.impersonate,
                timeout=arguments.timeout,
                output=arguments.output,
            )
        except Exception as error:
            result = {
                "accepted": False,
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        result["attempt"] = number
        attempts.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["accepted"]:
            return 0
        if number < arguments.attempts:
            time.sleep(2)

    print(
        json.dumps(
            {"accepted": False, "attempts": len(attempts)},
            ensure_ascii=False,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
