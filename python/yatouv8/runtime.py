"""Public Python lifecycle and value-conversion layer for yatouv8."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import math
from typing import Any, Mapping

from ._native import Runtime as _NativeRuntime


class JSException(RuntimeError):
    """A JavaScript exception returned without corrupting the persistent realm."""

    def __init__(self, name: str, message: str) -> None:
        self.name = name
        self.message = message
        super().__init__(f"{name}: {message}")


@dataclass(frozen=True, slots=True)
class JSValue:
    """Lossless fallback for values that have no direct JSON representation."""

    kind: str
    display: str


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    """One challenge execution plus host-boundary outputs for the HTTP client."""

    value: Any
    cookies: list[dict[str, Any]]
    pending_navigation: dict[str, Any] | None
    drain: dict[str, Any]
    trace_stats: dict[str, Any]


@dataclass(slots=True)
class BrowserProfile:
    """Chrome 150 identity plus replayed or request-coupled timing."""

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )
    platform: str = "Win32"
    language: str = "zh-CN"
    languages: list[str] = field(default_factory=lambda: ["zh-CN", "zh"])
    hardware_concurrency: int = 12
    screen_width: int = 1920
    screen_height: int = 1080
    screen_avail_width: int = 1920
    screen_avail_height: int = 1032
    screen_depth: int = 24
    outer_width: int = 1280
    outer_height: int = 720
    navigation_timing: dict[str, int | None] = field(default_factory=lambda: {
        "connect_start": 3,
        "secure_connection_start": None,
        "unload_event_end": None,
        "domain_lookup_start": 3,
        "domain_lookup_end": 3,
        "response_start": 4,
        "connect_end": 3,
        "response_end": 4,
        "request_start": 3,
        "dom_loading": 14,
        "redirect_start": None,
        "load_event_end": 18,
        "dom_complete": 18,
        "load_event_start": 18,
        "dom_content_loaded_event_end": 17,
        "unload_event_start": None,
        "redirect_end": None,
        "dom_interactive": 17,
        "fetch_start": 3,
        "dom_content_loaded_event_start": 17,
    })
    navigation_entry: dict[str, Any] = field(default_factory=lambda: {
        "delivery_type": "cache",
        "next_hop_protocol": "",
        "response_status": 0,
        "transfer_size": 0,
        "encoded_body_size": 0,
        "decoded_body_size": 0,
    })
    clock: dict[str, Any] = field(default_factory=lambda: {
        "mode": "recorded",
        "buckets": [
            {"value_ms": value, "repeat": repeat}
            for value, repeat in (
                (79.70000004768372, 42), (79.80000001192093, 56),
                (79.90000003576279, 158), (82.0, 1),
                (83.90000003576279, 1), (86.0, 1),
                (87.30000001192093, 1), (88.40000003576279, 1),
                (89.80000001192093, 1), (94.30000001192093, 1),
                (98.80000001192093, 1), (103.30000001192093, 1),
                (107.5, 1), (112.10000002384186, 1), (117.0, 1),
                (121.80000001192093, 1), (126.70000004768372, 1),
                (131.10000002384186, 1), (135.70000004768372, 1),
                (140.60000002384186, 1), (144.9000000357628, 1),
                (149.30000001192093, 1), (154.10000002384186, 1),
                (167.4000000357628, 1), (172.10000002384186, 1),
                (177.30000001192093, 1), (181.5, 1),
                (186.60000002384186, 1), (190.70000004768372, 1),
                (195.0, 1), (199.5, 1), (203.80000001192093, 1),
                (208.4000000357628, 1), (212.5, 1),
                (217.20000004768372, 1),
            )
        ],
        "fallback_quantum_ms": 0.1,
        "fallback_repeats": 24,
    })


@dataclass(frozen=True, slots=True)
class HttpNavigationTiming:
    """Causal navigation offsets derived from one completed HTTP request."""

    navigation_start_ms: float
    name_lookup_ms: float
    connect_ms: float
    app_connect_ms: float
    pretransfer_ms: float
    response_start_ms: float
    response_end_ms: float

    @classmethod
    def from_curl_response(
        cls,
        response: Any,
        *,
        navigation_start_ms: float,
    ) -> "HttpNavigationTiming":
        """Build timing from curl_cffi ``Response.infos`` with safe fallback."""

        if not math.isfinite(navigation_start_ms) or navigation_start_ms <= 0:
            raise ValueError("navigation_start_ms must be a positive finite epoch value")
        infos = {
            getattr(key, "name", str(key)): float(value)
            for key, value in dict(getattr(response, "infos", {}) or {}).items()
        }
        elapsed = getattr(response, "elapsed", None)
        fallback_seconds = float(elapsed.total_seconds()) if elapsed is not None else 0.0

        def milliseconds(name: str, fallback: float = 0.0) -> float:
            value = infos.get(name, fallback)
            return max(0.0, float(value) * 1_000.0)

        total = milliseconds("TOTAL_TIME", fallback_seconds)
        if total <= 0:
            raise ValueError("curl response does not expose a positive total request time")
        lookup = min(milliseconds("NAMELOOKUP_TIME"), total)
        connect = min(max(milliseconds("CONNECT_TIME"), lookup), total)
        app_connect = min(max(milliseconds("APPCONNECT_TIME", connect / 1_000.0), connect), total)
        pretransfer = min(max(milliseconds("PRETRANSFER_TIME", app_connect / 1_000.0), app_connect), total)
        response_start = min(
            max(milliseconds("STARTTRANSFER_TIME", total / 1_000.0), pretransfer),
            total,
        )
        return cls(
            navigation_start_ms=navigation_start_ms,
            name_lookup_ms=lookup,
            connect_ms=connect,
            app_connect_ms=app_connect,
            pretransfer_ms=pretransfer,
            response_start_ms=response_start,
            response_end_ms=total,
        )

    @staticmethod
    def _legacy_ms(value: float) -> int:
        return max(0, int(round(value)))

    def navigation_profile(self) -> dict[str, int | None]:
        """Return legacy PerformanceTiming offsets valid during inline parsing."""

        lookup = self._legacy_ms(self.name_lookup_ms)
        connect = self._legacy_ms(self.connect_ms)
        app_connect = self._legacy_ms(self.app_connect_ms)
        pretransfer = self._legacy_ms(self.pretransfer_ms)
        response_start = self._legacy_ms(self.response_start_ms)
        response_end = self._legacy_ms(self.response_end_ms)
        return {
            "connect_start": lookup,
            "secure_connection_start": connect if app_connect > connect else None,
            "unload_event_end": None,
            "domain_lookup_start": 0,
            "domain_lookup_end": lookup,
            "response_start": response_start,
            "connect_end": app_connect,
            "response_end": response_end,
            "request_start": pretransfer,
            "dom_loading": response_end,
            "redirect_start": None,
            "load_event_end": None,
            "dom_complete": None,
            "load_event_start": None,
            "dom_content_loaded_event_end": None,
            "unload_event_start": None,
            "redirect_end": None,
            "dom_interactive": None,
            "fetch_start": 0,
            "dom_content_loaded_event_start": None,
        }

    def clock_profile(self, *, quantum_ms: float = 0.1) -> dict[str, Any]:
        """Start a real monotonic clock at the completed-response offset."""

        return {
            "mode": "system_monotonic",
            "start_ms": self.response_end_ms,
            "quantum_ms": quantum_ms,
        }

    @staticmethod
    def navigation_entry_profile(response: Any) -> dict[str, Any]:
        """Map curl transfer metadata to PerformanceNavigationTiming fields."""

        infos = {
            getattr(key, "name", str(key)): float(value)
            for key, value in dict(getattr(response, "infos", {}) or {}).items()
        }
        http_version = int(infos.get("HTTP_VERSION", 0))
        if http_version in {3, 4, 5}:
            protocol = "h2"
        elif http_version in {30, 31}:
            protocol = "h3"
        elif http_version in {1, 2}:
            protocol = "http/1.1"
        else:
            protocol = ""
        body = bytes(getattr(response, "content", b"") or b"")
        encoded_size = max(0, int(infos.get("SIZE_DOWNLOAD_T", len(body))))
        header_size = max(0, int(infos.get("HEADER_SIZE", 0)))
        return {
            "delivery_type": "",
            "next_hop_protocol": protocol,
            "response_status": int(getattr(response, "status_code", 0) or 0),
            "transfer_size": header_size + encoded_size,
            "encoded_body_size": encoded_size,
            "decoded_body_size": len(body),
        }


@dataclass(slots=True)
class GetTraceConfig:
    """Opt-in bounded L1 diagnostics for browser-host property reads."""

    enabled: bool = False
    max_events: int = 50_000


@dataclass(slots=True)
class ExecutionTraceConfig:
    """Opt-in V8 Inspector source capture and precise block coverage."""

    enabled: bool = False
    capture_source: bool = True
    max_scripts: int = 256
    max_source_bytes: int = 1_048_576


@dataclass(slots=True)
class RuntimeConfig:
    """Configuration serialized directly into the native runtime contract."""

    profile: BrowserProfile = field(default_factory=BrowserProfile)
    url: str = "https://fixture.invalid/"
    viewport_width: int = 1280
    viewport_height: int = 633
    device_scale_factor: float = 1.0
    time_origin_ms: float = 1786103386944.1
    random_seed: int = 0x5EED150
    trace_id: str = "yatou-python-runtime"
    get_trace: GetTraceConfig = field(default_factory=GetTraceConfig)
    execution_trace: ExecutionTraceConfig = field(default_factory=ExecutionTraceConfig)

    @classmethod
    def from_curl_response(
        cls,
        response: Any,
        *,
        navigation_start_ms: float,
        profile: BrowserProfile | None = None,
        clock_quantum_ms: float = 0.1,
        **runtime_options: Any,
    ) -> "RuntimeConfig":
        """Create a request-coupled runtime for a curl_cffi response."""

        timing = HttpNavigationTiming.from_curl_response(
            response,
            navigation_start_ms=navigation_start_ms,
        )
        coupled_profile = replace(
            profile or BrowserProfile(),
            navigation_timing=timing.navigation_profile(),
            navigation_entry=timing.navigation_entry_profile(response),
            clock=timing.clock_profile(quantum_ms=clock_quantum_ms),
        )
        runtime_options.setdefault("url", str(response.url))
        runtime_options.setdefault("viewport_width", 1280)
        runtime_options.setdefault("viewport_height", 633)
        runtime_options.setdefault("time_origin_ms", navigation_start_ms)
        return cls(profile=coupled_profile, **runtime_options)

    def to_json(self) -> str:
        """Return canonical compact JSON for the Rust data contract."""

        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Runtime:
    """Persistent browser realm backed by a dedicated V8 owner thread."""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()
        self._native = _NativeRuntime(self.config.to_json())

    @property
    def closed(self) -> bool:
        """Whether runtime shutdown has begun."""

        return bool(self._native.closed)

    def eval(self, source: str) -> Any:
        """Evaluate JavaScript and convert JSON-representable results to Python."""

        ok, kind, display, encoded, exception_name, exception_message = self._native.eval_raw(source)
        if not ok:
            raise JSException(exception_name or "Error", exception_message or "JavaScript threw")
        if encoded is not None:
            return json.loads(encoded)
        if kind in {"undefined", "null"}:
            return None
        if kind == "bigint":
            return int(display)
        return JSValue(kind=kind, display=display)

    def add_resource(
        self,
        url: str,
        body: bytes | bytearray | memoryview | str,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Add an exact offline response. Missing URLs never fall back to a network."""

        payload = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        self._native.add_resource(url, payload, status, dict(headers or {}))

    def drain(self, limit: int = 1000) -> dict[str, Any]:
        """Run deterministic timers and queued microtasks."""

        return json.loads(self._native.drain_json(limit))

    @property
    def trace(self) -> dict[str, Any]:
        """Return the current validated L0/L1 trace."""

        records = [json.loads(line) for line in self._native.trace_json().splitlines() if line]
        header = next(record["record"] for record in records if record["record_type"] == "header")
        footer = next(record["record"] for record in records if record["record_type"] == "footer")
        events = [record["record"] for record in records if record["record_type"] == "event"]
        return {"header": header, "events": events, "footer": footer}

    @property
    def environment(self) -> dict[str, Any]:
        """Return immutable profile and execution-mode metadata."""

        return json.loads(self._native.environment_json())

    @property
    def get_trace_stats(self) -> dict[str, Any]:
        """Return the bounded GET diagnostic counters for this runtime."""

        stats = json.loads(self._native.trace_stats_json())
        if not isinstance(stats, dict):
            raise RuntimeError("invalid GET trace statistics returned by the runtime")
        return stats

    @property
    def execution_trace(self) -> dict[str, Any]:
        """Return the latest dynamic-script source and precise coverage capture."""

        capture = json.loads(self._native.execution_trace_json())
        if not isinstance(capture, dict):
            raise RuntimeError("invalid execution trace returned by the runtime")
        return capture

    def import_cookies(self, cookies: Any) -> int:
        """Import a mapping, CookieJar, or curl_cffi-compatible cookie collection."""

        normalized: list[dict[str, Any]] = []
        # curl_cffi.Cookies implements Mapping, but Mapping.items() resolves by
        # name and raises CookieConflict when geo redirects leave the same name
        # on .google.com and .google.com.hk.  Iterate its backing CookieJar
        # first so domain/path identity is preserved.
        if hasattr(cookies, "jar"):
            cookies = cookies.jar
        elif isinstance(cookies, Mapping):
            normalized = [{"name": str(name), "value": str(value)} for name, value in cookies.items()]
        if not normalized:
            for cookie in cookies:
                if isinstance(cookie, Mapping):
                    normalized.append(dict(cookie))
                    continue
                normalized.append({
                    "name": str(cookie.name),
                    "value": str(cookie.value),
                    "domain": getattr(cookie, "domain", ""),
                    "path": getattr(cookie, "path", "/"),
                    "secure": bool(getattr(cookie, "secure", False)),
                    "expires": getattr(cookie, "expires", None),
                    "httpOnly": bool(getattr(cookie, "rest", {}).get("HttpOnly", False)),
                })
        return int(self._native.import_cookies_json(json.dumps(normalized, separators=(",", ":"))))

    def export_cookies(self, target: Any | None = None) -> list[dict[str, Any]]:
        """Return structured cookies and optionally merge them into a session jar."""

        cookies = json.loads(self._native.export_cookies_json())
        if target is not None:
            jar = getattr(target, "cookies", target)
            for cookie in cookies:
                kwargs = {
                    "domain": cookie.get("domain") or None,
                    "path": cookie.get("path") or "/",
                }
                try:
                    jar.set(cookie["name"], cookie["value"], **kwargs)
                except TypeError:
                    jar.set(cookie["name"], cookie["value"])
        return cookies

    @property
    def pending_navigation(self) -> dict[str, Any] | None:
        """Peek at the next location-driven navigation without consuming it."""

        return json.loads(self._native.navigation_json(False))

    def take_navigation(self) -> dict[str, Any] | None:
        """Consume and return the next location-driven navigation."""

        return json.loads(self._native.navigation_json(True))

    def eval_challenge(self, source: str, *, drain_limit: int = 10_000) -> ChallengeResult:
        """Execute one extracted challenge script and return its session handoff."""

        value = self.eval(source)
        drained = self.drain(drain_limit)
        return ChallengeResult(
            value=value,
            cookies=self.export_cookies(),
            pending_navigation=self.pending_navigation,
            drain=drained,
            trace_stats=self.get_trace_stats,
        )

    def close(self) -> None:
        """Stop the owner thread. Safe to call more than once."""

        self._native.close()

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


Context = Runtime
