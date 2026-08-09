"""Run the Google SG_SS challenge and its second hop in one curl session.

This is an online acceptance gate, not a trace collector.  GET tracing and the
V8 Inspector are deliberately left disabled so diagnostic wrappers cannot
change the value graph observed by the challenge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import time
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlsplit

import yatouv8


WINDOWS_CHROME_150_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


def inline_scripts(html: str) -> list[str]:
    """Return inline scripts in document order."""

    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)


def browser_headers(*, referer: str | None = None) -> dict[str, str]:
    """Return one coherent Windows/Chrome 150 navigation header set."""

    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "max-age=0",
        "priority": "u=0, i",
        "sec-ch-ua": '"Not_A Brand";v="99", "Chromium";v="150", "Google Chrome";v="150"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin" if referer else "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": WINDOWS_CHROME_150_UA,
    }
    if referer:
        headers["referer"] = referer
    return headers


def response_markers(response: Any) -> dict[str, Any]:
    """Classify a response without relying on one fragile CSS selector."""

    text = str(getattr(response, "text", "") or "")
    url = str(getattr(response, "url", "") or "")
    split = urlsplit(url)
    lower = text.lower()
    h3_count = len(re.findall(r"<h3\b", text, re.IGNORECASE))
    search_markers = {
        "search_results_page": "SearchResultsPage" in text,
        "search_id": bool(re.search(r'\bid=["\']search["\']', text, re.IGNORECASE)),
        "rso_id": bool(re.search(r'\bid=["\']rso["\']', text, re.IGNORECASE)),
        "result_headings": h3_count > 0,
    }
    sorry = (
        split.path.startswith("/sorry/")
        or "unusual traffic from your computer network" in lower
        or "我们的系统检测到您的计算机网络中存在异常流量" in text
    )
    result_dom = search_markers["search_results_page"] or (
        search_markers["result_headings"]
        and (search_markers["search_id"] or search_markers["rso_id"])
    )
    return {
        "status": int(getattr(response, "status_code", 0) or 0),
        "url": url,
        "length": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "sorry": sorry,
        "result_dom": result_dom,
        "h3_count": h3_count,
        "markers": search_markers,
    }


def iter_cookie_records(cookies: Any) -> Iterable[dict[str, Any]]:
    """Normalize curl_cffi/http.cookiejar-compatible cookie collections."""

    jar = getattr(cookies, "jar", cookies)
    for cookie in jar:
        if isinstance(cookie, dict):
            yield cookie
        else:
            yield {
                "name": str(cookie.name),
                "value": str(cookie.value),
                "domain": str(getattr(cookie, "domain", "")),
                "path": str(getattr(cookie, "path", "/")),
            }


def sg_ss_values(cookies: Any, *, hostname: str | None = None) -> list[str]:
    """Return SG_SS values visible to the target host."""

    values = []
    hostname = (hostname or "").lower()
    for cookie in iter_cookie_records(cookies):
        if cookie.get("name") != "SG_SS":
            continue
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        if hostname and domain and not (hostname == domain or hostname.endswith("." + domain)):
            continue
        values.append(str(cookie.get("value", "")))
    return values


def set_cookie_lines(response: Any) -> list[str]:
    """Collect Set-Cookie lines across redirects without exposing token values."""

    lines: list[str] = []
    for item in [*list(getattr(response, "history", []) or []), response]:
        headers = getattr(item, "headers", None)
        if headers is None:
            continue
        getter = getattr(headers, "get_list", None)
        if callable(getter):
            lines.extend(str(value) for value in getter("set-cookie"))
            continue
        value = headers.get("set-cookie") if hasattr(headers, "get") else None
        if value:
            lines.append(str(value))
    return lines


def sg_ss_consumed(response: Any, cookies: Any, *, hostname: str) -> bool:
    """Recognize Google's one-shot SG_SS=0 acknowledgement."""

    if "0" in sg_ss_values(cookies, hostname=hostname):
        return True
    return any(re.match(r"\s*SG_SS=0(?:;|$)", line, re.IGNORECASE) for line in set_cookie_lines(response))


def valid_navigation(navigation: Any, *, source_url: str) -> bool:
    """Require location.replace to preserve the redirected challenge entrypoint."""

    if not (
        isinstance(navigation, dict)
        and navigation.get("kind") == "replace"
        and navigation.get("from") == source_url
        and isinstance(navigation.get("url"), str)
    ):
        return False
    source = urlsplit(source_url)
    destination = urlsplit(navigation["url"])
    source_query = dict(parse_qsl(source.query, keep_blank_values=True))
    destination_query = dict(parse_qsl(destination.query, keep_blank_values=True))
    return bool(
        (destination.scheme, destination.netloc, destination.path)
        == (source.scheme, source.netloc, source.path)
        and all(destination_query.get(key) == value for key, value in source_query.items())
        and destination_query.get("sei")
    )


def redacted_token(cookie: dict[str, Any] | None) -> dict[str, Any] | None:
    """Persist token lineage while keeping the actual challenge token secret."""

    if cookie is None:
        return None
    value = str(cookie.get("value", ""))
    return {
        "name": cookie.get("name"),
        "domain": cookie.get("domain"),
        "path": cookie.get("path"),
        "value_prefix": value[:1],
        "value_length": len(value),
        "value_sha256": hashlib.sha256(value.encode()).hexdigest(),
    }


def inject_sg_ss(session: Any, cookie: dict[str, Any]) -> None:
    """Merge only the generated SG_SS record into the original session jar."""

    session.cookies.set(
        "SG_SS",
        str(cookie["value"]),
        domain=str(cookie.get("domain") or ""),
        path=str(cookie.get("path") or "/"),
    )


def execute_challenge(
    response: Any,
    cookies: Any,
    *,
    navigation_start_ms: float,
) -> dict[str, Any]:
    """Execute the first four inline scripts with a request-coupled clock."""

    scripts = inline_scripts(response.text)
    selected = scripts[:4]
    config = yatouv8.RuntimeConfig.from_curl_response(
        response,
        navigation_start_ms=navigation_start_ms,
        profile=yatouv8.BrowserProfile(user_agent=WINDOWS_CHROME_150_UA),
        get_trace=yatouv8.GetTraceConfig(enabled=False),
        execution_trace=yatouv8.ExecutionTraceConfig(enabled=False),
    )
    errors = []
    with yatouv8.Runtime(config) as runtime:
        imported = runtime.import_cookies(cookies)
        for index, source in enumerate(selected):
            try:
                runtime.eval(source)
            except yatouv8.JSException as error:
                errors.append({"script_index": index, "name": error.name, "message": error.message})
        drained = runtime.drain(10_000)
        state = runtime.eval(
            "({knitsail:typeof globalThis.knitsail,sgs:typeof globalThis.sgs,"
            "td:globalThis.td||null,now:performance.now(),"
            "timing:{navigationStart:performance.timing.navigationStart,"
            "responseStart:performance.timing.responseStart,"
            "responseEnd:performance.timing.responseEnd}})"
        )
        exported = runtime.export_cookies()
        navigation = runtime.take_navigation()
    generated = [cookie for cookie in exported if cookie.get("name") == "SG_SS"]
    return {
        "inline_script_count": len(scripts),
        "executed_script_count": len(selected),
        "imported_cookie_count": imported,
        "errors": errors,
        "drain": drained,
        "state": state,
        "sg_ss": generated[-1] if generated else None,
        "navigation": navigation,
        "clock": config.profile.clock,
        "navigation_timing": config.profile.navigation_timing,
        "navigation_entry": config.profile.navigation_entry,
    }


def run_attempt(
    *,
    target: str,
    proxy: str,
    timeout: float,
    impersonate: str,
) -> dict[str, Any]:
    """Run one cold HTTP session, homepage warm-up, VM handoff and second hop."""

    try:
        from curl_cffi import CurlInfo
        from curl_cffi.requests import Session
    except ImportError as error:  # pragma: no cover - environment error
        raise RuntimeError("live acceptance requires curl_cffi") from error

    infos = [
        CurlInfo.NAMELOOKUP_TIME,
        CurlInfo.CONNECT_TIME,
        CurlInfo.APPCONNECT_TIME,
        CurlInfo.PRETRANSFER_TIME,
        CurlInfo.STARTTRANSFER_TIME,
        CurlInfo.TOTAL_TIME,
        CurlInfo.HTTP_VERSION,
        CurlInfo.SIZE_DOWNLOAD_T,
        CurlInfo.HEADER_SIZE,
    ]
    origin = urlsplit(target)
    home_url = f"{origin.scheme}://{origin.netloc}/"
    proxies = {"http": proxy, "https": proxy} if proxy else None
    started_ms = time.time_ns() / 1_000_000
    with Session(impersonate=impersonate, curl_infos=infos, proxies=proxies) as session:
        home = session.get(
            home_url,
            headers=browser_headers(),
            timeout=timeout,
            allow_redirects=True,
        )
        request_start_ms = time.time_ns() / 1_000_000
        first = session.get(
            target,
            headers=browser_headers(referer=str(home.url)),
            timeout=timeout,
            allow_redirects=True,
        )
        first_markers = response_markers(first)
        vm = execute_challenge(first, session.cookies, navigation_start_ms=request_start_ms)
        token = vm.pop("sg_ss")
        navigation = vm.get("navigation")
        if token is not None:
            inject_sg_ss(session, token)

        second = None
        second_markers = None
        consumed = False
        if isinstance(navigation, dict) and isinstance(navigation.get("url"), str):
            second = session.get(
                navigation["url"],
                headers=browser_headers(referer=str(first.url)),
                timeout=timeout,
                allow_redirects=True,
            )
            second_markers = response_markers(second)
            consumed = sg_ss_consumed(second, session.cookies, hostname=origin.hostname or "")

        predicates = {
            "homepage_200": home.status_code == 200,
            "challenge_200": first.status_code == 200,
            "challenge_scripts_complete": vm["executed_script_count"] == 4 and not vm["errors"],
            "knitsail_initialized": vm["state"].get("knitsail") == "object",
            "sg_ss_generated": bool(token and str(token.get("value", "")).startswith("*")),
            "same_entrypoint_navigation_with_sei": valid_navigation(
                navigation,
                source_url=str(first.url),
            ),
            "second_hop_200": bool(second_markers and second_markers["status"] == 200),
            "second_hop_not_sorry": bool(second_markers and not second_markers["sorry"]),
            "search_results_dom": bool(second_markers and second_markers["result_dom"]),
            "sg_ss_consumed_to_zero": consumed,
        }
        return {
            "started_unix_ms": round(started_ms, 3),
            "finished_unix_ms": round(time.time_ns() / 1_000_000, 3),
            "accepted": all(predicates.values()),
            "predicates": predicates,
            "home": response_markers(home),
            "first": first_markers,
            "vm": vm,
            "generated_sg_ss": redacted_token(token),
            "second": second_markers,
            "post_second_sg_ss_values": [
                "0" if value == "0" else f"<redacted:{len(value)}>"
                for value in sg_ss_values(session.cookies, hostname=origin.hostname or "")
            ],
        }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.google.com/search?q=亚非")
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--impersonate", default="chrome146")
    parser.add_argument("--output", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.attempts < 1 or arguments.attempts > 20:
        raise SystemExit("--attempts must be in 1..=20")
    attempts = []
    for index in range(arguments.attempts):
        try:
            attempt = run_attempt(
                target=arguments.url,
                proxy=arguments.proxy,
                timeout=arguments.timeout,
                impersonate=arguments.impersonate,
            )
        except Exception as error:  # preserve bounded online evidence
            attempt = {
                "accepted": False,
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        attempt["attempt"] = index + 1
        attempts.append(attempt)
        if attempt.get("accepted"):
            break

    report = {
        "schema": "yatouv8-google-vm-live-acceptance/v1",
        "target": arguments.url,
        "proxy": arguments.proxy,
        "network_profile": (
            f"curl_cffi {arguments.impersonate} TLS + explicit Windows Chrome 150 headers"
        ),
        "diagnostics": {"get_trace_enabled": False, "execution_trace_enabled": False},
        "accepted": any(attempt.get("accepted") for attempt in attempts),
        "attempts": attempts,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(arguments.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
