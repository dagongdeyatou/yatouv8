"""High-level HTTP challenge handoff built on the yatouv8 runtime."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from typing import Any

from .runtime import BrowserProfile, JSException, Runtime, RuntimeConfig


class ChallengeSolveError(RuntimeError):
    """Raised when an HTTP challenge cannot produce a usable handoff."""


@dataclass(frozen=True, slots=True)
class ChallengeBundle:
    """Serializable state required for the request following a challenge."""

    navigation_url: str
    cookies: list[dict[str, Any]]
    headers: dict[str, str]
    sg_ss: str
    sg_ss_cookie: dict[str, Any]
    source_url: str
    inline_script_count: int
    executed_script_count: int
    imported_cookie_count: int
    drain: dict[str, Any]

    def apply_cookies(self, target: Any) -> int:
        """Merge every challenge cookie into a Cookies jar or session."""

        jar = getattr(target, "cookies", target)
        if not hasattr(jar, "set"):
            raise TypeError("target must expose a cookie set() method")
        for cookie in self.cookies:
            kwargs = {
                "domain": str(cookie.get("domain") or ""),
                "path": str(cookie.get("path") or "/"),
                "secure": bool(cookie.get("secure", False)),
            }
            try:
                jar.set(str(cookie["name"]), str(cookie["value"]), **kwargs)
            except TypeError:
                kwargs.pop("secure")
                jar.set(str(cookie["name"]), str(cookie["value"]), **kwargs)
        return len(self.cookies)

    def request_kwargs(self) -> dict[str, Any]:
        """Return the URL and headers for a module-level requests call."""

        return {"url": self.navigation_url, "headers": dict(self.headers)}


def browser_headers(
    *,
    profile: BrowserProfile | None = None,
    referer: str | None = None,
) -> dict[str, str]:
    """Build navigation headers coherent with one yatouv8 browser profile."""

    selected = profile or BrowserProfile()
    match = re.search(r"Chrome/(\d+)", selected.user_agent)
    major = match.group(1) if match else "150"
    if selected.platform == "Win32":
        client_platform = "Windows"
    elif selected.platform.startswith("Mac"):
        client_platform = "macOS"
    elif "Linux" in selected.platform:
        client_platform = "Linux"
    else:
        client_platform = selected.platform
    headers = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "accept-language": ",".join(
            language if index == 0 else f"{language};q={max(0.1, 1.0 - index / 10):.1f}"
            for index, language in enumerate(selected.languages)
        ),
        "cache-control": "max-age=0",
        "priority": "u=0, i",
        "sec-ch-ua": (
            f'"Not_A Brand";v="99", "Chromium";v="{major}", '
            f'"Google Chrome";v="{major}"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f'"{client_platform}"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin" if referer else "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": selected.user_agent,
    }
    if referer:
        headers["referer"] = referer
    return headers


def _inline_scripts(html: str) -> list[str]:
    """Return inline script bodies in document order."""

    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)


def _elapsed_seconds(response: Any) -> float:
    """Read a positive request duration from curl_cffi response metadata."""

    infos = {
        getattr(key, "name", str(key)): float(value)
        for key, value in dict(getattr(response, "infos", {}) or {}).items()
    }
    total = float(infos.get("TOTAL_TIME", 0.0))
    if total > 0:
        return total
    elapsed = getattr(response, "elapsed", None)
    if elapsed is None:
        return 0.0
    if hasattr(elapsed, "total_seconds"):
        return max(0.0, float(elapsed.total_seconds()))
    return max(0.0, float(elapsed))


def _navigation_start_ms(response: Any) -> float:
    """Estimate request start when the caller did not record it explicitly."""

    elapsed_seconds = _elapsed_seconds(response)
    if elapsed_seconds <= 0:
        raise ChallengeSolveError(
            "response does not expose request timing; pass navigation_start_ms explicitly"
        )
    return time.time_ns() / 1_000_000 - elapsed_seconds * 1_000.0


def solve_with_yatouv8(
    response: Any,
    cookies: Any,
    *,
    navigation_start_ms: float | None = None,
    profile: BrowserProfile | None = None,
    script_limit: int = 4,
    drain_limit: int = 10_000,
) -> ChallengeBundle:
    """Execute inline challenge scripts and return a stateless HTTP handoff.

    ``response`` is a curl_cffi-compatible response and ``cookies`` is the
    complete jar accumulated before that response.  The returned bundle can
    be applied to a fresh cookie jar; retaining the original Session object is
    not required.
    """

    if script_limit < 1:
        raise ValueError("script_limit must be positive")
    if drain_limit < 1:
        raise ValueError("drain_limit must be positive")
    source_url = str(getattr(response, "url", "") or "")
    if not source_url:
        raise ChallengeSolveError("response does not expose its final URL")
    scripts = _inline_scripts(str(getattr(response, "text", "") or ""))
    if len(scripts) < script_limit:
        raise ChallengeSolveError(
            f"challenge exposes {len(scripts)} inline scripts; {script_limit} required"
        )
    selected_profile = profile or BrowserProfile()
    start_ms = (
        _navigation_start_ms(response)
        if navigation_start_ms is None
        else float(navigation_start_ms)
    )
    if not math.isfinite(start_ms) or start_ms <= 0:
        raise ValueError("navigation_start_ms must be a positive finite epoch value")
    config = RuntimeConfig.from_curl_response(
        response,
        navigation_start_ms=start_ms,
        profile=selected_profile,
    )

    errors: list[str] = []
    with Runtime(config) as runtime:
        imported = runtime.import_cookies(cookies)
        for index, source in enumerate(scripts[:script_limit]):
            try:
                runtime.eval(source)
            except JSException as error:
                errors.append(f"script[{index}] {error.name}: {error.message}")
        drained = runtime.drain(drain_limit)
        exported = runtime.export_cookies()
        navigation = runtime.take_navigation()

    if errors:
        raise ChallengeSolveError("challenge script failure: " + "; ".join(errors))
    generated = [cookie for cookie in exported if cookie.get("name") == "SG_SS"]
    if not generated or not str(generated[-1].get("value", "")).startswith("*"):
        raise ChallengeSolveError("challenge did not generate an SG_SS token")
    if not isinstance(navigation, dict) or not isinstance(navigation.get("url"), str):
        raise ChallengeSolveError("challenge did not produce a navigation URL")
    sg_ss_cookie = dict(generated[-1])
    return ChallengeBundle(
        navigation_url=str(navigation["url"]),
        cookies=[dict(cookie) for cookie in exported],
        headers=browser_headers(profile=selected_profile, referer=source_url),
        sg_ss=str(sg_ss_cookie["value"]),
        sg_ss_cookie=sg_ss_cookie,
        source_url=source_url,
        inline_script_count=len(scripts),
        executed_script_count=script_limit,
        imported_cookie_count=imported,
        drain=drained,
    )
