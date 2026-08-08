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
    BotguardRun, BrowserProfile, BrowserRuntime, ClockBucket, ClockMode, EvalResult,
    GetTraceConfig, RuntimeConfig, RuntimeError, V8Error, evaluate_to_string, run_botguard,
};

mod host;

pub use host::{Resource, ResourceError, ResourceStore};

mod trace;

pub use trace::{ReplayTape, ReplayedResource, TraceRecorder, TraceRuntimeError};

/// Dispatch one generated surface invocation and append its L1 evidence event.
///
/// # Errors
///
/// Returns [`TraceRuntimeError`] when trace ordering or lineage is invalid.
pub fn dispatch_surface_with_l1<H: yatou_surface::SurfaceHandler>(
    handler: &mut H,
    recorder: &mut TraceRecorder,
    logical_time_ns: u64,
    parent_seq: Option<u64>,
    invocation: yatou_surface::SurfaceInvocation,
) -> Result<yatou_schema::ApiOutcome, TraceRuntimeError> {
    let outcome = handler.dispatch(&invocation);
    recorder.record_l1(
        logical_time_ns,
        parent_seq,
        yatou_schema::ApiLedgerEvent {
            operation: invocation.operation,
            target: invocation.target,
            member: invocation.member,
            arguments: invocation.arguments,
            outcome: outcome.clone(),
            call_site: None,
        },
    )?;
    Ok(outcome)
}
