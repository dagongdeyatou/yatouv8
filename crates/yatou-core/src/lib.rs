//! Core runtime ownership and V8 substrate.

/// Build metadata used by the Python bridge and diagnostics.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BuildInfo {
    /// Cargo package version.
    pub version: &'static str,
    /// Normative baseline targeted by the initial architecture contract.
    pub baseline: &'static str,
    /// V8 crate version locked by the workspace.
    pub v8_crate: &'static str,
}

/// Returns compile-time build metadata without initializing V8.
#[must_use]
pub const fn build_info() -> BuildInfo {
    BuildInfo {
        version: env!("CARGO_PKG_VERSION"),
        baseline: "win11-chrome150.0.7871.188-headful-m2-v2",
        v8_crate: "150.4.0",
    }
}

#[cfg(feature = "v8-runtime")]
mod runtime;

#[cfg(feature = "v8-runtime")]
pub use runtime::{
    BotguardRun, BrowserProfile, BrowserRuntime, ClockMode, EvalResult, GetTraceConfig,
    RuntimeConfig, RuntimeError, V8Error, evaluate_to_string, run_botguard,
};

mod host;

pub use host::{Resource, ResourceError, ResourceStore};

mod trace;

pub use trace::{ReplayTape, ReplayedResource, TraceRecorder, TraceRuntimeError};
