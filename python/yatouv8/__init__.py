"""Evidence-driven Chrome-compatible V8 host."""

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
from .challenge import (
    ChallengeBundle,
    ChallengeSolveError,
    browser_headers,
    solve_with_yatouv8,
)

__all__ = [
    "BrowserProfile",
    "ChallengeBundle",
    "ChallengeResult",
    "ChallengeSolveError",
    "Context",
    "ExecutionTraceConfig",
    "GetTraceConfig",
    "HttpNavigationTiming",
    "JSException",
    "JSValue",
    "Runtime",
    "RuntimeConfig",
    "analyze_execution_trace",
    "browser_headers",
    "build_info",
    "solve_with_yatouv8",
    "v8_smoke_value",
]
