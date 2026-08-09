"""Measure which HTTP state must accompany a yatouv8-generated SG_SS token.

Each strategy obtains its own fresh challenge.  Challenge tokens and cookie
values are never written to the report; only response markers and redacted
token lineage are retained.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from typing import Any, Iterable
from urllib.parse import urlsplit

from curl_cffi import CurlInfo
from curl_cffi.requests import Session

from live_runner import (
    browser_headers,
    execute_challenge,
    inject_sg_ss,
    redacted_token,
    response_markers,
    sg_ss_consumed,
    valid_navigation,
)


STRATEGIES = (
    "same_session_full_jar",
    "new_session_full_jar",
    "new_session_sg_ss_only",
    "replay_consumed_sg_ss",
)


def curl_infos() -> list[CurlInfo]:
    """Return the timing fields needed by RuntimeConfig.from_curl_response."""

    return [
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


def cookie_records(cookies: Any) -> list[dict[str, Any]]:
    """Copy cookie transport fields without retaining them in final evidence."""

    jar = getattr(cookies, "jar", cookies)
    records: list[dict[str, Any]] = []
    for cookie in jar:
        if isinstance(cookie, dict):
            records.append(
                {
                    "name": str(cookie.get("name", "")),
                    "value": str(cookie.get("value", "")),
                    "domain": str(cookie.get("domain", "")),
                    "path": str(cookie.get("path", "/")),
                    "secure": bool(cookie.get("secure", False)),
                }
            )
        else:
            records.append(
                {
                    "name": str(cookie.name),
                    "value": str(cookie.value),
                    "domain": str(getattr(cookie, "domain", "")),
                    "path": str(getattr(cookie, "path", "/")),
                    "secure": bool(getattr(cookie, "secure", False)),
                }
            )
    return records


def install_cookies(session: Session, records: Iterable[dict[str, Any]]) -> None:
    """Reconstruct a curl_cffi cookie jar in a newly created session."""

    for cookie in records:
        session.cookies.set(
            str(cookie["name"]),
            str(cookie["value"]),
            domain=str(cookie.get("domain") or ""),
            path=str(cookie.get("path") or "/"),
            secure=bool(cookie.get("secure", False)),
        )


def cookie_inventory(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Describe transported state without exposing cookie values."""

    records = list(records)
    return {
        "count": len(records),
        "names": sorted({str(cookie["name"]) for cookie in records}),
        "domains": sorted({str(cookie.get("domain") or "") for cookie in records}),
    }


def session_kwargs(*, proxy: str, impersonate: str) -> dict[str, Any]:
    """Keep every case on the same proxy and TLS impersonation profile."""

    proxies = {"http": proxy, "https": proxy} if proxy else None
    return {
        "impersonate": impersonate,
        "curl_infos": curl_infos(),
        "proxies": proxies,
    }


def accepted_response(markers: dict[str, Any] | None) -> bool:
    """Recognize a usable Google result response."""

    return bool(
        markers
        and markers["status"] == 200
        and not markers["sorry"]
        and markers["result_dom"]
    )


def fetch_second(
    session: Session,
    *,
    navigation_url: str,
    referer: str,
    timeout: float,
) -> Any:
    """Perform the VM-requested navigation."""

    return session.get(
        navigation_url,
        headers=browser_headers(referer=referer),
        timeout=timeout,
        allow_redirects=True,
    )


def run_strategy(
    strategy: str,
    *,
    target: str,
    proxy: str,
    timeout: float,
    impersonate: str,
    replay_count: int,
) -> dict[str, Any]:
    """Obtain a fresh challenge and evaluate one session-transfer strategy."""

    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")

    origin = urlsplit(target)
    home_url = f"{origin.scheme}://{origin.netloc}/"
    started_ms = time.time_ns() / 1_000_000
    first_response = None
    vm: dict[str, Any] | None = None
    token: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []
    first_use: dict[str, Any] | None = None
    replay_attempts: list[dict[str, Any]] = []
    outcome_response = None

    with Session(**session_kwargs(proxy=proxy, impersonate=impersonate)) as source:
        home = source.get(
            home_url,
            headers=browser_headers(),
            timeout=timeout,
            allow_redirects=True,
        )
        request_start_ms = time.time_ns() / 1_000_000
        first_response = source.get(
            target,
            headers=browser_headers(referer=str(home.url)),
            timeout=timeout,
            allow_redirects=True,
        )
        vm = execute_challenge(
            first_response,
            source.cookies,
            navigation_start_ms=request_start_ms,
        )
        token = vm.pop("sg_ss")
        navigation = vm.get("navigation")
        if token is not None:
            inject_sg_ss(source, token)
        records = cookie_records(source.cookies)

        challenge_ready = bool(
            home.status_code == 200
            and first_response.status_code == 200
            and vm["executed_script_count"] == 4
            and not vm["errors"]
            and token
            and str(token.get("value", "")).startswith("*")
            and valid_navigation(navigation, source_url=str(first_response.url))
        )
        if not challenge_ready:
            return {
                "strategy": strategy,
                "challenge_ready": False,
                "home": response_markers(home),
                "first": response_markers(first_response),
                "vm": {
                    "inline_script_count": vm["inline_script_count"],
                    "executed_script_count": vm["executed_script_count"],
                    "errors": vm["errors"],
                    "state": vm["state"],
                    "navigation_present": isinstance(navigation, dict),
                },
                "generated_sg_ss": redacted_token(token),
                "cookie_inventory": cookie_inventory(records),
                "finished_unix_ms": round(time.time_ns() / 1_000_000, 3),
            }

        navigation_url = str(navigation["url"])
        referer = str(first_response.url)

        if strategy == "same_session_full_jar":
            outcome_response = fetch_second(
                source,
                navigation_url=navigation_url,
                referer=referer,
                timeout=timeout,
            )
        elif strategy == "replay_consumed_sg_ss":
            used = fetch_second(
                source,
                navigation_url=navigation_url,
                referer=referer,
                timeout=timeout,
            )
            used_markers = response_markers(used)
            first_use = {
                "response": used_markers,
                "accepted": accepted_response(used_markers),
                "sg_ss_consumed_to_zero": sg_ss_consumed(
                    used,
                    source.cookies,
                    hostname=origin.hostname or "",
                ),
            }
            outcome_response = used

    # Closing the source session proves the following cases use a fresh curl
    # handle and cannot inherit its connection pool or TLS session implicitly.
    if strategy in {"new_session_full_jar", "new_session_sg_ss_only"}:
        selected = records
        if strategy == "new_session_sg_ss_only":
            selected = [cookie for cookie in records if cookie["name"] == "SG_SS"]
        with Session(**session_kwargs(proxy=proxy, impersonate=impersonate)) as destination:
            install_cookies(destination, selected)
            outcome_response = fetch_second(
                destination,
                navigation_url=str(vm["navigation"]["url"]),
                referer=str(first_response.url),
                timeout=timeout,
            )
            consumed = sg_ss_consumed(
                outcome_response,
                destination.cookies,
                hostname=origin.hostname or "",
            )
            transferred_inventory = cookie_inventory(selected)
    elif strategy == "replay_consumed_sg_ss":
        selected = records
        if first_use and first_use["accepted"]:
            for replay_index in range(1, replay_count + 1):
                with Session(**session_kwargs(proxy=proxy, impersonate=impersonate)) as destination:
                    install_cookies(destination, selected)
                    outcome_response = fetch_second(
                        destination,
                        navigation_url=str(vm["navigation"]["url"]),
                        referer=str(first_response.url),
                        timeout=timeout,
                    )
                    replay_markers = response_markers(outcome_response)
                    replay_attempts.append(
                        {
                            "replay": replay_index,
                            "response": replay_markers,
                            "accepted": accepted_response(replay_markers),
                            "sg_ss_consumed_to_zero": sg_ss_consumed(
                                outcome_response,
                                destination.cookies,
                                hostname=origin.hostname or "",
                            ),
                        }
                    )
            consumed = bool(
                replay_attempts and replay_attempts[-1]["sg_ss_consumed_to_zero"]
            )
        else:
            consumed = bool(first_use and first_use["sg_ss_consumed_to_zero"])
        transferred_inventory = cookie_inventory(selected)
    else:
        consumed = sg_ss_consumed(
            outcome_response,
            source.cookies,
            hostname=origin.hostname or "",
        )
        transferred_inventory = cookie_inventory(records)

    markers = response_markers(outcome_response)
    result = {
        "strategy": strategy,
        "challenge_ready": True,
        "started_unix_ms": round(started_ms, 3),
        "finished_unix_ms": round(time.time_ns() / 1_000_000, 3),
        "generated_sg_ss": redacted_token(token),
        "source_cookie_inventory": cookie_inventory(records),
        "transferred_cookie_inventory": transferred_inventory,
        "outcome": markers,
        "accepted": accepted_response(markers),
        "sg_ss_consumed_to_zero": consumed,
    }
    if first_use is not None:
        result["first_use"] = first_use
        result["replay_attempts"] = replay_attempts
        result["replay_accepted_count"] = sum(
            1 for replay in replay_attempts if replay["accepted"]
        )
        result["all_replays_accepted"] = bool(replay_attempts) and all(
            replay["accepted"] for replay in replay_attempts
        )
    return result


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://www.google.com/search?q=亚非")
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--impersonate", default="chrome146")
    parser.add_argument("--replay-count", type=int, default=3)
    parser.add_argument("--strategy", choices=STRATEGIES, action="append")
    parser.add_argument("--output", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.attempts < 1 or arguments.attempts > 10:
        raise SystemExit("--attempts must be in 1..=10")
    if arguments.replay_count < 1 or arguments.replay_count > 10:
        raise SystemExit("--replay-count must be in 1..=10")

    cases = []
    strategies = tuple(arguments.strategy or STRATEGIES)
    for strategy in strategies:
        attempts = []
        for number in range(1, arguments.attempts + 1):
            try:
                attempt = run_strategy(
                    strategy,
                    target=arguments.url,
                    proxy=arguments.proxy,
                    timeout=arguments.timeout,
                    impersonate=arguments.impersonate,
                    replay_count=arguments.replay_count,
                )
            except Exception as error:  # preserve bounded online evidence
                attempt = {
                    "strategy": strategy,
                    "challenge_ready": False,
                    "error": {"type": type(error).__name__, "message": str(error)},
                }
            attempt["attempt"] = number
            attempts.append(attempt)
            valid_observation = bool(attempt.get("challenge_ready"))
            if strategy in {"same_session_full_jar", "new_session_full_jar"}:
                valid_observation = valid_observation and bool(attempt.get("accepted"))
            elif strategy == "replay_consumed_sg_ss":
                valid_observation = valid_observation and bool(
                    attempt.get("first_use", {}).get("accepted")
                )
            if valid_observation:
                break
        cases.append({"strategy": strategy, "attempts": attempts, "result": attempts[-1]})

    report = {
        "schema": "yatouv8-google-vm-session-matrix/v2",
        "target": arguments.url,
        "proxy": arguments.proxy,
        "impersonate": arguments.impersonate,
        "cases": cases,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(arguments.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
