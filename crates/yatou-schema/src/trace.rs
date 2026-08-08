//! Versioned L0 replay and L1 browser API ledger contracts.

use std::collections::{BTreeMap, HashMap, HashSet};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{BaselineId, CURRENT_SCHEMA_VERSION, SchemaVersion};

/// Producer that originally observed a trace.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TraceSource {
    /// Google Chrome oracle capture.
    Chrome,
    /// yatouv8 runtime capture.
    Yatouv8,
    /// Minimal deterministic conformance fixture.
    Fixture,
}

/// Header written as the first NDJSON record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TraceHeader {
    /// Data-contract version.
    pub schema_version: SchemaVersion,
    /// Unique identifier for this trace.
    pub trace_id: String,
    /// Chrome baseline that defines expected behavior.
    pub baseline_id: BaselineId,
    /// Producer that observed the events.
    pub source: TraceSource,
    /// UTC RFC 3339 creation time.
    pub created_at: String,
    /// Producer implementation and version.
    pub producer: String,
}

/// Outcome of a top-level JavaScript evaluation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvalOutcome {
    /// Evaluation returned normally.
    Return,
    /// Evaluation terminated with an exception.
    Throw,
}

/// Bounded exception representation shared by L0 and L1.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ExceptionSummary {
    /// JavaScript exception constructor name.
    pub name: String,
    /// Bounded exception message.
    pub message: String,
    /// Optional digest of a separately retained stack artifact.
    pub stack_sha256: Option<String>,
}

/// L0 host-boundary event required for deterministic replay.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReplayEvent {
    /// A top-level evaluation began.
    EvalStart {
        /// Stable evaluation identifier.
        eval_id: String,
        /// Digest of the evaluated source.
        source_sha256: String,
    },
    /// A top-level evaluation completed.
    EvalEnd {
        /// Identifier from the matching start event.
        eval_id: String,
        /// Normal or exceptional completion.
        outcome: EvalOutcome,
    },
    /// A resource lookup crossed the host boundary.
    ResourceRequest {
        /// Stable request identifier.
        request_id: String,
        /// HTTP-like request method.
        method: String,
        /// Exact requested URL.
        url: String,
    },
    /// A recorded resource result became available.
    ResourceResponse {
        /// Identifier from the matching request event.
        request_id: String,
        /// HTTP-like status code.
        status: u16,
        /// Canonically ordered response headers.
        headers: BTreeMap<String, String>,
        /// Replay body encoded as base64.
        body_base64: String,
        /// Digest of the decoded response body.
        body_sha256: String,
    },
    /// A timer was registered.
    TimerSchedule {
        /// Runtime-local timer identifier.
        timer_id: u64,
        /// Requested delay in milliseconds.
        delay_ms: f64,
        /// Whether the timer repeats.
        repeating: bool,
    },
    /// A scheduled timer callback became runnable.
    TimerFire {
        /// Identifier from the schedule event.
        timer_id: u64,
    },
    /// A trusted input event crossed the host boundary.
    Input {
        /// Input family such as `mouse` or `keyboard`.
        input_type: String,
        /// Bounded structured event data.
        payload: serde_json::Value,
    },
    /// An exception was observed at a replay boundary.
    Exception {
        /// Bounded exception representation.
        exception: ExceptionSummary,
    },
    /// A named deterministic state digest was emitted.
    Checkpoint {
        /// Stable checkpoint name.
        name: String,
        /// Digest of canonical checkpoint state.
        state_sha256: String,
    },
}

/// JavaScript value category retained by the low-overhead L1 ledger.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum JsValueKind {
    /// JavaScript `undefined`.
    Undefined,
    /// JavaScript `null`.
    Null,
    /// Boolean primitive.
    Boolean,
    /// Number primitive.
    Number,
    /// `BigInt` primitive.
    Bigint,
    /// String primitive.
    String,
    /// Symbol primitive.
    Symbol,
    /// Callable object.
    Function,
    /// Non-callable object.
    Object,
}

/// Bounded L1 value representation that avoids retaining arbitrary objects.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ValueSummary {
    /// JavaScript category.
    pub kind: JsValueKind,
    /// Optional bounded primitive or shape preview.
    pub preview: Option<String>,
    /// Digest of canonical full evidence when retained separately.
    pub sha256: Option<String>,
}

/// Source location recorded without a full L2 stack.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CallSite {
    /// Script URL or stable script identifier.
    pub script: String,
    /// Zero-based source line.
    pub line: u32,
    /// Zero-based source column.
    pub column: u32,
}

/// Browser-surface operation captured by L1.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ApiOperation {
    /// Property read.
    Get,
    /// Property write.
    Set,
    /// Function or method call.
    Call,
    /// Constructor invocation.
    Construct,
    /// Enumeration of an object's own string and/or symbol keys.
    OwnKeys,
    /// Lookup of one own-property descriptor without invoking its accessor.
    GetOwnPropertyDescriptor,
    /// Lookup of an object's direct prototype.
    GetPrototypeOf,
    /// Property-presence test (`in`, `Reflect.has`, or an equivalent host trap).
    Has,
    /// Definition or redefinition of an own property.
    DefineProperty,
}

/// Result of an L1 browser-surface operation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ApiOutcome {
    /// Operation returned normally.
    Return {
        /// Bounded return value.
        value: ValueSummary,
    },
    /// Operation threw a JavaScript exception.
    Throw {
        /// Bounded exception details.
        exception: ExceptionSummary,
    },
}

/// One L1 browser API ledger entry.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ApiLedgerEvent {
    /// Operation family.
    pub operation: ApiOperation,
    /// Stable receiver or constructor path.
    pub target: String,
    /// Member name for property and method operations.
    pub member: Option<String>,
    /// Bounded argument summaries in call order.
    pub arguments: Vec<ValueSummary>,
    /// Return or throw outcome.
    pub outcome: ApiOutcome,
    /// Low-overhead single call site, when available.
    pub call_site: Option<CallSite>,
}

/// Typed body of one trace event.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "level", content = "entry")]
pub enum TraceEventBody {
    /// Replay-critical host-boundary event.
    #[serde(rename = "l0")]
    L0(ReplayEvent),
    /// Browser-surface operation ledger entry.
    #[serde(rename = "l1")]
    L1(ApiLedgerEvent),
}

/// One ordered event record.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct TraceEvent {
    /// Contiguous zero-based sequence number.
    pub seq: u64,
    /// Monotonic logical time from trace start.
    pub logical_time_ns: u64,
    /// Earlier causal event, when known.
    pub parent_seq: Option<u64>,
    /// L0 or L1 payload.
    #[serde(flatten)]
    pub body: TraceEventBody,
}

/// Footer written as the final NDJSON record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TraceFooter {
    /// Total event count.
    pub event_count: u64,
    /// Number of L0 events.
    pub l0_count: u64,
    /// Number of L1 events.
    pub l1_count: u64,
    /// Final sequence number, or none for an empty stream.
    pub last_seq: Option<u64>,
    /// Whether the recorder closed the stream normally.
    pub complete: bool,
}

/// Physical NDJSON record.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "record_type", content = "record", rename_all = "snake_case")]
pub enum TraceRecord {
    /// Stream header.
    Header(TraceHeader),
    /// Ordered event.
    Event(TraceEvent),
    /// Stream footer.
    Footer(TraceFooter),
}

/// In-memory representation of one complete trace stream.
#[derive(Clone, Debug, PartialEq)]
pub struct TraceStream {
    /// Stream header.
    pub header: TraceHeader,
    /// Ordered events.
    pub events: Vec<TraceEvent>,
    /// Stream footer.
    pub footer: TraceFooter,
}

/// Trace decoding and semantic validation failures.
#[derive(Debug, Error, Eq, PartialEq)]
pub enum TraceStreamError {
    /// NDJSON record could not be decoded.
    #[error("invalid trace JSON at line {line}: {message}")]
    InvalidJson {
        /// One-based line number.
        line: usize,
        /// Decoder detail.
        message: String,
    },
    /// Header is missing, duplicated, or out of order.
    #[error("invalid trace header placement")]
    InvalidHeader,
    /// Footer is missing, duplicated, or out of order.
    #[error("invalid trace footer placement")]
    InvalidFooter,
    /// Header schema version is unsupported.
    #[error("unsupported trace schema version: {0}")]
    UnsupportedVersion(u32),
    /// Trace identifier is empty or contains unsafe characters.
    #[error("invalid trace id: {0}")]
    InvalidTraceId(String),
    /// Event sequence is not contiguous.
    #[error("expected trace sequence {expected}, found {actual}")]
    InvalidSequence {
        /// Expected sequence number.
        expected: u64,
        /// Actual sequence number.
        actual: u64,
    },
    /// Logical time moved backwards.
    #[error("logical time regressed at sequence {0}")]
    LogicalTimeRegression(u64),
    /// Causal parent does not precede its child.
    #[error("invalid parent sequence at event {0}")]
    InvalidParent(u64),
    /// Footer counts do not describe the event records.
    #[error("trace footer counts do not match events")]
    FooterCountMismatch,
    /// A digest is not lowercase SHA-256.
    #[error("invalid trace SHA-256 digest: {0}")]
    InvalidSha256(String),
    /// Paired host-boundary events are inconsistent.
    #[error("invalid L0 lifecycle: {0}")]
    InvalidLifecycle(String),
    /// Trace serialization failed.
    #[error("trace serialization failed: {0}")]
    Serialization(String),
}

impl TraceStream {
    /// Decode a complete trace from NDJSON and validate all stream invariants.
    ///
    /// # Errors
    ///
    /// Returns [`TraceStreamError`] for malformed records, ordering errors, invalid
    /// lifecycle pairs, or inconsistent footer counts.
    pub fn from_ndjson(input: &str) -> Result<Self, TraceStreamError> {
        let mut header = None;
        let mut events = Vec::new();
        let mut footer = None;
        for (index, line) in input.lines().enumerate() {
            if line.trim().is_empty() {
                continue;
            }
            let record = serde_json::from_str::<TraceRecord>(line).map_err(|error| {
                TraceStreamError::InvalidJson {
                    line: index + 1,
                    message: error.to_string(),
                }
            })?;
            match record {
                TraceRecord::Header(value)
                    if header.is_none() && events.is_empty() && footer.is_none() =>
                {
                    header = Some(value);
                }
                TraceRecord::Header(_) => return Err(TraceStreamError::InvalidHeader),
                TraceRecord::Event(value) if header.is_some() && footer.is_none() => {
                    events.push(value);
                }
                TraceRecord::Footer(value) if header.is_some() && footer.is_none() => {
                    footer = Some(value);
                }
                TraceRecord::Event(_) | TraceRecord::Footer(_) => {
                    return Err(TraceStreamError::InvalidFooter);
                }
            }
        }
        let stream = Self {
            header: header.ok_or(TraceStreamError::InvalidHeader)?,
            events,
            footer: footer.ok_or(TraceStreamError::InvalidFooter)?,
        };
        stream.validate()?;
        Ok(stream)
    }

    /// Serialize the stream as one canonical-structure JSON record per line.
    ///
    /// # Errors
    ///
    /// Returns [`TraceStreamError`] when validation or JSON serialization fails.
    pub fn to_ndjson(&self) -> Result<String, TraceStreamError> {
        self.validate()?;
        let mut output = String::new();
        let records = std::iter::once(TraceRecord::Header(self.header.clone()))
            .chain(self.events.iter().cloned().map(TraceRecord::Event))
            .chain(std::iter::once(TraceRecord::Footer(self.footer.clone())));
        for record in records {
            let line = serde_json::to_string(&record)
                .map_err(|error| TraceStreamError::Serialization(error.to_string()))?;
            output.push_str(&line);
            output.push('\n');
        }
        Ok(output)
    }

    /// Validate sequence, time, causal, digest, lifecycle, and footer invariants.
    ///
    /// # Errors
    ///
    /// Returns [`TraceStreamError`] when the trace cannot be admitted for replay.
    pub fn validate(&self) -> Result<(), TraceStreamError> {
        if self.header.schema_version != CURRENT_SCHEMA_VERSION {
            return Err(TraceStreamError::UnsupportedVersion(
                self.header.schema_version.0,
            ));
        }
        if !valid_identifier(&self.header.trace_id) {
            return Err(TraceStreamError::InvalidTraceId(
                self.header.trace_id.clone(),
            ));
        }

        let mut last_time = 0;
        let mut l0_count = 0_u64;
        let mut l1_count = 0_u64;
        let mut evals = HashSet::new();
        let mut resources = HashSet::new();
        let mut timers = HashMap::new();
        for (index, event) in self.events.iter().enumerate() {
            let expected = u64::try_from(index).unwrap_or(u64::MAX);
            if event.seq != expected {
                return Err(TraceStreamError::InvalidSequence {
                    expected,
                    actual: event.seq,
                });
            }
            if index > 0 && event.logical_time_ns < last_time {
                return Err(TraceStreamError::LogicalTimeRegression(event.seq));
            }
            last_time = event.logical_time_ns;
            if event.parent_seq.is_some_and(|parent| parent >= event.seq) {
                return Err(TraceStreamError::InvalidParent(event.seq));
            }
            match &event.body {
                TraceEventBody::L0(entry) => {
                    l0_count += 1;
                    validate_replay_event(entry, &mut evals, &mut resources, &mut timers)?;
                }
                TraceEventBody::L1(entry) => {
                    l1_count += 1;
                    validate_ledger_event(entry)?;
                }
            }
        }
        if !evals.is_empty() || !resources.is_empty() {
            return Err(TraceStreamError::InvalidLifecycle(
                "unclosed eval or resource boundary".to_owned(),
            ));
        }

        let event_count = u64::try_from(self.events.len()).unwrap_or(u64::MAX);
        let last_seq = self.events.last().map(|event| event.seq);
        if !self.footer.complete
            || self.footer.event_count != event_count
            || self.footer.l0_count != l0_count
            || self.footer.l1_count != l1_count
            || self.footer.last_seq != last_seq
        {
            return Err(TraceStreamError::FooterCountMismatch);
        }
        Ok(())
    }
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn validate_sha256(value: &str) -> Result<(), TraceStreamError> {
    if value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        Ok(())
    } else {
        Err(TraceStreamError::InvalidSha256(value.to_owned()))
    }
}

fn validate_exception(exception: &ExceptionSummary) -> Result<(), TraceStreamError> {
    if let Some(digest) = &exception.stack_sha256 {
        validate_sha256(digest)?;
    }
    Ok(())
}

fn validate_value(value: &ValueSummary) -> Result<(), TraceStreamError> {
    if let Some(digest) = &value.sha256 {
        validate_sha256(digest)?;
    }
    Ok(())
}

fn validate_ledger_event(entry: &ApiLedgerEvent) -> Result<(), TraceStreamError> {
    for value in &entry.arguments {
        validate_value(value)?;
    }
    match &entry.outcome {
        ApiOutcome::Return { value } => validate_value(value),
        ApiOutcome::Throw { exception } => validate_exception(exception),
    }
}

fn validate_replay_event(
    entry: &ReplayEvent,
    evals: &mut HashSet<String>,
    resources: &mut HashSet<String>,
    timers: &mut HashMap<u64, bool>,
) -> Result<(), TraceStreamError> {
    match entry {
        ReplayEvent::EvalStart {
            eval_id,
            source_sha256,
        } => {
            validate_sha256(source_sha256)?;
            if !evals.insert(eval_id.clone()) {
                return Err(TraceStreamError::InvalidLifecycle(format!(
                    "duplicate eval start: {eval_id}"
                )));
            }
        }
        ReplayEvent::EvalEnd { eval_id, .. } => {
            if !evals.remove(eval_id) {
                return Err(TraceStreamError::InvalidLifecycle(format!(
                    "eval end without start: {eval_id}"
                )));
            }
        }
        ReplayEvent::ResourceRequest { request_id, .. } => {
            if !resources.insert(request_id.clone()) {
                return Err(TraceStreamError::InvalidLifecycle(format!(
                    "duplicate resource request: {request_id}"
                )));
            }
        }
        ReplayEvent::ResourceResponse {
            request_id,
            body_sha256,
            ..
        } => {
            validate_sha256(body_sha256)?;
            if !resources.remove(request_id) {
                return Err(TraceStreamError::InvalidLifecycle(format!(
                    "resource response without request: {request_id}"
                )));
            }
        }
        ReplayEvent::TimerSchedule {
            timer_id,
            repeating,
            ..
        } => {
            if timers.insert(*timer_id, *repeating).is_some() {
                return Err(TraceStreamError::InvalidLifecycle(format!(
                    "duplicate timer schedule: {timer_id}"
                )));
            }
        }
        ReplayEvent::TimerFire { timer_id } => match timers.get(timer_id) {
            Some(true) => {}
            Some(false) => {
                timers.remove(timer_id);
            }
            None => {
                return Err(TraceStreamError::InvalidLifecycle(format!(
                    "timer fire without schedule: {timer_id}"
                )));
            }
        },
        ReplayEvent::Exception { exception } => validate_exception(exception)?,
        ReplayEvent::Checkpoint { state_sha256, .. } => validate_sha256(state_sha256)?,
        ReplayEvent::Input { .. } => {}
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_stream() -> TraceStream {
        TraceStream {
            header: TraceHeader {
                schema_version: CURRENT_SCHEMA_VERSION,
                trace_id: "trace-test-v1".to_owned(),
                baseline_id: BaselineId::parse("chrome150").expect("baseline"),
                source: TraceSource::Fixture,
                created_at: "2026-08-07T00:00:00Z".to_owned(),
                producer: "test".to_owned(),
            },
            events: vec![
                TraceEvent {
                    seq: 0,
                    logical_time_ns: 0,
                    parent_seq: None,
                    body: TraceEventBody::L0(ReplayEvent::EvalStart {
                        eval_id: "eval-1".to_owned(),
                        source_sha256: "a".repeat(64),
                    }),
                },
                TraceEvent {
                    seq: 1,
                    logical_time_ns: 1,
                    parent_seq: Some(0),
                    body: TraceEventBody::L0(ReplayEvent::EvalEnd {
                        eval_id: "eval-1".to_owned(),
                        outcome: EvalOutcome::Return,
                    }),
                },
            ],
            footer: TraceFooter {
                event_count: 2,
                l0_count: 2,
                l1_count: 0,
                last_seq: Some(1),
                complete: true,
            },
        }
    }

    #[test]
    fn ndjson_round_trip_preserves_trace() {
        let stream = fixture_stream();
        let encoded = stream.to_ndjson().expect("encode");
        let decoded = TraceStream::from_ndjson(&encoded).expect("decode");
        assert_eq!(decoded, stream);
    }

    #[test]
    fn rejects_non_contiguous_sequence() {
        let mut stream = fixture_stream();
        stream.events[1].seq = 2;
        assert!(matches!(
            stream.validate(),
            Err(TraceStreamError::InvalidSequence { .. })
        ));
    }

    #[test]
    fn rejects_unmatched_resource_response() {
        let mut stream = fixture_stream();
        stream.events.insert(
            1,
            TraceEvent {
                seq: 1,
                logical_time_ns: 1,
                parent_seq: Some(0),
                body: TraceEventBody::L0(ReplayEvent::ResourceResponse {
                    request_id: "missing".to_owned(),
                    status: 200,
                    headers: BTreeMap::new(),
                    body_base64: String::new(),
                    body_sha256: "b".repeat(64),
                }),
            },
        );
        stream.events[2].seq = 2;
        stream.footer.event_count = 3;
        stream.footer.l0_count = 3;
        stream.footer.last_seq = Some(2);
        assert!(matches!(
            stream.validate(),
            Err(TraceStreamError::InvalidLifecycle(_))
        ));
    }
}
