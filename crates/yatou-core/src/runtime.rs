//! V8 substrate and the first Chrome-150-compatible Google `BotGuard` host slice.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Mutex, Once, mpsc};
use std::thread::{self, JoinHandle};

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;
use yatou_schema::{
    ApiLedgerEvent, ApiOperation, ApiOutcome, BaselineId, CURRENT_SCHEMA_VERSION, EvalOutcome,
    ExceptionSummary, JsValueKind, ReplayEvent, TraceHeader, TraceSource, TraceStream,
    ValueSummary,
};

use crate::{Resource, ResourceError, TraceRecorder, TraceRuntimeError};

mod trusted_types;

static INITIALIZE_V8: Once = Once::new();

/// Errors produced by the V8 evaluator or browser host bootstrap.
#[derive(Debug, Error)]
pub enum V8Error {
    /// JavaScript source could not be allocated as a V8 string.
    #[error("failed to allocate JavaScript source")]
    SourceAllocation,
    /// V8 rejected the source during compilation.
    #[error("JavaScript compilation failed: {0}")]
    Compilation(String),
    /// Script execution returned no value, usually because an exception was thrown.
    #[error("JavaScript execution failed: {0}")]
    Execution(String),
    /// Result could not be converted to a JavaScript string.
    #[error("result string conversion failed")]
    ResultConversion,
    /// A required native browser function could not be installed.
    #[error("failed to install native browser function: {0}")]
    NativeInstallation(&'static str),
    /// `BotGuard` returned a malformed result envelope.
    #[error("invalid BotGuard result envelope: {0}")]
    ResultDecode(String),
    /// Generated trace failed its semantic contract.
    #[error("invalid BotGuard trace: {0}")]
    Trace(String),
}

/// One run-length encoded observation from an accepted Chrome clock capture.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ClockBucket {
    /// Exact `performance.now()` value observed in Chrome.
    pub value_ms: f64,
    /// Number of consecutive calls that returned this value.
    pub repeat: u32,
}

/// Configurable `performance.now()` behavior.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "mode", rename_all = "snake_case")]
pub enum ClockMode {
    /// Monotonic fixed increments suitable for deterministic replay.
    FixedStep {
        /// First returned value in milliseconds.
        start_ms: f64,
        /// Increment after every observation.
        step_ms: f64,
    },
    /// Replay a run-length encoded Chrome distribution, then continue with the
    /// captured quantization rather than inventing random jitter.
    Recorded {
        /// Consecutive Chrome values and their observed repeat counts.
        buckets: Vec<ClockBucket>,
        /// Quantized increment used after the finite capture is exhausted.
        fallback_quantum_ms: f64,
        /// Calls sharing one fallback quantum.
        fallback_repeats: u32,
    },
}

/// Minimal evidence-derived browser profile required by the M6 target.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct BrowserProfile {
    /// Baseline user agent.
    pub user_agent: String,
    /// Browser platform.
    pub platform: String,
    /// Preferred language.
    pub language: String,
    /// Ordered language preferences.
    pub languages: Vec<String>,
    /// Logical CPU count.
    pub hardware_concurrency: u32,
    /// Screen width.
    pub screen_width: u32,
    /// Screen height.
    pub screen_height: u32,
    /// Available screen width.
    pub screen_avail_width: u32,
    /// Available screen height.
    pub screen_avail_height: u32,
    /// Color and pixel depth.
    pub screen_depth: u32,
    /// Deterministic clock profile.
    pub clock: ClockMode,
}

impl Default for BrowserProfile {
    fn default() -> Self {
        Self {
            user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
                         (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
                .to_owned(),
            platform: "Win32".to_owned(),
            language: "zh-CN".to_owned(),
            languages: vec!["zh-CN".to_owned(), "zh".to_owned()],
            hardware_concurrency: 12,
            screen_width: 1_920,
            screen_height: 1_080,
            screen_avail_width: 1_920,
            screen_avail_height: 1_032,
            screen_depth: 24,
            clock: ClockMode::Recorded {
                buckets: default_chrome_clock_buckets(),
                fallback_quantum_ms: 0.1,
                fallback_repeats: 24,
            },
        }
    }
}

fn default_chrome_clock_buckets() -> Vec<ClockBucket> {
    // win11-chrome150.0.7871.188-headful-m2-v2, captured 2026-08-07.
    const OBSERVATIONS: &[(f64, u32)] = &[
        (79.700_000_047_683_72, 42),
        (79.800_000_011_920_93, 56),
        (79.900_000_035_762_79, 158),
        (82.0, 1),
        (83.900_000_035_762_79, 1),
        (86.0, 1),
        (87.300_000_011_920_93, 1),
        (88.400_000_035_762_79, 1),
        (89.800_000_011_920_93, 1),
        (94.300_000_011_920_93, 1),
        (98.800_000_011_920_93, 1),
        (103.300_000_011_920_93, 1),
        (107.5, 1),
        (112.100_000_023_841_86, 1),
        (117.0, 1),
        (121.800_000_011_920_93, 1),
        (126.700_000_047_683_72, 1),
        (131.100_000_023_841_86, 1),
        (135.700_000_047_683_72, 1),
        (140.600_000_023_841_86, 1),
        (144.900_000_035_762_8, 1),
        (149.300_000_011_920_93, 1),
        (154.100_000_023_841_86, 1),
        (167.400_000_035_762_8, 1),
        (172.100_000_023_841_86, 1),
        (177.300_000_011_920_93, 1),
        (181.5, 1),
        (186.600_000_023_841_86, 1),
        (190.700_000_047_683_72, 1),
        (195.0, 1),
        (199.5, 1),
        (203.800_000_011_920_93, 1),
        (208.400_000_035_762_8, 1),
        (212.5, 1),
        (217.200_000_047_683_72, 1),
    ];
    OBSERVATIONS
        .iter()
        .map(|&(value_ms, repeat)| ClockBucket { value_ms, repeat })
        .collect()
}

/// End-to-end result of executing the archived Google `BotGuard` model.
#[derive(Debug)]
pub struct BotguardRun {
    /// Returned `BotGuard` token, when execution succeeded.
    pub token: Option<String>,
    /// JavaScript error summary, when execution failed.
    pub error: Option<String>,
    /// Whether the returned token starts with the observed `!` marker.
    pub starts_with_bang: bool,
    /// Token length in Unicode scalar values.
    pub token_length: usize,
    /// Number of native browser-boundary calls captured by L1.
    pub api_call_count: usize,
    /// Canonical digest of the token shape checkpoint, never of random token bytes.
    pub token_shape_sha256: String,
    /// Complete L0/L1 runtime trace.
    pub trace: TraceStream,
    /// Optional diagnostic interpreter observations; empty for an unmodified model.
    pub diagnostic_trace: Vec<serde_json::Value>,
}

#[derive(Clone, Debug)]
struct NativeObservation {
    order: u32,
    target: &'static str,
    member: &'static str,
    arguments: Vec<ValueSummary>,
    outcome: ValueSummary,
}

#[derive(Debug)]
struct CallbackState {
    clock_next_ms: f64,
    clock_step_ms: f64,
    clock_recorded: Vec<f64>,
    clock_index: usize,
    clock_fallback_repeats: u32,
    clock_fallback_count: u32,
    observation_sequence: u32,
    observations: Vec<NativeObservation>,
}

impl Default for CallbackState {
    fn default() -> Self {
        Self {
            clock_next_ms: 0.0,
            clock_step_ms: 0.1,
            clock_recorded: Vec::new(),
            clock_index: 0,
            clock_fallback_repeats: 1,
            clock_fallback_count: 0,
            observation_sequence: 0,
            observations: Vec::new(),
        }
    }
}

thread_local! {
    static CALLBACK_STATE: RefCell<CallbackState> = RefCell::new(CallbackState::default());
}

#[derive(Debug, Deserialize)]
struct BotguardEnvelope {
    token: Option<String>,
    error: Option<BotguardJsError>,
    diagnostic_trace: Vec<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct BotguardJsError {
    name: String,
    message: String,
}

fn initialize_v8() {
    INITIALIZE_V8.call_once(|| {
        let platform = v8::new_default_platform(0, false).make_shared();
        v8::V8::initialize_platform(platform);
        v8::V8::initialize();
    });
}

/// Evaluates JavaScript in a fresh Isolate and Context and returns its string form.
///
/// This function deliberately has no browser globals. It is the M1 substrate proof,
/// not a compatibility claim.
///
/// # Errors
///
/// Returns [`V8Error`] when source allocation, compilation, execution, or result
/// conversion fails.
pub fn evaluate_to_string(source: &str) -> Result<String, V8Error> {
    initialize_v8();

    let isolate = &mut v8::Isolate::new(v8::CreateParams::default());
    v8::scope!(let handle_scope, isolate);
    let context = v8::Context::new(handle_scope, v8::ContextOptions::default());
    let scope = &mut v8::ContextScope::new(handle_scope, context);

    execute_to_string(scope, source)
}

/// Execute an archived real Google `BotGuard` model and encrypted bytecode offline.
///
/// The model and bytecode are passed as caller-owned evidence. This function has no
/// network adapter and installs only the profile, encoding, event, and clock surfaces
/// needed by the target trace.
///
/// # Errors
///
/// Returns [`V8Error`] for browser bootstrap, model compilation/execution, result
/// decoding, or trace-contract failures.
pub fn run_botguard(
    model_source: &str,
    encrypted_bytecode: &[u8],
    profile: &BrowserProfile,
) -> Result<BotguardRun, V8Error> {
    initialize_v8();
    configure_callbacks(&profile.clock);

    let isolate = &mut v8::Isolate::new(v8::CreateParams::default());
    v8::scope!(let handle_scope, isolate);
    let context = v8::Context::new(handle_scope, v8::ContextOptions::default());
    let scope = &mut v8::ContextScope::new(handle_scope, context);

    install_native_functions(scope, context)?;
    execute_to_string(scope, &browser_bootstrap(profile))?;
    execute_to_string(scope, model_source)?;

    let encoded = base64::engine::general_purpose::STANDARD.encode(encrypted_bytecode);
    let encoded = serde_json::to_string(&encoded)
        .map_err(|error| V8Error::ResultDecode(error.to_string()))?;
    let invoke = format!(
        r#"JSON.stringify((() => {{
            try {{
                const instance = new botguard.bg({encoded});
                const token = instance.invoke();
                return {{
                    token: typeof token === "string" ? token : null,
                    error: null,
                    diagnostic_trace: globalThis.__yatouTrace || []
                }};
            }} catch (error) {{
                return {{
                    token: null,
                    error: {{
                        name: String(error && error.name || "Error"),
                        message: String(error && error.message || error)
                    }},
                    diagnostic_trace: globalThis.__yatouTrace || []
                }};
            }}
        }})())"#
    );
    let envelope_json = execute_to_string(scope, &invoke)?;
    let envelope = serde_json::from_str::<BotguardEnvelope>(&envelope_json)
        .map_err(|error| V8Error::ResultDecode(error.to_string()))?;
    let observations = take_observations();
    finish_botguard_run(model_source, envelope, &observations)
}

fn configure_callbacks(clock: &ClockMode) {
    let (clock_next_ms, clock_step_ms, clock_recorded, clock_fallback_repeats) = match clock {
        ClockMode::FixedStep { start_ms, step_ms } => (*start_ms, *step_ms, Vec::new(), 1),
        ClockMode::Recorded {
            buckets,
            fallback_quantum_ms,
            fallback_repeats,
        } => {
            let values = buckets
                .iter()
                .flat_map(|bucket| std::iter::repeat_n(bucket.value_ms, bucket.repeat as usize))
                .collect::<Vec<_>>();
            let start = values.first().copied().unwrap_or(0.0);
            (start, *fallback_quantum_ms, values, *fallback_repeats)
        }
    };
    CALLBACK_STATE.with(|state| {
        *state.borrow_mut() = CallbackState {
            clock_next_ms,
            clock_step_ms,
            clock_recorded,
            clock_index: 0,
            clock_fallback_repeats,
            clock_fallback_count: 0,
            observation_sequence: 0,
            observations: Vec::new(),
        };
    });
}

fn take_observations() -> Vec<NativeObservation> {
    CALLBACK_STATE.with(|state| std::mem::take(&mut state.borrow_mut().observations))
}

fn summary(kind: JsValueKind, preview: impl Into<String>) -> ValueSummary {
    ValueSummary {
        kind,
        preview: Some(preview.into()),
        sha256: None,
    }
}

fn record_native(
    target: &'static str,
    member: &'static str,
    arguments: Vec<ValueSummary>,
    outcome: ValueSummary,
) {
    CALLBACK_STATE.with(|state| {
        let mut state = state.borrow_mut();
        state.observation_sequence = state.observation_sequence.saturating_add(1);
        let order = state.observation_sequence;
        state.observations.push(NativeObservation {
            order,
            target,
            member,
            arguments,
            outcome,
        });
    });
}

#[allow(clippy::needless_pass_by_value)]
fn observation_sequence_callback(
    scope: &mut v8::PinScope,
    _args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let order = CALLBACK_STATE.with(|state| {
        let mut state = state.borrow_mut();
        state.observation_sequence = state.observation_sequence.saturating_add(1);
        state.observation_sequence
    });
    retval.set(v8::Number::new(scope, f64::from(order)).into());
}

#[allow(clippy::needless_pass_by_value)]
fn atob_callback(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let Some(input) = args.get(0).to_string(scope) else {
        return;
    };
    let input = input.to_rust_string_lossy(scope);
    let Ok(decoded) = base64::engine::general_purpose::STANDARD.decode(&input) else {
        return;
    };
    let Some(result) = v8::String::new_from_one_byte(scope, &decoded, v8::NewStringType::Normal)
    else {
        return;
    };
    record_native(
        "globalThis",
        "atob",
        vec![summary(
            JsValueKind::String,
            format!("chars:{}", input.len()),
        )],
        summary(JsValueKind::String, format!("bytes:{}", decoded.len())),
    );
    retval.set(result.into());
}

#[allow(clippy::needless_pass_by_value)]
fn btoa_callback(
    scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let Some(input) = args.get(0).to_string(scope) else {
        return;
    };
    let mut bytes = vec![0; input.length()];
    input.write_one_byte_v2(scope, 0, &mut bytes, v8::WriteFlags::default());
    let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
    let Some(result) = v8::String::new(scope, &encoded) else {
        return;
    };
    record_native(
        "globalThis",
        "btoa",
        vec![summary(
            JsValueKind::String,
            format!("bytes:{}", bytes.len()),
        )],
        summary(JsValueKind::String, format!("chars:{}", encoded.len())),
    );
    retval.set(result.into());
}

#[allow(clippy::needless_pass_by_value)]
fn add_event_listener_callback(
    _scope: &mut v8::PinScope,
    args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let event_kind = if args.length() > 0 {
        "string"
    } else {
        "undefined"
    };
    record_native(
        "EventTarget.prototype",
        "addEventListener",
        vec![summary(JsValueKind::String, event_kind)],
        summary(JsValueKind::Undefined, "undefined"),
    );
    retval.set_undefined();
}

#[allow(clippy::needless_pass_by_value)]
fn performance_now_callback(
    _scope: &mut v8::PinScope,
    _args: v8::FunctionCallbackArguments,
    mut retval: v8::ReturnValue,
) {
    let value = CALLBACK_STATE.with(|state| {
        let mut state = state.borrow_mut();
        if let Some(value) = state.clock_recorded.get(state.clock_index).copied() {
            state.clock_index += 1;
            state.clock_next_ms = value;
            return value;
        }
        let value = state.clock_next_ms;
        state.clock_fallback_count = state.clock_fallback_count.saturating_add(1);
        if state.clock_fallback_count >= state.clock_fallback_repeats {
            state.clock_next_ms += state.clock_step_ms;
            state.clock_fallback_count = 0;
        }
        value
    });
    record_native(
        "Performance.prototype",
        "now",
        Vec::new(),
        summary(JsValueKind::Number, "number"),
    );
    retval.set_double(value);
}

#[allow(clippy::needless_pass_by_value)]
fn global_get_trace_callback(
    scope: &mut v8::PinScope,
    key: v8::Local<v8::Name>,
    args: v8::PropertyCallbackArguments,
    mut retval: v8::ReturnValue<v8::Value>,
) -> v8::Intercepted {
    let Ok(key) = v8::Local::<v8::String>::try_from(key) else {
        return v8::Intercepted::kNo;
    };
    let member = key.to_rust_string_lossy(scope);
    let holder = args.holder();
    let value = holder.get_real_named_property(scope, key.into());

    if !member.starts_with("__yatou") {
        let logger = runtime_bridge(scope, holder)
            .and_then(|bridge| bridge_member(scope, bridge, "__yatouRecordGlobalGet"))
            .and_then(|logger| v8::Local::<v8::Function>::try_from(logger).ok());
        let mut observed_value = value;
        if let Some(logger) = logger {
            let outcome = value.unwrap_or_else(|| v8::undefined(scope).into());
            let member_value: v8::Local<v8::Value> = key.into();
            let threw: v8::Local<v8::Value> = v8::Boolean::new(scope, false).into();
            if let Some(observed) =
                logger.call(scope, holder.into(), &[member_value, outcome, threw])
                && value.is_some()
            {
                observed_value = Some(observed);
            }
        }

        if let Some(value) = observed_value {
            retval.set(value);
            return v8::Intercepted::kYes;
        }
    }

    if let Some(value) = value {
        retval.set(value);
        v8::Intercepted::kYes
    } else {
        v8::Intercepted::kNo
    }
}

#[allow(clippy::needless_pass_by_value)]
fn global_descriptor_fallthrough_callback(
    _scope: &mut v8::PinScope,
    _key: v8::Local<v8::Name>,
    _args: v8::PropertyCallbackArguments,
    _retval: v8::ReturnValue<v8::Value>,
) -> v8::Intercepted {
    v8::Intercepted::kNo
}

const RUNTIME_BRIDGE_PRIVATE: &str = "yatouv8.runtime.bridge";

fn runtime_bridge<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    global: v8::Local<v8::Object>,
) -> Option<v8::Local<'s, v8::Object>> {
    let name = v8::String::new(scope, RUNTIME_BRIDGE_PRIVATE)?;
    let key = v8::Private::for_api(scope, Some(name));
    let value = global.get_private(scope, key)?;
    v8::Local::<v8::Object>::try_from(value).ok()
}

fn bridge_member<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    bridge: v8::Local<v8::Object>,
    name: &str,
) -> Option<v8::Local<'s, v8::Value>> {
    let key = v8::String::new(scope, name)?;
    bridge.get(scope, key.into())
}

fn capture_runtime_bridge(
    scope: &mut v8::PinScope,
    context: v8::Local<v8::Context>,
) -> Result<v8::Global<v8::Object>, V8Error> {
    const MEMBERS: &[&str] = &[
        "__yatouNextObservationSequence",
        "__yatouTakeHostLog",
        "__yatouSetGetTraceActive",
        "__yatouRecordGlobalGet",
        "__yatouGetTraceStats",
        "__yatouInstallResource",
        "__yatouDrain",
        "__yatouImportCookies",
        "__yatouExportCookies",
        "__yatouTakeNavigation",
        "__yatouPeekNavigation",
        "__yatouEnvironment",
    ];
    let global = context.global(scope);
    let bridge = v8::Object::new(scope);
    for &member in MEMBERS {
        let key = v8::String::new(scope, member).ok_or(V8Error::SourceAllocation)?;
        let value = global
            .get_real_named_property(scope, key.into())
            .ok_or(V8Error::NativeInstallation(member))?;
        if !bridge.set(scope, key.into(), value).unwrap_or(false) {
            return Err(V8Error::NativeInstallation(member));
        }
    }
    let private_name =
        v8::String::new(scope, RUNTIME_BRIDGE_PRIVATE).ok_or(V8Error::SourceAllocation)?;
    let private = v8::Private::for_api(scope, Some(private_name));
    if !global
        .set_private(scope, private, bridge.into())
        .unwrap_or(false)
    {
        return Err(V8Error::NativeInstallation("runtime bridge"));
    }
    for member in MEMBERS.iter().copied().chain(["__yatouConfig"]) {
        let key = v8::String::new(scope, member).ok_or(V8Error::SourceAllocation)?;
        if !global.delete(scope, key.into()).unwrap_or(false) {
            return Err(V8Error::NativeInstallation("runtime bridge cleanup"));
        }
    }
    Ok(v8::Global::new(scope, bridge))
}

fn call_runtime_bridge<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    bridge: &v8::Global<v8::Object>,
    member: &str,
    arguments: &[v8::Local<'s, v8::Value>],
) -> Result<v8::Local<'s, v8::Value>, V8Error> {
    let bridge = v8::Local::new(scope, bridge);
    let function = bridge_member(scope, bridge, member)
        .and_then(|value| v8::Local::<v8::Function>::try_from(value).ok())
        .ok_or(V8Error::NativeInstallation("runtime bridge member"))?;
    function
        .call(scope, bridge.into(), arguments)
        .ok_or_else(|| V8Error::Execution(format!("runtime bridge call failed: {member}")))
}

fn bridge_json<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    bridge: &v8::Global<v8::Object>,
    member: &str,
    arguments: &[v8::Local<'s, v8::Value>],
) -> Result<String, V8Error> {
    let value = call_runtime_bridge(scope, bridge, member, arguments)?;
    let json = v8::json::stringify(scope, value)
        .ok_or_else(|| V8Error::Execution(format!("runtime bridge JSON failed: {member}")))?;
    Ok(json.to_rust_string_lossy(scope))
}

fn runtime_context<'s>(
    scope: &mut v8::PinScope<'s, '_, ()>,
    get_trace: GetTraceConfig,
) -> v8::Local<'s, v8::Context> {
    if !get_trace.enabled {
        return v8::Context::new(scope, v8::ContextOptions::default());
    }
    let global_template = v8::ObjectTemplate::new(scope);
    global_template.set_named_property_handler(
        v8::NamedPropertyHandlerConfiguration::new()
            .getter(global_get_trace_callback)
            .descriptor(global_descriptor_fallthrough_callback)
            .flags(v8::PropertyHandlerFlags::ONLY_INTERCEPT_STRINGS),
    );
    v8::Context::new(
        scope,
        v8::ContextOptions {
            global_template: Some(global_template),
            ..v8::ContextOptions::default()
        },
    )
}

fn install_native_functions(
    scope: &mut v8::PinScope,
    context: v8::Local<v8::Context>,
) -> Result<(), V8Error> {
    let global = context.global(scope);
    let observation_sequence = v8::Function::new(scope, observation_sequence_callback).ok_or(
        V8Error::NativeInstallation("__yatouNextObservationSequence"),
    )?;
    set_hidden_function(
        scope,
        global,
        "__yatouNextObservationSequence",
        observation_sequence,
    )?;
    let atob =
        v8::Function::new(scope, atob_callback).ok_or(V8Error::NativeInstallation("atob"))?;
    set_function(scope, global, "atob", atob)?;
    let btoa =
        v8::Function::new(scope, btoa_callback).ok_or(V8Error::NativeInstallation("btoa"))?;
    set_function(scope, global, "btoa", btoa)?;
    let add_event_listener = v8::Function::new(scope, add_event_listener_callback)
        .ok_or(V8Error::NativeInstallation("addEventListener"))?;
    set_function(scope, global, "addEventListener", add_event_listener)?;

    let performance = v8::Object::new(scope);
    let now = v8::Function::new(scope, performance_now_callback)
        .ok_or(V8Error::NativeInstallation("performance.now"))?;
    set_function(scope, performance, "now", now)?;
    let key = v8::String::new(scope, "performance").ok_or(V8Error::SourceAllocation)?;
    if !global
        .set(scope, key.into(), performance.into())
        .unwrap_or(false)
    {
        return Err(V8Error::NativeInstallation("performance"));
    }
    trusted_types::install(scope, context)?;
    Ok(())
}

fn set_hidden_function(
    scope: &mut v8::PinScope,
    object: v8::Local<v8::Object>,
    name: &'static str,
    function: v8::Local<v8::Function>,
) -> Result<(), V8Error> {
    let key = v8::String::new(scope, name).ok_or(V8Error::SourceAllocation)?;
    function.set_name(key);
    if object
        .define_own_property(
            scope,
            key.into(),
            function.into(),
            v8::PropertyAttribute::DONT_ENUM,
        )
        .unwrap_or(false)
    {
        Ok(())
    } else {
        Err(V8Error::NativeInstallation(name))
    }
}

fn set_function(
    scope: &mut v8::PinScope,
    object: v8::Local<v8::Object>,
    name: &'static str,
    function: v8::Local<v8::Function>,
) -> Result<(), V8Error> {
    let key = v8::String::new(scope, name).ok_or(V8Error::SourceAllocation)?;
    function.set_name(key);
    if object
        .set(scope, key.into(), function.into())
        .unwrap_or(false)
    {
        Ok(())
    } else {
        Err(V8Error::NativeInstallation(name))
    }
}

fn browser_bootstrap(profile: &BrowserProfile) -> String {
    let profile = serde_json::to_string(profile).expect("browser profile is serializable");
    format!(
        r#"(() => {{
            const p = {profile};
            const data = (object, key, value, enumerable = true) =>
                Object.defineProperty(object, key, {{ value, writable: true, enumerable, configurable: true }});
            const getter = (object, key, value, enumerable = true) =>
                Object.defineProperty(object, key, {{ get: () => value, enumerable, configurable: true }});
            getter(globalThis, "window", globalThis);
            getter(globalThis, "self", globalThis);
            const navigator = {{}};
            for (const [key, value] of Object.entries({{
                userAgent: p.user_agent,
                appVersion: p.user_agent.replace(/^Mozilla\//, ""),
                appCodeName: "Mozilla",
                appName: "Netscape",
                platform: p.platform,
                language: p.language,
                languages: Object.freeze(p.languages.slice()),
                hardwareConcurrency: p.hardware_concurrency,
                webdriver: false,
                cookieEnabled: true,
                onLine: true,
                product: "Gecko",
                productSub: "20030107",
                vendor: "Google Inc."
            }})) getter(navigator, key, value);
            getter(globalThis, "navigator", navigator);
            const screen = {{}};
            for (const [key, value] of Object.entries({{
                width: p.screen_width,
                height: p.screen_height,
                availWidth: p.screen_avail_width,
                availHeight: p.screen_avail_height,
                colorDepth: p.screen_depth,
                pixelDepth: p.screen_depth,
                availLeft: 0,
                availTop: 0
            }})) getter(screen, key, value);
            getter(globalThis, "screen", screen);
            data(performance, "timeOrigin", 1786103386944.1);
            const document = {{
                URL: "about:blank",
                documentURI: "about:blank",
                referrer: "",
                cookie: "",
                readyState: "complete",
                visibilityState: "visible",
                hidden: false,
                documentElement: {{ style: {{}}, clientWidth: 1280, clientHeight: 720 }},
                body: {{ style: {{}}, appendChild() {{}}, removeChild() {{}} }},
                createElement(tag) {{
                    return {{
                        tagName: String(tag).toUpperCase(), style: {{}}, children: [],
                        contentWindow: globalThis,
                        appendChild(child) {{ this.children.push(child); return child; }},
                        remove() {{}}, setAttribute() {{}}, getAttribute() {{ return null; }},
                        getContext() {{ return null; }}, toDataURL() {{ return "data:,"; }}
                    }};
                }},
                addEventListener,
                removeEventListener() {{}},
                getElementsByTagName() {{ return []; }},
                querySelector() {{ return null; }}
            }};
            getter(globalThis, "document", document);
            data(globalThis, "location", {{ href: "about:blank", protocol: "about:", host: "", hostname: "", pathname: "blank" }});
            data(globalThis, "innerWidth", 1280);
            data(globalThis, "innerHeight", 720);
            data(globalThis, "devicePixelRatio", 1);
            data(globalThis, "removeEventListener", function removeEventListener() {{}});
            data(globalThis, "__yatouTrace", [], false);
        }})()"#
    )
}

fn execute_to_string(scope: &mut v8::PinScope, source: &str) -> Result<String, V8Error> {
    let source = v8::String::new(scope, source).ok_or(V8Error::SourceAllocation)?;
    let script = v8::Script::compile(scope, source, None)
        .ok_or_else(|| V8Error::Compilation("V8 returned no script".to_owned()))?;
    let value = script
        .run(scope)
        .ok_or_else(|| V8Error::Execution("V8 returned no value".to_owned()))?;
    let value = value.to_string(scope).ok_or(V8Error::ResultConversion)?;
    Ok(value.to_rust_string_lossy(scope))
}

fn execute_value<'s>(
    scope: &mut v8::PinScope<'s, '_>,
    source: &str,
) -> Result<v8::Local<'s, v8::Value>, V8Error> {
    let source = v8::String::new(scope, source).ok_or(V8Error::SourceAllocation)?;
    let script = v8::Script::compile(scope, source, None)
        .ok_or_else(|| V8Error::Compilation("V8 returned no script".to_owned()))?;
    script
        .run(scope)
        .ok_or_else(|| V8Error::Execution("V8 returned no value".to_owned()))
}

fn finish_botguard_run(
    model_source: &str,
    envelope: BotguardEnvelope,
    observations: &[NativeObservation],
) -> Result<BotguardRun, V8Error> {
    let error = envelope
        .error
        .map(|error| format!("{}: {}", error.name, error.message));
    let token_length = envelope.token.as_deref().map_or(0, str::len);
    let starts_with_bang = envelope
        .token
        .as_deref()
        .is_some_and(|token| token.starts_with('!'));
    let shape = serde_json::json!({
        "error": error.is_none(),
        "starts_with_bang": starts_with_bang,
        "token_length": token_length,
        "token_type": if envelope.token.is_some() { "string" } else { "null" },
    });
    let shape_bytes =
        serde_json::to_vec(&shape).map_err(|error| V8Error::ResultDecode(error.to_string()))?;
    let token_shape_sha256 = sha256_hex(&shape_bytes);
    let trace = botguard_trace(
        model_source,
        observations,
        &token_shape_sha256,
        error.is_none(),
    )?;
    Ok(BotguardRun {
        token: envelope.token,
        error,
        starts_with_bang,
        token_length,
        api_call_count: observations.len(),
        token_shape_sha256,
        trace,
        diagnostic_trace: envelope.diagnostic_trace,
    })
}

fn botguard_trace(
    model_source: &str,
    observations: &[NativeObservation],
    checkpoint_sha256: &str,
    succeeded: bool,
) -> Result<TraceStream, V8Error> {
    let header = TraceHeader {
        schema_version: CURRENT_SCHEMA_VERSION,
        trace_id: "google-botguard-archived-m6-yatou".to_owned(),
        baseline_id: BaselineId::parse("win11-chrome150.0.7871.188-headful-m2-v2")
            .map_err(|error| V8Error::Trace(error.to_string()))?,
        source: TraceSource::Yatouv8,
        created_at: "2026-08-07T00:00:00Z".to_owned(),
        producer: "yatou-core/0.1.0-alpha.0".to_owned(),
    };
    let mut recorder = TraceRecorder::new(header);
    let eval_seq = recorder
        .record_l0(
            0,
            None,
            ReplayEvent::EvalStart {
                eval_id: "botguard.invoke".to_owned(),
                source_sha256: sha256_hex(model_source.as_bytes()),
            },
        )
        .map_err(|error| V8Error::Trace(error.to_string()))?;
    for (index, observation) in observations.iter().enumerate() {
        recorder
            .record_l1(
                u64::try_from(index + 1).unwrap_or(u64::MAX),
                Some(eval_seq),
                ApiLedgerEvent {
                    operation: ApiOperation::Call,
                    target: observation.target.to_owned(),
                    member: Some(observation.member.to_owned()),
                    arguments: observation.arguments.clone(),
                    outcome: ApiOutcome::Return {
                        value: observation.outcome.clone(),
                    },
                    call_site: None,
                },
            )
            .map_err(|error| V8Error::Trace(error.to_string()))?;
    }
    let checkpoint_time = u64::try_from(observations.len() + 1).unwrap_or(u64::MAX);
    recorder
        .record_l0(
            checkpoint_time,
            Some(eval_seq),
            ReplayEvent::Checkpoint {
                name: "botguard.result.shape".to_owned(),
                state_sha256: checkpoint_sha256.to_owned(),
            },
        )
        .map_err(|error| V8Error::Trace(error.to_string()))?;
    recorder
        .record_l0(
            checkpoint_time.saturating_add(1),
            Some(eval_seq),
            ReplayEvent::EvalEnd {
                eval_id: "botguard.invoke".to_owned(),
                outcome: if succeeded {
                    EvalOutcome::Return
                } else {
                    EvalOutcome::Throw
                },
            },
        )
        .map_err(|error| V8Error::Trace(error.to_string()))?;
    recorder
        .finish()
        .map_err(|error| V8Error::Trace(error.to_string()))
}

fn sha256_hex(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

/// Configuration for one persistent browser-compatible V8 realm.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RuntimeConfig {
    /// Browser identity and deterministic clock profile.
    pub profile: BrowserProfile,
    /// Initial document URL.
    pub url: String,
    /// Viewport width in CSS pixels.
    pub viewport_width: u32,
    /// Viewport height in CSS pixels.
    pub viewport_height: u32,
    /// Device scale factor.
    pub device_scale_factor: f64,
    /// Wall-clock origin paired with `performance.now()`.
    pub time_origin_ms: f64,
    /// Seed for deterministic `crypto.getRandomValues()` in replay mode.
    pub random_seed: u32,
    /// Trace identifier. It must contain only identifier-safe characters.
    pub trace_id: String,
    /// Optional diagnostic property-read ledger. Disabled for oracle runs.
    #[serde(default)]
    pub get_trace: GetTraceConfig,
}

/// Bounded L1 property-read diagnostics.
///
/// GET tracing is opt-in because observing arbitrary JavaScript property reads
/// requires transparent proxies around browser-host values. Production/oracle
/// runs keep the original object graph untouched.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
pub struct GetTraceConfig {
    /// Whether browser-host property reads are appended as L1 `get` events.
    pub enabled: bool,
    /// Maximum number of GET events retained per runtime.
    pub max_events: u32,
}

impl Default for GetTraceConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            max_events: 50_000,
        }
    }
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        static RUNTIME_SEQUENCE: AtomicU64 = AtomicU64::new(1);
        Self {
            profile: BrowserProfile::default(),
            url: "https://fixture.invalid/".to_owned(),
            viewport_width: 1_280,
            viewport_height: 720,
            device_scale_factor: 1.0,
            time_origin_ms: 1_786_103_386_944.1,
            random_seed: 0x05ee_d150,
            trace_id: format!(
                "yatou-runtime-{}",
                RUNTIME_SEQUENCE.fetch_add(1, Ordering::Relaxed)
            ),
            get_trace: GetTraceConfig::default(),
        }
    }
}

impl RuntimeConfig {
    fn validate(&self) -> Result<(), RuntimeError> {
        let valid_trace_id = !self.trace_id.is_empty()
            && self
                .trace_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'));
        if !valid_trace_id {
            return Err(RuntimeError::Configuration(
                "trace_id must use only ASCII letters, digits, '.', '_' or '-'".to_owned(),
            ));
        }
        if self.url.is_empty() || self.url.chars().any(char::is_whitespace) {
            return Err(RuntimeError::Configuration(
                "url must be a non-empty absolute serialization without whitespace".to_owned(),
            ));
        }
        if self.viewport_width == 0 || self.viewport_height == 0 {
            return Err(RuntimeError::Configuration(
                "viewport dimensions must be positive".to_owned(),
            ));
        }
        if !self.device_scale_factor.is_finite() || self.device_scale_factor <= 0.0 {
            return Err(RuntimeError::Configuration(
                "device_scale_factor must be finite and positive".to_owned(),
            ));
        }
        match &self.profile.clock {
            ClockMode::FixedStep { start_ms, step_ms } => {
                if !start_ms.is_finite() || !step_ms.is_finite() || *step_ms < 0.0 {
                    return Err(RuntimeError::Configuration(
                        "fixed-step clock values must be finite and step_ms must be non-negative"
                            .to_owned(),
                    ));
                }
            }
            ClockMode::Recorded {
                buckets,
                fallback_quantum_ms,
                fallback_repeats,
            } => {
                let mut previous = None;
                let valid = !buckets.is_empty()
                    && *fallback_repeats > 0
                    && fallback_quantum_ms.is_finite()
                    && *fallback_quantum_ms >= 0.0
                    && buckets.iter().all(|bucket| {
                        let ordered = previous.is_none_or(|value| bucket.value_ms >= value);
                        previous = Some(bucket.value_ms);
                        bucket.value_ms.is_finite() && bucket.repeat > 0 && ordered
                    });
                if !valid {
                    return Err(RuntimeError::Configuration(
                        "recorded clock requires ordered finite buckets, positive repeats, and a non-negative fallback quantum"
                            .to_owned(),
                    ));
                }
            }
        }
        if self.get_trace.enabled
            && (self.get_trace.max_events == 0 || self.get_trace.max_events > 1_000_000)
        {
            return Err(RuntimeError::Configuration(
                "get_trace.max_events must be between 1 and 1000000 when enabled".to_owned(),
            ));
        }
        Ok(())
    }
}

/// Stable result envelope returned by the persistent runtime.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct EvalResult {
    /// Whether the source returned without throwing.
    pub ok: bool,
    /// JavaScript value category (`undefined`, `object`, `string`, and so on).
    pub kind: String,
    /// Bounded JavaScript string representation.
    pub display: String,
    /// `JSON.stringify` result when the value is JSON-representable.
    pub json: Option<String>,
    /// Exception constructor name when `ok` is false.
    pub exception_name: Option<String>,
    /// Exception message when `ok` is false.
    pub exception_message: Option<String>,
}

/// Failures crossing the persistent runtime's owner-thread boundary.
#[derive(Debug, Error)]
pub enum RuntimeError {
    /// Invalid runtime configuration.
    #[error("invalid runtime configuration: {0}")]
    Configuration(String),
    /// Invalid caller-provided offline resource.
    #[error(transparent)]
    Resource(#[from] ResourceError),
    /// Runtime is closed or its owner thread exited.
    #[error("runtime is closed")]
    Closed,
    /// Runtime owner thread returned a structured failure.
    #[error("runtime worker failed: {0}")]
    Worker(String),
    /// Runtime owner thread panicked during shutdown.
    #[error("runtime worker panicked")]
    WorkerPanicked,
}

type WorkerReply<T> = mpsc::Sender<Result<T, String>>;

enum RuntimeCommand {
    Eval {
        source: String,
        reply: WorkerReply<EvalResult>,
    },
    AddResource {
        resource: Resource,
        reply: WorkerReply<()>,
    },
    Drain {
        limit: u32,
        reply: WorkerReply<serde_json::Value>,
    },
    Trace {
        reply: WorkerReply<TraceStream>,
    },
    Environment {
        reply: WorkerReply<serde_json::Value>,
    },
    ImportCookies {
        cookies: serde_json::Value,
        reply: WorkerReply<u64>,
    },
    ExportCookies {
        reply: WorkerReply<serde_json::Value>,
    },
    Navigation {
        take: bool,
        reply: WorkerReply<serde_json::Value>,
    },
    TraceStats {
        reply: WorkerReply<serde_json::Value>,
    },
    Close {
        reply: mpsc::Sender<()>,
    },
}

/// Persistent V8 isolate and browser realm owned by a dedicated native thread.
///
/// Commands from Python or Rust are serialized onto the owner thread. No V8
/// handle crosses that boundary, and resource access is restricted to explicit
/// [`Resource`] values.
pub struct BrowserRuntime {
    commands: mpsc::Sender<RuntimeCommand>,
    worker: Mutex<Option<JoinHandle<()>>>,
    closed: AtomicBool,
}

impl std::fmt::Debug for BrowserRuntime {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("BrowserRuntime")
            .field("closed", &self.closed.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

impl BrowserRuntime {
    /// Start an owner thread, create one isolate/context, and install the browser host.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] for invalid configuration, thread creation, V8
    /// initialization, or browser bootstrap failures.
    pub fn new(config: RuntimeConfig) -> Result<Self, RuntimeError> {
        config.validate()?;
        let (commands, receiver) = mpsc::channel();
        let (ready_tx, ready_rx) = mpsc::channel();
        let worker = thread::Builder::new()
            .name("yatouv8-isolate-owner".to_owned())
            .spawn(move || runtime_worker(config, receiver, ready_tx))
            .map_err(|error| RuntimeError::Worker(error.to_string()))?;
        match ready_rx.recv() {
            Ok(Ok(())) => Ok(Self {
                commands,
                worker: Mutex::new(Some(worker)),
                closed: AtomicBool::new(false),
            }),
            Ok(Err(error)) => {
                let _ = worker.join();
                Err(RuntimeError::Worker(error))
            }
            Err(_) => {
                let _ = worker.join();
                Err(RuntimeError::Worker(
                    "owner thread exited during initialization".to_owned(),
                ))
            }
        }
    }

    /// Evaluate source in the persistent realm.
    ///
    /// JavaScript exceptions are represented by [`EvalResult::ok`] rather than
    /// destroying the context.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when the owner thread is unavailable or cannot
    /// serialize the result.
    pub fn eval(&self, source: impl Into<String>) -> Result<EvalResult, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::Eval {
                source: source.into(),
                reply,
            })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Add or replace one exact offline resource.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] for invalid content or an unavailable owner thread.
    pub fn add_resource(&self, resource: Resource) -> Result<(), RuntimeError> {
        resource.validate()?;
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::AddResource { resource, reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Drain deterministic microtasks and timers up to `limit` callbacks.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] for owner-thread or host failures.
    pub fn drain(&self, limit: u32) -> Result<serde_json::Value, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::Drain { limit, reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Return a validated snapshot of every L0/L1 event recorded so far.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when trace validation or the owner thread fails.
    pub fn trace(&self) -> Result<TraceStream, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::Trace { reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Return immutable environment metadata exposed to the realm.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when the owner thread cannot serialize metadata.
    pub fn environment(&self) -> Result<serde_json::Value, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::Environment { reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Import structured cookies into the document jar.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when `cookies` is not an array or the owner
    /// thread cannot update the jar.
    pub fn import_cookies(&self, cookies: serde_json::Value) -> Result<u64, RuntimeError> {
        if !cookies.is_array() {
            return Err(RuntimeError::Configuration(
                "cookies must be a JSON array".to_owned(),
            ));
        }
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::ImportCookies { cookies, reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Export cookies visible to the current URL, including `HttpOnly` entries
    /// imported by the host session.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when the owner thread is unavailable.
    pub fn export_cookies(&self) -> Result<serde_json::Value, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::ExportCookies { reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Peek or consume the next navigation requested by `location.assign`,
    /// `location.replace`, or `location.reload`.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when the owner thread is unavailable.
    pub fn navigation(&self, take: bool) -> Result<serde_json::Value, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::Navigation { take, reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Return bounded property/reflection trace counters without exposing an
    /// internal JavaScript helper on the global object.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError`] when the owner thread is unavailable.
    pub fn trace_stats(&self) -> Result<serde_json::Value, RuntimeError> {
        self.ensure_open()?;
        let (reply, response) = mpsc::channel();
        self.commands
            .send(RuntimeCommand::TraceStats { reply })
            .map_err(|_| RuntimeError::Closed)?;
        recv_worker(&response)
    }

    /// Stop the owner thread. Calling this method more than once is harmless.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeError::WorkerPanicked`] when shutdown joins a panicked worker.
    pub fn close(&self) -> Result<(), RuntimeError> {
        if self.closed.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        let (reply, response) = mpsc::channel();
        let _ = self.commands.send(RuntimeCommand::Close { reply });
        let _ = response.recv();
        let worker = self
            .worker
            .lock()
            .map_err(|_| RuntimeError::Worker("worker lock poisoned".to_owned()))?
            .take();
        if worker.is_some_and(|worker| worker.join().is_err()) {
            return Err(RuntimeError::WorkerPanicked);
        }
        Ok(())
    }

    /// Whether shutdown has begun.
    #[must_use]
    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }

    fn ensure_open(&self) -> Result<(), RuntimeError> {
        if self.is_closed() {
            Err(RuntimeError::Closed)
        } else {
            Ok(())
        }
    }
}

impl Drop for BrowserRuntime {
    fn drop(&mut self) {
        let _ = self.close();
    }
}

fn recv_worker<T>(response: &mpsc::Receiver<Result<T, String>>) -> Result<T, RuntimeError> {
    response
        .recv()
        .map_err(|_| RuntimeError::Closed)?
        .map_err(RuntimeError::Worker)
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum HostObservation {
    Api {
        order: u32,
        target: String,
        member: String,
        operation: String,
        arguments: Vec<HostValueSummary>,
        outcome: HostValueSummary,
        threw: bool,
    },
    ResourceRequest {
        order: u32,
        request_id: String,
        method: String,
        url: String,
    },
    ResourceResponse {
        order: u32,
        request_id: String,
        status: u16,
        headers: BTreeMap<String, String>,
        body: Vec<u8>,
        body_sha256: String,
    },
    TimerSchedule {
        order: u32,
        timer_id: u64,
        delay_ms: f64,
        repeating: bool,
    },
    TimerFire {
        order: u32,
        timer_id: u64,
    },
}

#[derive(Debug, Deserialize)]
struct HostValueSummary {
    kind: String,
    preview: String,
}

enum SessionObservation {
    Native(NativeObservation),
    Host(HostObservation),
}

impl SessionObservation {
    const fn order(&self) -> u32 {
        match self {
            Self::Native(observation) => observation.order,
            Self::Host(observation) => observation.order(),
        }
    }
}

impl HostObservation {
    const fn order(&self) -> u32 {
        match self {
            Self::Api { order, .. }
            | Self::ResourceRequest { order, .. }
            | Self::ResourceResponse { order, .. }
            | Self::TimerSchedule { order, .. }
            | Self::TimerFire { order, .. } => *order,
        }
    }
}

struct SessionTrace {
    recorder: TraceRecorder,
    logical_time: u64,
    eval_sequence: u64,
}

impl SessionTrace {
    fn new(config: &RuntimeConfig) -> Result<Self, String> {
        let baseline_id = BaselineId::parse(yatou_surface::GENERATED_BASELINE_ID)
            .map_err(|error| error.to_string())?;
        Ok(Self {
            recorder: TraceRecorder::new(TraceHeader {
                schema_version: CURRENT_SCHEMA_VERSION,
                trace_id: config.trace_id.clone(),
                baseline_id,
                source: TraceSource::Yatouv8,
                created_at: "2026-08-07T00:00:00Z".to_owned(),
                producer: format!("yatou-core/{}", env!("CARGO_PKG_VERSION")),
            }),
            logical_time: 0,
            eval_sequence: 0,
        })
    }

    fn time(&mut self) -> u64 {
        let value = self.logical_time;
        self.logical_time = self.logical_time.saturating_add(1);
        value
    }

    fn start_eval(&mut self, source: &str) -> Result<(String, u64), TraceRuntimeError> {
        self.eval_sequence = self.eval_sequence.saturating_add(1);
        let eval_id = format!("eval-{}", self.eval_sequence);
        let time = self.time();
        let seq = self.recorder.record_l0(
            time,
            None,
            ReplayEvent::EvalStart {
                eval_id: eval_id.clone(),
                source_sha256: sha256_hex(source.as_bytes()),
            },
        )?;
        Ok((eval_id, seq))
    }

    fn finish_eval(
        &mut self,
        eval_id: String,
        parent: u64,
        result: &EvalResult,
    ) -> Result<(), TraceRuntimeError> {
        let digest = sha256_hex(&serde_json::to_vec(result).unwrap_or_default());
        let time = self.time();
        self.recorder.record_l0(
            time,
            Some(parent),
            ReplayEvent::Checkpoint {
                name: format!("{eval_id}.result"),
                state_sha256: digest,
            },
        )?;
        let time = self.time();
        self.recorder.record_l0(
            time,
            Some(parent),
            ReplayEvent::EvalEnd {
                eval_id,
                outcome: if result.ok {
                    EvalOutcome::Return
                } else {
                    EvalOutcome::Throw
                },
            },
        )?;
        Ok(())
    }

    fn observations(
        &mut self,
        parent: Option<u64>,
        native: Vec<NativeObservation>,
        host: Vec<HostObservation>,
    ) -> Result<(), TraceRuntimeError> {
        let mut observations = native
            .into_iter()
            .map(SessionObservation::Native)
            .chain(host.into_iter().map(SessionObservation::Host))
            .collect::<Vec<_>>();
        observations.sort_by_key(SessionObservation::order);
        for observation in observations {
            match observation {
                SessionObservation::Native(observation) => {
                    self.record_native(parent, observation)?;
                }
                SessionObservation::Host(observation) => self.record_host(parent, observation)?,
            }
        }
        Ok(())
    }

    fn record_native(
        &mut self,
        parent: Option<u64>,
        observation: NativeObservation,
    ) -> Result<(), TraceRuntimeError> {
        let time = self.time();
        self.recorder.record_l1(
            time,
            parent,
            ApiLedgerEvent {
                operation: ApiOperation::Call,
                target: observation.target.to_owned(),
                member: Some(observation.member.to_owned()),
                arguments: observation.arguments,
                outcome: ApiOutcome::Return {
                    value: observation.outcome,
                },
                call_site: None,
            },
        )?;
        Ok(())
    }

    #[allow(clippy::too_many_lines)]
    fn record_host(
        &mut self,
        parent: Option<u64>,
        observation: HostObservation,
    ) -> Result<(), TraceRuntimeError> {
        let time = self.time();
        match observation {
            HostObservation::Api {
                order: _,
                target,
                member,
                operation,
                arguments,
                outcome,
                threw,
            } => {
                let operation = match operation.as_str() {
                    "get" => ApiOperation::Get,
                    "set" => ApiOperation::Set,
                    "construct" => ApiOperation::Construct,
                    "own_keys" => ApiOperation::OwnKeys,
                    "get_own_property_descriptor" => ApiOperation::GetOwnPropertyDescriptor,
                    "get_prototype_of" => ApiOperation::GetPrototypeOf,
                    "has" => ApiOperation::Has,
                    "define_property" => ApiOperation::DefineProperty,
                    _ => ApiOperation::Call,
                };
                let outcome = if threw {
                    ApiOutcome::Throw {
                        exception: ExceptionSummary {
                            name: "Error".to_owned(),
                            message: outcome.preview,
                            stack_sha256: None,
                        },
                    }
                } else {
                    ApiOutcome::Return {
                        value: host_value(outcome),
                    }
                };
                self.recorder.record_l1(
                    time,
                    parent,
                    ApiLedgerEvent {
                        operation,
                        target,
                        member: Some(member),
                        arguments: arguments.into_iter().map(host_value).collect(),
                        outcome,
                        call_site: None,
                    },
                )?;
            }
            HostObservation::ResourceRequest {
                order: _,
                request_id,
                method,
                url,
            } => {
                self.recorder.record_l0(
                    time,
                    parent,
                    ReplayEvent::ResourceRequest {
                        request_id,
                        method,
                        url,
                    },
                )?;
            }
            HostObservation::ResourceResponse {
                order: _,
                request_id,
                status,
                headers,
                body,
                body_sha256,
            } => {
                self.recorder.record_l0(
                    time,
                    parent,
                    ReplayEvent::ResourceResponse {
                        request_id,
                        status,
                        headers,
                        body_base64: base64::engine::general_purpose::STANDARD.encode(body),
                        body_sha256,
                    },
                )?;
            }
            HostObservation::TimerSchedule {
                order: _,
                timer_id,
                delay_ms,
                repeating,
            } => {
                self.recorder.record_l0(
                    time,
                    parent,
                    ReplayEvent::TimerSchedule {
                        timer_id,
                        delay_ms,
                        repeating,
                    },
                )?;
            }
            HostObservation::TimerFire { order: _, timer_id } => {
                self.recorder
                    .record_l0(time, parent, ReplayEvent::TimerFire { timer_id })?;
            }
        }
        Ok(())
    }

    fn snapshot(&self) -> Result<TraceStream, TraceRuntimeError> {
        self.recorder.clone().finish()
    }
}

fn host_value(value: HostValueSummary) -> ValueSummary {
    ValueSummary {
        kind: match value.kind.as_str() {
            "undefined" => JsValueKind::Undefined,
            "null" => JsValueKind::Null,
            "boolean" => JsValueKind::Boolean,
            "number" => JsValueKind::Number,
            "bigint" => JsValueKind::Bigint,
            "string" => JsValueKind::String,
            "symbol" => JsValueKind::Symbol,
            "function" => JsValueKind::Function,
            _ => JsValueKind::Object,
        },
        preview: Some(value.preview),
        sha256: None,
    }
}

#[allow(clippy::needless_pass_by_value, clippy::too_many_lines)]
fn runtime_worker(
    config: RuntimeConfig,
    receiver: mpsc::Receiver<RuntimeCommand>,
    ready: mpsc::Sender<Result<(), String>>,
) {
    initialize_v8();
    configure_callbacks(&config.profile.clock);
    let mut isolate = v8::Isolate::new(v8::CreateParams::default());
    isolate.set_microtasks_policy(v8::MicrotasksPolicy::Explicit);
    let setup = (|| -> Result<(v8::Global<v8::Context>, v8::Global<v8::Object>), V8Error> {
        v8::scope!(let handle_scope, &mut isolate);
        let context = runtime_context(handle_scope, config.get_trace);
        let scope = &mut v8::ContextScope::new(handle_scope, context);
        install_native_functions(scope, context)?;
        let surface_manifest: serde_json::Value = serde_json::from_str(include_str!(
            "../../../manifests/chrome150.runtime-surface.json"
        ))
        .map_err(|error| V8Error::ResultDecode(error.to_string()))?;
        let runtime_member_count = surface_manifest["interfaces"]
            .as_array()
            .map(|interfaces| {
                interfaces
                    .iter()
                    .map(|interface| interface["members"].as_array().map_or(0, Vec::len))
                    .sum::<usize>()
            })
            .unwrap_or_default();
        if surface_manifest["baseline_id"] != yatou_surface::GENERATED_BASELINE_ID
            || runtime_member_count != yatou_surface::GENERATED_MEMBERS.len()
        {
            return Err(V8Error::ResultDecode(
                "runtime surface and generated Rust table disagree".to_owned(),
            ));
        }
        let bootstrap_config = serde_json::json!({
            "profile": config.profile,
            "url": config.url,
            "viewport": {
                "width": config.viewport_width,
                "height": config.viewport_height,
                "device_scale_factor": config.device_scale_factor,
            },
            "time_origin_ms": config.time_origin_ms,
            "random_seed": config.random_seed,
            "get_trace": config.get_trace,
            "baseline": yatou_surface::GENERATED_BASELINE_ID,
            "surface_manifest": surface_manifest,
        });
        let bootstrap_config = serde_json::to_string(&bootstrap_config)
            .map_err(|error| V8Error::ResultDecode(error.to_string()))?;
        let bootstrap = format!(
            "globalThis.__yatouConfig = {bootstrap_config};\n{}",
            include_str!("browser_host.js")
        );
        execute_to_string(scope, &bootstrap)?;
        let bridge = capture_runtime_bridge(scope, context)?;
        Ok((v8::Global::new(scope, context), bridge))
    })();
    let (context, bridge) = match setup {
        Ok(handles) => handles,
        Err(error) => {
            let _ = ready.send(Err(error.to_string()));
            return;
        }
    };
    let mut trace = match SessionTrace::new(&config) {
        Ok(trace) => trace,
        Err(error) => {
            let _ = ready.send(Err(error));
            return;
        }
    };
    if ready.send(Ok(())).is_err() {
        return;
    }

    while let Ok(command) = receiver.recv() {
        match command {
            RuntimeCommand::Eval { source, reply } => {
                let response = (|| -> Result<EvalResult, String> {
                    let (eval_id, parent) = trace.start_eval(&source).map_err(|e| e.to_string())?;
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let result = evaluate_session_source(scope, &bridge, &source)
                        .map_err(|e| e.to_string())?;
                    set_get_trace_active(scope, &bridge, true).map_err(|e| e.to_string())?;
                    scope.perform_microtask_checkpoint();
                    set_get_trace_active(scope, &bridge, false).map_err(|e| e.to_string())?;
                    let host = take_host_observations(scope, &bridge)?;
                    let native = take_observations();
                    trace
                        .observations(Some(parent), native, host)
                        .map_err(|e| e.to_string())?;
                    trace
                        .finish_eval(eval_id, parent, &result)
                        .map_err(|e| e.to_string())?;
                    Ok(result)
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::AddResource { resource, reply } => {
                let response = (|| -> Result<(), String> {
                    resource.validate().map_err(|error| error.to_string())?;
                    let resource = serde_json::to_string(&resource).map_err(|e| e.to_string())?;
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let value = execute_value(scope, &format!("({resource})"))
                        .map_err(|error| error.to_string())?;
                    call_runtime_bridge(scope, &bridge, "__yatouInstallResource", &[value])
                        .map_err(|error| error.to_string())?;
                    Ok(())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::Drain { limit, reply } => {
                let response = (|| -> Result<serde_json::Value, String> {
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    set_get_trace_active(scope, &bridge, true).map_err(|e| e.to_string())?;
                    let limit: v8::Local<v8::Value> =
                        v8::Integer::new_from_unsigned(scope, limit).into();
                    let result = bridge_json(scope, &bridge, "__yatouDrain", &[limit])
                        .map_err(|error| error.to_string())?;
                    scope.perform_microtask_checkpoint();
                    set_get_trace_active(scope, &bridge, false).map_err(|e| e.to_string())?;
                    let host = take_host_observations(scope, &bridge)?;
                    let native = take_observations();
                    trace
                        .observations(None, native, host)
                        .map_err(|e| e.to_string())?;
                    serde_json::from_str(&result).map_err(|error| error.to_string())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::Trace { reply } => {
                let response = trace.snapshot().map_err(|error| error.to_string());
                let _ = reply.send(response);
            }
            RuntimeCommand::Environment { reply } => {
                let response = (|| -> Result<serde_json::Value, String> {
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let local_bridge = v8::Local::new(scope, &bridge);
                    let environment = bridge_member(scope, local_bridge, "__yatouEnvironment")
                        .ok_or_else(|| "runtime environment bridge is missing".to_owned())?;
                    let json = v8::json::stringify(scope, environment)
                        .ok_or_else(|| "runtime environment serialization failed".to_owned())?
                        .to_rust_string_lossy(scope);
                    serde_json::from_str(&json).map_err(|error| error.to_string())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::ImportCookies { cookies, reply } => {
                let response = (|| -> Result<u64, String> {
                    let cookies = serde_json::to_string(&cookies).map_err(|e| e.to_string())?;
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let value = execute_value(scope, &format!("({cookies})"))
                        .map_err(|error| error.to_string())?;
                    let result =
                        call_runtime_bridge(scope, &bridge, "__yatouImportCookies", &[value])
                            .map_err(|error| error.to_string())?;
                    result
                        .integer_value(scope)
                        .map(|value| u64::try_from(value).unwrap_or_default())
                        .ok_or_else(|| "cookie import did not return a count".to_owned())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::ExportCookies { reply } => {
                let response = (|| -> Result<serde_json::Value, String> {
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let json = bridge_json(scope, &bridge, "__yatouExportCookies", &[])
                        .map_err(|error| error.to_string())?;
                    serde_json::from_str(&json).map_err(|error| error.to_string())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::Navigation { take, reply } => {
                let response = (|| -> Result<serde_json::Value, String> {
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let member = if take {
                        "__yatouTakeNavigation"
                    } else {
                        "__yatouPeekNavigation"
                    };
                    let json = bridge_json(scope, &bridge, member, &[])
                        .map_err(|error| error.to_string())?;
                    serde_json::from_str(&json).map_err(|error| error.to_string())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::TraceStats { reply } => {
                let response = (|| -> Result<serde_json::Value, String> {
                    v8::scope!(let handle_scope, &mut isolate);
                    let local_context = v8::Local::new(handle_scope, &context);
                    let scope = &mut v8::ContextScope::new(handle_scope, local_context);
                    let json = bridge_json(scope, &bridge, "__yatouGetTraceStats", &[])
                        .map_err(|error| error.to_string())?;
                    serde_json::from_str(&json).map_err(|error| error.to_string())
                })();
                let _ = reply.send(response);
            }
            RuntimeCommand::Close { reply } => {
                let _ = reply.send(());
                break;
            }
        }
    }
}

fn evaluate_session_source(
    scope: &mut v8::PinScope,
    bridge: &v8::Global<v8::Object>,
    source: &str,
) -> Result<EvalResult, V8Error> {
    let wrapper = r#"(function (setGetTraceActive, source) {
            const indirectEval = eval;
            try {
                let value;
                setGetTraceActive(true);
                try {
                    value = (0, indirectEval)(source);
                } finally {
                    setGetTraceActive(false);
                }
                let json = null;
                try {
                    const encoded = JSON.stringify(value);
                    if (encoded !== undefined) json = encoded;
                } catch (_error) {}
                let display;
                try { display = String(value); } catch (_error) { display = "<unprintable>"; }
                return JSON.stringify({
                    ok: true,
                    kind: value === null ? "null" : typeof value,
                    display: display.length > 4096 ? display.slice(0, 4096) : display,
                    json,
                    exception_name: null,
                    exception_message: null
                });
            } catch (error) {
                setGetTraceActive(false);
                return JSON.stringify({
                    ok: false,
                    kind: "undefined",
                    display: "undefined",
                    json: null,
                    exception_name: String(error && error.name || "Error"),
                    exception_message: String(error && error.message || error)
                });
            }
        })"#;
    let function = execute_value(scope, wrapper).and_then(|value| {
        v8::Local::<v8::Function>::try_from(value).map_err(|_| V8Error::ResultConversion)
    })?;
    let local_bridge = v8::Local::new(scope, bridge);
    let setter = bridge_member(scope, local_bridge, "__yatouSetGetTraceActive")
        .ok_or(V8Error::NativeInstallation("runtime trace switch"))?;
    let source = v8::String::new(scope, source).ok_or(V8Error::SourceAllocation)?;
    let receiver: v8::Local<v8::Value> = v8::undefined(scope).into();
    let result = function
        .call(scope, receiver, &[setter, source.into()])
        .ok_or_else(|| V8Error::Execution("session evaluation wrapper failed".to_owned()))?;
    let result = result.to_string(scope).ok_or(V8Error::ResultConversion)?;
    let result = result.to_rust_string_lossy(scope);
    serde_json::from_str(&result).map_err(|error| V8Error::ResultDecode(error.to_string()))
}

fn set_get_trace_active(
    scope: &mut v8::PinScope,
    bridge: &v8::Global<v8::Object>,
    active: bool,
) -> Result<(), V8Error> {
    let active: v8::Local<v8::Value> = v8::Boolean::new(scope, active).into();
    let _ = call_runtime_bridge(scope, bridge, "__yatouSetGetTraceActive", &[active])?;
    Ok(())
}

fn take_host_observations(
    scope: &mut v8::PinScope,
    bridge: &v8::Global<v8::Object>,
) -> Result<Vec<HostObservation>, String> {
    let json =
        bridge_json(scope, bridge, "__yatouTakeHostLog", &[]).map_err(|error| error.to_string())?;
    serde_json::from_str(&json).map_err(|error| error.to_string())
}
