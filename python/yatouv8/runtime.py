"""Public Python lifecycle and value-conversion layer for yatouv8."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
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


@dataclass(slots=True)
class BrowserProfile:
    """Chrome 150 identity and deterministic fixed-step clock profile."""

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
    clock: dict[str, float | str] = field(
        default_factory=lambda: {"mode": "fixed_step", "start_ms": 79.7, "step_ms": 0.1}
    )


@dataclass(slots=True)
class RuntimeConfig:
    """Configuration serialized directly into the native runtime contract."""

    profile: BrowserProfile = field(default_factory=BrowserProfile)
    url: str = "https://fixture.invalid/"
    viewport_width: int = 1280
    viewport_height: int = 720
    device_scale_factor: float = 1.0
    time_origin_ms: float = 1786103386944.1
    random_seed: int = 0x5EED150
    trace_id: str = "yatou-python-runtime"

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

    def close(self) -> None:
        """Stop the owner thread. Safe to call more than once."""

        self._native.close()

    def __enter__(self) -> Runtime:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


Context = Runtime
