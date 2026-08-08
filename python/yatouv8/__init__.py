"""Evidence-driven Chrome-compatible V8 host for Windows 11."""

from ._native import build_info, v8_smoke_value
from .execution_trace import analyze_execution_trace
from .runtime import (
    BrowserProfile,
    ChallengeResult,
    Context,
    ExecutionTraceConfig,
    GetTraceConfig,
    HttpNavigationTiming,
    JSException,
    JSValue,
    Runtime,
    RuntimeConfig,
)

__all__ = [
    "BrowserProfile",
    "ChallengeResult",
    "Context",
    "ExecutionTraceConfig",
    "GetTraceConfig",
    "HttpNavigationTiming",
    "JSException",
    "JSValue",
    "Runtime",
    "RuntimeConfig",
    "analyze_execution_trace",
    "build_info",
    "v8_smoke_value",
]
